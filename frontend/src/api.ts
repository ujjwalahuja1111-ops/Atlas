import AsyncStorage from '@react-native-async-storage/async-storage';
// Sprint 4.1: authHeaders/apiFetch now live in ./http (shared across
// api.ts/ops_api.ts/knowledge_api.ts — audit finding L7 — and apiFetch adds
// global session-expiry handling — audit finding H5). Imported under the
// same local name every existing `await authHeaders()` call site already uses.
import { authHeaders, apiFetch, resetSessionExpiredGuard } from './http';

const BACKEND = process.env.EXPO_PUBLIC_BACKEND_URL;

/** Sprint 6 — root health check, now including whether the AI worker is
 * actually running (see intelligence_engine.is_worker_running()). Used to
 * clearly indicate AI is unavailable instead of polling indefinitely for
 * an ai_status that will never resolve when no API key is configured
 * (Sprint 5.0.2's optional-AI-worker mode). Unauthenticated, matching the
 * existing root endpoint. */
export async function apiGetPlatformStatus(): Promise<{ ai_enabled: boolean }> {
  const r = await fetch(`${BACKEND}/api/`);
  if (!r.ok) return { ai_enabled: true };  // fail open to the existing polling behaviour
  return r.json();
}
export const APP_VERSION = '2.0.0';

export type Role = 'management' | 'project_manager' | 'site_supervisor' | 'client';

export type User = {
  id: string;
  phone: string;
  name: string;
  role: Role;
  created_at: string;
  // Sprint 4.1 — User Management foundation. Optional because pre-existing
  // accounts (created via plain login before this sprint) never had these
  // fields written; the backend defaults a missing value to
  // approved/active/[] on read, and the frontend treats `undefined` the
  // same way (see isApprovedAndActive() below) so this is purely additive.
  approval_status?: 'pending' | 'approved' | 'rejected';
  is_active?: boolean;
  assigned_project_ids?: string[];
  // Sprint 4.3 — Identity & Access Foundation. `workspace` is the
  // admin-assigned UI experience, independent of the automatic role-based
  // derivation in roles.ts (which remains the fallback when this is
  // absent — see completeLoginRouting). `requested_workspace` is the "User
  // Type" collected at Sign Up: purely informational, shown to the admin,
  // never auto-applied. `scope_projects` gates whether this account's
  // project/site visibility is limited to `assigned_project_ids` — absent
  // (every pre-Sprint-4.3 account) means unrestricted, unchanged from
  // today; the frontend never needs to read this directly, it only shapes
  // what the backend's list endpoints return.
  workspace?: 'client' | 'supervisor' | 'pm' | 'admin' | null;
  requested_workspace?: 'client' | 'supervisor' | 'pm' | 'admin' | null;
  scope_projects?: boolean;
};

/** True unless the account is explicitly pending/rejected/deactivated.
 * Missing fields (pre-Sprint-4.1 accounts) default to true, matching the
 * backend's own backward-compatible default. Single source of truth so no
 * screen has to re-derive this logic. */
export function isApprovedAndActive(user: User | null): boolean {
  if (!user) return false;
  if (user.approval_status && user.approval_status !== 'approved') return false;
  if (user.is_active === false) return false;
  return true;
}

export type Project = {
  id: string;
  name: string;
  code: string;
  location: string;
  image_url: string;
  created_at: string;
};

export type Site = {
  id: string;
  project_id: string;
  name: string;
  location: string;
  image_url: string;
  created_at: string;
  archived_at?: string | null;
};

export type ProjectSummary = {
  project: { id: string; name: string; code?: string; location?: string };
  active_sites: number;
  total_sites: number;
  open_tasks: number;
  pending_material_requests: number;
  pending_labour_requests: number;
};

export type AiStatus = 'pending' | 'analyzed' | 'failed' | 'skipped';

