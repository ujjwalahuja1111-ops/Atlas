// The freehand product decision — thin typed client for the Event
// Intelligence endpoint, matching the established client pattern.
import { authHeaders as headers, apiFetch } from './http';
import type { AiProposal } from './ops_api';

const BACKEND = process.env.EXPO_PUBLIC_BACKEND_URL;

export type EventPossibleNextActivity = {
  activity_id: string; name: string; ready: boolean; possible_blockers: string[];
};

export type EventPossibleMilestone = {
  milestone_id: string; name: string; status: string; trigger: string | null; contract_value: number | null;
};

export type EventUnderstanding = {
  event_id: string; ai_status: string; summary: string | null; urgency: string | null;
  proposals: AiProposal[];
  possible_next_activity: EventPossibleNextActivity | null;
  possible_milestone: EventPossibleMilestone | null;
};

export async function apiGetEventUnderstanding(eventId: string): Promise<EventUnderstanding | null> {
  const r = await apiFetch(`${BACKEND}/api/events/${eventId}/understanding`, { headers: await headers() });
  if (!r.ok) return null;
  return r.json();
}
