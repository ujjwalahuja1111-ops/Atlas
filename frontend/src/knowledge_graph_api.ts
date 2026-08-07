// KG-UI-01 — thin typed client for KM-01's own, already-existing
// Knowledge Graph API. No backend change, no new endpoint — this file
// only gives the frontend types and a fetch wrapper matching the
// exact pattern cre_api.ts already established.
import { authHeaders, apiFetch } from './http';

const BACKEND = process.env.EXPO_PUBLIC_BACKEND_URL;

async function get<T>(path: string): Promise<T> {
  const r = await apiFetch(`${BACKEND}${path}`, { headers: await authHeaders() });
  if (!r.ok) throw new Error(await r.text());
  return r.json();
}

export type GraphEdge = {
  entity_type: string;
  entity_id: string;
  label: string;
  relationship: string;
};

export type EntityRelationships = {
  entity_type: string;
  entity_id: string;
  outgoing: GraphEdge[];
  incoming: GraphEdge[];
};

export type ImpactTraceStep = {
  entity_type: string;
  entity_id: string;
  label: string;
  via?: string; // absent only for the origin step
};

export type ImpactTrace = {
  origin: { entity_type: string; entity_id: string };
  chain: ImpactTraceStep[];
  hops_walked: number;
};

export type DecisionTrace = {
  entity_type: string;
  entity_id: string;
  evidence: GraphEdge[];
  commercial_events: {
    id: string; kind: string; entity_type: string; entity_id: string;
    actor_user_name: string; payload: Record<string, any>; created_at: string;
  }[];
};

export async function apiGetEntityRelationships(entityType: string, entityId: string): Promise<EntityRelationships> {
  return get(`/api/knowledge-graph/${entityType}/${entityId}/relationships`);
}

export async function apiGetImpactTrace(eventId: string): Promise<ImpactTrace> {
  return get(`/api/knowledge-graph/events/${eventId}/impact-trace`);
}

export async function apiGetDecisionTrace(entityType: string, entityId: string): Promise<DecisionTrace> {
  return get(`/api/knowledge-graph/${entityType}/${entityId}/decision-trace`);
}
