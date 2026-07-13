// Project Atlas — Admin User Management (Sprint 4.1) API additions
import { authHeaders, jsonHeaders, apiFetch } from './http';
import type { Role, User } from './api';

const BACKEND = process.env.EXPO_PUBLIC_BACKEND_URL;

export type ApprovalStatus = 'pending' | 'approved' | 'rejected';

async function handle<T>(r: Response): Promise<T> {
  if (!r.ok) throw new Error(await r.text());
  return r.json();
}

export async function apiListAdminUsers(approvalStatus?: ApprovalStatus): Promise<User[]> {
  const qs = approvalStatus ? `?approval_status=${approvalStatus}` : '';
  const r = await apiFetch(`${BACKEND}/api/admin/users${qs}`, { headers: await authHeaders() });
  return handle(r);
}

export async function apiApproveUser(id: string): Promise<User> {
  const r = await apiFetch(`${BACKEND}/api/admin/users/${id}/approve`, {
    method: 'POST', headers: await authHeaders(),
  });
  return handle(r);
}

export async function apiRejectUser(id: string): Promise<User> {
  const r = await apiFetch(`${BACKEND}/api/admin/users/${id}/reject`, {
    method: 'POST', headers: await authHeaders(),
  });
  return handle(r);
}

export async function apiAssignUserRole(id: string, role: Role): Promise<User> {
  const r = await apiFetch(`${BACKEND}/api/admin/users/${id}/role`, {
    method: 'POST', headers: await jsonHeaders(), body: JSON.stringify({ role }),
  });
  return handle(r);
}

// FAC-04 — Final Authorization Model Freeze: apiAssignUserWorkspace and its
// backend endpoint (POST /api/admin/users/{id}/workspace) are removed.
// Workspace is now a pure, deterministic function of role — assigning a
// role (above) is the only identity-shaping action an admin takes; it
// automatically re-derives and stores the correct workspace, so there is
// no longer a second, independent action that could leave the two out of
// sync.

export async function apiAssignUserProjects(id: string, projectIds: string[]): Promise<User> {
  const r = await apiFetch(`${BACKEND}/api/admin/users/${id}/projects`, {
    method: 'POST', headers: await jsonHeaders(), body: JSON.stringify({ project_ids: projectIds }),
  });
  return handle(r);
}

export async function apiSetUserActive(id: string, isActive: boolean): Promise<User> {
  const r = await apiFetch(`${BACKEND}/api/admin/users/${id}/active`, {
    method: 'POST', headers: await jsonHeaders(), body: JSON.stringify({ is_active: isActive }),
  });
  return handle(r);
}
