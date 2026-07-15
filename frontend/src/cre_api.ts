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

export async function apiExecutiveAnswer(question: string): Promise<any> {
  return get(`/api/reasoning/executive?question=${encodeURIComponent(question)}`);
}
