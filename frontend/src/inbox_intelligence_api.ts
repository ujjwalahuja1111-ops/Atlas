// PX-02 Phase 4 — thin typed client for the Inbox Intelligence
// coordination endpoints, matching the established client pattern.
import { authHeaders as headers, apiFetch } from './http';

const BACKEND = process.env.EXPO_PUBLIC_BACKEND_URL;

export type CoordinationCard = {
  entity_type: string | null; entity_id: string | null; count: number;
  latest_title: string; latest_body: string; created_at: string; read: boolean;
  notification_ids: string[]; target_phase: string; project_id: string | null;
  aging_signal: 'green' | 'amber' | 'red';
};

export type CoordinationInbox = {
  action_required: CoordinationCard[];
  waiting_for_you: CoordinationCard[];
  waiting_for_others: CoordinationCard[];
  escalations: CoordinationCard[];
  commercial_attention: CoordinationCard[];
  activity_feed: CoordinationCard[];
};

export type DailyDigest = { summary_lines: string[]; top_priority: string | null; generated_at: string };
export type ManagementDigest = {
  needs_attention_projects: { project_id: string; project_name: string; reason: string; health_status: string }[];
  payment_requests_awaiting_approval: number;
  escalated_blockers_count: number;
  escalated_blockers: { project_id: string; title: string }[];
};

export async function apiGetCoordinationInbox(projectId?: string): Promise<CoordinationInbox> {
  const qs = projectId ? `?project_id=${projectId}` : '';
  const r = await apiFetch(`${BACKEND}/api/inbox/coordination${qs}`, { headers: await headers() });
  if (!r.ok) throw new Error('coordination-inbox');
  return r.json();
}

export async function apiGetDailyDigest(): Promise<DailyDigest> {
  const r = await apiFetch(`${BACKEND}/api/inbox/daily-digest`, { headers: await headers() });
  if (!r.ok) throw new Error('daily-digest');
  return r.json();
}

export async function apiGetManagementDigest(): Promise<ManagementDigest> {
  const r = await apiFetch(`${BACKEND}/api/inbox/management-digest`, { headers: await headers() });
  if (!r.ok) throw new Error('management-digest');
  return r.json();
}