export type EventDoc = {
  id: string;
  site_id: string;
  // Sprint 6.1 — Foundation for AI Client Communication. project_id is
  // always populated (denormalized from the site at capture time).
  // activity_id is reserved for future capture flows / AI post-processing
  // to associate an event with a specific Construction Workflow activity
  // — no current UI sets it, so it's usually null.
  project_id: string;
  activity_id: string | null;
  user_id: string;
  user_name: string;
  kind: 'voice' | 'photo' | 'text' | 'mixed';
  text_input: string | null;
  audio_asset_id: string | null;
  photo_asset_ids: string[];
  gps: { lat: number; lng: number; accuracy?: number } | null;
  client_created_at: string | null;
  server_created_at: string;
  app_version: string | null;
  ai_status: AiStatus;
  ai_analysis_id: string | null;
};

export type AiAnalysis = {
  id: string;
  event_id: string;
  transcript: string | null;
  language_detected: string | null;
  structured: {
    type?: string;
    title?: string;
    summary?: string;
    materials?: { name: string; quantity: string | number; unit: string }[];
    issues?: string[];
    work_done?: string[];
    urgency?: 'low' | 'normal' | 'high';
    language_detected?: string;
  } | null;
  evidence: { kind: string; asset_id?: string; sha256?: string; value?: string }[];
  model_versions: { stt: string | null; llm: string | null };
  prompt_version_id: string | null;
  prompt_name: string;
  prompt_version: string;
  started_at: string;
  finished_at: string;
  error: string | null;
};

export type Correction = {
  id: string;
  original_event_id: string;
  corrected_by_user_id: string;
  corrected_by_user_name: string;
  payload: { note: string; corrected_field?: string; new_value?: string; reason?: string };
  created_at: string;
};

export type TimelineItem = {
  event: EventDoc;
  analysis: AiAnalysis | null;
  corrections: Correction[];
  photo_thumbs: { asset_id: string; base64: string }[];
};

const TOKEN_KEY = 'atlas_token';
const USER_KEY = 'atlas_user';
const SITE_KEY = 'atlas_active_site';

export async function saveAuth(token: string, user: User) {
  await AsyncStorage.setItem(TOKEN_KEY, token);
  await AsyncStorage.setItem(USER_KEY, JSON.stringify(user));
  resetSessionExpiredGuard();
}
export async function loadAuth(): Promise<{ token: string | null; user: User | null }> {
  const token = await AsyncStorage.getItem(TOKEN_KEY);
  const userStr = await AsyncStorage.getItem(USER_KEY);
  return { token, user: userStr ? JSON.parse(userStr) : null };
}
export async function clearAuth() {
  await AsyncStorage.removeItem(TOKEN_KEY);
  await AsyncStorage.removeItem(USER_KEY);
}

export async function apiLogin(phone: string, name: string, role: Role) {
  const r = await apiFetch(`${BACKEND}/api/auth/login`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ phone, name, role }),
  });
  if (!r.ok) {
    // FAC-03 P0 fix: login can now genuinely fail for a real, specific
    // reason (unknown phone, pending/rejected account is unaffected here
    // since login itself still succeeds for those - this covers unknown/
    // invalid phone) - surface the backend's actual detail message
    // instead of a generic "Login failed" so it's unambiguous why.
    let detail = 'Login failed';
    try { detail = (await r.json())?.detail || detail; } catch {}
    throw new Error(detail);
  }
  return (await r.json()) as { token: string; user: User };
}

/** Sign Up (Sprint 4.1, extended Sprint 4.3 with "User Type" /
 * requested_workspace). Creates a brand-new, pending account — distinct
 * from apiLogin's upsert-on-first-use behaviour. `requestedWorkspace` is
 * purely informational (shown to the admin, never auto-applied — see
 * memory_engine.register_user). See routes/auth.py `register` for the
 * full rationale. */
export async function apiRegister(
  phone: string, name: string,
  requestedWorkspace?: 'client' | 'supervisor' | 'pm' | 'admin',
) {
  const r = await apiFetch(`${BACKEND}/api/auth/register`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ phone, name, requested_workspace: requestedWorkspace }),
  });
  if (!r.ok) throw new Error(await r.text() || 'Sign up failed');
  return (await r.json()) as { token: string; user: User };
}

