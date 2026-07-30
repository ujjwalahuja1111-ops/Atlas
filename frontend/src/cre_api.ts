// CRE Integration — thin API wrappers around the EXISTING Construction
// Reasoning Engine endpoints (routes/reasoning.py). This file adds no
// reasoning of its own; every function here just calls an endpoint that
// already exists and types its response.
import { authHeaders, apiFetch } from './http';

const BACKEND = process.env.EXPO_PUBLIC_BACKEND_URL;

async function get<T>(path: string): Promise<T> {
  const r = await apiFetch(`${BACKEND}${path}`, { headers: await authHeaders() });
  if (!r.ok) throw new Error(await r.text());
  return r.json();
}

// ---------------- Client (the one client-callable reasoning view) ----------------
export type ClientDashboard = {
  project_id: string;
  project_name: string;
  stage: { current: string; current_label: string };
  summary_text: string;
  upcoming_milestones: { name: string }[];
  generated_at: string;
};

export async function apiClientDashboard(projectId: string): Promise<ClientDashboard> {
  return get(`/api/projects/${projectId}/client-dashboard`);
}

// ---------------- Internal roles (management / project_manager / site_supervisor) ----------------
export type ProjectHealth = {
  score: number;
  status: 'green' | 'amber' | 'red';
  dimensions: Record<string, { score: number; explanation: string; contributing_factors: any[] }>;
  drivers: string[];
  progress: { activities_total: number; activities_completed: number; percent_complete: number | null };
  open_insights: number;
  computed_at: string;
};

export async function apiProjectHealth(projectId: string): Promise<ProjectHealth> {
  return get(`/api/projects/${projectId}/health`);
}

// Beta-05 — Explain Health. Score/dimensions/drivers reused byte-for-byte
// from ProjectHealth; recommended_actions is the only new composition.
export type RecommendedAction = {
  insight_id: string; rule_id: string; domain: string;
  severity: 'critical' | 'warning' | 'advisory' | 'info';
  observation: string;
  suggested_action: { category: string; title: string; description: string } | null;
  created_at: string;
};

export type ExplainedHealth = ProjectHealth & {
  project_id: string;
  recommended_actions: RecommendedAction[];
  action_currency: { open_insight_count: number; most_recent_insight_at: string | null; note: string };
};

export async function apiExplainHealth(projectId: string): Promise<ExplainedHealth> {
  return get(`/api/projects/${projectId}/explain-health`);
}

export type Insight = {
  id: string;
  rule_id: string;
  domain: string;
  severity: 'critical' | 'warning' | 'advisory' | 'info';
  observation: string;
  risk: string;
  recommendation: string;
  suggested_operational_action: { category: string; title: string; description: string } | null;
  suggested_responsible_role: string | null;
  suggested_due_date: string | null;
  confidence: { level: string; reason: string };
  evidence: Record<string, any>;
  status: string;
  project_stage: string;
  created_at: string;
};
// Dashboard cards built on this type must only ever render observation,
// risk, recommendation, severity, and suggested_* fields — never
// rule_id/confidence/evidence, per "never expose internal CRE evidence,
// rule IDs, confidence or reasoning directly." This endpoint itself
// stays internal-only (routes/reasoning.py's _forbid_client) — the rule
// here is about what a dashboard CARD renders, not the API contract.

export async function apiListInsights(projectId: string, opts?: { status?: string; domain?: string }): Promise<Insight[]> {
  const params = new URLSearchParams();
  if (opts?.status) params.set('status', opts.status);
  if (opts?.domain) params.set('domain', opts.domain);
  const qs = params.toString() ? `?${params.toString()}` : '';
  return get(`/api/projects/${projectId}/insights${qs}`);
}

export type ProjectLookahead = {
  stage: { current: string; current_label: string };
  next_expected: any | null;
  upcoming: { activity_id: string; name: string; ready: boolean; prerequisites: any[]; possible_blockers: string[] }[];
  ready_now: string[];
  in_progress: { activity_id: string; name: string }[];
  blocked: { activity_id: string; name: string; since: string | null }[];
  computed_at: string;
};

