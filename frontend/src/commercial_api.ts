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

// CF-01 — the real Commercial Foundation Engine's composed summary.
// Returns null for any project without a real Contract yet (the
// engine's own get_project_commercial_summary does this deliberately)
// so callers can fall back to the lightweight CommercialReference
// layer above without treating that as an error.
export type Contract = {
  id: string; project_id: string; client_id: string | null;
  original_contract_value: number; current_contract_value: number; approved_variations_total: number;
  contract_date: string; duration_days: number;
  retention_percent: number; advance_percent: number; gst_percent: number;
  status: string;
};

export type Milestone = {
  id: string; project_id: string; name: string; sequence: number;
  planned_percent: number; contract_value: number; trigger: string;
  planned_date: string | null; forecast_date: string | null; actual_date: string | null;
  status: string;
};

export type PaymentRequest = {
  id: string; project_id: string; number: string; milestone_id: string;
  amount: number; raised_date: string; due_date: string; status: string; notes: string;
};

export type Payment = {
  id: string; payment_request_id: string; project_id: string;
  amount: number; date: string; method: string; reference: string; status: string;
};

export type Variation = {
  id: string; project_id: string; title: string; description: string;
  original_cost: number; proposed_cost: number; approved_cost: number | null;
  time_impact_days: number; status: string;
  raised_by_user_name: string; approved_by_user_name: string | null;
};

export type Budget = {
  id: string; project_id: string;
  original_budget: number; current_budget: number; committed_cost: number; actual_cost: number;
  forecast_cost: number; variance: number; remaining_budget: number;
};

export type UpcomingPayment = {
  amount: number; due_date: string; due_after: string | null; payment_request_id: string;
} | null;

export type CommercialSummary = {
  project_id: string;
  contract: Contract;
  budget: Budget | null;
  milestones: Milestone[];
  milestone_completion_percent: number;
  payment_requests: PaymentRequest[];
  payments: Payment[];
  outstanding_payments: { raised: number; received: number; outstanding: number };
  cash_flow_signal: string;
  upcoming_payment: UpcomingPayment;
  variations: Variation[];
  approved_variations_total: number;
  pending_variations_total: number;
} | null;

export async function apiGetCommercialSummary(projectId: string): Promise<CommercialSummary> {
  const r = await apiFetch(`${BACKEND}/api/projects/${projectId}/commercial/summary`, {
    headers: await authHeaders(),
  });
  if (!r.ok) throw new Error('commercial-summary');
  return r.json();
}

// ---------------------------------------------------------------------------
// CP-01 — Commercial Operations Phase I: Contract, Budget, Milestone
// create/edit. Viewing reuses apiGetCommercialSummary above (contract,
// budget, and milestones are all already part of that response) — no
// separate GET functions needed for this slice.
// ---------------------------------------------------------------------------

export type ContractCreateInput = {
  project_id: string; client_id?: string | null;
  original_contract_value: number; contract_date: string; duration_days: number;
  retention_percent?: number; advance_percent?: number; gst_percent?: number;
};

export async function apiCreateContract(input: ContractCreateInput): Promise<Contract> {
  const r = await apiFetch(`${BACKEND}/api/commercial/contracts`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', ...(await authHeaders()) },
    body: JSON.stringify(input),
  });
  if (!r.ok) throw new Error('create-contract');
  return r.json();
}

export type ContractUpdateInput = {
  duration_days?: number; retention_percent?: number; advance_percent?: number; gst_percent?: number;
};

export async function apiUpdateContract(projectId: string, input: ContractUpdateInput): Promise<Contract> {
  const r = await apiFetch(`${BACKEND}/api/projects/${projectId}/commercial/contract`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json', ...(await authHeaders()) },
    body: JSON.stringify(input),
  });
  if (!r.ok) throw new Error('update-contract');
  return r.json();
}

export async function apiTransitionContractStatus(projectId: string, status: string): Promise<Contract> {
  const r = await apiFetch(`${BACKEND}/api/projects/${projectId}/commercial/contract/status`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', ...(await authHeaders()) },
    body: JSON.stringify({ status }),
  });
  if (!r.ok) throw new Error('transition-contract-status');
  return r.json();
}

export async function apiCreateBudget(projectId: string, originalBudget: number): Promise<Budget> {
  const r = await apiFetch(`${BACKEND}/api/commercial/budgets`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', ...(await authHeaders()) },
    body: JSON.stringify({ project_id: projectId, original_budget: originalBudget }),
  });
  if (!r.ok) throw new Error('create-budget');
  return r.json();
}

export async function apiReviseBudget(projectId: string, newCurrentBudget: number, reason: string): Promise<Budget> {
  const r = await apiFetch(`${BACKEND}/api/projects/${projectId}/commercial/budget/revise`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', ...(await authHeaders()) },
    body: JSON.stringify({ new_current_budget: newCurrentBudget, reason }),
  });
  if (!r.ok) throw new Error('revise-budget');
  return r.json();
}

export type MilestoneCreateInput = {
  project_id: string; name: string; sequence: number;
  planned_percent: number; trigger: string; planned_date?: string | null;
};

