import { useEffect, useState } from 'react';
import { AlertTriangle, Loader2, RefreshCw, ShieldOff, ShieldCheck } from 'lucide-react';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Skeleton } from '@/components/ui/skeleton';
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table';
import { authApi } from '@/services/auth-api';
import {
  type AdminUserSummary,
  type AuditEvent,
  fetchAdminUsers,
  fetchAuditLog,
  revokeUserSession,
  toggleUserActive,
} from '@/services/admin-api';

type LoadState = 'idle' | 'loading' | 'ready' | 'error';

function roleBadgeVariant(role: string): 'default' | 'destructive' | 'outline' | 'secondary' {
  if (role === 'admin') return 'destructive';
  if (role === 'member') return 'default';
  if (role === 'viewer') return 'secondary';
  return 'outline';
}

function actionBadgeVariant(action: string): 'destructive' | 'warning' | 'outline' {
  if (action === 'revoke_session') return 'destructive';
  if (action === 'toggle_user_active') return 'warning';
  return 'outline';
}

function formatTimestamp(ts: string): string {
  if (!ts) return '--';
  return ts.replace('T', ' ').replace(/\.\d+/, '').replace('Z', '');
}

function AdminUsersTable({
  users,
  currentAdminId,
  onRevoke,
  onToggleActive,
  pendingUserId,
}: {
  users: AdminUserSummary[];
  currentAdminId: number | null;
  onRevoke: (userId: number) => void;
  onToggleActive: (userId: number) => void;
  pendingUserId: number | null;
}) {
  return (
    <Table data-testid="admin-users-table">
      <TableHeader>
        <TableRow>
          <TableHead>ID</TableHead>
          <TableHead>Username</TableHead>
          <TableHead>Email</TableHead>
          <TableHead>Role</TableHead>
          <TableHead>Status</TableHead>
          <TableHead className="text-right">Token v</TableHead>
          <TableHead>Actions</TableHead>
        </TableRow>
      </TableHeader>
      <TableBody>
        {users.map(u => {
          const isSelf = currentAdminId !== null && u.id === currentAdminId;
          const isPending = pendingUserId === u.id;
          return (
            <TableRow
              key={u.id}
              data-testid="admin-user-row"
              data-user-id={u.id}
              data-self={isSelf ? 'true' : 'false'}
            >
              <TableCell>{u.id}</TableCell>
              <TableCell className="font-mono">
                {u.username}
                {isSelf ? <Badge variant="outline" className="ml-2">you</Badge> : null}
              </TableCell>
              <TableCell>{u.email ?? '--'}</TableCell>
              <TableCell>
                <Badge variant={roleBadgeVariant(u.role)}>{u.role}</Badge>
              </TableCell>
              <TableCell>
                {u.is_active ? (
                  <Badge variant="success">active</Badge>
                ) : (
                  <Badge variant="destructive">disabled</Badge>
                )}
              </TableCell>
              <TableCell className="text-right">{u.token_version}</TableCell>
              <TableCell>
                <div className="flex flex-wrap items-center gap-2">
                  <Button
                    size="sm"
                    variant="destructive"
                    data-testid="revoke-session-button"
                    disabled={isSelf || isPending}
                    onClick={() => onRevoke(u.id)}
                    title={isSelf ? '不能撤销自己的会话' : '撤销该用户的所有 token'}
                  >
                    {isPending ? (
                      <Loader2 className="h-3 w-3 animate-spin" />
                    ) : (
                      <ShieldOff className="h-3 w-3" />
                    )}
                    <span className="ml-1">Revoke session</span>
                  </Button>
                  <Button
                    size="sm"
                    variant={u.is_active ? 'outline' : 'default'}
                    data-testid="toggle-active-button"
                    disabled={isSelf || isPending}
                    onClick={() => onToggleActive(u.id)}
                    title={isSelf ? '不能对自己执行此操作' : ''}
                  >
                    {u.is_active ? (
                      <>
                        <ShieldOff className="h-3 w-3" />
                        <span className="ml-1">Disable</span>
                      </>
                    ) : (
                      <>
                        <ShieldCheck className="h-3 w-3" />
                        <span className="ml-1">Enable</span>
                      </>
                    )}
                  </Button>
                </div>
              </TableCell>
            </TableRow>
          );
        })}
      </TableBody>
    </Table>
  );
}

function AuditEventList({ events }: { events: AuditEvent[] }) {
  if (events.length === 0) {
    return (
      <div
        data-testid="admin-audit-empty"
        className="rounded-md border border-border/40 bg-muted/20 px-3 py-6 text-center text-sm text-muted-foreground"
      >
        暂无审计事件。
      </div>
    );
  }
  return (
    <Table data-testid="admin-audit-table">
      <TableHeader>
        <TableRow>
          <TableHead>Timestamp</TableHead>
          <TableHead>Actor</TableHead>
          <TableHead>Action</TableHead>
          <TableHead>Target</TableHead>
          <TableHead>Details</TableHead>
        </TableRow>
      </TableHeader>
      <TableBody>
        {events.map(ev => (
          <TableRow key={ev.event_id} data-testid="admin-audit-row">
            <TableCell className="font-mono text-xs">{formatTimestamp(ev.timestamp)}</TableCell>
            <TableCell>{ev.actor_username}</TableCell>
            <TableCell>
              <Badge variant={actionBadgeVariant(ev.action)}>{ev.action}</Badge>
            </TableCell>
            <TableCell>{ev.target_username ?? '--'}</TableCell>
            <TableCell className="font-mono text-xs">
              {Object.keys(ev.details ?? {}).length > 0
                ? JSON.stringify(ev.details)
                : '--'}
            </TableCell>
          </TableRow>
        ))}
      </TableBody>
    </Table>
  );
}

