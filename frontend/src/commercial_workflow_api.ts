// PX-03 Phase 2 — thin typed client for the Commercial Workflow
// endpoints, matching the established client pattern exactly.
import { authHeaders as headers, apiFetch } from './http';

const BACKEND = process.env.EXPO_PUBLIC_BACKEND_URL;

export type KpiValue = {
  value: number | null;
  calculation: { formula: string; inputs?: Record<string, number | null> };
};

export type ProfitabilityPanel = {
  project_id: string;
  kpis: {
    contract_value: KpiValue; approved_variations: KpiValue; current_revenue_potential: KpiValue;
    budget: KpiValue; actual_expenses: KpiValue; committed_cost: KpiValue; remaining_budget: KpiValue;
    forecast_profit: KpiValue; forecast_margin_percent: KpiValue;
  };
};

export type BillingCollections = {
  billed_to_date: KpiValue; received_to_date: KpiValue;
  outstanding_receivables: KpiValue; collection_efficiency_percent: KpiValue;
};

export type CommercialHealth = { status: 'healthy' | 'attention' | 'risk'; reasons: string[] };

export type CashFlowTimelineItem = { date: string; kind: string; payload: Record<string, any> };

export type ClientSafeBillSummary = {
  project_id: string; approved_contract_amount: number; approved_variations_total: number;
  payment_requests: { number: string; amount: number; status: string; due_date: string | null; raised_date: string | null }[];
  billed_to_date: number; received_to_date: number; outstanding_amount: number;
};

async function get<T>(path: string): Promise<T | null> {
  const r = await apiFetch(`${BACKEND}${path}`, { headers: await headers() });
  if (r.status === 403) return null;
  if (!r.ok) throw new Error(path);
  return r.json();
}

export const apiGetProfitabilityPanel = (projectId: string) =>
  get<ProfitabilityPanel>(`/api/projects/${projectId}/commercial/profitability-panel`);

export const apiGetBillingCollections = (projectId: string) =>
  get<BillingCollections>(`/api/projects/${projectId}/commercial/billing-collections`);

export const apiGetCommercialHealth = (projectId: string) =>
  get<CommercialHealth>(`/api/projects/${projectId}/commercial/health`);

export const apiGetCashFlowTimeline = (projectId: string) =>
  get<CashFlowTimelineItem[]>(`/api/projects/${projectId}/commercial/cash-flow-timeline`);

export const apiGetClientSafeBillSummary = (projectId: string) =>
  get<ClientSafeBillSummary>(`/api/projects/${projectId}/commercial/client-safe-bill-summary`);
