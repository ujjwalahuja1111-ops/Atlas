// Project Atlas — Construction Knowledge Core (Sprint 4 / V4) API additions
import AsyncStorage from '@react-native-async-storage/async-storage';
const BACKEND = process.env.EXPO_PUBLIC_BACKEND_URL;
const TOKEN_KEY = 'atlas_token';
async function headers(): Promise<Record<string, string>> {
  const t = await AsyncStorage.getItem(TOKEN_KEY);
  return t ? { Authorization: `Bearer ${t}` } : {};
}
async function jheaders() { return { 'Content-Type': 'application/json', ...(await headers()) }; }

export type KnowledgeType =
  | 'category' | 'phase' | 'activity' | 'checklist_template' | 'required_document';

export type KnowledgeRelationship = {
  id: string;
  type: string;
  target_id: string;
  target_name?: string | null;
  metadata: Record<string, any>;
  created_by_user_id: string;
  created_by_user_name: string;
  created_at: string;
};

export type ChecklistItem = { id: string; text: string };

export type KnowledgeItem = {
  id: string;
  type: KnowledgeType;
  name: string;
  description: string;
  code: string;
  category_id: string | null;
  category_name?: string | null;
  phase_id: string | null;
  phase_name?: string | null;
  tags: string[];
  ai_keywords: string[];
  default_duration_days: number | null;
  checklist_items: ChecklistItem[];
  document_kind: string | null;
  relationships: KnowledgeRelationship[];
  version: number;
  archived_at: string | null;
  created_by_user_id: string; created_by_user_name: string;
  updated_by_user_id: string; updated_by_user_name: string;
  created_at: string; updated_at: string;
};

export type KnowledgeVersion = {
  id: string;
  item_id: string;
  item_type: KnowledgeType;
  version: number;
  snapshot: KnowledgeItem;
  changed_by_user_id: string;
  changed_by_user_name: string;
  created_at: string;
};

export type KnowledgeMeta = { types: KnowledgeType[]; relationship_types: string[] };

export type KnowledgeItemInput = {
  type: KnowledgeType;
  name: string;
  description?: string;
  code?: string;
  category_id?: string | null;
  phase_id?: string | null;
  tags?: string[];
  ai_keywords?: string[];
  default_duration_days?: number | null;
  checklist_items?: ChecklistItem[];
  document_kind?: string | null;
};

export type KnowledgeItemUpdate = Partial<Omit<KnowledgeItemInput, 'type'>>;

export type KnowledgeListFilters = {
  type?: KnowledgeType;
  category_id?: string;
  phase_id?: string;
  tag?: string;
  q?: string;
  include_archived?: boolean;
};

async function handle<T>(r: Response): Promise<T> {
  if (!r.ok) throw new Error(await r.text());
  return r.json();
}

export async function apiListKnowledgeItems(filters: KnowledgeListFilters = {}): Promise<KnowledgeItem[]> {
  const params = new URLSearchParams();
  if (filters.type) params.set('type', filters.type);
  if (filters.category_id) params.set('category_id', filters.category_id);
  if (filters.phase_id) params.set('phase_id', filters.phase_id);
  if (filters.tag) params.set('tag', filters.tag);
  if (filters.q) params.set('q', filters.q);
  if (filters.include_archived) params.set('include_archived', 'true');
  const qs = params.toString() ? `?${params.toString()}` : '';
  const r = await fetch(`${BACKEND}/api/knowledge-items${qs}`, { headers: await headers() });
  return handle(r);
}

export async function apiGetKnowledgeItem(id: string): Promise<KnowledgeItem> {
  const r = await fetch(`${BACKEND}/api/knowledge-items/${id}`, { headers: await headers() });
  return handle(r);
}

export async function apiCreateKnowledgeItem(input: KnowledgeItemInput): Promise<KnowledgeItem> {
  const r = await fetch(`${BACKEND}/api/knowledge-items`, {
    method: 'POST', headers: await jheaders(), body: JSON.stringify(input),
  });
  return handle(r);
}

export async function apiUpdateKnowledgeItem(id: string, input: KnowledgeItemUpdate): Promise<KnowledgeItem> {
  const r = await fetch(`${BACKEND}/api/knowledge-items/${id}`, {
    method: 'PATCH', headers: await jheaders(), body: JSON.stringify(input),
  });
  return handle(r);
}

export async function apiArchiveKnowledgeItem(id: string): Promise<KnowledgeItem> {
  const r = await fetch(`${BACKEND}/api/knowledge-items/${id}/archive`, {
    method: 'POST', headers: await headers(),
  });
  return handle(r);
}

export async function apiUnarchiveKnowledgeItem(id: string): Promise<KnowledgeItem> {
  const r = await fetch(`${BACKEND}/api/knowledge-items/${id}/unarchive`, {
    method: 'POST', headers: await headers(),
  });
  return handle(r);
}

export async function apiListKnowledgeVersions(id: string): Promise<KnowledgeVersion[]> {
  const r = await fetch(`${BACKEND}/api/knowledge-items/${id}/versions`, { headers: await headers() });
  return handle(r);
}

export async function apiAddKnowledgeRelationship(
  id: string, input: { type: string; target_id: string; metadata?: Record<string, any> },
): Promise<KnowledgeItem> {
  const r = await fetch(`${BACKEND}/api/knowledge-items/${id}/relationships`, {
    method: 'POST', headers: await jheaders(), body: JSON.stringify(input),
  });
  return handle(r);
}

export async function apiRemoveKnowledgeRelationship(id: string, relationshipId: string): Promise<KnowledgeItem> {
  const r = await fetch(`${BACKEND}/api/knowledge-items/${id}/relationships/${relationshipId}`, {
    method: 'DELETE', headers: await headers(),
  });
  return handle(r);
}

export async function apiKnowledgeMeta(): Promise<KnowledgeMeta> {
  const r = await fetch(`${BACKEND}/api/knowledge-meta`, { headers: await headers() });
  return handle(r);
}