export function AdminPage() {
  const [users, setUsers] = useState<AdminUserSummary[]>([]);
  const [events, setEvents] = useState<AuditEvent[]>([]);
  const [state, setState] = useState<LoadState>('loading');
  const [error, setError] = useState<string | null>(null);
  const [pendingUserId, setPendingUserId] = useState<number | null>(null);
  const [currentAdminId, setCurrentAdminId] = useState<number | null>(null);

  const reload = async () => {
    setState('loading');
    setError(null);
    try {
      // Resolve the current user id (so the UI can disable self-actions)
      // and the page data in parallel. We don't fail the page if /auth/me
      // is unavailable — the backend enforces self-action rejection
      // independently.
      const [usersRes, auditRes, meRes] = await Promise.allSettled([
        fetchAdminUsers(),
        fetchAuditLog({ limit: 50 }),
        authApi.getMe(),
      ]);
      const firstError =
        usersRes.status === 'rejected' ? usersRes.reason :
        auditRes.status === 'rejected' ? auditRes.reason : null;
      if (firstError) {
        throw firstError;
      }
      setUsers(usersRes.status === 'fulfilled' ? usersRes.value.users : []);
      setEvents(auditRes.status === 'fulfilled' ? auditRes.value.events : []);
      if (meRes.status === 'fulfilled' && typeof meRes.value?.id === 'number') {
        setCurrentAdminId(meRes.value.id);
      }
      setState('ready');
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
      setState('error');
    }
  };

  useEffect(() => {
    void reload();
  }, []);

  const handleRevoke = async (userId: number) => {
    setPendingUserId(userId);
    try {
      await revokeUserSession(userId);
      await reload();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setPendingUserId(null);
    }
  };

  const handleToggleActive = async (userId: number) => {
    setPendingUserId(userId);
    try {
      await toggleUserActive(userId);
      await reload();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setPendingUserId(null);
    }
  };

  // Best-effort: we don't have the current user's id surfaced in the page
  // (no /auth/me wiring here); the backend enforces self-action rejection
  // independently, so we leave `currentAdminId=null` and the UI falls back
  // to backend-side checks.
  return (
    <div className="space-y-6 p-6" data-testid="admin-page">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-semibold">Admin Console</h1>
          <p className="text-sm text-muted-foreground">
            审计日志 / 用户管理 / 会话撤销 ——
            所有操作会被记录到后端 audit-log 环形缓冲 (最多 1000 条)。
          </p>
        </div>
        <Button
          variant="outline"
          size="sm"
          onClick={() => void reload()}
          data-testid="admin-reload-button"
        >
          <RefreshCw className="h-4 w-4" />
          <span className="ml-2">Refresh</span>
        </Button>
      </div>

      {error && (
        <div
          data-testid="admin-error"
          className="flex items-start gap-2 rounded-md border border-red-500/40 bg-red-50/40 px-3 py-2 text-sm text-red-700 dark:bg-red-950/30 dark:text-red-200"
        >
          <AlertTriangle className="h-4 w-4 mt-0.5 shrink-0" />
          <span>{error}</span>
        </div>
      )}

      <Card>
        <CardHeader>
          <CardTitle>Users</CardTitle>
          <CardDescription>
            管理所有用户账户,撤销会话 (下次请求时强制重新登录) 或临时禁用。
          </CardDescription>
        </CardHeader>
        <CardContent>
          {state === 'loading' && users.length === 0 ? (
            <Skeleton className="h-32 w-full" />
          ) : users.length === 0 ? (
            <div className="rounded-md border border-border/40 bg-muted/20 px-3 py-6 text-center text-sm text-muted-foreground">
              系统中尚无用户。
            </div>
          ) : (
            <AdminUsersTable
              users={users}
              currentAdminId={currentAdminId}
              onRevoke={handleRevoke}
              onToggleActive={handleToggleActive}
              pendingUserId={pendingUserId}
            />
          )}
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>Audit Log</CardTitle>
          <CardDescription>
            最近 50 条 admin 操作的环形缓冲。重启后清空,持久化版本是 follow-up 工作。
          </CardDescription>
        </CardHeader>
        <CardContent>
          {state === 'loading' && events.length === 0 ? (
            <Skeleton className="h-32 w-full" />
          ) : (
            <AuditEventList events={events} />
          )}
        </CardContent>
      </Card>
    </div>
  );
}
