// Project Atlas — Operations (V3) API additions
import { authHeaders as headers, jsonHeaders as jheaders, apiFetch } from './http';
const BACKEND = process.env.EXPO_PUBLIC_BACKEND_URL;

export type OperationalCategory =
  | 'material_requirement' | 'labour_requirement' | 'equipment_requirement'
  | 'client_approval' | 'drawing_request' | 'site_issue'
  | 'quality_observation' | 'safety_observation'
  | 'commitment' | 'inspection' | 'follow_up' | 'general';

export type OperationalStatus =
  | 'open' | 'assigned' | 'acknowledged' | 'in_progress'
  | 'fulfilled' | 'verified' | 'closed' | 'reopened'
  | 'archived' | 'cancelled' | 'duplicate';

export type OperationalHealth =
  | 'on_track' | 'due_soon' | 'overdue' | 'blocked' | 'waiting_external' | 'completed';

export type OperationalItem = {
  id: string;
  category: OperationalCategory;
  title: string;
  description: string;
  site_id: string;
  project_id: string;
  origin_type: string;
  origin_reference_id: string | null;
  inherited_evidence_event_id: string | null;
  status: OperationalStatus;
  priority: 'low' | 'normal' | 'high' | 'critical';
  created_by_user_id: string; created_by_user_name: string;
  assigned_to_user_id: string | null; assigned_to_user_name: string | null;
  assigned_by_user_id: string | null; assigned_by_user_name: string | null;
  completed_by_user_id: string | null; completed_by_user_name: string | null;
  verified_by_user_id: string | null; verified_by_user_name: string | null;
  created_at: string;
  required_by: string | null;
  assigned_at: string | null; started_at: string | null;
  completed_at: string | null; verified_at: string | null; closed_at: string | null;
  blocker: { category: string; note?: string; set_at: string; set_by_user_name?: string } | null;
  health: OperationalHealth;
  last_updated_at: string;
  suggested_owner_role?: string | null;
  ai_confidence?: string | null;
  ai_details?: Record<string, any> | null;
  project_name?: string | null;
  site_name?: string | null;
  metrics: {
    current_age_hours: number | null;
    time_remaining_hours: number | null;
    days_overdue: number;
    time_to_complete_hours: number | null;
    verification_delay_hours: number | null;
  };
};

export type OperationalEvent = {
  id: string;
  operational_item_id: string;
  kind: string;
  actor_user_id: string; actor_user_name: string;
  prev_status: string | null; new_status: string | null;
  payload: any;
  created_at: string;
};

export type AiProposal = {
  id: string;
  event_id: string; site_id: string;
  category: OperationalCategory;
  title: string; description: string;
  suggested_priority: 'low' | 'normal' | 'high' | 'critical';
  suggested_owner_role?: string;
  confidence: 'low' | 'medium' | 'high';
  decision: 'pending' | 'accepted' | 'rejected' | 'edited';
  decided_by_user_name: string | null;
  decided_at: string | null;
  operational_item_id: string | null;
  source_snippet: string;
  details?: Record<string, any>;
  created_at: string;
  project_id?: string | null;
  project_name?: string | null;
  site_name?: string | null;
};

export type AssignableUser = { id: string; name: string; role: string };

export async function apiListUsers(role?: string, projectId?: string): Promise<AssignableUser[]> {
  const params = new URLSearchParams();
  if (role) params.set('role', role);
  if (projectId) params.set('project_id', projectId);
  const qs = params.toString() ? `?${params.toString()}` : '';
  const r = await apiFetch(`${BACKEND}/api/users${qs}`, { headers: await headers() });
  if (!r.ok) throw new Error('users');
  return r.json();
}

export async function apiAssignItem(id: string, assigned_to_user_id: string, note?: string, timeline?: {
  target_start?: string | null; target_finish?: string | null; duration_days?: number | null;
}) {
  const r = await apiFetch(`${BACKEND}/api/operational-items/${id}/assign`, {
    method: 'POST', headers: await jheaders(),
    body: JSON.stringify({ assigned_to_user_id, note, ...(timeline || {}) }),
  });
  if (!r.ok) throw new Error(await r.text());
  return r.json();
}

export type OperationalCenter = {
  open: OperationalItem[];
  overdue: OperationalItem[];
  high_priority: OperationalItem[];
  awaiting_verification: OperationalItem[];
  recently_completed: OperationalItem[];
  recently_updated: OperationalItem[];
  counts: { open: number; overdue: number; high_priority: number; awaiting_verification: number; blocked: number };
};

export async function apiListItems(filter: {
  site_id?: string; status?: string; priority?: string; category?: string; assigned_to_me?: boolean;
} = {}): Promise<OperationalItem[]> {
  const qs = new URLSearchParams();
  for (const [k, v] of Object.entries(filter)) if (v !== undefined && v !== null && v !== '') qs.set(k, String(v));
  const r = await apiFetch(`${BACKEND}/api/operational-items?${qs.toString()}`, { headers: await headers() });
  if (!r.ok) throw new Error('items');
  return r.json();
}

export async function apiGetItem(id: string): Promise<{ item: OperationalItem; history: OperationalEvent[]; evidence: any | null }> {
  const r = await apiFetch(`${BACKEND}/api/operational-items/${id}`, { headers: await headers() });
  if (!r.ok) throw new Error('item');
  return r.json();
}

export async function apiTransitionItem(id: string, to_status: string, note?: string): Promise<OperationalItem> {
  const r = await apiFetch(`${BACKEND}/api/operational-items/${id}/transition`, {
    method: 'POST', headers: await jheaders(),
    body: JSON.stringify({ to_status, note }),
  });
  if (!r.ok) throw new Error(await r.text());
  return r.json();
}