export async function apiProjectLookahead(projectId: string): Promise<ProjectLookahead> {
  return get(`/api/projects/${projectId}/lookahead`);
}

export type ProjectForecast = {
  stage: { current: string; current_label: string };
  [k: string]: any;
};

export async function apiProjectForecast(projectId: string): Promise<ProjectForecast> {
  return get(`/api/projects/${projectId}/forecast`);
}

export type ProjectBriefing = {
  project_id: string;
  project_name: string;
  stage: string;
  stage_label: string;
  completed_yesterday: { activity_id: string; name: string; at: string | null }[];
  todays_priorities: { insight_id: string; severity: string; observation: string; recommendation: string; suggested_due_date: string | null }[];
  blocked_activities: { activity_id: string; name: string; since: string | null }[];
  required_decisions: { open_insights_awaiting_review: number; pending_client_approvals: number };
  upcoming_milestones: { activity_id: string; name: string; planned_finish: string | null }[];
  next_expected: any | null;
  client_actions: { item_id: string; title: string; priority: string; status: string; required_by: string | null }[];
  material_risks: { item_id: string; title: string; priority: string; status: string; required_by: string | null }[];
  safety_reminders: { item_id: string; title: string; priority: string; status: string; required_by: string | null }[];
  generated_at: string;
};

export async function apiProjectBriefing(projectId: string): Promise<ProjectBriefing> {
  return get(`/api/projects/${projectId}/briefing`);
}

/** Projected subset of Insight returned by executive_answer's
 * attention_today question (reasoning_engine.py's MongoDB projection
 * explicitly limits the fields to these 7) - deliberately NOT the full
 * Insight type, which has several fields (rule_id, confidence,
 * evidence, status, etc.) this narrower response does not include. */
export type AttentionInsight = {
  id: string;
  project_id: string;
  project_name: string;
  severity: 'critical' | 'warning' | 'advisory' | 'info';
  observation: string;
  recommendation: string;
  suggested_due_date: string | null;
  domain: string;
};

export type ExecutiveAnswer = {
  question: string;
  question_text: string;
  scope: { projects_considered: number };
  // 'answer' shape depends on `question` - reasoning_engine.executive_answer's
  // branches each build a different dict. Typed narrowly for
  // attention_today (the only question CreDashboard.tsx currently uses);
  // other questions' answer shapes are intentionally left as `any` rather
  // than guessed at.
  answer: { items: AttentionInsight[]; total_open_urgent: number } | any;
  explanation: string;
};

export async function apiExecutiveAnswer(question: string): Promise<ExecutiveAnswer> {
  return get(`/api/reasoning/executive?question=${encodeURIComponent(question)}`);
}

// ---------------- Portfolio Control Center (Phase 1 — schedule only) ----------------
export type PortfolioFinancials = {
  enabled: boolean;
  budget: number | null;
  forecast_cost: number | null;
  cost_variance: number | null;
  profitability: number | null;
  cash_flow: number | null;
  cash_flow_signal?: string | null;
};

export type PortfolioProjectRow = {
  project_id: string;
  project_name: string;
  progress_percent: number | null;
  planned_completion: string | null;
  forecast_completion: string | null;
  schedule_variance_days: number | null;
  health_status: 'Healthy' | 'Attention' | 'Critical';
  health_score: number;
  health_explanation: string[];
  critical_issues_count: number;
  open_operational_items: number;
  pending_client_approvals: number;
  critical_operational_items: number;
  overdue_client_approvals: number;
  next_milestone: string | null;
  financials: PortfolioFinancials;
};

export type PortfolioSummary = {
  active_projects: number;
  healthy: number;
  attention: number;
  critical: number;
  projects_behind_schedule: number;
  pending_client_approvals: number;
  critical_operational_items: number;
  total_contract_value: number | null;
  total_forecast_cost: number | null;
  total_outstanding_receivables: number | null;
};

export type PortfolioControlCenter = {
  summary: PortfolioSummary;
  projects: PortfolioProjectRow[];
  generated_at: string;
};

