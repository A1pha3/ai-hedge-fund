"""每日管道 driver (由 scripts/daily_daemon.sh 常驻守护调用, 2026-08-18).

为什么是 python 而不是 bash wrapper: 外置卷 (/Volumes/mini_matrix) 受 macOS
TCC「可移动卷」保护 — launchd 直接启动的 bash **读取**卷上文件会
Operation not permitted (rc=126), 本 driver 由用户终端启动的 daemon (scripts/daily_daemon.sh) 调用,
继承终端授权, 无 TCC 问题。(2026-08-18 曾试 launchd/cron 直启, 均被
macOS 可移除卷权限拦截, 已弃用 — 详见 daemon 脚本头注。)

行为 (同原 bash wrapper 设计):
  1. 交易日判断: trade_calendar.json 含今天 → 开市; 日历不可读 → 周一~五保守;
     休市 → 记状态安静退出
  2. --auto: rc=75 (管道锁被手动实例占用) → 等 120s 重试, 最多 3 次
  3. --daily-action: 仅在 --auto 成功后; rc=14 (POLICY_HALT: regime 全闸/
     熔断/入场窗口) 归一为成功
  4. 状态: logs/.daily_run_status.json; 日志: logs/cron/pipeline_YYYYMMDD.log
"""

from __future__ import annotations

import json
import subprocess
import sys
import time
from datetime import date, datetime
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
# 看门狗 (发现 A): --auto 正常 2-15 分钟, 挂起场景 (网络死锁等) 无外层超时会永久
# 停摆整个守护 — 超时强杀记失败, streak 告警接管
AUTO_TIMEOUT_S = 3600
ACTION_TIMEOUT_S = 600
PY = REPO / ".venv" / "bin" / "python"
LOG_DIR = REPO / "logs" / "cron"


def _log(fh, msg: str) -> None:
    line = f"[{datetime.now():%H:%M:%S}] {msg}\n"
    fh.write(line)
    fh.flush()


def _record(status_path: Path, payload: dict) -> None:
    """原子写当前状态 + 追加每日历史 (发现 C/D: 原子性与去重)。"""
    from src.utils.atomic_files import atomic_write_json

    atomic_write_json(status_path, payload)
    history = status_path.parent / "cron" / "status_history.jsonl"
    history.parent.mkdir(parents=True, exist_ok=True)  # helper 独立调用时不依赖 main 的 mkdir
    with open(history, "a", encoding="utf-8") as fh:
        fh.write(json.dumps(payload, ensure_ascii=False) + "\n")


def _write_status(status_path: Path, today: str, auto_rc: int, action_rc, final_rc,
                  dur: int, log) -> int:
    """写当前状态 + 追加每日历史 + 连续失败 streak 告警 (无人值守的告警面).

    状态文件只存最后一天 → 无法察觉连续失败; 历史 jsonl 每日一行 (审计资产),
    streak ≥3 天时醒目告警 — 这是无外部通知渠道下能做的告警上限。
    """
    history = status_path.parent / "cron" / "status_history.jsonl"
    payload = {"date": today, "auto_rc": auto_rc, "action_rc": action_rc,
               "final_rc": final_rc, "duration_s": dur}
    _record(status_path, payload)
    try:
        rows = [json.loads(l) for l in history.read_text(encoding="utf-8").splitlines() if l.strip()]
        streak = 0
        for row in reversed(rows):   # 从最新往前数连续失败 (今天的行已含)
            fr = row.get("final_rc")
            if fr is None or fr != 0:
                streak += 1
            else:
                break
    except Exception:  # noqa: BLE001 - 历史读取失败不阻断
        streak = 0
    if streak >= 3:
        _log(log, f"⚠⚠⚠ 管道已连续失败 {streak} 天 — 检查数据源/手动跑 --auto 排查 "
                  f"(历史: {history})")
    return final_rc if final_rc is not None else (auto_rc if auto_rc != 0 else 0)


