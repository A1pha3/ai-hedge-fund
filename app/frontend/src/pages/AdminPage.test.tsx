import { describe, expect, it, vi, beforeEach } from 'vitest';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { AdminPage } from '@/pages/AdminPage';

vi.mock('@/services/admin-api', () => ({
  fetchAdminUsers: vi.fn(),
  fetchAuditLog: vi.fn(),
  revokeUserSession: vi.fn(),
  toggleUserActive: vi.fn(),
}));

vi.mock('@/services/auth-api', () => ({
  authApi: {
    getMe: vi.fn(),
  },
}));

import {
  fetchAdminUsers,
  fetchAuditLog,
  revokeUserSession,
  toggleUserActive,
} from '@/services/admin-api';
import { authApi } from '@/services/auth-api';

const mockedUsers = vi.mocked(fetchAdminUsers);
const mockedAudit = vi.mocked(fetchAuditLog);
const mockedRevoke = vi.mocked(revokeUserSession);
const mockedToggle = vi.mocked(toggleUserActive);
const mockedMe = vi.mocked(authApi.getMe);

function mockMeAs(id: number, username: string) {
  mockedMe.mockResolvedValue({
    id,
    username,
    email: `${username}@example.com`,
    role: 'admin',
    created_at: '2026-01-01T00:00:00',
    updated_at: '2026-01-01T00:00:00',
  });
}

const baseUsers = {
  users: [
    {
      id: 1,
      username: 'root',
      email: 'root@example.com',
      role: 'admin',
      is_active: true,
      token_version: 0,
      created_at: '2026-01-01T00:00:00',
      updated_at: '2026-01-01T00:00:00',
    },
    {
      id: 2,
      username: 'alice',
      email: 'alice@example.com',
      role: 'member',
      is_active: true,
      token_version: 3,
      created_at: '2026-02-01T00:00:00',
      updated_at: '2026-02-15T00:00:00',
    },
    {
      id: 3,
      username: 'bob',
      email: null,
      role: 'viewer',
      is_active: false,
      token_version: 1,
      created_at: '2026-03-01T00:00:00',
      updated_at: null,
    },
  ],
  total: 3,
};

const baseAudit = {
  events: [
    {
      event_id: 'evt-1',
      timestamp: '2026-06-06T10:00:00Z',
      actor_id: 1,
      actor_username: 'root',
      action: 'revoke_session',
      target_user_id: 2,
      target_username: 'alice',
      details: { previous_token_version: 2, new_token_version: 3 },
    },
  ],
  total_count: 1,
  returned_count: 1,
  since: null,
  limit: 50,
};

beforeEach(() => {
  mockedUsers.mockReset();
  mockedAudit.mockReset();
  mockedRevoke.mockReset();
  mockedToggle.mockReset();
  mockedMe.mockReset();
  // Default: current user is the admin "root" (id=1) so the first row
  // is correctly identified as the self row.
  mockMeAs(1, 'root');
});

