// P2-09 — thin typed client for the Notification Inbox routes, matching
// the exact pattern already established in ops_api.ts/cre_api.ts.
import { authHeaders as headers, apiFetch } from './http';

const BACKEND = process.env.EXPO_PUBLIC_BACKEND_URL;

export type Notification = {
  id: string; user_id: string; category: string; title: string; body: string;
  project_id: string | null; entity_type: string | null; entity_id: string | null;
  read: boolean; created_at: string; read_at?: string;
};

export async function apiListNotifications(category?: string, unreadOnly?: boolean): Promise<Notification[]> {
  const params = new URLSearchParams();
  if (category && category !== 'all') params.set('category', category);
  if (unreadOnly) params.set('unread_only', 'true');
  const qs = params.toString() ? `?${params.toString()}` : '';
  const r = await apiFetch(`${BACKEND}/api/notifications${qs}`, { headers: await headers() });
  if (!r.ok) throw new Error('notifications');
  return r.json();
}

export async function apiUnreadNotificationCount(): Promise<number> {
  const r = await apiFetch(`${BACKEND}/api/notifications/unread-count`, { headers: await headers() });
  if (!r.ok) throw new Error('unread-count');
  const data = await r.json();
  return data.unread_count;
}

export async function apiMarkNotificationRead(id: string): Promise<Notification> {
  const r = await apiFetch(`${BACKEND}/api/notifications/${id}/read`, { method: 'POST', headers: await headers() });
  if (!r.ok) throw new Error('mark-read');
  return r.json();
}

export async function apiMarkAllNotificationsRead(category?: string): Promise<number> {
  const params = new URLSearchParams();
  if (category && category !== 'all') params.set('category', category);
  const qs = params.toString() ? `?${params.toString()}` : '';
  const r = await apiFetch(`${BACKEND}/api/notifications/read-all${qs}`, { method: 'POST', headers: await headers() });
  if (!r.ok) throw new Error('mark-all-read');
  const data = await r.json();
  return data.marked_read;
}
