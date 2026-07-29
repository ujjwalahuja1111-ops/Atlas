import { useCallback, useEffect, useState } from 'react';
import {
  View, Text, StyleSheet, ScrollView, Pressable, ActivityIndicator,
  RefreshControl, Alert,
} from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import { Ionicons } from '@expo/vector-icons';
import { useRouter, useLocalSearchParams } from 'expo-router';
import { theme } from '@/src/theme';
import { getViewRole, type ViewRole } from '@/src/roles';
import {
  apiGetCommercialSummary, apiListCommercialEvents, apiDecideVariation,
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
  variation_submitted: 'Variation submitted', variation_approved: 'Variation approved',
  variation_rejected: 'Variation rejected', payment_requested: 'Payment requested',
  payment_received: 'Payment received', milestone_achieved: 'Milestone completed',
  budget_updated: 'Budget updated', budget_created: 'Budget created',
};

const EVENT_KIND_ICON: Record<string, any> = {
  contract_created: 'document-text', contract_revised: 'document-text',
  variation_submitted: 'swap-horizontal', variation_approved: 'checkmark-circle',
  variation_rejected: 'close-circle', payment_requested: 'cash-outline',
  payment_received: 'cash', milestone_achieved: 'flag', budget_updated: 'wallet',
};

type SectionKey = 'contract' | 'budget' | 'milestones' | 'payment_requests' | 'payments' | 'variations' | 'timeline';

