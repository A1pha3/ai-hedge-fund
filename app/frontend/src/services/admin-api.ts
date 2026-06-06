/**
 * Admin API service (P2 2.5) — wraps the admin / audit endpoints.
 * All endpoints require an admin-role JWT; the backend enforces this via
 * `require_admin` in app/backend/routes/admin_audit.py.
 */

import { authFetch } from './auth-api';

const API_BASE_URL = import.meta.env.VITE_API_URL || 'http://localhost:8000';

export interface AuditEvent {
  event_id: string;
  timestamp: string;
  actor_id: number;
  actor_username: string;
  action: string;
  target_user_id: number | null;
  target_username: string | null;
  details: Record<string, unknown>;
}

export interface AuditLogResponse {
  events: AuditEvent[];
  total_count: number;
  returned_count: number;
  since: string | null;
  limit: number;
}

export interface AdminUserSummary {
  id: number;
  username: string;
  email: string | null;
  role: string;
  is_active: boolean;
  token_version: number;
  created_at: string | null;
  updated_at: string | null;
}

export interface AdminUserListResponse {
  users: AdminUserSummary[];
  total: number;
}

export interface RevokeSessionResponse {
  user_id: number;
  username: string;
  previous_token_version: number;
  new_token_version: number;
  event: AuditEvent;
}

export interface ToggleActiveResponse {
  user_id: number;
  username: string;
  is_active: boolean;
  event: AuditEvent;
}

async function jsonOrThrow<T>(res: Response): Promise<T> {
  if (!res.ok) {
    const detail = await res.text();
    throw new Error(`admin api ${res.status}: ${detail || res.statusText}`);
  }
  return (await res.json()) as T;
}

export async function fetchAuditLog(params: {
  since?: string;
  limit?: number;
  signal?: AbortSignal;
}): Promise<AuditLogResponse> {
  const url = new URL(`${API_BASE_URL}/admin/audit-log`);
  if (params.since) url.searchParams.set('since', params.since);
  url.searchParams.set('limit', String(params.limit ?? 100));
  return jsonOrThrow<AuditLogResponse>(await authFetch(url.toString(), { signal: params.signal }));
}

export async function fetchAdminUsers(signal?: AbortSignal): Promise<AdminUserListResponse> {
  return jsonOrThrow<AdminUserListResponse>(
    await authFetch(`${API_BASE_URL}/admin/users`, { signal }),
  );
}

export async function revokeUserSession(userId: number): Promise<RevokeSessionResponse> {
  return jsonOrThrow<RevokeSessionResponse>(
    await authFetch(`${API_BASE_URL}/admin/revoke-session/${userId}`, { method: 'POST' }),
  );
}

export async function toggleUserActive(userId: number): Promise<ToggleActiveResponse> {
  return jsonOrThrow<ToggleActiveResponse>(
    await authFetch(`${API_BASE_URL}/admin/users/${userId}/toggle-active`, {
      method: 'POST',
    }),
  );
}
