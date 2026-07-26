// Commercial reference data and cross-project comparison API functions.
// The commercial reference layer is deliberately NOT a Commercial
// Foundation Engine implementation — see
// memory_engine.set_commercial_reference's own docstring on the
// backend. Used by the Project Dashboard's Commercial section and the
// Admin Dashboard's Portfolio Summary widget.
import { authHeaders, apiFetch } from './http';

const BACKEND = process.env.EXPO_PUBLIC_BACKEND_URL;

export type CommercialReference = {
  project_id: string;
  project_name?: string;
  contract_value?: number;
  approved_variations?: number;
  pending_variations?: number;
  budget?: number;
  current_cost?: number;
  forecast?: number;
  retention_percent?: number;
  advance_percent?: number;
  advance_recovered_percent?: number | null;
  ra_bills_total?: number;
  ra_bills_paid?: number;
  ra_bills_pending?: number;
  ra_bills_under_review?: number;
  cash_flow_signal?: string;
  contract_duration_days?: number;
  current_day?: number;
  progress_percent?: number;
  updated_at?: string;
} | null;

export async function apiGetCommercialReference(projectId: string): Promise<CommercialReference> {
  const r = await apiFetch(`${BACKEND}/api/projects/${projectId}/commercial-reference`, {
    headers: await authHeaders(),
  });
  if (!r.ok) throw new Error('commercial-reference');
  return r.json();
}

export type ComparisonRow = {
  project_id: string;
  project_name: string;
  health: { status: string; score: number; explanation: string[] };
  workflow: { total_activities: number; status_counts: Record<string, number>; blocked: number };
  operations: { total_items: number; open_items: number; status_counts: Record<string, number>; blocked: number; critical_open: number };
  timeline: { event_count: number };
  commercial: CommercialReference;
  schedule_variance_days: number | null;
  forecast_completion: string | null;
  variation_exposure_percent: number | null;
  cash_flow_signal: string | null | undefined;
};

export async function apiCompareProjects(projectIds: string[]): Promise<{ projects: ComparisonRow[] }> {
  const r = await apiFetch(`${BACKEND}/api/portfolio/compare?project_ids=${projectIds.join(',')}`, {
    headers: await authHeaders(),
  });
  if (!r.ok) throw new Error('compare-projects');
  return r.json();
}
