"""User and InvitationCode SQLAlchemy models for authentication."""

from sqlalchemy import Boolean, Column, DateTime, ForeignKey, Integer, String
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

from app.backend.database.connection import Base


class User(Base):
    """User model for authentication."""

    __tablename__ = "users"

    id = Column(Integer, primary_key=True, autoincrement=True)
    username = Column(String(50), unique=True, nullable=False, index=True)
    password_hash = Column(String(255), nullable=False)  # bcrypt hash, never plaintext
    email = Column(String(255), unique=True, nullable=True)
    role = Column(String(20), nullable=False, default="user")  # 'admin' | 'user'
    is_active = Column(Boolean, nullable=False, default=True)
    login_attempts = Column(Integer, nullable=False, default=0)
    locked_until = Column(DateTime, nullable=True)
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())

    # Relationships
    created_codes = relationship("InvitationCode", foreign_keys="InvitationCode.created_by", back_populates="creator")

    def __repr__(self):
        return f"<User(id={self.id}, username='{self.username}', role='{self.role}')>"


class InvitationCode(Base):
    """Invitation code model for controlled registration."""

    __tablename__ = "invitation_codes"

    id = Column(Integer, primary_key=True, autoincrement=True)
    code = Column(String(32), unique=True, nullable=False, index=True)
    created_by = Column(Integer, ForeignKey("users.id"), nullable=False)
    used_by = Column(Integer, ForeignKey("users.id"), nullable=True)
    is_used = Column(Boolean, nullable=False, default=False)
    expires_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, server_default=func.now())

    # Relationships
    creator = relationship("User", foreign_keys=[created_by], back_populates="created_codes")
    consumer = relationship("User", foreign_keys=[used_by])

    def __repr__(self):
        return f"<InvitationCode(code='{self.code}', is_used={self.is_used})>"