export async function apiCommentItem(id: string, text: string) {
  const r = await apiFetch(`${BACKEND}/api/operational-items/${id}/comments`, {
    method: 'POST', headers: await jheaders(),
    body: JSON.stringify({ text }),
  });
  if (!r.ok) throw new Error(await r.text());
  return r.json();
}

/** Client Approval Workflow — "Request Clarification". Does not change
 * item status; see routes/operational_items.py's request-clarification
 * endpoint. */
export async function apiRequestClarification(id: string, note: string) {
  const r = await apiFetch(`${BACKEND}/api/operational-items/${id}/request-clarification`, {
    method: 'POST', headers: await jheaders(),
    body: JSON.stringify({ note }),
  });
  if (!r.ok) throw new Error(await r.text());
  return r.json();
}

export async function apiSetBlocker(id: string, category: string, note?: string) {
  const r = await apiFetch(`${BACKEND}/api/operational-items/${id}/blocker`, {
    method: 'POST', headers: await jheaders(),
    body: JSON.stringify({ category, note }),
  });
  if (!r.ok) throw new Error(await r.text());
  return r.json();
}

export async function apiClearBlocker(id: string) {
  const r = await apiFetch(`${BACKEND}/api/operational-items/${id}/blocker`, {
    method: 'DELETE', headers: await headers(),
  });
  if (!r.ok) throw new Error(await r.text());
  return r.json();
}

export async function apiOperationalCenter(site_id?: string): Promise<OperationalCenter> {
  const qs = site_id ? `?site_id=${encodeURIComponent(site_id)}` : '';
  const r = await apiFetch(`${BACKEND}/api/operational-center${qs}`, { headers: await headers() });
  if (!r.ok) throw new Error('center');
  return r.json();
}

export async function apiSiteRequirements(site_id: string) {
  const r = await apiFetch(`${BACKEND}/api/sites/${site_id}/requirements`, { headers: await headers() });
  if (!r.ok) throw new Error('requirements');
  return r.json();
}

export async function apiListProposals(filter: { event_id?: string; site_id?: string; status?: string } = {}): Promise<AiProposal[]> {
  const qs = new URLSearchParams();
  for (const [k, v] of Object.entries(filter)) if (v) qs.set(k, String(v));
  const r = await apiFetch(`${BACKEND}/api/ai-proposals?${qs.toString()}`, { headers: await headers() });
  if (!r.ok) throw new Error('proposals');
  return r.json();
}

export type AcceptProposalInput = Partial<Pick<AiProposal, 'title' | 'description' | 'category' | 'suggested_priority'>> & {
  priority?: AiProposal['suggested_priority'];
  required_by?: string;
  assigned_to_user_id?: string;
};

export async function apiAcceptProposal(id: string, edits: AcceptProposalInput = {}) {
  const r = await apiFetch(`${BACKEND}/api/ai-proposals/${id}/accept`, {
    method: 'POST', headers: await jheaders(),
    body: JSON.stringify(edits),
  });
  if (!r.ok) throw new Error(await r.text());
  return r.json();
}

export async function apiRejectProposal(id: string, reason?: string) {
  const r = await apiFetch(`${BACKEND}/api/ai-proposals/${id}/reject`, {
    method: 'POST', headers: await jheaders(),
    body: JSON.stringify({ reason }),
  });
  if (!r.ok) throw new Error(await r.text());
  return r.json();
}

// ---------------- V3.3: edit, voice-update, duplicate ----------------
export type EditItemInput = Partial<{
  title: string;
  description: string;
  priority: 'low' | 'normal' | 'high' | 'critical';
  required_by: string;
  quantity: string;
  unit: string;
  assigned_to_user_id: string;
}>;

export async function apiEditItem(id: string, edits: EditItemInput): Promise<OperationalItem> {
  const r = await apiFetch(`${BACKEND}/api/operational-items/${id}`, {
    method: 'PATCH', headers: await jheaders(),
    body: JSON.stringify(edits),
  });
  if (!r.ok) throw new Error(await r.text());
  return r.json();
}

export type ItemUpdateResult = {
  item: OperationalItem; audio_asset_id: string | null; transcript: string; summary: string | null; language: string | null;
};

export async function apiVoiceUpdate(id: string, audioUri: string): Promise<ItemUpdateResult> {
  const form = new FormData();
  // @ts-ignore RN FormData file shape
  form.append('audio', { uri: audioUri, name: 'voice.m4a', type: 'audio/m4a' });
  const r = await apiFetch(`${BACKEND}/api/operational-items/${id}/voice-update`, {
    method: 'POST', headers: await headers(), body: form as any,
  });
  if (!r.ok) throw new Error(await r.text());
  return r.json();
}

/** FAC-OPS-06 — text sibling of apiVoiceUpdate, same endpoint, same
 * response shape. Support: Voice, Text - "do not build a second
 * recording flow" for voice; text needs no recording at all. */
export async function apiTextUpdate(id: string, text: string): Promise<ItemUpdateResult> {
  const form = new FormData();
  form.append('text', text);
  const r = await apiFetch(`${BACKEND}/api/operational-items/${id}/voice-update`, {
    method: 'POST', headers: await headers(), body: form as any,
  });
  if (!r.ok) throw new Error(await r.text());
  return r.json();
}

export async function apiMarkDuplicate(id: string, duplicate_of_item_id: string, note?: string) {
  const r = await apiFetch(`${BACKEND}/api/operational-items/${id}/duplicate`, {
    method: 'POST', headers: await jheaders(),
    body: JSON.stringify({ duplicate_of_item_id, note }),
  });
  if (!r.ok) throw new Error(await r.text());
  return r.json();
}
