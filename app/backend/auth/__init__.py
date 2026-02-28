"""AI Hedge Fund Authentication Module

CLI entry point for authentication management commands.
Usage: uv run python -m app.backend.auth <command>
"""

import argparse
import getpass
import sys
import os
from pathlib import Path

# Ensure project root is in path
project_root = Path(__file__).parent.parent.parent.parent
sys.path.insert(0, str(project_root))

# Load environment variables
from dotenv import load_dotenv

env_path = project_root / ".env"
load_dotenv(dotenv_path=env_path)


def main():
    parser = argparse.ArgumentParser(description="AI Hedge Fund 认证管理")
    subparsers = parser.add_subparsers(dest="command", help="可用命令")

    # init
    subparsers.add_parser("init", help="初始化认证系统，创建管理员账户")

    # gen-invite
    invite_parser = subparsers.add_parser("gen-invite", help="生成邀请码")
    invite_parser.add_argument("--expires-in", default="7d", help="有效期（如 7d, 30d，默认 7d）")
    invite_parser.add_argument("--count", type=int, default=1, help="生成数量（默认 1）")

    # reset-admin-password
    subparsers.add_parser("reset-admin-password", help="重置管理员密码")

    # list-users
    subparsers.add_parser("list-users", help="列出所有用户")

    # list-invites
    subparsers.add_parser("list-invites", help="列出所有邀请码")

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        sys.exit(1)

    # Late imports to avoid circular dependencies
    from app.backend.database.connection import SessionLocal, engine
    from app.backend.database.models import Base

    # Ensure tables exist
    Base.metadata.create_all(bind=engine)

    db = SessionLocal()

    try:
        if args.command == "init":
            _cmd_init(db)
        elif args.command == "gen-invite":
            _cmd_gen_invite(db, args.expires_in, args.count)
        elif args.command == "reset-admin-password":
            _cmd_reset_admin_password(db)
        elif args.command == "list-users":
            _cmd_list_users(db)
        elif args.command == "list-invites":
            _cmd_list_invites(db)
    finally:
        db.close()


def _cmd_init(db):
    """Initialize auth system and create admin user."""
    from app.backend.models.user import User
    from app.backend.auth.utils import hash_password

    # Check if admin already exists
    existing = db.query(User).filter(User.username == "einstein").first()
    if existing:
        print("✓ 管理员 einstein 已存在，跳过创建")
        return

    default_password = os.getenv("AUTH_ADMIN_DEFAULT_PASSWORD", "Hedge@2026!")
    admin = User(
        username="einstein",
        password_hash=hash_password(default_password),
        role="admin",
        is_active=True,
    )
    db.add(admin)
    db.commit()

    print("✓ 数据库表已创建")
    print("✓ 管理员 einstein 已创建")
    print("⚠ 默认密码请查看 AUTH_ADMIN_DEFAULT_PASSWORD 环境变量或 .env 文件")
    print("⚠ 请及时使用 reset-admin-password 命令修改管理员默认密码")


def _cmd_gen_invite(db, expires_in: str, count: int):
    """Generate invitation codes."""
    from app.backend.models.user import User, InvitationCode
    from app.backend.auth.utils import generate_invitation_code
    from datetime import datetime, timedelta

    # Check admin exists
    admin = db.query(User).filter(User.username == "einstein").first()
    if not admin:
        print("✗ 管理员不存在，请先运行 init 命令")
        sys.exit(1)

    # Parse expires_in
    expires_at = None
    if expires_in:
        days = int(expires_in.rstrip("d"))
        expires_at = datetime.utcnow() + timedelta(days=days)

    for i in range(count):
        code = generate_invitation_code()
        invite = InvitationCode(
            code=code,
            created_by=admin.id,
            expires_at=expires_at,
        )
        db.add(invite)
        db.commit()

        print(f"✓ 邀请码已生成")
        print(f"  邀请码: {code}")
        if expires_at:
            print(f"  有效期: {expires_at.strftime('%Y-%m-%d %H:%M:%S')}")
        print(f"  状态: 未使用")
        if i < count - 1:
            print()


def _cmd_reset_admin_password(db):
    """Reset admin password interactively."""
    from app.backend.models.user import User
    from app.backend.auth.utils import hash_password

    admin = db.query(User).filter(User.username == "einstein").first()
    if not admin:
        print("✗ 管理员不存在，请先运行 init 命令")
        sys.exit(1)

    password = getpass.getpass("请输入新密码: ")
    confirm = getpass.getpass("请确认新密码: ")

    if password != confirm:
        print("✗ 两次输入的密码不一致")
        sys.exit(1)

    if len(password) < 6:
        print("✗ 密码长度至少 6 位")
        sys.exit(1)

    admin.password_hash = hash_password(password)
    db.commit()

    print("✓ 管理员密码已更新（立即生效）")


def _cmd_list_users(db):
    """List all users."""
    from app.backend.models.user import User

    users = db.query(User).all()
    if not users:
        print("暂无用户")
        return

    print(f"{'ID':<4} {'用户名':<16} {'角色':<8} {'邮箱':<24} {'创建时间'}")
    print(f"{'--':<4} {'--------':<16} {'------':<8} {'-----------------':<24} {'-------------------'}")
    for u in users:
        email = u.email or "-"
        created = u.created_at.strftime("%Y-%m-%d %H:%M:%S") if u.created_at else "-"
        print(f"{u.id:<4} {u.username:<16} {u.role:<8} {email:<24} {created}")


def _cmd_list_invites(db):
    """List all invitation codes."""
    from app.backend.models.user import InvitationCode, User

    invites = db.query(InvitationCode).all()
    if not invites:
        print("暂无邀请码")
        return

    print(f"{'邀请码':<22} {'状态':<8} {'使用者':<12} {'创建时间':<22} {'过期时间'}")
    print(f"{'------------------':<22} {'------':<8} {'------':<12} {'-------------------':<22} {'-------------------'}")
    for inv in invites:
        status = "已使用" if inv.is_used else "未使用"
        used_by = "-"
        if inv.used_by:
            user = db.query(User).filter(User.id == inv.used_by).first()
            used_by = user.username if user else str(inv.used_by)
        created = inv.created_at.strftime("%Y-%m-%d %H:%M:%S") if inv.created_at else "-"
        expires = inv.expires_at.strftime("%Y-%m-%d %H:%M:%S") if inv.expires_at else "-"
        print(f"{inv.code:<22} {status:<8} {used_by:<12} {created:<22} {expires}")


if __name__ == "__main__":
    main()
