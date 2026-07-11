// Project Atlas — Construction Workflow Engine (Sprint 5) API additions
import { authHeaders, jsonHeaders, apiFetch } from './http';

const BACKEND = process.env.EXPO_PUBLIC_BACKEND_URL;

export type WorkflowStatus = 'not_started' | 'ready' | 'in_progress' | 'blocked' | 'completed';

export type WorkflowDependency = { id: string; name: string; status: WorkflowStatus };

export type WorkflowActivity = {
  id: string;
  project_id: string;
  knowledge_activity_id: string;
  template_id: string;
  template_name: string;
  name: string;
  description: string;
  category_id: string | null;
  phase_id: string | null;
  trade: string | null;
  unit: string | null;
  default_duration_days: number | null;
  requires_inspection: boolean;
  order: number;
  status: WorkflowStatus;
  depends_on_activity_ids: string[];
  depends_on: WorkflowDependency[];
  // Sprint 6.1 — execution targets. Plain ISO date strings (YYYY-MM-DD),
  // nullable, no validation against status — foundation for future delay
  // detection / schedule variance reporting, not that reporting itself.
  planned_start: string | null;
  planned_finish: string | null;
  actual_start: string | null;
  actual_finish: string | null;
  created_at: string;
  updated_at: string;
  status_updated_by_user_id: string;
  status_updated_by_user_name: string;
  status_updated_at: string;
};

async function handle<T>(r: Response): Promise<T> {
  if (!r.ok) throw new Error(await r.text());
  return r.json();
}

export async function apiGenerateWorkflow(projectId: string, templateId: string): Promise<WorkflowActivity[]> {
  const r = await apiFetch(`${BACKEND}/api/projects/${projectId}/workflow/generate`, {
    method: 'POST', headers: await jsonHeaders(), body: JSON.stringify({ template_id: templateId }),
  });
  return handle(r);
}

export async function apiGetWorkflow(projectId: string): Promise<WorkflowActivity[]> {
  const r = await apiFetch(`${BACKEND}/api/projects/${projectId}/workflow`, { headers: await authHeaders() });
  return handle(r);
}

export async function apiSetWorkflowActivityStatus(activityId: string, status: WorkflowStatus): Promise<WorkflowActivity> {
  const r = await apiFetch(`${BACKEND}/api/workflow-activities/${activityId}/status`, {
    method: 'POST', headers: await jsonHeaders(), body: JSON.stringify({ status }),
  });
  return handle(r);
}

/** Sprint 6.1 — Planned/Actual Start/Finish. Any subset of the four
 * fields may be provided; omitted fields are left unchanged (a `null`
 * value explicitly clears that field). */
export type WorkflowScheduleInput = Partial<{
  planned_start: string | null;
  planned_finish: string | null;
  actual_start: string | null;
  actual_finish: string | null;
}>;

export async function apiSetWorkflowActivitySchedule(activityId: string, updates: WorkflowScheduleInput): Promise<WorkflowActivity> {
  const r = await apiFetch(`${BACKEND}/api/workflow-activities/${activityId}/schedule`, {
    method: 'POST', headers: await jsonHeaders(), body: JSON.stringify(updates),
  });
  return handle(r);
}

export async function apiWorkflowMeta(): Promise<{ statuses: WorkflowStatus[] }> {
  const r = await apiFetch(`${BACKEND}/api/workflow-meta`, { headers: await authHeaders() });
  return handle(r);
}

export async function apiSeedDefaultTemplates(): Promise<{ created: string[]; already_existed: string[] }> {
  const r = await apiFetch(`${BACKEND}/api/workflow-templates/seed-defaults`, {
    method: 'POST', headers: await authHeaders(),
  });
  return handle(r);
}
