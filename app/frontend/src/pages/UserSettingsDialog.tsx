/**
 * UserSettingsDialog — Change password & bind email.
 * Rendered as a modal dialog, triggered from the main layout.
 */

import { useState, useEffect, type FormEvent } from 'react';
import { useAuth } from '@/contexts/auth-context';
import { authApi } from '@/services/auth-api';

interface UserSettingsDialogProps {
  onClose: () => void;
}

export function UserSettingsDialog({ onClose }: UserSettingsDialogProps) {
  const { user, updateUser, logout } = useAuth();
  const [activeTab, setActiveTab] = useState<'password' | 'email'>('password');

  const [confirmLogout, setConfirmLogout] = useState(false);

  // Close on Escape key
  useEffect(() => {
    const handleKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose();
    };
    window.addEventListener('keydown', handleKey);
    return () => window.removeEventListener('keydown', handleKey);
  }, [onClose]);

  // Password form
  const [oldPassword, setOldPassword] = useState('');
  const [newPassword, setNewPassword] = useState('');
  const [pwdError, setPwdError] = useState<string | null>(null);
  const [pwdSuccess, setPwdSuccess] = useState(false);
  const [pwdLoading, setPwdLoading] = useState(false);

  // Email form
  const [email, setEmail] = useState(user?.email || '');
  const [emailError, setEmailError] = useState<string | null>(null);
  const [emailSuccess, setEmailSuccess] = useState(false);
  const [emailLoading, setEmailLoading] = useState(false);

  const handlePasswordSubmit = async (e: FormEvent) => {
    e.preventDefault();
    setPwdError(null);
    setPwdSuccess(false);
    setPwdLoading(true);
    try {
      await authApi.changePassword(oldPassword, newPassword);
      setPwdSuccess(true);
      setOldPassword('');
      setNewPassword('');
      // Auto-logout immediately since token_version has changed
      logout();
    } catch (err: unknown) {
      setPwdError(err instanceof Error ? err.message : '修改失败');
    } finally {
      setPwdLoading(false);
    }
  };

  const handleEmailSubmit = async (e: FormEvent) => {
    e.preventDefault();
    setEmailError(null);
    setEmailSuccess(false);
    setEmailLoading(true);
    try {
      await authApi.bindEmail(email);
      setEmailSuccess(true);
      if (user) {
        updateUser({ ...user, email });
      }
    } catch (err: unknown) {
      setEmailError(err instanceof Error ? err.message : '绑定失败');
    } finally {
      setEmailLoading(false);
    }
  };

  const isAdmin = user?.role === 'admin';

  return (
    <div className="settings-overlay" onClick={onClose}>
      <div className="settings-dialog" onClick={(e) => e.stopPropagation()}>
        {/* Header */}
        <div className="settings-header">
          <div>
            <h2 className="settings-title">用户设置</h2>
            <p className="settings-user">
              <span className="settings-badge">{user?.role === 'admin' ? 'ADMIN' : 'USER'}</span>
              {user?.username}
            </p>
          </div>
          <button onClick={onClose} className="settings-close" aria-label="关闭">
            <svg width="16" height="16" viewBox="0 0 16 16" fill="none">
              <path d="M4 4l8 8M12 4l-8 8" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" />
            </svg>
          </button>
        </div>

        {/* Tabs */}
        <div className="settings-tabs">
          <button
            className={`settings-tab ${activeTab === 'password' ? 'active' : ''}`}
            onClick={() => setActiveTab('password')}
          >
            修改密码
          </button>
          <button
            className={`settings-tab ${activeTab === 'email' ? 'active' : ''}`}
            onClick={() => setActiveTab('email')}
          >
            绑定邮箱
          </button>
        </div>

        {/* Password tab */}
        {activeTab === 'password' && (
          <form onSubmit={handlePasswordSubmit} className="settings-form">
            {isAdmin ? (
              <div className="settings-warning">
                管理员密码只能通过服务器 CLI 修改：
                <code className="settings-cli-hint">
                  uv run python -m app.backend.auth reset-admin-password
                </code>
              </div>
            ) : (
              <>
                {pwdError && <div className="settings-error">{pwdError}</div>}
                {pwdSuccess && <div className="settings-success">密码修改成功，请重新登录</div>}

                <div className="settings-field">
                  <label htmlFor="old-pwd">当前密码</label>
                  <input
                    id="old-pwd"
                    type="password"
                    autoComplete="current-password"
                    required
                    minLength={8}
                    value={oldPassword}
                    onChange={(e) => setOldPassword(e.target.value)}
                    className="settings-input"
                  />
                </div>

                <div className="settings-field">
                  <label htmlFor="new-pwd">新密码</label>
                  <input
                    id="new-pwd"
                    type="password"
                    autoComplete="new-password"
                    required
                    minLength={8}
                    value={newPassword}
                    onChange={(e) => setNewPassword(e.target.value)}
                    placeholder="大小写字母 + 数字，至少 8 位"
                    className="settings-input"
                  />
                </div>

                <button
                  type="submit"
                  disabled={pwdLoading}
                  className="settings-submit"
                >
                  {pwdLoading ? '修改中…' : '确认修改'}
                </button>
              </>
            )}
          </form>
        )}

        {/* Email tab */}
        {activeTab === 'email' && (
          <form onSubmit={handleEmailSubmit} className="settings-form">
            {emailError && <div className="settings-error">{emailError}</div>}
            {emailSuccess && <div className="settings-success">邮箱绑定成功</div>}

            <div className="settings-field">
              <label htmlFor="bind-email">邮箱地址</label>
              <input
                id="bind-email"
                type="email"
                autoComplete="email"
                required
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                placeholder="your@email.com"
                className="settings-input"
              />
            </div>

            <button
              type="submit"
              disabled={emailLoading}
              className="settings-submit"
            >
              {emailLoading ? '绑定中…' : '确认绑定'}
            </button>
          </form>
        )}

        {/* Logout button */}
        <div className="settings-footer">
          {confirmLogout ? (
            <div className="settings-logout-confirm">
              <span className="settings-logout-prompt">确认退出登录？</span>
              <button onClick={logout} className="settings-logout">确认退出</button>
              <button onClick={() => setConfirmLogout(false)} className="settings-logout-cancel">取消</button>
            </div>
          ) : (
            <button onClick={() => setConfirmLogout(true)} className="settings-logout">
              退出登录
            </button>
          )}
        </div>
      </div>
    </div>
  );
}