export async function apiPortfolioControlCenter(): Promise<PortfolioControlCenter> {
  return get(`/api/portfolio/control-center`);
}

// Beta-05 continuation — Priority Engine: "Today's Highest Priorities,"
// one ranked, cross-project list.
export type PriorityItem = {
  kind: 'project_health' | 'schedule' | 'approval' | 'commercial' | 'recommended_action';
  project_id: string; project_name: string;
  severity: 'critical' | 'warning' | 'advisory' | 'info';
  title: string; detail: string;
  insight_id?: string;
};

export type PriorityEngineResult = {
  generated_at: string;
  projects_covered: number;
  priorities: PriorityItem[];
};

export async function apiPriorityEngine(): Promise<PriorityEngineResult> {
  return get(`/api/portfolio/priorities`);
}

// Beta-05 final convergence — Cross-Project Intelligence, Commercial
// Intelligence, Executive Timeline, Portfolio Search.
export type RepeatedPattern = {
  rule_id: string; domain: string; description: string; severity: string;
  project_ids: string[]; project_names: string[]; project_count: number;
};

export type CrossProjectIntelligence = {
  generated_at: string; projects_covered: number; repeated_patterns: RepeatedPattern[];
};

export async function apiCrossProjectIntelligence(): Promise<CrossProjectIntelligence> {
  return get(`/api/portfolio/cross-project-intelligence`);
}

export type CommercialIntelligence = {
  generated_at: string;
  projects_with_commercial_data: number;
  projects_over_budget: { project_id: string; project_name: string; variance: number }[];
  projects_approaching_budget: { project_id: string; project_name: string; forecast_cost: number; budget: number }[];
  projects_awaiting_payment: { project_id: string; project_name: string; outstanding: number; upcoming_payment: any }[];
  large_pending_variations: { project_id: string; project_name: string; pending_variations_total: number }[];
  cash_flow_risk: { project_id: string; project_name: string; cash_flow_signal: string }[];
  total_outstanding_portfolio_wide: number;
};

export async function apiCommercialIntelligence(): Promise<CommercialIntelligence> {
  return get(`/api/portfolio/commercial-intelligence`);
}

export type ExecutiveTimelineEvent = {
  project_id: string; project_name: string; source: 'reality' | 'commercial';
  [key: string]: any;
};

export type ExecutiveTimeline = {
  generated_at: string; projects_covered: number; events: ExecutiveTimelineEvent[];
};

export async function apiExecutiveTimeline(params?: { project_id?: string; category?: string }): Promise<ExecutiveTimeline> {
  const qs = new URLSearchParams();
  if (params?.project_id) qs.set('project_id', params.project_id);
  if (params?.category) qs.set('category', params.category);
  const suffix = qs.toString() ? `?${qs.toString()}` : '';
  return get(`/api/portfolio/executive-timeline${suffix}`);
}

export type PortfolioSearchResult = {
  query: string; total_results: number;
  projects: any[]; sites: any[]; activities: any[]; operational_items: any[]; variations: any[]; payments: any[];
};

export async function apiPortfolioSearch(q: string): Promise<PortfolioSearchResult> {
  return get(`/api/portfolio/search?q=${encodeURIComponent(q)}`);
}

/** Triggers a fresh CRE reasoning pass for a project (snapshot -> rules
 * -> persist insights + a reasoning_runs record). Idempotent - rerunning
 * on unchanged state refreshes existing open insights rather than
 * duplicating them. This is the ONLY way GET .../insights (and, in turn,
 * the Highest Risks / Delays / Suggested Actions / Pending Inspections
 * cards below, which all read from the persisted reasoning_insights
 * collection) ever gets populated for a real project - health/lookahead/
 * briefing compute fresh on every read and don't need this, but the
 * insights list does. */
export async function apiRunReasoning(projectId: string): Promise<any> {
  const r = await apiFetch(`${BACKEND}/api/projects/${projectId}/reasoning/run`, {
    method: 'POST', headers: { 'Content-Type': 'application/json', ...(await authHeaders()) },
    body: JSON.stringify({}),
  });
  if (!r.ok) throw new Error(await r.text());
  return r.json();
}
