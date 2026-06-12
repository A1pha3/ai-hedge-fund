import { fireEvent, render, screen } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it } from 'vitest';

import { AuthGuard } from './AuthGuard';
import { AuthProvider } from '@/contexts/auth-context';

describe('AuthGuard startup auth routing', () => {
  beforeEach(() => {
    localStorage.clear();
    window.history.replaceState({}, '', '/');
  });

  afterEach(() => {
    window.history.replaceState({}, '', '/');
  });

  it('opens the reset password screen from URL state and prefills the reset token', async () => {
    window.history.replaceState({}, '', '/?auth=reset-password&token=email-reset-token');

    render(
      <AuthProvider>
        <AuthGuard>
          <div>app shell</div>
        </AuthGuard>
      </AuthProvider>,
    );

    await screen.findByRole('heading', { name: '重置密码' });

    expect(screen.getByLabelText(/重置令牌/)).toHaveValue('email-reset-token');
  });

  it('syncs auth page transitions back into the URL', async () => {
    render(
      <AuthProvider>
        <AuthGuard>
          <div>app shell</div>
        </AuthGuard>
      </AuthProvider>,
    );

    fireEvent.click(await screen.findByRole('button', { name: '忘记密码？' }));

    await screen.findByRole('heading', { name: '找回密码' });
    expect(window.location.search).toContain('auth=forgot-password');

    fireEvent.click(screen.getByRole('button', { name: '← 返回登录' }));

    await screen.findByRole('heading', { name: 'AI Hedge Fund' });
    expect(window.location.search).toBe('');
  });
});
