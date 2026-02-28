/**
 * Authentication API service — handles all auth HTTP calls.
 * Adds Bearer token to all protected requests.
 */

const API_BASE_URL = import.meta.env.VITE_API_URL || 'http://localhost:8000';
const TOKEN_KEY = 'hedge_fund_token';

// ---- Types ----

export interface AuthUser {
  id: number;
  username: string;
  email: string | null;
  role: 'admin' | 'user';
  created_at: string | null;
  updated_at: string | null;
}

export interface TokenResponse {
  access_token: string;
  token_type: string;
  user: AuthUser;
}

export interface MessageResponse {
  message: string;
}

export interface ForgotPasswordResponse {
  message: string;
  reset_token: string | null;
}

// ---- Token Management ----

export function getStoredToken(): string | null {
  return localStorage.getItem(TOKEN_KEY);
}

export function setStoredToken(token: string): void {
  localStorage.setItem(TOKEN_KEY, token);
}

export function clearStoredToken(): void {
  localStorage.removeItem(TOKEN_KEY);
}

// ---- Authenticated Fetch ----

/**
 * Build standard headers with auth token.
 * Exported for use by all API service modules.
 */
export function authHeaders(extra?: Record<string, string>): Record<string, string> {
  const headers: Record<string, string> = { ...extra };
  const token = getStoredToken();
  if (token) {
    headers['Authorization'] = `Bearer ${token}`;
  }
  return headers;
}

/**
 * Global 401 handler — dispatches a custom event so AuthContext can react
 * without a hard page refresh.
 */
function handleUnauthorized(): void {
  clearStoredToken();
  window.dispatchEvent(new CustomEvent('auth:unauthorized'));
}

/**
 * Wrapper around fetch that automatically adds the Authorization header.
 * On 401, clears the token and fires an event for AuthContext to handle.
 */
export async function authFetch(
  url: string,
  options: RequestInit = {}
): Promise<Response> {
  const token = getStoredToken();
  const headers = new Headers(options.headers);

  if (token) {
    headers.set('Authorization', `Bearer ${token}`);
  }

  const response = await fetch(url, { ...options, headers });

  // Auto-logout on 401
  if (response.status === 401 && token) {
    handleUnauthorized();
  }

  return response;
}

// ---- Auth API ----

export const authApi = {
  async login(username: string, password: string): Promise<TokenResponse> {
    const res = await fetch(`${API_BASE_URL}/auth/login`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ username, password }),
    });
    if (!res.ok) {
      const error = await res.json().catch(() => ({ detail: '登录失败' }));
      throw new Error(error.detail || '登录失败');
    }
    return res.json();
  },

  async register(
    username: string,
    password: string,
    invitation_code: string
  ): Promise<AuthUser> {
    const res = await fetch(`${API_BASE_URL}/auth/register`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ username, password, invitation_code }),
    });
    if (!res.ok) {
      const error = await res.json().catch(() => ({ detail: '注册失败' }));
      throw new Error(error.detail || '注册失败');
    }
    return res.json();
  },

  async getMe(): Promise<AuthUser> {
    const res = await authFetch(`${API_BASE_URL}/auth/me`);
    if (!res.ok) {
      throw new Error('Token invalid');
    }
    return res.json();
  },

  async changePassword(
    oldPassword: string,
    newPassword: string
  ): Promise<MessageResponse> {
    const res = await authFetch(`${API_BASE_URL}/auth/password`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        old_password: oldPassword,
        new_password: newPassword,
      }),
    });
    if (!res.ok) {
      const error = await res.json().catch(() => ({ detail: '修改失败' }));
      throw new Error(error.detail || '修改失败');
    }
    return res.json();
  },

  async bindEmail(email: string): Promise<MessageResponse> {
    const res = await authFetch(`${API_BASE_URL}/auth/email`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ email }),
    });
    if (!res.ok) {
      const error = await res.json().catch(() => ({ detail: '绑定失败' }));
      throw new Error(error.detail || '绑定失败');
    }
    return res.json();
  },

  async forgotPassword(
    username: string,
    email: string
  ): Promise<ForgotPasswordResponse> {
    const res = await fetch(`${API_BASE_URL}/auth/forgot-password`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ username, email }),
    });
    if (!res.ok) {
      const error = await res.json().catch(() => ({ detail: '请求失败' }));
      throw new Error(error.detail || '请求失败');
    }
    return res.json();
  },

  async resetPassword(
    token: string,
    newPassword: string
  ): Promise<MessageResponse> {
    const res = await fetch(`${API_BASE_URL}/auth/reset-password`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ token, new_password: newPassword }),
    });
    if (!res.ok) {
      const error = await res.json().catch(() => ({ detail: '重置失败' }));
      throw new Error(error.detail || '重置失败');
    }
    return res.json();
  },
};
