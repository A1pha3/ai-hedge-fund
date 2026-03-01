"""Tests for CLI commands in app.backend.auth.__init__ (auth management CLI)."""

import io
import re
import sys
from datetime import datetime, timedelta, timezone
from unittest.mock import patch, MagicMock

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.backend.database.connection import Base
from app.backend.models.user import User, InvitationCode
from app.backend.auth.utils import hash_password, verify_password
from app.backend.auth.constants import ADMIN_USERNAME


@pytest.fixture()
def cli_db():
    """Create in-memory DB session for CLI testing."""
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    db = Session()
    yield db
    db.close()


# ---- _cmd_init ----

class TestCmdInit:
    """Tests for the 'init' CLI command."""

    def test_creates_admin(self, cli_db, capsys):
        from app.backend.auth import _cmd_init

        _cmd_init(cli_db)
        captured = capsys.readouterr()

        assert "已创建" in captured.out
        admin = cli_db.query(User).filter(User.username == ADMIN_USERNAME).first()
        assert admin is not None
        assert admin.role == "admin"
        assert admin.is_active is True

    def test_skips_if_admin_exists(self, cli_db, capsys):
        from app.backend.auth import _cmd_init

        # Create admin first
        admin = User(
            username=ADMIN_USERNAME,
            password_hash=hash_password("Exist123"),
            role="admin",
            is_active=True,
        )
        cli_db.add(admin)
        cli_db.commit()

        _cmd_init(cli_db)
        captured = capsys.readouterr()
        assert "已存在" in captured.out
        assert "跳过" in captured.out

    def test_uses_env_default_password(self, cli_db):
        from app.backend.auth import _cmd_init

        with patch.dict("os.environ", {"AUTH_ADMIN_DEFAULT_PASSWORD": "EnvPass1"}):
            _cmd_init(cli_db)

        admin = cli_db.query(User).filter(User.username == ADMIN_USERNAME).first()
        assert verify_password("EnvPass1", admin.password_hash)


# ---- _cmd_gen_invite ----

class TestCmdGenInvite:
    """Tests for the 'gen-invite' CLI command."""

    def _seed_admin(self, db):
        admin = User(
            username=ADMIN_USERNAME,
            password_hash=hash_password("Admin123"),
            role="admin",
            is_active=True,
        )
        db.add(admin)
        db.commit()
        return admin

    def test_generates_single_invite(self, cli_db, capsys):
        from app.backend.auth import _cmd_gen_invite

        self._seed_admin(cli_db)
        _cmd_gen_invite(cli_db, expires_in="7d", count=1)
        captured = capsys.readouterr()

        assert "邀请码已生成" in captured.out
        assert "未使用" in captured.out
        invites = cli_db.query(InvitationCode).all()
        assert len(invites) == 1
        assert invites[0].is_used is False

    def test_generates_multiple_invites(self, cli_db, capsys):
        from app.backend.auth import _cmd_gen_invite

        self._seed_admin(cli_db)
        _cmd_gen_invite(cli_db, expires_in="30d", count=3)
        captured = capsys.readouterr()

        invites = cli_db.query(InvitationCode).all()
        assert len(invites) == 3
        # Each code should be unique
        codes = {inv.code for inv in invites}
        assert len(codes) == 3

    def test_no_admin_exits(self, cli_db, capsys):
        from app.backend.auth import _cmd_gen_invite

        with pytest.raises(SystemExit) as exc:
            _cmd_gen_invite(cli_db, expires_in="7d", count=1)
        assert exc.value.code == 1
        captured = capsys.readouterr()
        assert "管理员不存在" in captured.out


# ---- _cmd_reset_admin_password ----

