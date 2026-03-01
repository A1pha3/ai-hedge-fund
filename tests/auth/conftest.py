"""Shared fixtures for auth module tests."""

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.backend.database.connection import Base
from app.backend.models.user import User, InvitationCode
from app.backend.auth.utils import hash_password, generate_invitation_code


@pytest.fixture()
def db_session():
    """Create an in-memory SQLite database for testing."""
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    Base.metadata.create_all(bind=engine)
    TestSession = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    session = TestSession()
    try:
        yield session
    finally:
        session.close()
        Base.metadata.drop_all(bind=engine)
        engine.dispose()


@pytest.fixture()
def admin_user(db_session):
    """Create an admin user in the test database."""
    user = User(
        username="einstein",
        password_hash=hash_password("Admin123"),
        role="admin",
        is_active=True,
    )
    db_session.add(user)
    db_session.commit()
    db_session.refresh(user)
    return user


@pytest.fixture()
def regular_user(db_session):
    """Create a regular user in the test database."""
    user = User(
        username="testuser",
        password_hash=hash_password("Test1234"),
        email="test@example.com",
        role="user",
        is_active=True,
    )
    db_session.add(user)
    db_session.commit()
    db_session.refresh(user)
    return user


@pytest.fixture()
def inactive_user(db_session):
    """Create an inactive user in the test database."""
    user = User(
        username="inactive",
        password_hash=hash_password("Pass1234"),
        role="user",
        is_active=False,
    )
    db_session.add(user)
    db_session.commit()
    db_session.refresh(user)
    return user


@pytest.fixture()
def valid_invite(db_session, admin_user):
    """Create a valid invitation code."""
    code = generate_invitation_code()
    invite = InvitationCode(
        code=code,
        created_by=admin_user.id,
        is_used=False,
    )
    db_session.add(invite)
    db_session.commit()
    db_session.refresh(invite)
    return invite


@pytest.fixture()
def used_invite(db_session, admin_user, regular_user):
    """Create a used invitation code."""
    invite = InvitationCode(
        code="INV-USEDCODE1234",
        created_by=admin_user.id,
        is_used=True,
        used_by=regular_user.id,
    )
    db_session.add(invite)
    db_session.commit()
    db_session.refresh(invite)
    return invite
