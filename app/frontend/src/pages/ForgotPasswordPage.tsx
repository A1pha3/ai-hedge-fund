/**
 * ForgotPasswordPage — Initiate password reset via email.
 */

import { useState, type FormEvent } from 'react';
import { useAuth } from '@/contexts/auth-context';
import { authApi } from '@/services/auth-api';
import { BrandLogo, ErrorIcon, SuccessCheckIcon } from '@/components/auth-icons';

export function ForgotPasswordPage() {
  const [username, setUsername] = useState('');
  const [email, setEmail] = useState('');
  const [submitted, setSubmitted] = useState(false);
  const [resetToken, setResetToken] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [isLoading, setIsLoading] = useState(false);
  const { setAuthPage } = useAuth();

  const handleSubmit = async (e: FormEvent) => {
    e.preventDefault();
    setError(null);
    setIsLoading(true);
    try {
      const result = await authApi.forgotPassword(username, email);
      setSubmitted(true);
      if (result.reset_token) {
        setResetToken(result.reset_token);
      }
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : '请求失败');
    } finally {
      setIsLoading(false);
    }
  };

  return (
    <div className="auth-page">
      <div className="auth-grid-bg" />
      <div className="auth-gradient-overlay" />

      <div className="auth-container">
        <div className="auth-brand">
          <div className="auth-logo">
            <BrandLogo />
          </div>
          <h1 className="auth-title">找回密码</h1>
          <p className="auth-subtitle">
            {submitted ? '重置链接已发送' : '输入绑定的用户名和邮箱'}
          </p>
        </div>

        {submitted ? (
          <div className="auth-form">
            <div className="auth-success">
              <SuccessCheckIcon />
              <span>{resetToken ? '已生成密码重置令牌' : '如果用户名和邮箱匹配，密码重置邮件已发送'}</span>
            </div>
            {resetToken && (
              <div className="auth-field">
                <label htmlFor="reset-token-display" className="auth-label">
                  <span className="auth-label-prefix">→</span>
                  重置令牌（请复制）
                </label>
                <input
                  id="reset-token-display"
                  className="auth-input font-mono"
                  type="text"
                  readOnly
                  value={resetToken}
                  title="密码重置令牌"
                  onClick={(e) => (e.target as HTMLInputElement).select()}
                />
              </div>
            )}
            <button
              type="button"
              onClick={() => setAuthPage('reset-password')}
              className="auth-submit"
            >
              前往重置密码
            </button>
            <div className="auth-links">
              <button
                type="button"
                onClick={() => setAuthPage('login')}
                className="auth-link"
              >
                ← 返回登录
              </button>
            </div>
          </div>
        ) : (
          <form onSubmit={handleSubmit} className="auth-form">
            {error && (
              <div className="auth-error" role="alert" aria-live="polite">
                <ErrorIcon />
                <span>{error}</span>
              </div>
            )}

            <div className="auth-field">
              <label htmlFor="forgot-username" className="auth-label">
                <span className="auth-label-prefix">01</span>
                用户名
              </label>
              <input
                id="forgot-username"
                name="username"
                type="text"
                autoComplete="username"
                autoFocus
                spellCheck={false}
                required
                value={username}
                onChange={(e) => setUsername(e.target.value)}
                placeholder="请输入用户名…"
                className="auth-input"
              />
            </div>

            <div className="auth-field">
              <label htmlFor="forgot-email" className="auth-label">
                <span className="auth-label-prefix">02</span>
                邮箱
              </label>
              <input
                id="forgot-email"
                name="email"
                type="email"
                autoComplete="email"
                required
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                placeholder="绑定的邮箱地址…"
                className="auth-input"
              />
            </div>

            <button
              type="submit"
              disabled={isLoading}
              className="auth-submit"
            >
              {isLoading ? <span className="auth-spinner" /> : null}
              <span>{isLoading ? '提交中…' : '发送重置邮件'}</span>
            </button>

            <div className="auth-links">
              <button
                type="button"
                onClick={() => setAuthPage('login')}
                className="auth-link"
              >
                ← 返回登录
              </button>
            </div>
          </form>
        )}

        <div className="auth-footer">
          <span className="auth-footer-dot" />
          <span>Password Recovery</span>
        </div>
      </div>
    </div>
  );
}