export default function CommercialWorkspaceScreen() {
  const router = useRouter();
  const { id } = useLocalSearchParams<{ id: string }>();
  const [viewRole, setViewRole] = useState<ViewRole | null>(null);
  const [summary, setSummary] = useState<CommercialSummary>(null);
  const [events, setEvents] = useState<CommercialEvent[]>([]);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [expanded, setExpanded] = useState<Record<SectionKey, boolean>>({
    contract: true, budget: true, milestones: true, payment_requests: false,
    payments: false, variations: true, timeline: false,
  });
  const [decidingId, setDecidingId] = useState<string | null>(null);
  const [variationFilter, setVariationFilter] = useState<'all' | 'pending' | 'approved' | 'rejected' | 'implemented'>('all');
  const [prFilter, setPrFilter] = useState<'all' | 'unpaid' | 'paid' | 'overdue'>('all');

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

  const onRefresh = async () => {
    setRefreshing(true);
    await load();
    setRefreshing(false);
  };

  const toggle = (key: SectionKey) => setExpanded((e) => ({ ...e, [key]: !e[key] }));

  const isManagement = viewRole === 'admin';
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

      <ScrollView
        contentContainerStyle={styles.content}
        refreshControl={<RefreshControl refreshing={refreshing} onRefresh={onRefresh} tintColor={theme.color.brand} />}
      >
        {!summary ? (
          <View style={styles.emptyState} testID="workspace-empty">
            <Ionicons name="wallet-outline" size={32} color={theme.color.textDim} />
            <Text style={styles.emptyStateText}>No commercial data for this project yet.</Text>
          </View>
        ) : (
          <>
            {/* CONTRACT */}
            <Section title="CONTRACT" icon="document-text" expanded={expanded.contract} onToggle={() => toggle('contract')} testID="section-contract">
              <View style={styles.tileGrid}>
                <Tile label="Original Contract Value" value={formatInr(summary.contract.original_contract_value)} />
                <Tile label="Current Contract Value" value={formatInr(summary.contract.current_contract_value)} />
                <Tile label="Approved Variations" value={formatInr(summary.approved_variations_total)} />
                <Tile label="Pending Variations" value={formatInr(summary.pending_variations_total)} />
              </View>
              <View style={styles.metaRow}>
                <Text style={styles.metaText}>Contract Date: {formatDate(summary.contract.contract_date)}</Text>
                <Text style={styles.metaText}>Duration: {summary.contract.duration_days} days</Text>
                <Text style={styles.metaText}>Status: {summary.contract.status}</Text>
              </View>
            </Section>

            {/* BUDGET — management only */}
            {isManagement && (
              <Section title="BUDGET" icon="wallet" expanded={expanded.budget} onToggle={() => toggle('budget')} testID="section-budget">
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

            {/* CASH FLOW */}
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

            {/* MILESTONES */}
            <Section title="MILESTONES" icon="flag" expanded={expanded.milestones} onToggle={() => toggle('milestones')} testID="section-milestones">
              {summary.milestones.length === 0 ? (
                <Text style={styles.mutedText}>No milestones yet.</Text>
              ) : (
                summary.milestones
                  .slice()
                  .sort((a, b) => a.sequence - b.sequence)
                  .map((m) => (
                    <MilestoneRow key={m.id} milestone={m}
                      linkedPr={summary.payment_requests.find((pr) => pr.milestone_id === m.id) || null} />
                  ))
              )}
            </Section>

            {/* PAYMENT REQUESTS */}
            <Section title="PAYMENT REQUESTS" icon="receipt" expanded={expanded.payment_requests} onToggle={() => toggle('payment_requests')} testID="section-payment-requests">
              <FilterRow
                options={[['all', 'All'], ['unpaid', 'Unpaid'], ['paid', 'Paid'], ['overdue', 'Overdue']]}
                value={prFilter} onChange={(v) => setPrFilter(v as any)} testIDPrefix="pr-filter" />
              {filterPaymentRequests(summary.payment_requests, prFilter).length === 0 ? (
                <Text style={styles.mutedText}>No payment requests match this filter.</Text>
              ) : (
                filterPaymentRequests(summary.payment_requests, prFilter).map((pr) => (
                  <PaymentRequestRow key={pr.id} pr={pr} payments={summary.payments}
                    milestone={summary.milestones.find((m) => m.id === pr.milestone_id) || null} />
                ))
              )}
            </Section>

            {/* PAYMENTS */}
            <Section title="PAYMENTS" icon="cash" expanded={expanded.payments} onToggle={() => toggle('payments')} testID="section-payments">
              {summary.payments.length === 0 ? (
                <Text style={styles.mutedText}>No payments recorded yet.</Text>
              ) : (
                summary.payments
                  .slice()
                  .sort((a, b) => (a.date < b.date ? 1 : -1))
                  .map((p) => <PaymentRow key={p.id} payment={p} />)
              )}
            </Section>

            {/* VARIATIONS */}
            <Section title="VARIATIONS" icon="swap-horizontal" expanded={expanded.variations} onToggle={() => toggle('variations')} testID="section-variations">
              <FilterRow
                options={[['all', 'All'], ['pending', 'Pending'], ['approved', 'Approved'], ['rejected', 'Rejected'], ['implemented', 'Implemented']]}
                value={variationFilter} onChange={(v) => setVariationFilter(v as any)} testIDPrefix="variation-filter" />
              {filterVariations(summary.variations, variationFilter).length === 0 ? (
                <Text style={styles.mutedText}>No variations match this filter.</Text>
              ) : (
                filterVariations(summary.variations, variationFilter).map((v) => (
                  <VariationCard key={v.id} variation={v} canDecide={canDecide}
                    deciding={decidingId === v.id} onDecide={onDecide} />
                ))
              )}
            </Section>

            {/* COMMERCIAL TIMELINE */}
            <Section title="COMMERCIAL TIMELINE" icon="time" expanded={expanded.timeline} onToggle={() => toggle('timeline')} testID="section-timeline">
              {events.length === 0 ? (
                <Text style={styles.mutedText}>No commercial events recorded yet.</Text>
              ) : (
                events.map((e) => <TimelineRow key={e.id} event={e} />)
              )}
            </Section>
          </>
        )}
      </ScrollView>
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

function Section({ title, icon, expanded, onToggle, children, testID, noCollapse }: {
  title: string; icon: any; expanded: boolean; onToggle: () => void; children: React.ReactNode;
  testID: string; noCollapse?: boolean;
}) {
  return (
    <View style={styles.section} testID={testID}>
      <Pressable onPress={noCollapse ? undefined : onToggle} style={styles.sectionHeader} disabled={noCollapse}>
        <View style={styles.sectionTitleRow}>
          <Ionicons name={icon} size={16} color={theme.color.brand} />
          <Text style={styles.sectionTitle}>{title}</Text>
        </View>
        {!noCollapse && <Ionicons name={expanded ? 'chevron-up' : 'chevron-down'} size={18} color={theme.color.textDim} />}
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

function MilestoneRow({ milestone, linkedPr }: { milestone: Milestone; linkedPr: PaymentRequest | null }) {
  const done = ['achieved', 'payment_requested', 'paid', 'closed'].includes(milestone.status);
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
      </View>
      <Text style={styles.statusPill}>{MILESTONE_STATUS_LABEL[milestone.status] || milestone.status}</Text>
    </View>
  );
}

function PaymentRequestRow({ pr, payments, milestone }: { pr: PaymentRequest; payments: Payment[]; milestone: Milestone | null }) {
  const paidAmount = payments.filter((p) => p.payment_request_id === pr.id).reduce((s, p) => s + p.amount, 0);
  const remaining = pr.amount - paidAmount;
  return (
    <View style={styles.row} testID={`payment-request-${pr.id}`}>
      <View style={{ flex: 1 }}>
        <Text style={styles.rowTitle}>{pr.number} — {formatInr(pr.amount)}</Text>
        <Text style={styles.rowSubtext}>
          Remaining: {formatInr(remaining)} · Due {formatDate(pr.due_date)}
          {milestone ? ` · ${milestone.name}` : ''}
        </Text>
      </View>
      <Text style={[styles.statusPill, pr.status === 'overdue' && styles.statusPillError]}>{pr.status}</Text>
    </View>
  );
}

function PaymentRow({ payment }: { payment: Payment }) {
  return (
    <View style={styles.row} testID={`payment-${payment.id}`}>
      <Ionicons name="checkmark-circle" size={18} color={theme.color.success} />
      <View style={{ flex: 1, marginLeft: 8 }}>
        <Text style={styles.rowTitle}>{formatInr(payment.amount)}</Text>
        <Text style={styles.rowSubtext}>{formatDate(payment.date)} · {payment.method}{payment.reference ? ` · ${payment.reference}` : ''}</Text>
      </View>
      <Text style={styles.statusPill}>{payment.status}</Text>
    </View>
  );
}

function VariationCard({ variation, canDecide, deciding, onDecide }: {
  variation: Variation; canDecide: boolean; deciding: boolean;
  onDecide: (id: string, decision: 'approved' | 'rejected') => void;
}) {
  const pending = ['submitted', 'client_review'].includes(variation.status);
  const afterCost = variation.status === 'approved' ? variation.approved_cost : variation.proposed_cost;
  const costImpact = (afterCost ?? variation.proposed_cost) - variation.original_cost;
  return (
    <View style={styles.variationCard} testID={`variation-${variation.id}`}>
      <Text style={styles.rowTitle}>{variation.title}</Text>
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
      {pending && canDecide ? (
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
