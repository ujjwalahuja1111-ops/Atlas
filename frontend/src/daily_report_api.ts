// PX-02 Phase 3 — thin typed client for the Daily Site Report routes,
// matching the exact pattern already established in
// notifications_api.ts/commercial_api.ts.
import { authHeaders as headers, apiFetch } from './http';

const BACKEND = process.env.EXPO_PUBLIC_BACKEND_URL;

export type DailyReportMetrics = {
  new_capture_events: number; operational_items_resolved: number; new_blockers_raised: number;
  approvals_completed: number; pending_approvals: number; photos_attached: number;
};

export type DailyReportBlocker = {
  title: string; age: string; impact_category: string; owner?: string;
};

export type DailyReportClientDecision = { title: string; requested_date: string; pending_for: string };
export type DailyReportCommercialAttention = { kind: string; created_at: string };
export type DailyReportForecast = { statement: string; confidence: string };
export type DailyReportPhotoSummary = { count: number; captions: string[]; thumbnail_note: string };

export type DailyReport = {
  project_id: string; project_name: string; date: string; client_safe: boolean;
  executive_summary: string; work_completed_today: string[];
  site_activity_snapshot: DailyReportMetrics; blockers_and_risks: DailyReportBlocker[];
  client_decisions_pending: DailyReportClientDecision[];
  commercial_attention: DailyReportCommercialAttention[];
  ai_forecast_impact: DailyReportForecast; attached_photo_summary: DailyReportPhotoSummary;
  health_status: string; generated_at: string;
};

export async function apiGetTodaysDailyReport(projectId: string, clientSafe = false): Promise<DailyReport> {
  const qs = clientSafe ? '?client_safe=true' : '';
  const r = await apiFetch(`${BACKEND}/api/projects/${projectId}/daily-report/today${qs}`, { headers: await headers() });
  if (!r.ok) throw new Error('daily-report-today');
  return r.json();
}

export async function apiGetDailyReportForDate(projectId: string, date: string, clientSafe = false): Promise<DailyReport> {
  const params = new URLSearchParams({ date });
  if (clientSafe) params.set('client_safe', 'true');
  const r = await apiFetch(`${BACKEND}/api/projects/${projectId}/daily-report?${params.toString()}`, { headers: await headers() });
  if (!r.ok) throw new Error('daily-report');
  return r.json();
}

export async function apiExportDailyReportMarkdown(projectId: string, date: string, clientSafe = false): Promise<string> {
  const params = new URLSearchParams({ date, format: 'md' });
  if (clientSafe) params.set('client_safe', 'true');
  const r = await apiFetch(`${BACKEND}/api/projects/${projectId}/daily-report/export?${params.toString()}`, { headers: await headers() });
  if (!r.ok) throw new Error('daily-report-export');
  return r.text();
}