describe('AdminPage (P2 2.5)', () => {
  it('renders users and audit log on mount', async () => {
    mockedUsers.mockResolvedValueOnce(baseUsers);
    mockedAudit.mockResolvedValueOnce(baseAudit);
    render(<AdminPage />);

    await waitFor(() => {
      expect(screen.getByTestId('admin-users-table')).toBeTruthy();
    });
    const rows = screen.getAllByTestId('admin-user-row');
    expect(rows).toHaveLength(3);
    expect(screen.getByTestId('admin-audit-table')).toBeTruthy();
    expect(screen.getAllByTestId('admin-audit-row')).toHaveLength(1);
  });

  it('renders empty state when no users exist', async () => {
    mockedUsers.mockResolvedValueOnce({ users: [], total: 0 });
    mockedAudit.mockResolvedValueOnce({ events: [], total_count: 0, returned_count: 0, since: null, limit: 50 });
    render(<AdminPage />);
    await waitFor(() => {
      expect(screen.getByText(/系统中尚无用户/)).toBeTruthy();
    });
    expect(screen.getByTestId('admin-audit-empty')).toBeTruthy();
  });

  it('renders the error banner when fetch fails', async () => {
    mockedUsers.mockRejectedValueOnce(new Error('403 forbidden'));
    mockedAudit.mockResolvedValueOnce(baseAudit);
    render(<AdminPage />);
    await waitFor(() => {
      expect(screen.getByTestId('admin-error')).toBeTruthy();
    });
    expect(screen.getByTestId('admin-error').textContent).toContain('403');
  });

  it('invokes revokeUserSession when Revoke session is clicked', async () => {
    mockedUsers.mockResolvedValue(baseUsers);
    mockedAudit.mockResolvedValue(baseAudit);
    mockedRevoke.mockResolvedValueOnce({
      user_id: 2,
      username: 'alice',
      previous_token_version: 3,
      new_token_version: 4,
      event: {
        event_id: 'evt-2',
        timestamp: '2026-06-06T11:00:00Z',
        actor_id: 1,
        actor_username: 'root',
        action: 'revoke_session',
        target_user_id: 2,
        target_username: 'alice',
        details: { previous_token_version: 3, new_token_version: 4 },
      },
    });
    render(<AdminPage />);
    await waitFor(() => screen.getAllByTestId('revoke-session-button'));

    // Self button (root) is disabled. Click the alice (id=2) revoke button.
    const buttons = screen.getAllByTestId('revoke-session-button');
    expect(buttons[0]).toBeDisabled(); // self
    fireEvent.click(buttons[1]); // alice

    await waitFor(() => {
      expect(mockedRevoke).toHaveBeenCalledWith(2);
    });
  });

  it('invokes toggleUserActive when Enable / Disable is clicked', async () => {
    mockedUsers.mockResolvedValue(baseUsers);
    mockedAudit.mockResolvedValue(baseAudit);
    mockedToggle.mockResolvedValueOnce({
      user_id: 3,
      username: 'bob',
      is_active: true,
      event: {
        event_id: 'evt-3',
        timestamp: '2026-06-06T12:00:00Z',
        actor_id: 1,
        actor_username: 'root',
        action: 'toggle_user_active',
        target_user_id: 3,
        target_username: 'bob',
        details: { is_active: true },
      },
    });
    render(<AdminPage />);
    await waitFor(() => screen.getAllByTestId('toggle-active-button'));

    fireEvent.click(screen.getAllByTestId('toggle-active-button')[2]); // bob
    await waitFor(() => {
      expect(mockedToggle).toHaveBeenCalledWith(3);
    });
  });

  it('displays role and status badges correctly', async () => {
    mockedUsers.mockResolvedValueOnce(baseUsers);
    mockedAudit.mockResolvedValueOnce(baseAudit);
    render(<AdminPage />);
    await waitFor(() => screen.getAllByTestId('admin-user-row'));
    // Find badges by their text content
    const rows = screen.getAllByTestId('admin-user-row');
    expect(rows[0].textContent).toContain('admin');
    expect(rows[1].textContent).toContain('member');
    expect(rows[2].textContent).toContain('disabled');
    expect(rows[2].textContent).toContain('viewer');
  });

  it('disables self-action buttons (root) but enables buttons for other users', async () => {
    mockedUsers.mockResolvedValueOnce(baseUsers);
    mockedAudit.mockResolvedValueOnce(baseAudit);
    render(<AdminPage />);
    await waitFor(() => screen.getAllByTestId('admin-user-row'));
    const revokeButtons = screen.getAllByTestId('revoke-session-button');
    expect(revokeButtons[0]).toBeDisabled(); // root (self)
    expect(revokeButtons[1]).not.toBeDisabled(); // alice
    expect(revokeButtons[2]).not.toBeDisabled(); // bob
  });

  it('reloads both tables after a successful revoke', async () => {
    mockedUsers.mockResolvedValueOnce(baseUsers).mockResolvedValueOnce({
      users: baseUsers.users.map(u => u.id === 2 ? { ...u, token_version: 4 } : u),
      total: 3,
    });
    mockedAudit.mockResolvedValue(baseAudit);
    mockedRevoke.mockResolvedValueOnce({
      user_id: 2,
      username: 'alice',
      previous_token_version: 3,
      new_token_version: 4,
      event: {
        event_id: 'evt-4',
        timestamp: '2026-06-06T13:00:00Z',
        actor_id: 1,
        actor_username: 'root',
        action: 'revoke_session',
        target_user_id: 2,
        target_username: 'alice',
        details: { previous_token_version: 3, new_token_version: 4 },
      },
    });
    render(<AdminPage />);
    await waitFor(() => screen.getAllByTestId('revoke-session-button'));

    fireEvent.click(screen.getAllByTestId('revoke-session-button')[1]);
    await waitFor(() => {
      expect(mockedRevoke).toHaveBeenCalledWith(2);
    });
    await waitFor(() => {
      expect(mockedUsers).toHaveBeenCalledTimes(2); // initial + reload
    });
  });
});
