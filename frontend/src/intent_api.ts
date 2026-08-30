// Atlas Intent & Orchestration — Phase 1. Thin typed client, matching
// the established pattern (event_intelligence_api.ts).
import { authHeaders as headers, apiFetch } from './http';

const BACKEND = process.env.EXPO_PUBLIC_BACKEND_URL;

export type IntentCandidate = { id: string; name: string };

export type IntentResponse =
  | { type: 'result'; intent: string; project?: { id: string; name: string }; result: { ok: boolean; data?: any; error?: string; partial_errors?: string[] | null } }
  | { type: 'clarification_needed'; question: string; candidates: IntentCandidate[] }
  | { type: 'unresolved'; message: string };

export async function apiPostIntent(text: string, activeProjectId?: string | null): Promise<IntentResponse> {
  const r = await apiFetch(`${BACKEND}/api/intent`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', ...(await headers()) },
    body: JSON.stringify({ text, active_project_id: activeProjectId || null }),
  });
  if (!r.ok) {
    return { type: 'unresolved', message: 'Something went wrong — please try again.' };
  }
  return r.json();
}

/** The clarification round-trip's own completion (spec Item 22) — the
 * user's answer to a just-asked "which project?" question. Resends
 * the original query text with an explicit confirmed_project_id
 * rather than active_project_id, since re-running normal resolution
 * against the same ambiguous mention would simply hit the same
 * ambiguity again. */
export async function apiPostIntentWithConfirmedProject(text: string, confirmedProjectId: string): Promise<IntentResponse> {
  const r = await apiFetch(`${BACKEND}/api/intent`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', ...(await headers()) },
    body: JSON.stringify({ text, confirmed_project_id: confirmedProjectId }),
  });
  if (!r.ok) {
    return { type: 'unresolved', message: 'Something went wrong — please try again.' };
  }
  return r.json();
}
