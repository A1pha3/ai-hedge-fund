/**
 * RegisterPage — Invitation-code-gated registration form.
 * Same "Terminal Luxe" aesthetic as LoginPage.
 */

import { useState, useRef, useEffect, useMemo, type FormEvent } from 'react';
import { useAuth } from '@/contexts/auth-context';
import { BrandLogo, SuccessIcon, ErrorIcon } from '@/components/auth-icons';

/** Evaluate password strength: 0-4 score */
function getPasswordStrength(pw: string): { score: number; label: string; cls: string } {
  if (!pw) return { score: 0, label: '', cls: '' };
  let score = 0;
  if (pw.length >= 8) score++;
  if (/[a-z]/.test(pw)) score++;
  if (/[A-Z]/.test(pw)) score++;
  if (/\d/.test(pw)) score++;
  if (pw.length >= 12 || /[^a-zA-Z0-9]/.test(pw)) score++;
  const labels: Record<number, [string, string]> = {
    1: ['弱', 'pwd-weak'],
    2: ['较弱', 'pwd-fair'],
    3: ['中等', 'pwd-good'],
    4: ['强', 'pwd-strong'],
    5: ['很强', 'pwd-strong'],
  };
  const [label, cls] = labels[score] || ['', ''];
  return { score: Math.min(score, 4), label, cls };
}

export function RegisterPage() {
  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const [confirmPassword, setConfirmPassword] = useState('');
  const [invitationCode, setInvitationCode] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState(false);
  const [isLoading, setIsLoading] = useState(false);
  const usernameRef = useRef<HTMLInputElement>(null);
  const { register, setAuthPage } = useAuth();
  const pwdStrength = useMemo(() => getPasswordStrength(password), [password]);

  useEffect(() => {
    usernameRef.current?.focus();
  }, []);

  const handleSubmit = async (e: FormEvent) => {
    e.preventDefault();
    setError(null);
    if (password !== confirmPassword) {
      setError('两次输入的密码不一致');
      return;
    }
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
              <SuccessIcon />
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
            <BrandLogo />
          </div>
          <h1 className="auth-title">创建账户</h1>
          <p className="auth-subtitle">需要管理员提供的邀请码</p>
        </div>

        <form onSubmit={handleSubmit} className="auth-form">
          {error && (
            <div className="auth-error" role="alert" aria-live="polite">
              <ErrorIcon />
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
              minLength={8}
              maxLength={128}
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              placeholder="大小写字母 + 数字，至少 8 位…"
              className="auth-input"
            />
            {password && (
              <div className="pwd-strength-bar">
                <div className={`pwd-strength-fill ${pwdStrength.cls}`} data-score={pwdStrength.score} />
                <span className={`pwd-strength-label ${pwdStrength.cls}`}>{pwdStrength.label}</span>
              </div>
            )}
          </div>

          <div className="auth-field">
            <label htmlFor="reg-confirm" className="auth-label">
              <span className="auth-label-prefix">03</span>
              确认密码
            </label>
            <input
              id="reg-confirm"
              name="confirm_password"
              type="password"
              autoComplete="new-password"
              spellCheck={false}
              required
              minLength={8}
              maxLength={128}
              value={confirmPassword}
              onChange={(e) => setConfirmPassword(e.target.value)}
              placeholder="再次输入密码…"
              className="auth-input"
            />
          </div>

          <div className="auth-field">
            <label htmlFor="reg-invite" className="auth-label">
              <span className="auth-label-prefix">04</span>
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
