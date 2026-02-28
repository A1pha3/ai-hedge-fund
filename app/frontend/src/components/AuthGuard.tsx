/**
 * AuthGuard — Route guard that shows auth pages or the main app.
 *
 * Since this project doesn't use react-router-dom, AuthGuard uses
 * conditional rendering based on auth state from AuthContext.
 */

import { type ReactNode } from 'react';
import { useAuth } from '@/contexts/auth-context';
import { LoginPage } from '@/pages/LoginPage';
import { RegisterPage } from '@/pages/RegisterPage';
import { ForgotPasswordPage } from '@/pages/ForgotPasswordPage';

interface AuthGuardProps {
  children: ReactNode;
}

export function AuthGuard({ children }: AuthGuardProps) {
  const { isAuthenticated, isLoading, authPage } = useAuth();

  // Show loading spinner while verifying token
  if (isLoading) {
    return (
      <div className="auth-page">
        <div className="auth-grid-bg" />
        <div className="auth-gradient-overlay" />
        <div className="auth-container">
          <div className="auth-brand">
            <div className="auth-logo auth-logo-pulse">
              <svg width="36" height="36" viewBox="0 0 36 36" fill="none">
                <rect x="2" y="2" width="32" height="32" rx="6" stroke="currentColor" strokeWidth="2" />
                <path d="M10 26L14 14L18 22L22 10L26 18" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round" />
                <circle cx="14" cy="14" r="2" fill="currentColor" />
                <circle cx="22" cy="10" r="2" fill="currentColor" />
              </svg>
            </div>
            <p className="auth-subtitle">正在验证身份…</p>
          </div>
        </div>
      </div>
    );
  }

  // Not authenticated — show appropriate auth page
  if (!isAuthenticated) {
    switch (authPage) {
      case 'register':
        return <RegisterPage />;
      case 'forgot-password':
        return <ForgotPasswordPage />;
      default:
        return <LoginPage />;
    }
  }

  // Authenticated — render the main app
  return <>{children}</>;
}
