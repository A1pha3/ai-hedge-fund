import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import {
  authApi,
  authFetch,
  authHeaders,
  clearStoredToken,
  getStoredToken,
  setStoredToken,
} from './auth-api';

function jsonRes(body: unknown, init?: ResponseInit): Response {
  return new Response(JSON.stringify(body), {
    status: 200,
    headers: { 'Content-Type': 'application/json' },
    ...init,
  });
}

function mockFetch(response: Response) {
  return vi.spyOn(globalThis, 'fetch').mockResolvedValue(response);
}

describe('auth-api token helpers', () => {
  beforeEach(() => {
    localStorage.clear();
  });

  afterEach(() => {
    vi.restoreAllMocks();
    localStorage.clear();
  });

  it('stores and clears the auth token', () => {
    expect(getStoredToken()).toBeNull();

    setStoredToken('token-123');
    expect(getStoredToken()).toBe('token-123');

    clearStoredToken();
    expect(getStoredToken()).toBeNull();
  });

  it('adds the Authorization header when a token exists', () => {
    setStoredToken('token-abc');

    expect(authHeaders({ 'Content-Type': 'application/json' })).toEqual({
      'Content-Type': 'application/json',
      Authorization: 'Bearer token-abc',
    });
  });
});

describe('authFetch', () => {
  beforeEach(() => {
    localStorage.clear();
  });

  afterEach(() => {
    vi.restoreAllMocks();
    localStorage.clear();
  });

  it('clears the stored token and dispatches auth:unauthorized on 401', async () => {
    setStoredToken('expired-token');
    const eventSpy = vi.fn();
    window.addEventListener('auth:unauthorized', eventSpy);
    mockFetch(new Response('nope', { status: 401 }));

    const response = await authFetch('/protected');

    expect(response.status).toBe(401);
    expect(getStoredToken()).toBeNull();
    expect(eventSpy).toHaveBeenCalledTimes(1);

    window.removeEventListener('auth:unauthorized', eventSpy);
  });
});

describe('authApi service methods', () => {
  afterEach(() => {
    vi.restoreAllMocks();
  });

  it('POSTs login credentials and returns the parsed token response', async () => {
    const fetchSpy = mockFetch(
      jsonRes({
        access_token: 'jwt-token',
        token_type: 'bearer',
        user: {
          id: 1,
          username: 'alice',
          email: 'alice@example.com',
          role: 'member',
          created_at: '2026-01-01T00:00:00',
          updated_at: '2026-01-02T00:00:00',
        },
      }),
    );

    const result = await authApi.login('alice', 'Secret123');

    expect(result.access_token).toBe('jwt-token');
    const [url, init] = fetchSpy.mock.calls[0];
    expect(url).toContain('/auth/login');
    expect(init?.method).toBe('POST');
    expect(JSON.parse(String(init?.body))).toEqual({
      username: 'alice',
      password: 'Secret123',
    });
  });

  it('surfaces backend detail when reset password fails', async () => {
    mockFetch(jsonRes({ detail: '重置令牌无效或已过期' }, { status: 400 }));

    await expect(authApi.resetPassword('bad-token', 'NewPass123')).rejects.toThrow('重置令牌无效或已过期');
  });

  it('POSTs reset token and new password to the reset endpoint', async () => {
    const fetchSpy = mockFetch(jsonRes({ message: 'ok' }));

    const result = await authApi.resetPassword('reset-token', 'NewPass123');

    expect(result.message).toBe('ok');
    const [url, init] = fetchSpy.mock.calls[0];
    expect(url).toContain('/auth/reset-password');
    expect(init?.method).toBe('POST');
    expect(JSON.parse(String(init?.body))).toEqual({
      token: 'reset-token',
      new_password: 'NewPass123',
    });
  });
});
