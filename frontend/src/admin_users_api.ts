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
