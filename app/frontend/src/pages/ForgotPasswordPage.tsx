/**
 * ForgotPasswordPage — Initiate password reset via email.
 */

import { useState, type FormEvent } from 'react';
import { useAuth } from '@/contexts/auth-context';
import { authApi } from '@/services/auth-api';

export function ForgotPasswordPage() {
  const [username, setUsername] = useState('');
  const [email, setEmail] = useState('');
  const [submitted, setSubmitted] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [isLoading, setIsLoading] = useState(false);
  const { setAuthPage } = useAuth();

  const handleSubmit = async (e: FormEvent) => {
    e.preventDefault();
    setError(null);
    setIsLoading(true);
    try {
      await authApi.forgotPassword(username, email);
      setSubmitted(true);
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
            <svg width="36" height="36" viewBox="0 0 36 36" fill="none">
              <rect x="2" y="2" width="32" height="32" rx="6" stroke="currentColor" strokeWidth="2" />
              <path d="M10 26L14 14L18 22L22 10L26 18" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round" />
              <circle cx="14" cy="14" r="2" fill="currentColor" />
              <circle cx="22" cy="10" r="2" fill="currentColor" />
            </svg>
          </div>
          <h1 className="auth-title">找回密码</h1>
          <p className="auth-subtitle">
            {submitted ? '重置链接已发送' : '输入绑定的用户名和邮箱'}
          </p>
        </div>

        {submitted ? (
          <div className="auth-form">
            <div className="auth-success">
              <svg width="20" height="20" viewBox="0 0 20 20" fill="none">
                <circle cx="10" cy="10" r="8" stroke="currentColor" strokeWidth="1.5" />
                <path d="M7 10l2 2 4-4" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" />
              </svg>
              <span>如果用户名和邮箱匹配，密码重置邮件已发送，请查收</span>
            </div>
            <button
              type="button"
              onClick={() => setAuthPage('login')}
              className="auth-submit"
            >
              返回登录
            </button>
          </div>
        ) : (
          <form onSubmit={handleSubmit} className="auth-form">
            {error && (
              <div className="auth-error" role="alert" aria-live="polite">
                <svg width="14" height="14" viewBox="0 0 14 14" fill="none">
                  <circle cx="7" cy="7" r="6" stroke="currentColor" strokeWidth="1.5" />
                  <path d="M7 4v3.5M7 9.5v.5" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" />
                </svg>
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
