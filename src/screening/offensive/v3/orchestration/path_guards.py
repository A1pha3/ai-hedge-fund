"""Archive 路径守卫 — trial-root 下动态路径段的全组件防护 (2026-08-21).

对抗性审查 (autodev 第四轮) 发现家族性缺陷: ``stage_archive`` 与
``arm_capital`` 各自的 ``_validate_root`` 只 walk trial root 自身组件,
root 之下的动态段 (trial_id / stage_id / ``archive`` 常量段) 从不被
lstat — 四类穿透实锤: symlink 组件读穿 (跨 trial 混淆)、``..`` 穿越、
绝对路径注入 (``pathlib root / '/abs'`` 整体替换 root)、symlink 预置
写穿 (回执落盘到 root 之外)。``stage_archive`` 写面曾经存在的那次
"新建目录组件也不得是 symlink" 二次校验实为幂等冗余 — 安全剧场。

本模块是 orchestration 包内共享的单一守卫实现:

- ``require_safe_segment``: 拼路径前的单段形状校验 (非空、单段、非
  ``.``/``..``、不以点开头、无分隔符与盘符冒号) — 绝对注入与穿越在
  **构造路径时**即拒绝, 不留给 lstat;
- ``walk_components``: anchor → directory 逐组件 lstat, 拒 symlink 与
  非目录组件 (mkdir 新建组件同样覆盖 — 不再有"只验 root"的盲区);
- ``ensure_directory_components`` (第五轮): 逐段创建 + 逐段验证 —
  根除 ``mkdir(parents=True)`` 的穿透语义 (它会静默跟随预置 symlink
  在 root 之外创建目录)。已存在祖先段全组件 walk; 缺失段逐个
  ``mkdir()`` 后立即 lstat 复验; 并发同伴竞态创建的真实目录收敛
  放行。自 ``blob_store._ensure_directory`` 推广为单一实现。

错误码语义跨模块共享 (trial_id_rejected / path_traversal /
path_component_missing / path_component_rejected); 接线面通过 ``fail``
回调把共享错误码装进各自模块的类型化异常族, 本模块不持有调用方错误
类型。offline primitive: 纯路径守卫, 不构成权限。
"""

from __future__ import annotations

import re
import stat
from pathlib import Path
from typing import Any, Callable

# 单段安全名: 字母数字开头 (拒 . .. 前导点与绝对注入), 其后允许
# 字母数字/点/下划线/连字符; 拒路径分隔符与 Windows 盘符冒号。
_SAFE_SEGMENT = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}")

Fail = Callable[..., Exception]


class PathGuardError(RuntimeError):
    """path_guards 单元语义下的守卫失败 (code + message + details)。"""

    def __init__(self, code: str, message: str, **details: object) -> None:
        super().__init__(f"{code}: {message}")
        self.code = code
        self.details = details


def _raiser(fail: Fail | None) -> Fail:
    if fail is None:
        return PathGuardError
    return fail


def require_safe_segment(value: Any, *, field: str, fail: Fail | None = None) -> str:
    """要求 ``value`` 是可安全拼进路径的单段名称, 返回原值。

    拒绝: 非 str、空、``.``/``..``、含 ``/`` 或 ``\\`` (穿越)、以 ``/``
    开头 (pathlib 绝对注入会整体替换 root)、前导点 (隐藏段)、盘符冒号。
    错误码固定为 ``{field}_rejected``。
    """
    raiser = _raiser(fail)
    if type(value) is not str or _SAFE_SEGMENT.fullmatch(value) is None:
        raise raiser(
            f"{field}_rejected",
            f"{field} must be a single safe path segment",
            **{field: value if type(value) is str else repr(value)},
        )
    return value


def walk_components(
    directory: Path,
    *,
    fail: Fail | None = None,
    missing_code: str = "path_component_missing",
    rejected_code: str = "path_component_rejected",
) -> None:
    """anchor → ``directory`` 的每个组件必须是真实目录 (lstat, 拒 symlink)。

    ``directory`` 必须是 canonical 绝对路径且不含 ``..``。FileNotFound
    映射为 ``missing_code``, symlink 或非目录组件映射为 ``rejected_code``;
    两个错误码由接线面按各自语义命名。

    错误码 taxonomy (R35 发现 7 成文): ``missing_code``/``rejected_code``
    是 walk 发现, 参数化由接线面命名; ``path_not_canonical``/
    ``path_traversal`` 是**前置形状违规的固定共享码** — 调用方异常族
    (``fail``) 直接透传, 不参数化: 所有接线面对「非 canonical 绝对
    路径」「含 ``..``」的前置形状语义相同, 参数化只会制造同义码碎片。
    """
    raiser = _raiser(fail)
    if not isinstance(directory, Path) or not directory.is_absolute():
        raise raiser(
            "path_not_canonical",
            "a guarded archive path must be a canonical absolute path",
            path=str(directory),
        )
    if ".." in directory.parts:
        raise raiser(
            "path_traversal",
            "a guarded archive path must not contain a '..' path segment",
            path=str(directory),
        )
    current = Path(directory.anchor)
    for part in directory.parts[1:]:
        current /= part
        try:
            mode = current.lstat().st_mode
        except FileNotFoundError as exc:
            raise raiser(
                missing_code,
                "a guarded archive path component does not exist",
                component=str(current),
            ) from exc
        if stat.S_ISLNK(mode) or not stat.S_ISDIR(mode):
            raise raiser(
                rejected_code,
                "a guarded archive path must have no symlinked or "
                "non-directory component",
                component=str(current),
            )


