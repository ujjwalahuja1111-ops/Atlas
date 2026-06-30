import AsyncStorage from '@react-native-async-storage/async-storage';

const BACKEND = process.env.EXPO_PUBLIC_BACKEND_URL;
export const APP_VERSION = '2.0.0';

export type Role = 'supervisor' | 'coordinator' | 'management';

export type User = {
  id: string;
  phone: string;
  name: string;
  role: Role;
  created_at: string;
};

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
};

export type AiStatus = 'pending' | 'analyzed' | 'failed' | 'skipped';

export type EventDoc = {
  id: string;
  site_id: string;
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
async function authHeaders(): Promise<Record<string, string>> {
  const token = await AsyncStorage.getItem(TOKEN_KEY);
  return token ? { Authorization: `Bearer ${token}` } : {};
}

export async function apiLogin(phone: string, name: string, role: Role) {
  const r = await fetch(`${BACKEND}/api/auth/login`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ phone, name, role }),
  });
  if (!r.ok) throw new Error('Login failed');
  return (await r.json()) as { token: string; user: User };
}

export async function apiSeedDemo() {
  return fetch(`${BACKEND}/api/projects/seed`, { method: 'POST', headers: await authHeaders() });
}

export async function apiListProjects(includeArchived = false): Promise<Project[]> {
  const qs = includeArchived ? '?include_archived=true' : '';
  const r = await fetch(`${BACKEND}/api/projects${qs}`, { headers: await authHeaders() });
  if (!r.ok) throw new Error('projects');
  return r.json();
}

export async function apiCreateProject(input: { name: string; code?: string; location?: string; image_url?: string }): Promise<Project> {
  const r = await fetch(`${BACKEND}/api/projects`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', ...(await authHeaders()) },
    body: JSON.stringify(input),
  });
  if (!r.ok) throw new Error(await r.text());
  return r.json();
}

export async function apiUpdateProject(id: string, input: Partial<{ name: string; code: string; location: string; image_url: string }>): Promise<Project> {
  const r = await fetch(`${BACKEND}/api/projects/${id}`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json', ...(await authHeaders()) },
    body: JSON.stringify(input),
  });
  if (!r.ok) throw new Error(await r.text());
  return r.json();
}

export async function apiArchiveProject(id: string): Promise<Project> {
  const r = await fetch(`${BACKEND}/api/projects/${id}/archive`, {
    method: 'POST', headers: await authHeaders(),
  });
  if (!r.ok) throw new Error(await r.text());
  return r.json();
}

export async function apiUnarchiveProject(id: string): Promise<Project> {
  const r = await fetch(`${BACKEND}/api/projects/${id}/unarchive`, {
    method: 'POST', headers: await authHeaders(),
  });
  if (!r.ok) throw new Error(await r.text());
  return r.json();
}

export async function apiListSites(projectId?: string): Promise<Site[]> {
  const qs = projectId ? `?project_id=${encodeURIComponent(projectId)}` : '';
  const r = await fetch(`${BACKEND}/api/sites${qs}`, { headers: await authHeaders() });
  if (!r.ok) throw new Error('sites');
  return r.json();
}

export async function apiTimeline(siteId: string): Promise<TimelineItem[]> {
  const r = await fetch(`${BACKEND}/api/timeline?site_id=${encodeURIComponent(siteId)}`, {
    headers: await authHeaders(),
  });
  if (!r.ok) throw new Error('timeline');
  return r.json();
}

export async function apiGetEvent(id: string): Promise<TimelineItem> {
  const r = await fetch(`${BACKEND}/api/events/${id}`, { headers: await authHeaders() });
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
  const r = await fetch(`${BACKEND}/api/events`, {
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
  const r = await fetch(`${BACKEND}/api/events/${eventId}/corrections`, {
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
