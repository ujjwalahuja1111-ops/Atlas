import { useCallback, useEffect, useRef, useState } from 'react';
import {
  View, Text, StyleSheet, ScrollView, Pressable, ActivityIndicator,
  RefreshControl, Alert, Modal, TextInput, KeyboardAvoidingView, Platform,
} from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import { Ionicons } from '@expo/vector-icons';
import { useRouter, useLocalSearchParams } from 'expo-router';
import { theme } from '@/src/theme';
import { getViewRole, type ViewRole } from '@/src/roles';
import { DatePicker } from '@/src/DatePicker';
import {
  apiGetCommercialSummary, apiListCommercialEvents, apiDecideVariation,
  apiCreateContract, apiUpdateContract, apiCreateBudget, apiReviseBudget,
  apiCreateMilestone, apiUpdateMilestone,
  apiCreateVariation, apiSubmitVariation, apiSendVariationForClientReview,
  apiCreatePaymentRequest, apiRecordPayment,
  type CommercialSummary, type CommercialEvent, type Milestone, type PaymentRequest,
  type Payment, type Variation,
} from '@/src/commercial_api';

function formatInr(n: number | null | undefined): string {
  if (n === null || n === undefined) return '—';
  const sign = n < 0 ? '-' : '';
  const abs = Math.abs(n);
  if (abs >= 10000000) return `${sign}₹${(abs / 10000000).toFixed(2)} Cr`;
  if (abs >= 100000) return `${sign}₹${(abs / 100000).toFixed(1)}L`;
  return `${sign}₹${abs.toLocaleString('en-IN')}`;
}

function formatDate(iso: string | null): string {
  if (!iso) return '—';
  try { return new Date(iso).toLocaleDateString(undefined, { year: 'numeric', month: 'short', day: 'numeric' }); }
  catch { return '—'; }
}

const CASH_FLOW_COLOR: Record<string, string> = {
  healthy: theme.color.success, attention: theme.color.warning, critical: theme.color.error,
};

const EVENT_KIND_LABEL: Record<string, string> = {
  contract_created: 'Contract created', contract_revised: 'Contract revised',
  contract_updated: 'Contract terms updated', contract_status_changed: 'Contract status changed',
  variation_submitted: 'Variation submitted', variation_approved: 'Variation approved',
  variation_rejected: 'Variation rejected', payment_requested: 'Payment requested',
  payment_received: 'Payment received', milestone_achieved: 'Milestone completed',
  milestone_created: 'Milestone created', milestone_updated: 'Milestone updated',
  budget_revised: 'Budget revised', budget_created: 'Budget created',
};

const EVENT_KIND_ICON: Record<string, any> = {
  contract_created: 'document-text', contract_revised: 'document-text',
  variation_submitted: 'swap-horizontal', variation_approved: 'checkmark-circle',
  variation_rejected: 'close-circle', payment_requested: 'cash-outline',
  payment_received: 'cash', milestone_achieved: 'flag', budget_updated: 'wallet',
};

type SectionKey = 'contract' | 'budget' | 'milestones' | 'billing' | 'variations' | 'breakdown';

