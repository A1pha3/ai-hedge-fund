/**
 * RegisterPage — Invitation-code-gated registration form.
 * Same "Terminal Luxe" aesthetic as LoginPage.
 */

import { useState, useRef, useEffect, type FormEvent } from 'react';
import { useAuth } from '@/contexts/auth-context';

export function RegisterPage() {
  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const [invitationCode, setInvitationCode] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState(false);
  const [isLoading, setIsLoading] = useState(false);
  const usernameRef = useRef<HTMLInputElement>(null);
  const { register, setAuthPage } = useAuth();

  useEffect(() => {
    usernameRef.current?.focus();
  }, []);

  const handleSubmit = async (e: FormEvent) => {
    e.preventDefault();
    setError(null);
    setIsLoading(true);
    try {
      await register(username, password, invitationCode);
      setSuccess(true);
      setTimeout(() => setAuthPage('login'), 2000);
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : '注册失败');
      usernameRef.current?.focus();
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
              <svg width="36" height="36" viewBox="0 0 36 36" fill="none">
                <rect x="2" y="2" width="32" height="32" rx="6" stroke="currentColor" strokeWidth="2" />
                <path d="M12 18L16 22L24 14" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round" />
              </svg>
            </div>
            <h1 className="auth-title">注册成功</h1>
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

      <div className="auth-particles">
        {['α', 'β', 'Σ', 'Δ', 'μ', 'σ', 'λ', '∂'].map((char, i) => (
          <span key={i} className={`auth-particle auth-particle-${i}`}>
            {char}
          </span>
        ))}
      </div>

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
          <h1 className="auth-title">创建账户</h1>
          <p className="auth-subtitle">需要管理员提供的邀请码</p>
        </div>

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
            <label htmlFor="reg-username" className="auth-label">
              <span className="auth-label-prefix">01</span>
              用户名
            </label>
            <input
              ref={usernameRef}
              id="reg-username"
              name="username"
              type="text"
              autoComplete="username"
              spellCheck={false}
              required
              minLength={3}
              maxLength={50}
              pattern="^[a-zA-Z0-9_]+$"
              title="只能包含字母、数字和下划线"
              value={username}
              onChange={(e) => setUsername(e.target.value)}
              placeholder="字母、数字、下划线…"
              className="auth-input"
            />
          </div>

          <div className="auth-field">
            <label htmlFor="reg-password" className="auth-label">
              <span className="auth-label-prefix">02</span>
              密码
            </label>
            <input
              id="reg-password"
              name="password"
              type="password"
              autoComplete="new-password"
              spellCheck={false}
              required
              minLength={6}
              maxLength={128}
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              placeholder="至少 6 个字符…"
              className="auth-input"
            />
          </div>

          <div className="auth-field">
            <label htmlFor="reg-invite" className="auth-label">
              <span className="auth-label-prefix">03</span>
              邀请码
            </label>
            <input
              id="reg-invite"
              name="invitation_code"
              type="text"
              autoComplete="off"
              spellCheck={false}
              required
              minLength={8}
              maxLength={32}
              value={invitationCode}
              onChange={(e) => setInvitationCode(e.target.value)}
              placeholder="INV-XXXXXXXXXXXX"
              className="auth-input font-mono tracking-wider"
            />
          </div>

          <button
            type="submit"
            disabled={isLoading}
            className="auth-submit"
          >
            {isLoading ? <span className="auth-spinner" /> : null}
            <span>{isLoading ? '注册中…' : '注 册'}</span>
          </button>

          <div className="auth-links">
            <button
              type="button"
              onClick={() => setAuthPage('login')}
              className="auth-link"
            >
              ← 已有账户？登录
            </button>
          </div>
        </form>

        <div className="auth-footer">
          <span className="auth-footer-dot" />
          <span>Invitation Required</span>
        </div>
      </div>
    </div>
  );
}
