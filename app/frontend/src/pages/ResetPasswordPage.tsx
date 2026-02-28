/**
 * ResetPasswordPage — Complete password reset with token.
 * User arrives here after receiving a reset token (e.g. from admin/CLI).
 */

import { useState, type FormEvent } from 'react';
import { useAuth } from '@/contexts/auth-context';
import { authApi } from '@/services/auth-api';
import { SuccessIcon, ResetIcon, ErrorIcon } from '@/components/auth-icons';

export function ResetPasswordPage() {
  const [token, setToken] = useState('');
  const [newPassword, setNewPassword] = useState('');
  const [confirmPassword, setConfirmPassword] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState(false);
  const [isLoading, setIsLoading] = useState(false);
  const { setAuthPage } = useAuth();

  const handleSubmit = async (e: FormEvent) => {
    e.preventDefault();
    setError(null);

    if (newPassword !== confirmPassword) {
      setError('两次输入的密码不一致');
      return;
    }

    if (newPassword.length < 8) {
      setError('密码长度至少 8 位');
      return;
    }

    if (!/(?=.*[a-z])(?=.*[A-Z])(?=.*\d)/.test(newPassword)) {
      setError('密码需包含大写字母、小写字母和数字');
      return;
    }

    setIsLoading(true);
    try {
      await authApi.resetPassword(token, newPassword);
      setSuccess(true);
      setTimeout(() => setAuthPage('login'), 2000);
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : '重置失败');
    } finally {
      setIsLoading(false);
    }
  };

  if (success) {
    return (
      <div className="auth-page">
        <div className="auth-grid-bg" />
        <div className="auth-gradient-overlay" />
        <div className="auth-container">
          <div className="auth-brand">
            <div className="auth-logo">
              <SuccessIcon />
            </div>
            <h1 className="auth-title">密码已重置</h1>
            <p className="auth-subtitle">正在跳转登录页面…</p>
          </div>
        </div>
      </div>
    );
  }

  return (
    <div className="auth-page">
      <div className="auth-grid-bg" />
      <div className="auth-gradient-overlay" />

      <div className="auth-container">
        <div className="auth-brand">
          <div className="auth-logo">
            <ResetIcon />
          </div>
          <h1 className="auth-title">重置密码</h1>
          <p className="auth-subtitle">输入重置令牌和新密码</p>
        </div>

        <form className="auth-form" onSubmit={handleSubmit}>
          {error && (
            <div className="auth-error" role="alert" aria-live="polite">
              <ErrorIcon />
              <span>{error}</span>
            </div>
          )}

          <div className="auth-field">
            <label htmlFor="reset-token" className="auth-label">
              <span className="auth-label-prefix">01</span> 重置令牌
            </label>
            <input
              id="reset-token"
              className="auth-input"
              type="text"
              placeholder="粘贴重置令牌…"
              value={token}
              onChange={(e) => setToken(e.target.value)}
              required
              autoFocus
            />
          </div>

          <div className="auth-field">
            <label htmlFor="reset-new-pwd" className="auth-label">
              <span className="auth-label-prefix">02</span> 新密码
            </label>
            <input
              id="reset-new-pwd"
              className="auth-input"
              type="password"
              placeholder="大小写字母 + 数字，至少 8 位"
              value={newPassword}
              onChange={(e) => setNewPassword(e.target.value)}
              required
              minLength={8}
            />
          </div>

          <div className="auth-field">
            <label htmlFor="reset-confirm-pwd" className="auth-label">
              <span className="auth-label-prefix">03</span> 确认密码
            </label>
            <input
              id="reset-confirm-pwd"
              className="auth-input"
              type="password"
              placeholder="再次输入新密码"
              value={confirmPassword}
              onChange={(e) => setConfirmPassword(e.target.value)}
              required
              minLength={8}
            />
          </div>

          <button className="auth-submit" type="submit" disabled={isLoading}>
            {isLoading ? <span className="auth-spinner" /> : '重置密码'}
          </button>

          <div className="auth-links">
            <button type="button" className="auth-link" onClick={() => setAuthPage('login')}>
              ← 返回登录
            </button>
          </div>
        </form>

        <div className="auth-footer">
          <span className="auth-footer-dot" />
          <span>SECURE RESET</span>
        </div>
      </div>
    </div>
  );
}