def main() -> int:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    today = date.today().strftime("%Y%m%d")
    status_path = REPO / "logs" / ".daily_run_status.json"

    with open(LOG_DIR / f"pipeline_{today}.log", "a", encoding="utf-8") as log:
        # ---- 交易日判断 ----
        try:
            cal = json.loads((REPO / "data/reports/trade_calendar.json").read_text(encoding="utf-8"))
            is_open = today in {str(x) for x in cal}
        except Exception:  # noqa: BLE001 - 日历不可读 → 周一~五保守跑 (幂等无害)
            is_open = date.today().weekday() < 5
        if not is_open:
            _log(log, "休市日, 跳过")
            _record(status_path, {"date": today, "skipped": "market_closed", "final_rc": 0})
            return 0

        # ---- --auto (锁等待重试) ----
        start = time.time()
        auto_rc = 75
        for attempt in (1, 2, 3):
            _log(log, f"--auto 第 {attempt} 次启动")
            try:
                auto_rc = subprocess.call([str(PY), "src/main.py", "--auto"], cwd=str(REPO),
                                          stdout=log, stderr=subprocess.STDOUT,
                                          timeout=AUTO_TIMEOUT_S)
            except subprocess.TimeoutExpired:
                _log(log, f"--auto 看门狗超时 ({AUTO_TIMEOUT_S}s) — 强杀记失败 (防永久停摆)")
                auto_rc = 124
            if auto_rc != 75:
                break
            _log(log, "--auto 被管道锁占用 (75), 120s 后重试")
            time.sleep(120)
        if auto_rc != 0:
            _log(log, f"--auto 最终失败 rc={auto_rc} — 跳过 --daily-action (避免半新数据)")
            return _write_status(status_path, today, auto_rc, None, None, int(time.time() - start), log)
        _log(log, "--auto 完成 rc=0")

        # ---- --daily-action ----
        try:
            action_rc = subprocess.call([str(PY), "src/main.py", "--daily-action"], cwd=str(REPO),
                                        stdout=log, stderr=subprocess.STDOUT,
                                        timeout=ACTION_TIMEOUT_S)
        except subprocess.TimeoutExpired:
            _log(log, f"--daily-action 看门狗超时 ({ACTION_TIMEOUT_S}s) — 强杀记失败")
            action_rc = 124
        dur = int(time.time() - start)
        _run_advisory_sentinels(log)
        # rc=14 = POLICY_HALT_EXIT_CODE (regime 全闸/熔断/入场窗口) — 设计内停手, 非故障
        if action_rc == 14:
            _log(log, f"--daily-action 策略性停手 (设计内), 全链 {dur}s")
            final_rc = 0
        else:
            _log(log, f"--daily-action 完成 rc={action_rc}, 全链 {dur}s")
            final_rc = action_rc
        return _write_status(status_path, today, 0, action_rc, final_rc, dur, log)


def _run_advisory_sentinels(log) -> None:
    """daemon 日链收尾的 advisory 哨点群 — 只读诊断, 永不影响管道 rc/状态.

    - court 资产哨点 (trap 22 运营覆盖层): 公式指纹漂移/表龄超限当天可见。
    - 先验方向断言 (trap 4 重验闭环, 2026-08-19 接入): review_btst_prior_court
      --check 在事件表重建 (人工, 唯一新数据入口) 后自动重验先验-court 方向
      关系 — 漂移当天暴露, 不等下次人工评估 (trap 20: 先有检测才有处置)。
    - 资金流新鲜度哨点 (2026-08-19 对抗性复核): fund_flow 子集整段缺口
      (7/13-8/13, 118 只) 曾让 BTST 条件 2 用失真均值静默判定 — 缺口当天可见。
    """
    # court 资产哨点 (毫秒级)
    try:
        subprocess.call([str(PY), "scripts/court_asset_sentinel.py"], cwd=str(REPO),
                        stdout=log, stderr=subprocess.STDOUT, timeout=60)
    except Exception:  # noqa: BLE001 - 哨点自身故障不拖垮每日管道
        _log(log, "court 资产哨点异常 (advisory, 忽略)")
    # 先验方向断言 (秒级 bootstrap; 断言失败 = 先验-court 关系漂移信号, 记日志不改 rc)
    try:
        subprocess.call([str(PY), "scripts/review_btst_prior_court.py", "--check"],
                        cwd=str(REPO), stdout=log, stderr=subprocess.STDOUT, timeout=120)
    except Exception:  # noqa: BLE001 - 同上
        _log(log, "先验方向断言哨点异常 (advisory, 忽略)")
    # 资金流新鲜度 (秒级, 只读比对 price/fund_flow 缓存最新日期)
    try:
        subprocess.call([str(PY), "scripts/fund_flow_freshness_sentinel.py"],
                        cwd=str(REPO), stdout=log, stderr=subprocess.STDOUT, timeout=120)
    except Exception:  # noqa: BLE001 - 同上
        _log(log, "资金流新鲜度哨点异常 (advisory, 忽略)")


if __name__ == "__main__":
    sys.exit(main())