export async function apiSeedDemo() {
  return apiFetch(`${BACKEND}/api/projects/seed`, { method: 'POST', headers: await authHeaders() });
}

/** Self-service name edit (Sprint 4.1, audit M4 fix). */
export async function apiUpdateMe(name: string): Promise<User> {
  const r = await apiFetch(`${BACKEND}/api/me`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json', ...(await authHeaders()) },
    body: JSON.stringify({ name }),
  });
  if (!r.ok) throw new Error(await r.text());
  return r.json();
}

/** Sprint 6.2 Founder Verification fix — fetches the CURRENT, authoritative
 * user record from the server. Needed because loadAuth()/getViewRole() only
 * ever read a value cached once at login time (see (tabs)/_layout.tsx) —
 * an admin-assigned workspace/role change was invisible on an already-
 * logged-in device until that device explicitly logged out and back in. */
export async function apiGetMe(): Promise<User> {
  const r = await apiFetch(`${BACKEND}/api/me`, { headers: await authHeaders() });
  if (!r.ok) throw new Error(await r.text());
  return r.json();
}

export async function apiListProjects(includeArchived = false): Promise<Project[]> {
  const qs = includeArchived ? '?include_archived=true' : '';
  const r = await apiFetch(`${BACKEND}/api/projects${qs}`, { headers: await authHeaders() });
  if (!r.ok) throw new Error('projects');
  return r.json();
}

export async function apiCreateProject(input: { name: string; code?: string; location?: string; image_url?: string }): Promise<Project> {
  const r = await apiFetch(`${BACKEND}/api/projects`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', ...(await authHeaders()) },
    body: JSON.stringify(input),
  });
  if (!r.ok) throw new Error(await r.text());
  return r.json();
}

export async function apiUpdateProject(id: string, input: Partial<{ name: string; code: string; location: string; image_url: string }>): Promise<Project> {
  const r = await apiFetch(`${BACKEND}/api/projects/${id}`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json', ...(await authHeaders()) },
    body: JSON.stringify(input),
  });
  if (!r.ok) throw new Error(await r.text());
  return r.json();
}

export async function apiArchiveProject(id: string): Promise<Project> {
  const r = await apiFetch(`${BACKEND}/api/projects/${id}/archive`, {
    method: 'POST', headers: await authHeaders(),
  });
  if (!r.ok) throw new Error(await r.text());
  return r.json();
}

export async function apiUnarchiveProject(id: string): Promise<Project> {
  const r = await apiFetch(`${BACKEND}/api/projects/${id}/unarchive`, {
    method: 'POST', headers: await authHeaders(),
  });
  if (!r.ok) throw new Error(await r.text());
  return r.json();
}

export async function apiDeleteProject(id: string): Promise<{ deleted: boolean; refs?: Record<string, number> }> {
  const r = await apiFetch(`${BACKEND}/api/projects/${id}`, {
    method: 'DELETE', headers: await authHeaders(),
  });
  if (r.status === 409) {
    const body = await r.json();
    return { deleted: false, refs: body?.detail?.refs };
  }
  if (!r.ok) throw new Error(await r.text());
  return r.json();
}

export async function apiListSites(projectId?: string, includeArchived = false): Promise<Site[]> {
  const params = new URLSearchParams();
  if (projectId) params.set('project_id', projectId);
  if (includeArchived) params.set('include_archived', 'true');
  const qs = params.toString() ? `?${params.toString()}` : '';
  const r = await apiFetch(`${BACKEND}/api/sites${qs}`, { headers: await authHeaders() });
  if (!r.ok) throw new Error('sites');
  return r.json();
}

export async function apiCreateSite(input: { project_id: string; name: string; location?: string; image_url?: string }): Promise<Site> {
  const r = await apiFetch(`${BACKEND}/api/sites`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', ...(await authHeaders()) },
    body: JSON.stringify(input),
  });
  if (!r.ok) throw new Error(await r.text());
  return r.json();
}