export default function CommercialWorkspaceScreen() {
  const router = useRouter();
  const { id, action, milestoneId, paymentRequestId, variationId } = useLocalSearchParams<{
    id: string; action?: string; milestoneId?: string; paymentRequestId?: string; variationId?: string;
  }>();
  const [viewRole, setViewRole] = useState<ViewRole | null>(null);
  const [summary, setSummary] = useState<CommercialSummary>(null);
  const [events, setEvents] = useState<CommercialEvent[]>([]);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [expanded, setExpanded] = useState<Record<SectionKey, boolean>>({
    contract: true, budget: true, milestones: true, billing: false, variations: true, breakdown: true,
  });
  const [billingView, setBillingView] = useState<'requests' | 'payments'>('requests');
  const [showHistory, setShowHistory] = useState(false);
  const [decidingId, setDecidingId] = useState<string | null>(null);
  const [variationFilter, setVariationFilter] = useState<'all' | 'pending' | 'approved' | 'rejected' | 'implemented'>('all');
  const [prFilter, setPrFilter] = useState<'all' | 'unpaid' | 'paid' | 'overdue'>('all');

  // CP-01 — Commercial Operations Phase I. One generic form driver
  // shared across Contract/Budget/Milestone create and edit, rather
  // than six separate state trees for what is structurally the same
  // "open a modal, edit some fields, save" flow throughout.
  type ActiveForm =
    | { kind: 'create-contract' } | { kind: 'edit-contract' }
    | { kind: 'create-budget' } | { kind: 'edit-budget' }
    | { kind: 'create-milestone' } | { kind: 'edit-milestone'; milestoneId: string }
    | { kind: 'create-variation' }
    | { kind: 'create-payment-request'; milestoneId: string }
    | { kind: 'record-payment'; paymentRequestId: string };
  const [activeForm, setActiveForm] = useState<ActiveForm | null>(null);
  const [formValues, setFormValues] = useState<Record<string, string>>({});
  const [formSaving, setFormSaving] = useState(false);
  const setField = (key: string, value: string) => setFormValues((v) => ({ ...v, [key]: value }));
  const closeForm = () => { setActiveForm(null); setFormValues({}); };

  const load = useCallback(async () => {
    if (!id) return;
    setLoadError(null);
    try {
      const [s, e] = await Promise.all([
        apiGetCommercialSummary(id),
        apiListCommercialEvents(id).catch(() => []),
      ]);
      setSummary(s);
      setEvents(e);
    } catch {
      setLoadError('Could not load commercial data.');
    }
  }, [id]);

  useEffect(() => {
    getViewRole().then(setViewRole);
    (async () => { setLoading(true); await load(); setLoading(false); })();
  }, [load]);

  const deepLinkHandled = useRef(false);
  useEffect(() => {
    if (loading || !action || deepLinkHandled.current) return;
    deepLinkHandled.current = true;

    // create-contract deliberately runs even when summary is null —
    // that IS the no-contract state this specific action exists for.
    if (action === 'create-contract') {
      setFormValues({});
      setActiveForm({ kind: 'create-contract' });
      return;
    }
    if (!summary) return;

    if (action === 'raise-payment-request' && milestoneId) {
      const m = summary.milestones.find((x) => x.id === milestoneId);
      if (m) {
        setFormValues({ amount: String(m.contract_value) });
        setActiveForm({ kind: 'create-payment-request', milestoneId: m.id });
        return;
      }
    }
    if (action === 'record-payment' && paymentRequestId) {
      const pr = summary.payment_requests.find((x) => x.id === paymentRequestId);
      if (pr) {
        setFormValues({ amount: String(pr.amount) });
        setActiveForm({ kind: 'record-payment', paymentRequestId: pr.id });
        return;
      }
    }
    if (action === 'edit-milestone' && milestoneId) {
      const m = summary.milestones.find((x) => x.id === milestoneId);
      if (m) { openEditMilestone(m); return; }
    }
    if (action === 'view-variation' && variationId) {
      // No dedicated variation detail screen exists — reusing the
      // existing Variations section itself, expanded, is the correct
      // "land inside the work" per this task's own "reuse existing
      // navigation" rule rather than building a new detail screen.
      setExpanded((e) => ({ ...e, variations: true }));
      return;
    }
    if (action === 'edit-contract') {
      openEditContract();
      return;
    }
    if (action === 'edit-budget') {
      openEditBudget();
      return;
    }
    if (action === 'create-budget' && !summary.budget) {
      setFormValues({});
      setActiveForm({ kind: 'create-budget' });
      return;
    }
    // Intentional run-once-via-ref pattern (deepLinkHandled); openEdit*
    // are stable enough for this one-time resolution and are not memoized.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [loading, summary, action, milestoneId, paymentRequestId, variationId]);

  const onRefresh = async () => {
    setRefreshing(true);
    await load();
    setRefreshing(false);
  };

  const toggle = (key: SectionKey) => setExpanded((e) => ({ ...e, [key]: !e[key] }));

  const canDecide = viewRole === 'admin' || viewRole === 'pm';

  const onDecide = async (variationId: string, decision: 'approved' | 'rejected') => {
    if (decidingId) return;
    setDecidingId(variationId);
    try {
      await apiDecideVariation(variationId, decision);
      await load();
    } catch (e: any) {
      Alert.alert('Could not update variation', e?.message || 'Please try again.');
    } finally {
      setDecidingId(null);
    }
  };

  const onSubmitVariation = async (variationId: string) => {
    if (decidingId) return;
    setDecidingId(variationId);
    try {
      await apiSubmitVariation(variationId);
      await load();
    } catch (e: any) {
      Alert.alert('Could not submit variation', e?.message || 'Please try again.');
    } finally {
      setDecidingId(null);
    }
  };

  const onSendForReview = async (variationId: string) => {
    if (decidingId) return;
    setDecidingId(variationId);
    try {
      await apiSendVariationForClientReview(variationId);
      await load();
    } catch (e: any) {
      Alert.alert('Could not send for client review', e?.message || 'Please try again.');
    } finally {
      setDecidingId(null);
    }
  };

  const onSaveForm = async () => {
    if (!activeForm || !id) return;
    setFormSaving(true);
    try {
      const num = (key: string) => {
        const v = formValues[key];
        return v && v.trim() !== '' ? Number(v) : undefined;
      };
      switch (activeForm.kind) {
        case 'create-contract':
          await apiCreateContract({
            project_id: id,
            original_contract_value: num('original_contract_value') ?? 0,
            contract_date: formValues.contract_date || new Date().toISOString().slice(0, 10),
            duration_days: num('duration_days') ?? 0,
            retention_percent: num('retention_percent'),
            advance_percent: num('advance_percent'),
            gst_percent: num('gst_percent'),
          });
          break;
        case 'edit-contract':
          await apiUpdateContract(id, {
            duration_days: num('duration_days'),
            retention_percent: num('retention_percent'),
            advance_percent: num('advance_percent'),
            gst_percent: num('gst_percent'),
          });
          break;
        case 'create-budget':
          await apiCreateBudget(id, num('original_budget') ?? 0);
          break;
        case 'edit-budget':
          await apiReviseBudget(id, num('new_current_budget') ?? 0, formValues.reason || '');
          break;
        case 'create-milestone':
          await apiCreateMilestone({
            project_id: id,
            name: formValues.name || '',
            sequence: num('sequence') ?? 1,
            planned_percent: num('planned_percent') ?? 0,
            trigger: formValues.trigger || '',
            planned_date: formValues.planned_date || null,
          });
          break;
        case 'edit-milestone':
          await apiUpdateMilestone(activeForm.milestoneId, {
            name: formValues.name || undefined,
            sequence: num('sequence'),
            planned_percent: num('planned_percent'),
            trigger: formValues.trigger || undefined,
            planned_date: formValues.planned_date || undefined,
          });
          break;
        case 'create-variation':
          await apiCreateVariation({
            project_id: id,
            title: formValues.title || '',
            description: formValues.description || '',
            original_cost: num('original_cost') ?? 0,
            proposed_cost: num('proposed_cost') ?? 0,
            time_impact_days: num('time_impact_days'),
          });
          break;
        case 'create-payment-request':
          await apiCreatePaymentRequest({
            project_id: id,
            milestone_id: activeForm.milestoneId,
            amount: num('amount') ?? 0,
            raised_date: formValues.raised_date || new Date().toISOString().slice(0, 10),
            due_date: formValues.due_date || new Date().toISOString().slice(0, 10),
          });
          break;
        case 'record-payment':
          await apiRecordPayment({
            payment_request_id: activeForm.paymentRequestId,
            amount: num('amount') ?? 0,
            date: formValues.date || new Date().toISOString().slice(0, 10),
            method: formValues.method || 'bank_transfer',
            reference: formValues.reference || '',
          });
          break;
      }
      closeForm();
      await load();
    } catch (e: any) {
      Alert.alert('Could not save', e?.message || 'Please check the values and try again.');
    } finally {
      setFormSaving(false);
    }
  };

  const openEditContract = () => {
    if (!summary?.contract) return;
    setFormValues({
      duration_days: String(summary.contract.duration_days),
      retention_percent: String(summary.contract.retention_percent),
      advance_percent: String(summary.contract.advance_percent),
      gst_percent: String(summary.contract.gst_percent),
    });
    setActiveForm({ kind: 'edit-contract' });
  };

  const openEditBudget = () => {
    if (!summary?.budget) return;
    setFormValues({ new_current_budget: String(summary.budget.current_budget), reason: '' });
    setActiveForm({ kind: 'edit-budget' });
  };

  const openEditMilestone = (m: Milestone) => {
    setFormValues({
      name: m.name, sequence: String(m.sequence), planned_percent: String(m.planned_percent),
      trigger: m.trigger, planned_date: m.planned_date || '',
    });
    setActiveForm({ kind: 'edit-milestone', milestoneId: m.id });
  };

  if (loading) {
    return (
      <SafeAreaView style={styles.center} edges={['top']}>
        <ActivityIndicator color={theme.color.brand} size="large" />
      </SafeAreaView>
    );
  }

  return (
    <SafeAreaView style={styles.container} edges={['top']}>
      <View style={styles.header}>
        <Pressable onPress={() => router.back()} hitSlop={12} testID="workspace-back">
          <Ionicons name="chevron-back" size={26} color={theme.color.text} />
        </Pressable>
        <Text style={styles.headerTitle}>Commercial</Text>
        <View style={{ width: 26 }} />
      </View>

      {loadError ? (
        <Pressable testID="workspace-load-error" onPress={() => { setLoading(true); load().finally(() => setLoading(false)); }} style={styles.errorBanner}>
          <Ionicons name="warning" size={16} color={theme.color.error} />
          <Text style={styles.errorBannerText}>{loadError} Tap to retry.</Text>
        </Pressable>
      ) : null}

      {id && (
        <Pressable testID="legacy-open-full-workspace" onPress={() => router.push(`/projects/${id}/workspace`)} style={styles.legacyBanner}>
          <Text style={styles.legacyBannerText}>Bill Phase • Open Full Workspace</Text>
          <Ionicons name="arrow-forward" size={14} color={theme.color.brand} />
        </Pressable>
      )}

      <ScrollView
        contentContainerStyle={styles.content}
        refreshControl={<RefreshControl refreshing={refreshing} onRefresh={onRefresh} tintColor={theme.color.brand} />}
      >
        {!summary ? (
          <View style={styles.emptyState} testID="workspace-empty">
            <Ionicons name="wallet-outline" size={32} color={theme.color.textDim} />
            <Text style={styles.emptyStateText}>No commercial data for this project yet.</Text>
            {canDecide && (
              <Pressable testID="create-contract-btn" style={styles.primaryBtn}
                onPress={() => { setFormValues({}); setActiveForm({ kind: 'create-contract' }); }}>
                <Text style={styles.primaryBtnText}>Create Contract</Text>
              </Pressable>
            )}
          </View>
        ) : (
          <>
            {/* COMMERCIAL HEALTH — simple rule-based summary reusing
                existing data only: the backend's own cash_flow_signal
                (healthy/attention/critical) plus budget variance when
                a budget exists. No new computation, no AI. */}
            {(() => {
              const cashCritical = summary.cash_flow_signal === 'critical';
              const cashAttention = summary.cash_flow_signal === 'attention';
              const budgetOver = !!summary.budget && summary.budget.variance < 0;
              const healthy = !cashCritical && !cashAttention && !budgetOver;
              return (
                <View style={[styles.healthBanner, healthy ? styles.healthBannerGood : styles.healthBannerAttention]}>
                  <Text style={styles.healthBannerEmoji}>{healthy ? '🟢' : '🟡'}</Text>
                  <View style={{ flex: 1 }}>
                    <Text style={styles.healthBannerTitle}>Commercial Health</Text>
                    <Text style={styles.healthBannerSubtitle}>
                      {healthy ? 'Healthy' : cashCritical ? 'Attention required — cash flow critical'
                        : budgetOver ? 'Attention required — over budget' : 'Attention required — cash flow needs review'}
                    </Text>
                  </View>
                </View>
              );
            })()}

            {/* CASH FLOW — the anchor, per UX-01's own recommendation:
                the single most time-sensitive answer to "is this
                project financially healthy right now" leads the
                screen instead of sitting third. */}
            <Section title="CASH FLOW" icon="trending-up" expanded testID="section-cashflow" onToggle={() => {}} noCollapse>
              <View style={styles.cashFlowRow}>
                <View style={[styles.cashFlowBadge, { backgroundColor: CASH_FLOW_COLOR[summary.cash_flow_signal] || theme.color.textDim }]}>
                  <Text style={styles.cashFlowBadgeText}>{summary.cash_flow_signal.toUpperCase()}</Text>
                </View>
                <View style={{ flex: 1 }}>
                  <Text style={styles.metaText}>Raised: {formatInr(summary.outstanding_payments.raised)}</Text>
                  <Text style={styles.metaText}>Received: {formatInr(summary.outstanding_payments.received)}</Text>
                  <Text style={styles.metaText}>Outstanding: {formatInr(summary.outstanding_payments.outstanding)}</Text>
                </View>
              </View>
              {summary.upcoming_payment ? (
                <View style={styles.upcomingBox}>
                  <Ionicons name="calendar" size={16} color={theme.color.brand} />
                  <Text style={styles.upcomingText}>
                    {formatInr(summary.upcoming_payment.amount)} due {formatDate(summary.upcoming_payment.due_date)}
                    {summary.upcoming_payment.due_after ? ` — after ${summary.upcoming_payment.due_after}` : ''}
                  </Text>
                </View>
              ) : (
                <Text style={styles.mutedText}>No upcoming payment due.</Text>
              )}
            </Section>

            {/* P2-06 — Commercial Breakdown: makes profitability
                understandable from the UI alone, per this task's own
                success criterion. Every figure below is read directly
                from data this screen already loaded (summary.contract,
                summary.budget, summary.approved_variations_total) —
                no new calculation, only a source label naming which
                existing engine each number actually comes from. */}
            <Section title="COMMERCIAL BREAKDOWN" icon="calculator-outline" expanded={expanded.breakdown} onToggle={() => toggle('breakdown')} testID="section-breakdown">
              {(() => {
                const revenueTotal = summary.contract.current_contract_value;
                const budget = summary.budget;
                const forecastCost = budget?.forecast_cost ?? null;
                const forecastProfit = forecastCost !== null ? revenueTotal - forecastCost : null;
                const forecastMargin = forecastProfit !== null && revenueTotal > 0
                  ? (forecastProfit / revenueTotal) * 100 : null;
                return (
                  <View>
                    <BreakdownRow label="Contract Value" value={formatInr(summary.contract.original_contract_value)} source="Contract" />
                    <BreakdownRow label="Approved Variations" value={formatInr(summary.approved_variations_total)} source="Variation Engine" />
                    <BreakdownRow label="Revenue Total" value={formatInr(revenueTotal)} source="Contract" emphasis />
                    <View style={styles.breakdownDivider} />
                    <BreakdownRow label="Budget" value={budget ? formatInr(budget.current_budget) : 'Not Available Yet'} source="Budget Engine" unavailable={!budget} />
                    <BreakdownRow label="Committed Cost" value={budget ? formatInr(budget.committed_cost) : 'Not Available Yet'} source="Expense Ledger" unavailable={!budget} />
                    <BreakdownRow label="Actual Cost" value={budget ? formatInr(budget.actual_cost) : 'Not Available Yet'} source="Expense Ledger" unavailable={!budget} />
                    <View style={styles.breakdownDivider} />
                    <BreakdownRow label="Forecast Cost at Completion" value={forecastCost !== null ? formatInr(forecastCost) : 'Not Available Yet'} source="Forecast Calculation" unavailable={forecastCost === null} />
                    <BreakdownRow label="Forecast Profit" value={forecastProfit !== null ? formatInr(forecastProfit) : 'Not Available Yet'} source="Forecast Calculation" unavailable={forecastProfit === null} emphasis />
                    <BreakdownRow label="Forecast Margin" value={forecastMargin !== null ? `${forecastMargin.toFixed(1)}%` : 'Not Available Yet'} source="Forecast Calculation" unavailable={forecastMargin === null} emphasis />
                    {!budget && (
                      <Text style={styles.mutedText}>Cost figures need a Budget set up for this project — create one in the Budget section below.</Text>
                    )}
                  </View>
                );
              })()}
            </Section>

            {/* CONTRACT — stays highly visible, immediately after Cash Flow */}
            <Section title="CONTRACT" icon="document-text" expanded={expanded.contract} onToggle={() => toggle('contract')} testID="section-contract"
              headerAction={
                <View style={{ flexDirection: 'row', alignItems: 'center', gap: 14 }}>
                  <Pressable testID="explain-contract-btn" onPress={() => router.push(`/explain/contract/${id}?projectId=${id}`)} hitSlop={10}>
                    <Ionicons name="help-circle-outline" size={18} color={theme.color.textDim} />
                  </Pressable>
                  {canDecide && summary.contract.status === 'draft' && (
                    <Pressable testID="edit-contract-btn" onPress={openEditContract} hitSlop={10}>
                      <Ionicons name="create-outline" size={18} color={theme.color.brand} />
                    </Pressable>
                  )}
                </View>
              }>
              <View style={styles.tileGrid}>
                <Tile label="Original Contract Value" value={formatInr(summary.contract.original_contract_value)} />
                <Tile label="Current Contract Value" value={formatInr(summary.contract.current_contract_value)} />
                <Tile label="Approved Variations" value={formatInr(summary.approved_variations_total)} />
                <Tile label="Pending Variations" value={formatInr(summary.pending_variations_total)} />
              </View>
              {summary.contract.current_contract_value !== summary.contract.original_contract_value && (
                <View style={styles.revisionNote}>
                  <Ionicons name="information-circle" size={14} color={theme.color.brand} />
                  <Text style={styles.revisionNoteText}>
                    Contract value changed by {formatInr(summary.contract.current_contract_value - summary.contract.original_contract_value)} through approved variations
                  </Text>
                </View>
              )}
              <View style={styles.metaRow}>
                <Text style={styles.metaText}>Contract Date: {formatDate(summary.contract.contract_date)}</Text>
                <Text style={styles.metaText}>Duration: {summary.contract.duration_days} days</Text>
                <Text style={styles.metaText}>Status: {summary.contract.status}</Text>
              </View>
            </Section>

            {/* BUDGET — internal only, never client-visible; management or PM, matching the backend's own _require_write_access rule exactly */}
            {canDecide && (
              <Section title="BUDGET" icon="wallet" expanded={expanded.budget} onToggle={() => toggle('budget')} testID="section-budget"
                headerAction={
                  summary.budget ? (
                    <Pressable testID="edit-budget-btn" onPress={openEditBudget} hitSlop={10}>
                      <Ionicons name="create-outline" size={18} color={theme.color.brand} />
                    </Pressable>
                  ) : (
                    <Pressable testID="create-budget-btn" onPress={() => { setFormValues({}); setActiveForm({ kind: 'create-budget' }); }} hitSlop={10}>
                      <Ionicons name="add-circle-outline" size={20} color={theme.color.brand} />
                    </Pressable>
                  )
                }>
                {summary.budget ? (
                  <View style={styles.tileGrid}>
                    <Tile label="Budget" value={formatInr(summary.budget.current_budget)} />
                    <Tile label="Forecast Cost" value={formatInr(summary.budget.forecast_cost)} />
                    <Tile label="Actual Cost" value={formatInr(summary.budget.actual_cost)} />
                    <Tile label="Cost Variance" value={formatInr(summary.budget.variance)}
                      negative={summary.budget.variance < 0} />
                    <Tile label="Remaining Budget" value={formatInr(summary.budget.remaining_budget)} />
                    <Tile label="Profitability" value={formatInr(summary.contract.current_contract_value - summary.budget.forecast_cost)} />
                  </View>
                ) : (
                  <Text style={styles.mutedText}>No budget set for this project yet.</Text>
                )}
              </Section>
            )}

            {/* MILESTONES */}
            <Section title="MILESTONES" icon="flag" expanded={expanded.milestones} onToggle={() => toggle('milestones')} testID="section-milestones"
              headerAction={canDecide ? (
                <Pressable testID="create-milestone-btn"
                  onPress={() => { setFormValues({ sequence: String(summary.milestones.length + 1) }); setActiveForm({ kind: 'create-milestone' }); }}
                  hitSlop={10}>
                  <Ionicons name="add-circle-outline" size={20} color={theme.color.brand} />
                </Pressable>
              ) : undefined}>
              {summary.milestones.length === 0 ? (
                <Text style={styles.mutedText}>No milestones yet.</Text>
              ) : (
                summary.milestones
                  .slice()
                  .sort((a, b) => a.sequence - b.sequence)
                  .map((m) => (
                    <MilestoneRow key={m.id} milestone={m}
                      linkedPr={summary.payment_requests.find((pr) => pr.milestone_id === m.id) || null}
                      canEdit={canDecide && m.status === 'pending'} onEdit={() => openEditMilestone(m)}
                      canRaisePr={canDecide}
                      onRaisePr={() => { setFormValues({ amount: String(m.contract_value) }); setActiveForm({ kind: 'create-payment-request', milestoneId: m.id }); }} />
                  ))
              )}
            </Section>

            {/* VARIATIONS */}
            <Section title="VARIATIONS" icon="swap-horizontal" expanded={expanded.variations} onToggle={() => toggle('variations')} testID="section-variations"
              headerAction={canDecide ? (
                <Pressable testID="create-variation-btn"
                  onPress={() => { setFormValues({}); setActiveForm({ kind: 'create-variation' }); }}
                  hitSlop={10}>
                  <Ionicons name="add-circle-outline" size={20} color={theme.color.brand} />
                </Pressable>
              ) : undefined}>
              <FilterRow
                options={[['all', 'All'], ['pending', 'Pending'], ['approved', 'Approved'], ['rejected', 'Rejected'], ['implemented', 'Implemented']]}
                value={variationFilter} onChange={(v) => setVariationFilter(v as any)} testIDPrefix="variation-filter" />
              {filterVariations(summary.variations, variationFilter).length === 0 ? (
                <Text style={styles.mutedText}>No variations match this filter.</Text>
              ) : (
                filterVariations(summary.variations, variationFilter).map((v) => (
                  <VariationCard key={v.id} variation={v} canDecide={canDecide}
                    deciding={decidingId === v.id} onDecide={onDecide}
                    onSubmit={onSubmitVariation} onSendForReview={onSendForReview} />
                ))
              )}
            </Section>

            {/* BILLING — Payment Requests and Payments merged into one
                section with two views, per UX-01's own recommendation:
                these are the same underlying financial relationship
                (money owed, money received) seen from two angles, not
                two separate things. Both original filters and both
                original row types are fully preserved, only the
                container changed. */}
            <Section title="BILLING" icon="cash" expanded={expanded.billing} onToggle={() => toggle('billing')} testID="section-billing">
              <View style={styles.billingToggleRow}>
                <Pressable testID="billing-view-requests" onPress={() => setBillingView('requests')}
                  style={[styles.billingToggleBtn, billingView === 'requests' && styles.billingToggleBtnActive]}>
                  <Text style={[styles.billingToggleText, billingView === 'requests' && styles.billingToggleTextActive]}>Payment Requests</Text>
                </Pressable>
                <Pressable testID="billing-view-payments" onPress={() => setBillingView('payments')}
                  style={[styles.billingToggleBtn, billingView === 'payments' && styles.billingToggleBtnActive]}>
                  <Text style={[styles.billingToggleText, billingView === 'payments' && styles.billingToggleTextActive]}>Payments</Text>
                </Pressable>
              </View>
              {billingView === 'requests' ? (
                <>
                  <FilterRow
                    options={[['all', 'All'], ['unpaid', 'Unpaid'], ['paid', 'Paid'], ['overdue', 'Overdue']]}
                    value={prFilter} onChange={(v) => setPrFilter(v as any)} testIDPrefix="pr-filter" />
                  {filterPaymentRequests(summary.payment_requests, prFilter).length === 0 ? (
                    <Text style={styles.mutedText}>No payment requests match this filter.</Text>
                  ) : (
                    filterPaymentRequests(summary.payment_requests, prFilter).map((pr) => (
                      <PaymentRequestRow key={pr.id} pr={pr} payments={summary.payments}
                        milestone={summary.milestones.find((m) => m.id === pr.milestone_id) || null}
                        canRecord={canDecide}
                        onRecordPayment={() => { setFormValues({ amount: String(pr.amount) }); setActiveForm({ kind: 'record-payment', paymentRequestId: pr.id }); }} />
                    ))
                  )}
                </>
              ) : (
                summary.payments.length === 0 ? (
                  <Text style={styles.mutedText}>No payments recorded yet.</Text>
                ) : (
                  summary.payments
                    .slice()
                    .sort((a, b) => (a.date < b.date ? 1 : -1))
                    .map((p) => <PaymentRow key={p.id} payment={p} />)
                )
              )}
            </Section>

            {/* Commercial Timeline moved behind an explicit action per
                UX-01's own recommendation - the least time-sensitive
                information on this screen, no longer stacked at the
                bottom of every visit. */}
            <Pressable testID="view-history-btn" onPress={() => setShowHistory(true)} style={styles.viewHistoryRow}>
              <Ionicons name="time-outline" size={18} color={theme.color.brand} />
              <Text style={styles.viewHistoryText}>View Commercial History</Text>
              <Ionicons name="chevron-forward" size={16} color={theme.color.textDim} />
            </Pressable>
          </>
        )}
      </ScrollView>

      <Modal visible={showHistory} animationType="slide" transparent onRequestClose={() => setShowHistory(false)} testID="history-modal">
        <View style={styles.modalOverlay}>
          <View style={[styles.modalCard, { maxHeight: '85%' }]}>
            <View style={styles.historyModalHeader}>
              <Text style={styles.modalTitle}>Commercial History</Text>
              <Pressable testID="history-modal-close" onPress={() => setShowHistory(false)} hitSlop={10}>
                <Ionicons name="close" size={22} color={theme.color.text} />
              </Pressable>
            </View>
            <ScrollView>
              {events.length === 0 ? (
                <Text style={styles.mutedText}>No commercial events recorded yet.</Text>
              ) : (
                events.map((e) => <TimelineRow key={e.id} event={e} />)
              )}
            </ScrollView>
          </View>
        </View>
      </Modal>

      <FormModal
        visible={activeForm?.kind === 'create-contract'}
        title="Create Contract" testID="form-create-contract"
        fields={[
          { key: 'original_contract_value', label: 'Contract Value (₹)', keyboardType: 'numeric', placeholder: 'e.g. 3000000' },
          { key: 'contract_date', label: 'Contract Date', type: 'date' },
          { key: 'duration_days', label: 'Duration (days)', keyboardType: 'numeric', placeholder: 'e.g. 180' },
          { key: 'retention_percent', label: 'Retention % (default 5)', keyboardType: 'numeric' },
          { key: 'advance_percent', label: 'Advance % (default 10)', keyboardType: 'numeric' },
          { key: 'gst_percent', label: 'GST % (default 18)', keyboardType: 'numeric' },
        ]}
        values={formValues} onChange={setField} onSave={onSaveForm} onCancel={closeForm} saving={formSaving}
      />

      <FormModal
        visible={activeForm?.kind === 'edit-contract'}
        title="Edit Contract" testID="form-edit-contract"
        fields={[
          { key: 'duration_days', label: 'Duration (days)', keyboardType: 'numeric' },
          { key: 'retention_percent', label: 'Retention %', keyboardType: 'numeric' },
          { key: 'advance_percent', label: 'Advance %', keyboardType: 'numeric' },
          { key: 'gst_percent', label: 'GST %', keyboardType: 'numeric' },
        ]}
        values={formValues} onChange={setField} onSave={onSaveForm} onCancel={closeForm} saving={formSaving}
      />

      <FormModal
        visible={activeForm?.kind === 'create-budget'}
        title="Create Budget" testID="form-create-budget"
        fields={[{ key: 'original_budget', label: 'Original Budget (₹)', keyboardType: 'numeric', placeholder: 'e.g. 2500000' }]}
        values={formValues} onChange={setField} onSave={onSaveForm} onCancel={closeForm} saving={formSaving}
      />

      <FormModal
        visible={activeForm?.kind === 'edit-budget'}
        title="Revise Budget" testID="form-edit-budget"
        fields={[
          { key: 'new_current_budget', label: 'New Budget Amount (₹)', keyboardType: 'numeric' },
          { key: 'reason', label: 'Reason for revision', placeholder: 'e.g. material cost increase' },
        ]}
        values={formValues} onChange={setField} onSave={onSaveForm} onCancel={closeForm} saving={formSaving}
      />

      <FormModal
        visible={activeForm?.kind === 'create-milestone'}
        title="Create Milestone" testID="form-create-milestone"
        fields={[
          { key: 'name', label: 'Milestone Name', placeholder: 'e.g. Foundation Complete' },
          { key: 'sequence', label: 'Sequence', keyboardType: 'numeric' },
          { key: 'planned_percent', label: 'Planned % of Contract Value', keyboardType: 'numeric' },
          { key: 'trigger', label: 'Completion Trigger', placeholder: 'e.g. foundation inspection passed' },
          { key: 'planned_date', label: 'Planned Date', type: 'date' },
        ]}
        values={formValues} onChange={setField} onSave={onSaveForm} onCancel={closeForm} saving={formSaving}
      />

      <FormModal
        visible={activeForm?.kind === 'edit-milestone'}
        title="Edit Milestone" testID="form-edit-milestone"
        fields={[
          { key: 'name', label: 'Milestone Name' },
          { key: 'sequence', label: 'Sequence', keyboardType: 'numeric' },
          { key: 'planned_percent', label: 'Planned % of Contract Value', keyboardType: 'numeric' },
          { key: 'trigger', label: 'Completion Trigger' },
          { key: 'planned_date', label: 'Planned Date', type: 'date' },
        ]}
        values={formValues} onChange={setField} onSave={onSaveForm} onCancel={closeForm} saving={formSaving}
      />

      <FormModal
        visible={activeForm?.kind === 'create-variation'}
        title="Create Variation" testID="form-create-variation"
        fields={[
          { key: 'title', label: 'Title', placeholder: 'e.g. Additional foundation waterproofing' },
          { key: 'description', label: 'Description' },
          { key: 'original_cost', label: 'Original Cost (₹)', keyboardType: 'numeric', placeholder: '0' },
          { key: 'proposed_cost', label: 'Proposed Cost (₹)', keyboardType: 'numeric' },
          { key: 'time_impact_days', label: 'Schedule Impact (days, optional)', keyboardType: 'numeric' },
        ]}
        values={formValues} onChange={setField} onSave={onSaveForm} onCancel={closeForm} saving={formSaving}
      />

      <FormModal
        visible={activeForm?.kind === 'create-payment-request'}
        title="Raise Payment Request" testID="form-create-payment-request"
        fields={[
          { key: 'amount', label: 'Amount (₹)', keyboardType: 'numeric' },
          { key: 'raised_date', label: 'Raised Date', type: 'date' },
          { key: 'due_date', label: 'Due Date', type: 'date' },
        ]}
        values={formValues} onChange={setField} onSave={onSaveForm} onCancel={closeForm} saving={formSaving}
      />

      <FormModal
        visible={activeForm?.kind === 'record-payment'}
        title="Record Payment" testID="form-record-payment"
        fields={[
          { key: 'amount', label: 'Amount (₹)', keyboardType: 'numeric' },
          { key: 'date', label: 'Payment Date', type: 'date' },
          { key: 'method', label: 'Method', placeholder: 'e.g. bank_transfer' },
          { key: 'reference', label: 'Reference (optional)', placeholder: 'e.g. cheque or UTR number' },
        ]}
        values={formValues} onChange={setField} onSave={onSaveForm} onCancel={closeForm} saving={formSaving}
      />
    </SafeAreaView>
  );
}

function filterPaymentRequests(prs: PaymentRequest[], filter: string): PaymentRequest[] {
  const sorted = prs.slice().sort((a, b) => (a.due_date < b.due_date ? -1 : 1));
  if (filter === 'all') return sorted;
  if (filter === 'unpaid') return sorted.filter((pr) => !['paid', 'cancelled'].includes(pr.status));
  if (filter === 'overdue') return sorted.filter((pr) => pr.status === 'overdue');
  return sorted.filter((pr) => pr.status === filter);
}

function filterVariations(vs: Variation[], filter: string): Variation[] {
  if (filter === 'all') return vs;
  if (filter === 'pending') return vs.filter((v) => ['submitted', 'client_review'].includes(v.status));
  return vs.filter((v) => v.status === filter);
}

type FormFieldSpec = {
  key: string; label: string; keyboardType?: 'default' | 'numeric'; placeholder?: string; type?: 'date';
};

function FormModal({ visible, title, fields, values, onChange, onSave, onCancel, saving, testID }: {
  visible: boolean; title: string; fields: FormFieldSpec[]; values: Record<string, string>;
  onChange: (key: string, value: string) => void; onSave: () => void; onCancel: () => void;
  saving: boolean; testID: string;
}) {
  return (
    <Modal visible={visible} animationType="slide" transparent onRequestClose={onCancel} testID={testID}>
      <View style={styles.modalOverlay}>
        <KeyboardAvoidingView behavior={Platform.OS === 'ios' ? 'padding' : undefined} style={styles.modalCard}>
          <Text style={styles.modalTitle}>{title}</Text>
          <ScrollView keyboardShouldPersistTaps="handled">
            {fields.map((f) => (
              <View key={f.key} style={styles.formFieldWrap}>
                {f.type === 'date' ? (
                  <DatePicker
                    label={f.label}
                    testID={`${testID}-${f.key}`}
                    value={values[f.key] || null}
                    onChange={(iso) => onChange(f.key, iso || '')}
                    placeholder={f.placeholder}
                  />
                ) : (
                  <>
                    <Text style={styles.formFieldLabel}>{f.label}</Text>
                    <TextInput
                      testID={`${testID}-${f.key}`}
                      style={styles.formFieldInput}
                      value={values[f.key] ?? ''}
                      onChangeText={(t) => onChange(f.key, t)}
                      keyboardType={f.keyboardType === 'numeric' ? 'decimal-pad' : 'default'}
                      placeholder={f.placeholder}
                      placeholderTextColor={theme.color.textDim}
                    />
                  </>
                )}
              </View>
            ))}
          </ScrollView>
          <View style={styles.modalActions}>
            <Pressable testID={`${testID}-cancel`} onPress={onCancel} style={styles.modalCancelBtn} disabled={saving}>
              <Text style={styles.modalCancelText}>Cancel</Text>
            </Pressable>
            <Pressable testID={`${testID}-save`} onPress={onSave} style={styles.modalSaveBtn} disabled={saving}>
              {saving ? <ActivityIndicator color={theme.color.onBrand} size="small" /> : <Text style={styles.modalSaveText}>Save</Text>}
            </Pressable>
          </View>
        </KeyboardAvoidingView>
      </View>
    </Modal>
  );
}

function Section({ title, icon, expanded, onToggle, children, testID, noCollapse, headerAction }: {
  title: string; icon: any; expanded: boolean; onToggle: () => void; children: React.ReactNode;
  testID: string; noCollapse?: boolean; headerAction?: React.ReactNode;
}) {
  return (
    <View style={styles.section} testID={testID}>
      <Pressable onPress={noCollapse ? undefined : onToggle} style={styles.sectionHeader} disabled={noCollapse}>
        <View style={styles.sectionTitleRow}>
          <Ionicons name={icon} size={16} color={theme.color.brand} />
          <Text style={styles.sectionTitle}>{title}</Text>
        </View>
        <View style={{ flexDirection: 'row', alignItems: 'center', gap: 12 }}>
          {headerAction}
          {!noCollapse && <Ionicons name={expanded ? 'chevron-up' : 'chevron-down'} size={18} color={theme.color.textDim} />}
        </View>
      </Pressable>
      {expanded && <View style={styles.sectionBody}>{children}</View>}
    </View>
  );
}

function Tile({ label, value, negative }: { label: string; value: string; negative?: boolean }) {
  return (
    <View style={styles.tile}>
      <Text style={styles.tileLabel}>{label}</Text>

      <Text style={[styles.tileValue, negative && styles.tileValueNegative]}>{value}</Text>
    </View>
  );
}

function BreakdownRow({ label, value, source, emphasis, unavailable }: {
  label: string; value: string; source: string; emphasis?: boolean; unavailable?: boolean;
}) {
  return (
    <View style={styles.breakdownRow} testID={`breakdown-${label.replace(/\s+/g, '-').toLowerCase()}`}>
      <View style={{ flex: 1 }}>
        <Text style={[styles.breakdownLabel, emphasis && styles.breakdownLabelEmphasis]}>{label}</Text>
        <Text style={styles.breakdownSource}>{source}</Text>
      </View>
      <Text style={[styles.breakdownValue, emphasis && styles.breakdownValueEmphasis, unavailable && styles.breakdownValueUnavailable]}>
        {value}
      </Text>
    </View>
  );
}

function FilterRow({ options, value, onChange, testIDPrefix }: {
  options: [string, string][]; value: string; onChange: (v: string) => void; testIDPrefix: string;
}) {
  return (
    <View style={styles.filterRow}>
      {options.map(([v, label]) => (
        <Pressable key={v} testID={`${testIDPrefix}-${v}`} onPress={() => onChange(v)}
          style={[styles.filterChip, value === v && styles.filterChipActive]}>
          <Text style={[styles.filterChipText, value === v && styles.filterChipTextActive]}>{label}</Text>
        </Pressable>
      ))}
    </View>
  );
}

const MILESTONE_STATUS_LABEL: Record<string, string> = {
  pending: 'Upcoming', ready: 'Upcoming', achieved: 'Completed',
  payment_requested: 'Completed', paid: 'Completed', closed: 'Completed',
};

function MilestoneRow({ milestone, linkedPr, canEdit, onEdit, canRaisePr, onRaisePr }: {
  milestone: Milestone; linkedPr: PaymentRequest | null; canEdit?: boolean; onEdit?: () => void;
  canRaisePr?: boolean; onRaisePr?: () => void;
}) {
  const router = useRouter();
  const done = ['achieved', 'payment_requested', 'paid', 'closed'].includes(milestone.status);
  const canRaise = canRaisePr && milestone.status === 'achieved' && !linkedPr;
  return (
    <View style={styles.row} testID={`milestone-${milestone.id}`}>
      <Ionicons name={done ? 'checkmark-circle' : 'ellipse-outline'} size={18}
        color={done ? theme.color.success : theme.color.textDim} />
      <View style={{ flex: 1, marginLeft: 8 }}>
        <Text style={styles.rowTitle}>{milestone.name}</Text>
        <Text style={styles.rowSubtext}>
          {milestone.planned_percent}% · {formatInr(milestone.contract_value)} · {formatDate(milestone.planned_date)}
          {linkedPr ? ` · ${linkedPr.status}` : ''}
        </Text>
        {canRaise && (
          <Pressable testID={`raise-pr-${milestone.id}`} onPress={onRaisePr} style={styles.raisePrLink}>
            <Text style={styles.raisePrLinkText}>Raise Payment Request</Text>
          </Pressable>
        )}
      </View>
      <Pressable testID={`explain-milestone-${milestone.id}`}
        onPress={() => router.push(`/explain/milestone/${milestone.id}?projectId=${milestone.project_id}`)}
        hitSlop={10} style={{ marginRight: 8 }}>
        <Ionicons name="help-circle-outline" size={18} color={theme.color.textDim} />
      </Pressable>
      {canEdit && (
        <Pressable testID={`edit-milestone-${milestone.id}`} onPress={onEdit} hitSlop={10} style={{ marginRight: 8 }}>
          <Ionicons name="create-outline" size={16} color={theme.color.brand} />
        </Pressable>
      )}
      <Text style={styles.statusPill}>{MILESTONE_STATUS_LABEL[milestone.status] || milestone.status}</Text>
    </View>
  );
}

function PaymentRequestRow({ pr, payments, milestone, canRecord, onRecordPayment }: {
  pr: PaymentRequest; payments: Payment[]; milestone: Milestone | null;
  canRecord?: boolean; onRecordPayment?: () => void;
}) {
  const router = useRouter();
  const paidAmount = payments.filter((p) => p.payment_request_id === pr.id).reduce((s, p) => s + p.amount, 0);
  const remaining = pr.amount - paidAmount;
  const canPay = canRecord && remaining > 0 && !['cancelled', 'draft'].includes(pr.status);
  return (
    <View style={styles.row} testID={`payment-request-${pr.id}`}>
      <View style={{ flex: 1 }}>
        <Text style={styles.rowTitle}>{pr.number} — {formatInr(pr.amount)}</Text>
        <Text style={styles.rowSubtext}>
          Remaining: {formatInr(remaining)} · Due {formatDate(pr.due_date)}
          {milestone ? ` · ${milestone.name}` : ''}
        </Text>
        {canPay && (
          <Pressable testID={`record-payment-${pr.id}`} onPress={onRecordPayment} style={styles.recordPaymentLink}>
            <Text style={styles.recordPaymentLinkText}>Record Payment</Text>
          </Pressable>
        )}
      </View>
      <Pressable testID={`explain-payment-request-${pr.id}`}
        onPress={() => router.push(`/explain/payment_request/${pr.id}?projectId=${pr.project_id}`)}
        hitSlop={10} style={{ marginRight: 8 }}>
        <Ionicons name="help-circle-outline" size={18} color={theme.color.textDim} />
      </Pressable>
      <Text style={[styles.statusPill, pr.status === 'overdue' && styles.statusPillError]}>{pr.status}</Text>
    </View>
  );
}

function PaymentRow({ payment }: { payment: Payment }) {
  const router = useRouter();
  return (
    <View style={styles.row} testID={`payment-${payment.id}`}>
      <Ionicons name="checkmark-circle" size={18} color={theme.color.success} />
      <View style={{ flex: 1, marginLeft: 8 }}>
        <Text style={styles.rowTitle}>{formatInr(payment.amount)}</Text>
        <Text style={styles.rowSubtext}>{formatDate(payment.date)} · {payment.method}{payment.reference ? ` · ${payment.reference}` : ''}</Text>
      </View>
      <Pressable testID={`explain-payment-${payment.id}`}
        onPress={() => router.push(`/explain/payment/${payment.id}?projectId=${payment.project_id}`)}
        hitSlop={10} style={{ marginRight: 8 }}>
        <Ionicons name="help-circle-outline" size={18} color={theme.color.textDim} />
      </Pressable>
      <Text style={styles.statusPill}>{payment.status}</Text>
    </View>
  );
}

function VariationCard({ variation, canDecide, deciding, onDecide, onSubmit, onSendForReview }: {
  variation: Variation; canDecide: boolean; deciding: boolean;
  onDecide: (id: string, decision: 'approved' | 'rejected') => void;
  onSubmit: (id: string) => void; onSendForReview: (id: string) => void;
}) {
  const router = useRouter();
  const pending = ['submitted', 'client_review'].includes(variation.status);
  const afterCost = variation.status === 'approved' ? variation.approved_cost : variation.proposed_cost;
  const costImpact = (afterCost ?? variation.proposed_cost) - variation.original_cost;
  return (
    <View style={styles.variationCard} testID={`variation-${variation.id}`}>
      <View style={{ flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between' }}>
        <Text style={styles.rowTitle}>{variation.title}</Text>
        <Pressable testID={`explain-variation-${variation.id}`}
          onPress={() => router.push(`/explain/variation/${variation.id}?projectId=${variation.project_id}`)}
          hitSlop={10}>
          <Ionicons name="help-circle-outline" size={18} color={theme.color.textDim} />
        </Pressable>
      </View>
      <Text style={styles.rowSubtext}>{variation.description}</Text>
      <View style={styles.variationRow}>
        <Text style={styles.mutedText}>Before: {formatInr(variation.original_cost)}</Text>
        <Ionicons name="arrow-forward" size={12} color={theme.color.textDim} />
        <Text style={styles.rowSubtext}>After: {formatInr(afterCost)}</Text>
      </View>
      <View style={styles.variationImpactRow}>
        <Text style={styles.impactChip}>Cost {formatInr(costImpact)}</Text>
        {variation.time_impact_days > 0 && <Text style={styles.impactChip}>+{variation.time_impact_days}d</Text>}
      </View>
      <Text style={styles.mutedText}>Raised by {variation.raised_by_user_name}{variation.approved_by_user_name ? ` · decided by ${variation.approved_by_user_name}` : ''}</Text>
      {variation.status === 'draft' && canDecide ? (
        <Pressable testID={`variation-submit-${variation.id}`} disabled={deciding}
          onPress={() => onSubmit(variation.id)} style={styles.primaryBtn}>
          <Text style={styles.primaryBtnText}>SUBMIT</Text>
        </Pressable>
      ) : variation.status === 'submitted' && canDecide ? (
        <Pressable testID={`variation-send-review-${variation.id}`} disabled={deciding}
          onPress={() => onSendForReview(variation.id)} style={styles.primaryBtn}>
          <Text style={styles.primaryBtnText}>SEND FOR CLIENT REVIEW</Text>
        </Pressable>
      ) : pending && canDecide ? (
        <View style={styles.variationActionsRow}>
          <Pressable testID={`variation-reject-${variation.id}`} disabled={deciding}
            onPress={() => onDecide(variation.id, 'rejected')} style={styles.rejectButton}>
            <Text style={styles.rejectButtonText}>DECLINE</Text>
          </Pressable>
          <Pressable testID={`variation-approve-${variation.id}`} disabled={deciding}
            onPress={() => onDecide(variation.id, 'approved')} style={styles.approveButton}>
            <Text style={styles.approveButtonText}>APPROVE</Text>
          </Pressable>
        </View>
      ) : (
        <Text style={styles.statusPill}>{variation.status}</Text>
      )}
    </View>
  );
}

function TimelineRow({ event }: { event: CommercialEvent }) {
  return (
    <View style={styles.row} testID={`event-${event.id}`}>
      <Ionicons name={EVENT_KIND_ICON[event.kind] || 'ellipse'} size={16} color={theme.color.brand} />
      <View style={{ flex: 1, marginLeft: 8 }}>
        <Text style={styles.rowTitle}>{EVENT_KIND_LABEL[event.kind] || event.kind}</Text>
        <Text style={styles.rowSubtext}>{formatDate(event.created_at)} · {event.actor_user_name}</Text>
      </View>
    </View>
  );
}

const styles = StyleSheet.create({
  modalOverlay: {
    flex: 1, backgroundColor: 'rgba(0,0,0,0.5)', justifyContent: 'flex-end',
  },
  modalCard: {
    backgroundColor: theme.color.surface2, borderTopLeftRadius: theme.radius.lg,
    borderTopRightRadius: theme.radius.lg, padding: theme.spacing.lg, maxHeight: '80%',
  },
  modalTitle: { color: theme.color.text, fontSize: 17, fontWeight: '800', marginBottom: theme.spacing.md },
  formFieldWrap: { marginBottom: theme.spacing.md },
  formFieldLabel: { color: theme.color.textDim, fontSize: 12, fontWeight: '700', marginBottom: 4 },
  formFieldInput: {
    borderWidth: 1, borderColor: theme.color.border, borderRadius: theme.radius.sm,
    paddingHorizontal: 12, paddingVertical: 10, color: theme.color.text, fontSize: 15,
    backgroundColor: theme.color.surface,
  },
  modalActions: { flexDirection: 'row', gap: theme.spacing.sm, marginTop: theme.spacing.sm },
  modalCancelBtn: {
    flex: 1, paddingVertical: 12, borderRadius: theme.radius.sm, alignItems: 'center',
    borderWidth: 1, borderColor: theme.color.border,
  },
  modalCancelText: { color: theme.color.text, fontWeight: '700' },
  modalSaveBtn: {
    flex: 1, paddingVertical: 12, borderRadius: theme.radius.sm, alignItems: 'center',
    backgroundColor: theme.color.brand,
  },
  modalSaveText: { color: theme.color.onBrand, fontWeight: '700' },
  primaryBtn: {
    marginTop: theme.spacing.md, paddingHorizontal: 20, paddingVertical: 12,
    borderRadius: theme.radius.sm, backgroundColor: theme.color.brand,
  },
  primaryBtnText: { color: theme.color.onBrand, fontWeight: '700' },
  billingToggleRow: { flexDirection: 'row', gap: theme.spacing.sm, marginBottom: theme.spacing.sm },
  billingToggleBtn: {
    flex: 1, paddingVertical: 8, borderRadius: theme.radius.sm, alignItems: 'center',
    borderWidth: 1, borderColor: theme.color.border,
  },
  billingToggleBtnActive: { backgroundColor: theme.color.brand, borderColor: theme.color.brand },
  billingToggleText: { color: theme.color.textDim, fontSize: 13, fontWeight: '700' },
  billingToggleTextActive: { color: theme.color.onBrand },
  viewHistoryRow: {
    flexDirection: 'row', alignItems: 'center', gap: 8, paddingVertical: 14,
    paddingHorizontal: theme.spacing.md, justifyContent: 'center',
  },
  viewHistoryText: { color: theme.color.brand, fontWeight: '700', fontSize: 14 },
  raisePrLink: { marginTop: 4 },
  raisePrLinkText: { color: theme.color.brand, fontSize: 12, fontWeight: '700' },
  revisionNote: {
    flexDirection: 'row', alignItems: 'center', gap: 6, marginTop: 8,
    paddingVertical: 8, paddingHorizontal: 10, backgroundColor: theme.color.surface,
    borderRadius: theme.radius.sm,
  },
  revisionNoteText: { flex: 1, color: theme.color.textDim, fontSize: 12 },
  healthBanner: {
    flexDirection: 'row', alignItems: 'center', gap: theme.spacing.sm,
    marginHorizontal: theme.spacing.md, marginTop: theme.spacing.md,
    padding: theme.spacing.md, borderRadius: theme.radius.md, borderWidth: 1,
  },
  healthBannerGood: { backgroundColor: 'rgba(34,197,94,0.1)', borderColor: theme.color.success },
  healthBannerAttention: { backgroundColor: 'rgba(234,179,8,0.1)', borderColor: theme.color.warning },
  healthBannerEmoji: { fontSize: 24 },
  healthBannerTitle: { color: theme.color.text, fontSize: 14, fontWeight: '800' },
  healthBannerSubtitle: { color: theme.color.textDim, fontSize: 12, marginTop: 2 },
  recordPaymentLink: { marginTop: 4 },
  recordPaymentLinkText: { color: theme.color.brand, fontSize: 12, fontWeight: '700' },
  historyModalHeader: {
    flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between',
    marginBottom: theme.spacing.md,
  },
  container: { flex: 1, backgroundColor: theme.color.surface },
  center: { flex: 1, backgroundColor: theme.color.surface, alignItems: 'center', justifyContent: 'center' },
  header: {
    flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between',
    paddingHorizontal: theme.spacing.lg, paddingVertical: theme.spacing.md,
  },
  headerTitle: { color: theme.color.text, fontSize: 18, fontWeight: '800' },
  content: { padding: theme.spacing.lg, paddingBottom: 60, gap: theme.spacing.md },
  errorBanner: {
    flexDirection: 'row', alignItems: 'center', gap: 8, marginHorizontal: theme.spacing.lg,
    padding: 10, borderRadius: theme.radius.sm, backgroundColor: theme.color.surface2,
  },
  errorBannerText: { color: theme.color.error, fontSize: 13, flex: 1 },
  legacyBanner: {
    flexDirection: 'row', alignItems: 'center', justifyContent: 'center', gap: 6,
    marginHorizontal: theme.spacing.lg, marginTop: 6, paddingVertical: 8,
    borderRadius: theme.radius.sm, backgroundColor: theme.color.surface2,
    borderWidth: 1, borderColor: theme.color.border, borderStyle: 'dashed',
  },
  legacyBannerText: { color: theme.color.brand, fontSize: 12, fontWeight: '700' },
  emptyState: { alignItems: 'center', gap: 10, paddingVertical: 60 },
  emptyStateText: { color: theme.color.textDim, fontSize: 14 },
  section: { backgroundColor: theme.color.surface2, borderRadius: theme.radius.md, overflow: 'hidden' },
  sectionHeader: {
    flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between',
    padding: theme.spacing.md,
  },
  sectionTitleRow: { flexDirection: 'row', alignItems: 'center', gap: 8 },
  sectionTitle: { color: theme.color.text, fontSize: 13, fontWeight: '800', letterSpacing: 0.5 },
  sectionBody: { paddingHorizontal: theme.spacing.md, paddingBottom: theme.spacing.md, gap: 10 },
  tileGrid: { flexDirection: 'row', flexWrap: 'wrap', gap: 10 },
  tile: { minWidth: '46%', backgroundColor: theme.color.surface3, borderRadius: theme.radius.sm, padding: 10 },
  breakdownRow: { flexDirection: 'row', alignItems: 'center', paddingVertical: 8 },
  breakdownLabel: { color: theme.color.text, fontSize: 14, fontWeight: '600' },
  breakdownLabelEmphasis: { fontWeight: '800' },
  breakdownSource: { color: theme.color.textDim, fontSize: 11, marginTop: 2 },
  breakdownValue: { color: theme.color.text, fontSize: 14, fontWeight: '600' },
  breakdownValueEmphasis: { fontSize: 16, fontWeight: '800', color: theme.color.brand },
  breakdownValueUnavailable: { color: theme.color.textDim, fontStyle: 'italic', fontWeight: '400' },
  breakdownDivider: { height: 1, backgroundColor: theme.color.border, marginVertical: 8 },
  tileLabel: { color: theme.color.textDim, fontSize: 10, fontWeight: '800', letterSpacing: 0.3 },
  tileValue: { color: theme.color.text, fontSize: 15, fontWeight: '800', marginTop: 2 },
  tileValueNegative: { color: theme.color.error },
  metaRow: { flexDirection: 'row', flexWrap: 'wrap', gap: 12 },
  metaText: { color: theme.color.textDim, fontSize: 12 },
  mutedText: { color: theme.color.textDim, fontSize: 13 },
  cashFlowRow: { flexDirection: 'row', alignItems: 'flex-start', gap: 12 },
  cashFlowBadge: { paddingHorizontal: 12, paddingVertical: 6, borderRadius: theme.radius.pill },
  cashFlowBadgeText: { color: '#fff', fontSize: 11, fontWeight: '800' },
  upcomingBox: {
    flexDirection: 'row', alignItems: 'center', gap: 8, marginTop: 10, padding: 10,
    backgroundColor: theme.color.brandTint, borderRadius: theme.radius.sm,
    borderWidth: 1, borderColor: theme.color.brand,
  },
  upcomingText: { color: theme.color.text, fontSize: 13, fontWeight: '700', flex: 1 },
  row: { flexDirection: 'row', alignItems: 'center', paddingVertical: 8 },
  rowTitle: { color: theme.color.text, fontSize: 14, fontWeight: '700' },
  rowSubtext: { color: theme.color.textDim, fontSize: 12, marginTop: 2 },
  statusPill: {
    color: theme.color.brand, fontSize: 11, fontWeight: '800', backgroundColor: theme.color.brandTint,
    paddingHorizontal: 8, paddingVertical: 3, borderRadius: theme.radius.pill, overflow: 'hidden',
  },
  statusPillError: { color: theme.color.error },
  filterRow: { flexDirection: 'row', flexWrap: 'wrap', gap: 6 },
  filterChip: {
    paddingHorizontal: 10, paddingVertical: 5, borderRadius: theme.radius.pill,
    borderWidth: 1, borderColor: theme.color.border,
  },
  filterChipActive: { backgroundColor: theme.color.brand, borderColor: theme.color.brand },
  filterChipText: { color: theme.color.textDim, fontSize: 11, fontWeight: '700' },
  filterChipTextActive: { color: theme.color.onBrand },
  variationCard: { backgroundColor: theme.color.surface3, borderRadius: theme.radius.sm, padding: 12, gap: 6 },
  variationRow: { flexDirection: 'row', alignItems: 'center', gap: 8 },
  variationImpactRow: { flexDirection: 'row', gap: 8, flexWrap: 'wrap' },
  impactChip: {
    color: theme.color.brand, fontSize: 11, fontWeight: '800', backgroundColor: theme.color.brandTint,
    paddingHorizontal: 8, paddingVertical: 3, borderRadius: theme.radius.pill, overflow: 'hidden',
  },
  variationActionsRow: { flexDirection: 'row', gap: 8, marginTop: 4 },
  rejectButton: {
    flex: 1, alignItems: 'center', paddingVertical: 10, borderRadius: theme.radius.sm,
    borderWidth: 1, borderColor: theme.color.error,
  },
  rejectButtonText: { color: theme.color.error, fontWeight: '800', fontSize: 12 },
  approveButton: {
    flex: 1, alignItems: 'center', paddingVertical: 10, borderRadius: theme.radius.sm, backgroundColor: theme.color.brand,
  },
  approveButtonText: { color: theme.color.onBrand, fontWeight: '800', fontSize: 12 },
});