class TestCmdResetAdminPassword:
    """Tests for the 'reset-admin-password' CLI command."""

    def _seed_admin(self, db):
        admin = User(
            username=ADMIN_USERNAME,
            password_hash=hash_password("Old12345"),
            role="admin",
            is_active=True,
            token_version=0,
        )
        db.add(admin)
        db.commit()
        return admin

    def test_resets_password(self, cli_db, capsys):
        from app.backend.auth import _cmd_reset_admin_password

        self._seed_admin(cli_db)
        with patch("getpass.getpass", side_effect=["NewPass12", "NewPass12"]):
            _cmd_reset_admin_password(cli_db)

        captured = capsys.readouterr()
        assert "已更新" in captured.out

        admin = cli_db.query(User).filter(User.username == ADMIN_USERNAME).first()
        assert verify_password("NewPass12", admin.password_hash)
        assert admin.token_version == 1  # incremented

    def test_password_mismatch_exits(self, cli_db, capsys):
        from app.backend.auth import _cmd_reset_admin_password

        self._seed_admin(cli_db)
        with patch("getpass.getpass", side_effect=["Pass1234", "Different1"]):
            with pytest.raises(SystemExit) as exc:
                _cmd_reset_admin_password(cli_db)
            assert exc.value.code == 1

        captured = capsys.readouterr()
        assert "不一致" in captured.out

    def test_weak_password_exits(self, cli_db, capsys):
        from app.backend.auth import _cmd_reset_admin_password

        self._seed_admin(cli_db)
        with patch("getpass.getpass", side_effect=["weak", "weak"]):
            with pytest.raises(SystemExit) as exc:
                _cmd_reset_admin_password(cli_db)
            assert exc.value.code == 1

    def test_no_admin_exits(self, cli_db, capsys):
        from app.backend.auth import _cmd_reset_admin_password

        with pytest.raises(SystemExit) as exc:
            _cmd_reset_admin_password(cli_db)
        assert exc.value.code == 1
        captured = capsys.readouterr()
        assert "管理员不存在" in captured.out

    def test_token_version_increment(self, cli_db):
        """Resetting password should increment token_version to invalidate existing JWTs."""
        from app.backend.auth import _cmd_reset_admin_password

        admin = self._seed_admin(cli_db)
        old_version = admin.token_version

        with patch("getpass.getpass", side_effect=["Valid123", "Valid123"]):
            _cmd_reset_admin_password(cli_db)

        cli_db.refresh(admin)
        assert admin.token_version == old_version + 1


# ---- _cmd_list_users ----

class TestCmdListUsers:
    """Tests for the 'list-users' CLI command."""

    def test_empty_list(self, cli_db, capsys):
        from app.backend.auth import _cmd_list_users

        _cmd_list_users(cli_db)
        captured = capsys.readouterr()
        assert "暂无用户" in captured.out

    def test_lists_users(self, cli_db, capsys):
        from app.backend.auth import _cmd_list_users

        u1 = User(username="alice", password_hash="x", role="user", is_active=True, email="alice@test.com")
        u2 = User(username="bob", password_hash="x", role="admin", is_active=True)
        cli_db.add_all([u1, u2])
        cli_db.commit()

        _cmd_list_users(cli_db)
        captured = capsys.readouterr()
        assert "alice" in captured.out
        assert "bob" in captured.out
        assert "alice@test.com" in captured.out


# ---- _cmd_list_invites ----

class TestCmdListInvites:
    """Tests for the 'list-invites' CLI command."""

    def test_empty_list(self, cli_db, capsys):
        from app.backend.auth import _cmd_list_invites

        _cmd_list_invites(cli_db)
        captured = capsys.readouterr()
        assert "暂无邀请码" in captured.out

    def test_lists_invites(self, cli_db, capsys):
        from app.backend.auth import _cmd_list_invites

        # Seed admin for created_by
        admin = User(username="admin", password_hash="x", role="admin", is_active=True)
        cli_db.add(admin)
        cli_db.commit()

        inv = InvitationCode(code="TESTCODE123456", created_by=admin.id, is_used=False)
        cli_db.add(inv)
        cli_db.commit()

        _cmd_list_invites(cli_db)
        captured = capsys.readouterr()
        assert "TESTCODE123456" in captured.out
        assert "未使用" in captured.out

    def test_lists_used_invite(self, cli_db, capsys):
        from app.backend.auth import _cmd_list_invites

        admin = User(username="admin", password_hash="x", role="admin", is_active=True)
        user = User(username="invitee", password_hash="x", role="user", is_active=True)
        cli_db.add_all([admin, user])
        cli_db.commit()

        inv = InvitationCode(code="USEDCODE123456", created_by=admin.id, is_used=True, used_by=user.id)
        cli_db.add(inv)
        cli_db.commit()

        _cmd_list_invites(cli_db)
        captured = capsys.readouterr()
        assert "USEDCODE123456" in captured.out
        assert "已使用" in captured.out
        assert "invitee" in captured.out


# ---- main() ----

class TestMainEntrypoint:
    """Tests for the CLI main() entrypoint."""

    def test_no_command_prints_help(self, capsys):
        from app.backend.auth import main

        with patch("sys.argv", ["auth"]):
            with pytest.raises(SystemExit) as exc:
                main()
            assert exc.value.code == 1
