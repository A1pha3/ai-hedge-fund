/**
 * LoginPage — Distinctive financial-themed login interface.
 *
 * Design direction: "Terminal Luxe" — a dark, refined interface that evokes
 * Bloomberg terminals and quantitative trading floors. Monospaced typography
 * mixed with elegant serif accents. Animated grid background suggesting
 * real-time market data flow.
 */

import { useState, useRef, useEffect, type FormEvent } from 'react';
import { useAuth } from '@/contexts/auth-context';
import { BrandLogo, ErrorIcon } from '@/components/auth-icons';

export function LoginPage() {
  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [isLoading, setIsLoading] = useState(false);
  const usernameRef = useRef<HTMLInputElement>(null);
  const { login, setAuthPage } = useAuth();

  useEffect(() => {
    usernameRef.current?.focus();
  }, []);

  const handleSubmit = async (e: FormEvent) => {
    e.preventDefault();
    setError(null);
    setIsLoading(true);
    try {
      await login(username, password);
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : '用户名或密码错误');
      usernameRef.current?.focus();
    } finally {
      setIsLoading(false);
    }
  };

  return (
    <div className="auth-page">
      {/* Animated grid background */}
      <div className="auth-grid-bg" />
      <div className="auth-gradient-overlay" />

      {/* Floating data particles */}
      <div className="auth-particles">
        {['α', 'β', 'Σ', 'Δ', 'μ', 'σ', 'λ', '∂', '∫', 'π', '∞', 'Ω'].map((char, i) => (
          <span key={i} className={`auth-particle auth-particle-${i}`}>
            {char}
          </span>
        ))}
      </div>

      <div className="auth-container">
        {/* Brand header */}
        <div className="auth-brand">
          <div className="auth-logo">
            <BrandLogo />
          </div>
          <h1 className="auth-title">AI Hedge Fund</h1>
          <p className="auth-subtitle">Quantitative Intelligence Platform</p>
        </div>

        {/* Login form */}
        <form onSubmit={handleSubmit} className="auth-form">
          {error && (
            <div className="auth-error" role="alert" aria-live="polite">
              <ErrorIcon />
              <span>{error}</span>
            </div>
          )}

          <div className="auth-field">
            <label htmlFor="login-username" className="auth-label">
              <span className="auth-label-prefix">01</span>
              用户名
            </label>
            <input
              ref={usernameRef}
              id="login-username"
              name="username"
              type="text"
              autoComplete="username"
              spellCheck={false}
              required
              minLength={3}
              maxLength={50}
              value={username}
              onChange={(e) => setUsername(e.target.value)}
              placeholder="请输入用户名…"
              className="auth-input"
            />
          </div>

          <div className="auth-field">
            <label htmlFor="login-password" className="auth-label">
              <span className="auth-label-prefix">02</span>
              密码
            </label>
            <input
              id="login-password"
              name="password"
              type="password"
              autoComplete="current-password"
              spellCheck={false}
              required
              minLength={1}
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              placeholder="请输入密码…"
              className="auth-input"
            />
          </div>

          <button
            type="submit"
            disabled={isLoading}
            className="auth-submit"
          >
            {isLoading ? (
              <span className="auth-spinner" />
            ) : null}
            <span>{isLoading ? '验证中…' : '登 录'}</span>
          </button>

          <div className="auth-links">
            <button
              type="button"
              onClick={() => setAuthPage('forgot-password')}
              className="auth-link"
            >
              忘记密码？
            </button>
            <button
              type="button"
              onClick={() => setAuthPage('register')}
              className="auth-link"
            >
              创建新账户 →
            </button>
          </div>
        </form>

        {/* Footer */}
        <div className="auth-footer">
          <span className="auth-footer-dot" />
          <span>System Ready</span>
        </div>
      </div>
    </div>
  );
}