export async function apiCreateMilestone(input: MilestoneCreateInput): Promise<Milestone> {
  const r = await apiFetch(`${BACKEND}/api/commercial/milestones`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', ...(await authHeaders()) },
    body: JSON.stringify(input),
  });
  if (!r.ok) throw new Error('create-milestone');
  return r.json();
}

export type MilestoneUpdateInput = {
  name?: string; sequence?: number; planned_percent?: number; trigger?: string; planned_date?: string | null;
};

export async function apiUpdateMilestone(milestoneId: string, input: MilestoneUpdateInput): Promise<Milestone> {
  const r = await apiFetch(`${BACKEND}/api/commercial/milestones/${milestoneId}`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json', ...(await authHeaders()) },
    body: JSON.stringify(input),
  });
  if (!r.ok) throw new Error('update-milestone');
  return r.json();
}

// ---------------------------------------------------------------------------
// Client Experience Layer (CX-01) — thin, client-safe views over the
// same commercial_engine data above. Never includes Budget/Forecast/
// internal cost fields — see reasoning_engine.client_investment_summary's
// own docstring on the backend for why those are never even read here,
// not merely filtered out.
// ---------------------------------------------------------------------------

export type ClientInvestmentSummary = {
  project_id: string;
  contract_value: number;
  paid: number;
  outstanding: number;
  current_variation_total: number;
  upcoming_payment: { amount: number; due_date: string; due_after: string | null } | null;
} | null;

export async function apiGetClientInvestment(projectId: string): Promise<ClientInvestmentSummary> {
  const r = await apiFetch(`${BACKEND}/api/projects/${projectId}/client-investment`, {
    headers: await authHeaders(),
  });
  if (!r.ok) throw new Error('client-investment');
  return r.json();
}

export type PaymentJourneyStep = {
  milestone_id: string;
  name: string;
  sequence: number;
  milestone_status: string;
  payment_status: string | null;
  amount: number;
  planned_date: string | null;
  actual_date: string | null;
};

export type ClientPaymentJourney = {
  project_id: string;
  contract_value: number;
  steps: PaymentJourneyStep[];
} | null;

export async function apiGetClientPaymentJourney(projectId: string): Promise<ClientPaymentJourney> {
  const r = await apiFetch(`${BACKEND}/api/projects/${projectId}/client-payment-journey`, {
    headers: await authHeaders(),
  });
  if (!r.ok) throw new Error('client-payment-journey');
  return r.json();
}

export type ClientVariationView = {
  id: string; title: string; description: string;
  before_cost: number; after_cost: number;
  impact: { cost_impact: number; schedule_impact_days: number; payment_impact: number; forecast_impact: number };
  linked_drawing_ids: string[]; linked_photo_ids: string[]; linked_quotation_ids: string[];
  status: string; raised_by: string; decided_at: string | null; approved_by: string | null;
};

export type ClientVariationCentre = {
  project_id: string;
  pending: ClientVariationView[];
  history: ClientVariationView[];
} | null;

export async function apiGetClientVariationCentre(projectId: string): Promise<ClientVariationCentre> {
  const r = await apiFetch(`${BACKEND}/api/projects/${projectId}/client-variations`, {
    headers: await authHeaders(),
  });
  if (!r.ok) throw new Error('client-variations');
  return r.json();
}

export async function apiDecideVariation(variationId: string, decision: 'approved' | 'rejected'): Promise<ClientVariationView> {
  const r = await apiFetch(`${BACKEND}/api/commercial/variations/${variationId}/decide`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', ...(await authHeaders()) },
    body: JSON.stringify({ decision }),
  });
  if (!r.ok) throw new Error('decide-variation');
  return r.json();
}

// Beta-01 — a factual, data-driven activity rollup replacing the
// client dashboard's previous permanent "AI summaries coming soon"
// placeholder. No AI, no new engine — a count of real events already
// stored, in the last N days.
export type ClientRecentActivity = {
  project_id: string;
  period_days: number;
  activities_completed: number;
  photos_captured: number;
  voice_updates: number;
  payments_received: number;
  variations_decided: number;
  has_activity: boolean;
};

export async function apiGetClientRecentActivity(projectId: string): Promise<ClientRecentActivity> {
  const r = await apiFetch(`${BACKEND}/api/projects/${projectId}/client-recent-activity`, {
    headers: await authHeaders(),
  });
  if (!r.ok) throw new Error('client-recent-activity');
  return r.json();
}

// Beta-02 — Commercial Timeline. The one piece of Commercial Foundation
// data not already included in commercial/summary.
export type CommercialEvent = {
  id: string; project_id: string; kind: string;
  entity_type: string; entity_id: string;
  actor_user_id: string; actor_user_name: string;
  payload: Record<string, any>; created_at: string;
};

export async function apiListCommercialEvents(projectId: string): Promise<CommercialEvent[]> {
  const r = await apiFetch(`${BACKEND}/api/projects/${projectId}/commercial/events`, {
    headers: await authHeaders(),
  });
  if (!r.ok) throw new Error('commercial-events');
  return r.json();
}

