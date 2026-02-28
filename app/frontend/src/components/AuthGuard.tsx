/**
 * AuthGuard — Route guard that shows auth pages or the main app.
 *
 * Since this project doesn't use react-router-dom, AuthGuard uses
 * conditional rendering based on auth state from AuthContext.
 */

import { type ReactNode } from 'react';
import { useAuth } from '@/contexts/auth-context';
import { BrandLogo } from '@/components/auth-icons';
import { LoginPage } from '@/pages/LoginPage';
import { RegisterPage } from '@/pages/RegisterPage';
import { ForgotPasswordPage } from '@/pages/ForgotPasswordPage';
import { ResetPasswordPage } from '@/pages/ResetPasswordPage';

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
              <BrandLogo />
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
      case 'reset-password':
        return <ResetPasswordPage />;
      default:
        return <LoginPage />;
    }
  }

  // Authenticated — render the main app
  return <>{children}</>;
}
