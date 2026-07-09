// Project Atlas — Admin System Information (Sprint 4.2) API additions
import { authHeaders, apiFetch } from './http';

const BACKEND = process.env.EXPO_PUBLIC_BACKEND_URL;

export type SystemInfo = {
  project_name: string;
  version: string;
  git_commit: string;
  build_date: string;
  server_started_at: string;
  uptime_seconds: number;
  backend_status: string;
  database_status: string;
  total_users: number;
  total_projects: number;
  total_sites: number;
  pending_approvals: number;
};

export async function apiGetSystemInfo(): Promise<SystemInfo> {
  const r = await apiFetch(`${BACKEND}/api/admin/system-info`, { headers: await authHeaders() });
  if (!r.ok) throw new Error(await r.text());
  return r.json();
}
