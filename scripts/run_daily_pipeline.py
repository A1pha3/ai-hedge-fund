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
        # rc=14 = POLICY_HALT_EXIT_CODE (regime 全闸/熔断/入场窗口) — 设计内停手, 非故障
        if action_rc == 14:
            _log(log, f"--daily-action 策略性停手 (设计内), 全链 {dur}s")
            final_rc = 0
        else:
            _log(log, f"--daily-action 完成 rc={action_rc}, 全链 {dur}s")
            final_rc = action_rc
        return _write_status(status_path, today, 0, action_rc, final_rc, dur, log)


if __name__ == "__main__":
    sys.exit(main())