export async function apiUpdateSite(id: string, input: Partial<{ name: string; location: string; image_url: string }>): Promise<Site> {
  const r = await apiFetch(`${BACKEND}/api/sites/${id}`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json', ...(await authHeaders()) },
    body: JSON.stringify(input),
  });
  if (!r.ok) throw new Error(await r.text());
  return r.json();
}

export async function apiArchiveSite(id: string): Promise<Site> {
  const r = await apiFetch(`${BACKEND}/api/sites/${id}/archive`, {
    method: 'POST', headers: await authHeaders(),
  });
  if (!r.ok) throw new Error(await r.text());
  return r.json();
}

export async function apiUnarchiveSite(id: string): Promise<Site> {
  const r = await apiFetch(`${BACKEND}/api/sites/${id}/unarchive`, {
    method: 'POST', headers: await authHeaders(),
  });
  if (!r.ok) throw new Error(await r.text());
  return r.json();
}

export async function apiDeleteSite(id: string): Promise<{ deleted: boolean; refs?: Record<string, number> }> {
  const r = await apiFetch(`${BACKEND}/api/sites/${id}`, {
    method: 'DELETE', headers: await authHeaders(),
  });
  if (r.status === 409) {
    const body = await r.json();
    return { deleted: false, refs: body?.detail?.refs };
  }
  if (!r.ok) throw new Error(await r.text());
  return r.json();
}

export async function apiProjectSummary(projectId: string): Promise<ProjectSummary> {
  const r = await apiFetch(`${BACKEND}/api/projects/${projectId}/summary`, {
    headers: await authHeaders(),
  });
  if (!r.ok) throw new Error(await r.text());
  return r.json();
}

export async function apiTimeline(siteId: string): Promise<TimelineItem[]> {
  const r = await apiFetch(`${BACKEND}/api/timeline?site_id=${encodeURIComponent(siteId)}`, {
    headers: await authHeaders(),
  });
  if (!r.ok) throw new Error('timeline');
  return r.json();
}

export async function apiGetEvent(id: string): Promise<TimelineItem> {
  const r = await apiFetch(`${BACKEND}/api/events/${id}`, { headers: await authHeaders() });
  if (!r.ok) throw new Error('event');
  return r.json();
}

export async function apiCreateEvent(opts: {
  siteId: string;
  text?: string | null;
  audioUri?: string | null;
  photoUris?: string[];
  gps?: { lat: number; lng: number; accuracy?: number } | null;
}): Promise<EventDoc> {
  const form = new FormData();
  form.append('site_id', opts.siteId);
  if (opts.text) form.append('text', opts.text);
  if (opts.gps) form.append('gps', JSON.stringify(opts.gps));
  form.append('client_created_at', new Date().toISOString());
  form.append('app_version', APP_VERSION);
  if (opts.audioUri) {
    // @ts-ignore RN FormData file shape
    form.append('audio', { uri: opts.audioUri, name: 'voice.m4a', type: 'audio/m4a' });
  }
  for (const uri of opts.photoUris || []) {
    // @ts-ignore RN FormData file shape
    form.append('photos', { uri, name: 'photo.jpg', type: 'image/jpeg' });
  }
  const r = await apiFetch(`${BACKEND}/api/events`, {
    method: 'POST',
    headers: { ...(await authHeaders()) },
    body: form as any,
  });
  if (!r.ok) {
    const t = await r.text();
    throw new Error(t || 'Upload failed');
  }
  return r.json();
}

export async function apiAddCorrection(eventId: string, note: string): Promise<Correction> {
  const r = await apiFetch(`${BACKEND}/api/events/${eventId}/corrections`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', ...(await authHeaders()) },
    body: JSON.stringify({ note }),
  });
  if (!r.ok) throw new Error('correction');
  return r.json();
}

export async function setActiveSite(id: string) {
  await AsyncStorage.setItem(SITE_KEY, id);
}
export async function getActiveSite() {
  return AsyncStorage.getItem(SITE_KEY);
}

const PROJECT_KEY = 'atlas.project';
export async function setActiveProject(id: string) {
  await AsyncStorage.setItem(PROJECT_KEY, id);
}
export async function getActiveProject() {
  return AsyncStorage.getItem(PROJECT_KEY);
}
