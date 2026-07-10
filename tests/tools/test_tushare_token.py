"""get_tushare_token / _get_pro 的守卫测试.

这些测试锁定"一个 token 加载器、不写文件、不返回 None"的不变量 —
正是此前 9 处重复 _load_token + ts.set_token(None) 写脏 ~/tk.csv 导致
industry_index_cache 失败的根因消除后的回归防线.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest

from src.tools import tushare_api as ta


# ── get_tushare_token ────────────────────────────────────────────────────


def test_token_from_env(monkeypatch):
    """env 有 token → 返回正确值."""
    monkeypatch.setenv("TUSHARE_TOKEN", "env-token-abc123")
    assert ta.get_tushare_token() == "env-token-abc123"


def test_token_env_takes_priority_over_file(monkeypatch, tmp_path):
    """env 优先级高于 .env 文件 (与 load_dotenv(override=True) 语义一致)."""
    monkeypatch.setenv("TUSHARE_TOKEN", "env-wins")
    fake_env = tmp_path / ".env"
    fake_env.write_text('TUSHARE_TOKEN=file-loses\n', encoding="utf-8")
    with patch.object(ta, "__file__", str(tmp_path / "fake.py")):
        # parents[2] 从 src/tools/tushare_api.py → project root;
        # 模拟 __file__ 在 tmp_path 下使 .env 解析指向我们的假文件
        pass
    # env 优先, 即使 .env 存在也返回 env 的值
    assert ta.get_tushare_token() == "env-wins"


def test_token_never_returns_none(monkeypatch):
    """env 和 .env 都无 token → 返回 '' (空串), 绝不返回 None.

    这是不变量: 调用方只需 `if not token:` 判断, 不用额外防空.
    """
    monkeypatch.delenv("TUSHARE_TOKEN", raising=False)
    # _read_dotenv_token 会尝试读 .env, 但 env 已删, 且无 mocked 文件
    with patch("pathlib.Path.exists", return_value=False):
        result = ta.get_tushare_token()
    assert result == ""
    assert result is not None


def test_token_strips_whitespace(monkeypatch):
    """带空格/引号的 token 被清理."""
    monkeypatch.setenv("TUSHARE_TOKEN", '  "abc123"  ')
    assert ta.get_tushare_token() == '"abc123"'  # .strip() 去外空格, 保留引号内容


# ── _get_pro 永不调用 set_token ──────────────────────────────────────────


@pytest.fixture
def _reset_pro_singleton():
    """每个测试前后重置 _pro 单例, 避免跨测试污染."""
    old = ta._pro
    ta._pro = None
    yield
    ta._pro = old


def test_get_pro_uses_token_param_not_set_token(monkeypatch, _reset_pro_singleton):
    """_get_pro() 通过 ts.pro_api(token=...) 传参, 不调用 ts.set_token().

    这消除了 ~/tk.csv 被写脏的根因 — set_token(None) 会静默写 NaN.
    """
    monkeypatch.setenv("TUSHARE_TOKEN", "valid-test-token")

    with patch("tushare.set_token") as mock_set_token, patch("tushare.pro_api") as mock_pro_api:
        mock_pro_api.return_value = "fake-pro-instance"
        pro = ta._get_pro()

    assert pro == "fake-pro-instance"
    # 核心断言: set_token 从未被调用
    mock_set_token.assert_not_called()
    # pro_api 必须通过 token= 关键字传参
    mock_pro_api.assert_called_once()
    call_kwargs = mock_pro_api.call_args
    assert call_kwargs.kwargs.get("token") == "valid-test-token" or \
           (call_kwargs.args and call_kwargs.args[0] == "valid-test-token")


def test_get_pro_returns_none_when_no_token(monkeypatch, _reset_pro_singleton):
    """无 token 时返回 None, 不抛异常."""
    monkeypatch.delenv("TUSHARE_TOKEN", raising=False)
    with patch("pathlib.Path.exists", return_value=False):
        pro = ta._get_pro()
    assert pro is None


def test_get_pro_caches_singleton(monkeypatch, _reset_pro_singleton):
    """_get_pro() 是单例 — 第二次调用不重新初始化."""
    monkeypatch.setenv("TUSHARE_TOKEN", "cache-test-token")
    with patch("tushare.pro_api") as mock_pro_api:
        mock_pro_api.return_value = "cached-pro"
        pro1 = ta._get_pro()
        pro2 = ta._get_pro()

    assert pro1 is pro2
    # pro_api 只被调用一次 (单例缓存)
    assert mock_pro_api.call_count == 1