def ensure_directory_components(
    directory: Path,
    *,
    fail: Fail | None = None,
    missing_code: str = "path_component_missing",
    rejected_code: str = "path_component_rejected",
) -> None:
    """逐段创建目录并逐段验证 — 绝不穿过 symlink 预置创建 (第五轮).

    ``Path.mkdir(parents=True, exist_ok=True)`` 会静默跟随路径上已有的
    symlink 在 root 之外创建目录 (对抗性审查 PoC: victim 侧目录落盘的
    元数据副作用 — 即使后续 walk 拒绝, 穿出创建已经发生)。本原语把
    创建拆成单段步进:

    1. 前置: ``directory`` 必须是 canonical 绝对路径且不含 ``..``
       (与 ``walk_components`` 同一前置, 含同款固定共享前置码
       ``path_not_canonical``/``path_traversal`` — taxonomy 见其
       docstring, R35 发现 7);
    2. 自 ``directory`` 上溯至首个**已存在**祖先: 途中任何 symlink/
       非目录组件即刻拒绝 (rejected_code);
    3. 该祖先再经 ``walk_components`` 自 anchor 全组件复验;
    4. 缺失段按路径序逐个 ``mkdir()`` (无 parents/exist_ok), 每次
       创建后立即 lstat 复验; ``FileExistsError`` 时重验为真实目录
       则收敛放行 (并发同伴竞态), 预置 symlink/文件仍然拒绝。

    与仓库的恰等重放幂等/并发收敛纪律一致 (services 并发 publish
    收敛测试锁定)。
    """
    raiser = _raiser(fail)
    if not isinstance(directory, Path) or not directory.is_absolute():
        raise raiser(
            "path_not_canonical",
            "a guarded directory path must be a canonical absolute path",
            path=str(directory),
        )
    if ".." in directory.parts:
        raise raiser(
            "path_traversal",
            "a guarded directory path must not contain a '..' path segment",
            path=str(directory),
        )
    missing: list[str] = []
    probe = directory
    while True:
        try:
            mode = probe.lstat().st_mode
        except FileNotFoundError:
            missing.append(probe.name)
            probe = probe.parent
            continue
        except NotADirectoryError:
            # 某个祖先段是文件 (POSIX ENOTDIR, 非缺失): 该深度不可能有
            # 目录 — 不计入缺失, 上溯一层后由 S_ISREG 检查拒绝。
            probe = probe.parent
            continue
        if stat.S_ISLNK(mode) or not stat.S_ISDIR(mode):
            raise raiser(
                rejected_code,
                "a guarded directory path must have no symlinked or "
                "non-directory component",
                component=str(probe),
            )
        break
    walk_components(
        probe,
        fail=fail,
        missing_code=missing_code,
        rejected_code=rejected_code,
    )
    for name in reversed(missing):
        probe = probe / name
        try:
            probe.mkdir()
        except FileExistsError:
            # 竞态同伴可能刚创建了真实目录 — 重验后收敛; 预置的
            # symlink/文件仍然拒绝。
            mode = probe.lstat().st_mode
            if stat.S_ISLNK(mode) or not stat.S_ISDIR(mode):
                raise raiser(
                    rejected_code,
                    "a guarded directory path component was preset to a "
                    "non-directory",
                    component=str(probe),
                ) from None
            continue
        mode = probe.lstat().st_mode
        if stat.S_ISLNK(mode) or not stat.S_ISDIR(mode):
            raise raiser(
                rejected_code,
                "a guarded directory path must have no symlinked or "
                "non-directory component",
                component=str(probe),
            )


__all__ = [
    "Fail",
    "PathGuardError",
    "ensure_directory_components",
    "require_safe_segment",
    "walk_components",
]
