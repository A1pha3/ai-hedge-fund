import { render, screen } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { UserSettingsDialog } from './UserSettingsDialog';

const useAuthMock = vi.fn();

vi.mock('@/contexts/auth-context', () => ({
  useAuth: () => useAuthMock(),
}));

vi.mock('@/services/auth-api', () => ({
  authApi: {
    changePassword: vi.fn(),
    bindEmail: vi.fn(),
  },
}));

function makeAuthUser(role: 'admin' | 'member' | 'viewer') {
  return {
    user: {
      id: 1,
      username: 'tester',
      email: 'tester@example.com',
      role,
      created_at: '2026-01-01T00:00:00',
      updated_at: '2026-01-01T00:00:00',
    },
    updateUser: vi.fn(),
    logout: vi.fn(),
  };
}

describe('UserSettingsDialog role badge', () => {
  beforeEach(() => {
    useAuthMock.mockReset();
  });

  it('renders the member badge for member users', () => {
    useAuthMock.mockReturnValue(makeAuthUser('member'));

    render(<UserSettingsDialog onClose={vi.fn()} />);

    expect(screen.getByText('MEMBER')).toBeTruthy();
  });

  it('renders the viewer badge for viewer users', () => {
    useAuthMock.mockReturnValue(makeAuthUser('viewer'));

    render(<UserSettingsDialog onClose={vi.fn()} />);

    expect(screen.getByText('VIEWER')).toBeTruthy();
  });
});
