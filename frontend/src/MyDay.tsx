// "My Day" (Execution Experience Sprint 02, item 6) — replaces Sprint
// 01's WorkQueue with the full role-based execution dashboard. Same
// "first section on Home, ahead of the existing CRE cards" placement.
import { useEffect, useState } from 'react';
import { View, Text, StyleSheet, Pressable, ActivityIndicator } from 'react-native';
import { Ionicons } from '@expo/vector-icons';
import { useRouter } from 'expo-router';
import { theme } from './theme';
import { apiMyDay, type MyDayResponse, type MyDaySupervisor, type MyDayPm, type MyDayAdmin } from './ops_api';
import { URGENCY_COLOR, operationalItemUrgency, workflowActivityUrgency, type UrgencyState } from './urgency';

function isActivity(x: any): boolean {
  return typeof x?.name === 'string' && typeof x?.title !== 'string';
}

function urgencyOf(x: any): UrgencyState {
  return isActivity(x) ? workflowActivityUrgency(x) : operationalItemUrgency(x);
}

export function MyDaySection({ viewRole }: { viewRole: 'admin' | 'pm' | 'supervisor' }) {
  const router = useRouter();
  const [data, setData] = useState<MyDayResponse | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let cancelled = false;
    apiMyDay().then((d) => { if (!cancelled) { setData(d); setLoading(false); } })
      .catch(() => { if (!cancelled) setLoading(false); });
    return () => { cancelled = true; };
  }, []);

  if (loading) return <View style={styles.loader}><ActivityIndicator color={theme.color.brand} /></View>;
  if (!data) return null;

  const openItem = (x: any) => router.push(isActivity(x) ? `/workflow/${x.project_id}` : `/op/${x.id}`);
  const openCommercial = (x: any) => router.push(`/commercial/${x.project_id}`);

  if (data.role === 'site_supervisor') {
    const d = data as MyDaySupervisor;
    return (
      <View testID="my-day-supervisor">
        <MyDayGroup icon="flash" title="READY TO START" items={d.ready_to_start} onPress={openItem} highlight />
        <MyDayGroup icon="hammer" title="IN PROGRESS" items={d.in_progress} onPress={openItem} />
        <MyDayGroup icon="today" title="DUE TODAY" items={d.due_today} onPress={openItem} />
        <MyDayGroup icon="alert-circle" title="BLOCKED" items={d.blocked} onPress={openItem} />
        <MyDayGroup icon="cube" title="WAITING FOR MATERIAL" items={d.waiting_for_material} onPress={openItem} />
        <MyDayGroup icon="sparkles" title="RECENTLY ASSIGNED" items={d.recently_assigned} onPress={openItem} />
      </View>
    );
  }

  if (data.role === 'management') {
    const d = data as MyDayAdmin;
    return (
      <View style={styles.section} testID="my-day-admin">
        <View style={styles.headerRow}>
          <Ionicons name="pulse" size={18} color={theme.color.brand} />
          <Text style={styles.headerText}>PORTFOLIO HEALTH</Text>
        </View>
        <View style={styles.statsRow}>
          <StatPill label="Active" value={d.portfolio_health.active_projects} />
          <StatPill label="Healthy" value={d.portfolio_health.healthy} color={theme.color.success} />
          <StatPill label="Attention" value={d.portfolio_health.attention} color={theme.color.warning} />
          <StatPill label="Critical" value={d.portfolio_health.critical} color={URGENCY_COLOR.overdue} />
        </View>
        <View style={styles.statsRow}>
          <StatPill label="Delayed Projects" value={d.delayed_projects.length} color={URGENCY_COLOR.overdue} />
          <StatPill label="Critical Issues" value={d.critical_issues} color={URGENCY_COLOR.overdue} />
          <StatPill label="Pending Approvals" value={d.pending_approvals} />
          <StatPill label="Resource Alerts" value={d.resource_alerts} color={theme.color.warning} />
        </View>
        {d.delayed_projects.length > 0 && (
          <Pressable testID="my-day-admin-portfolio-link" onPress={() => router.push('/portfolio')} style={styles.linkRow}>
            <Text style={styles.linkText}>View Portfolio Control Center</Text>
            <Ionicons name="chevron-forward" size={16} color={theme.color.brand} />
          </Pressable>
        )}
      </View>
    );
  }

  // Project Manager
  const d = data as MyDayPm;
  return (
    <View testID="my-day-pm">
      <View style={styles.statsRow}>
        <StatPill label="Projects Needing Attention" value={d.projects_requiring_attention} color={theme.color.warning} />
        <StatPill label="Open Operational Items" value={d.open_operational_items_count} />
      </View>
      <MyDayGroup icon="time" title="DELAYED ACTIVITIES" items={d.delayed_activities} onPress={openItem} />
      <MyDayGroup icon="alert-circle" title="BLOCKED" items={d.blocked_activities} onPress={openItem} />
      <MyDayGroup icon="search" title="UPCOMING INSPECTIONS" items={d.upcoming_inspections} onPress={openItem} />
      <MyDayGroup icon="checkmark-done" title="PENDING APPROVALS" items={d.pending_approvals} onPress={openItem} />
      <MyDayGroup icon="flag" title="HIGH PRIORITY WORK" items={d.high_priority_work} onPress={openItem} />
      <MyDayGroup icon="warning" title="ESCALATIONS" items={d.escalations} onPress={openItem} />
      <CommercialAwarenessGroup icon="swap-horizontal" title="PENDING VARIATIONS" items={d.pending_variations} kind="variation" onPress={openCommercial} />
      <CommercialAwarenessGroup icon="receipt" title="PENDING PAYMENT REQUESTS" items={d.pending_payment_requests} kind="payment_request" onPress={openCommercial} />
      <CommercialAwarenessGroup icon="flag-outline" title="UPCOMING MILESTONES" items={d.upcoming_milestones} kind="milestone" onPress={openCommercial} />
      <Pressable testID="my-day-daily-review-link" onPress={() => router.push('/daily-review')} style={styles.linkRow}>
        <Text style={styles.linkText}>End-of-Day Review</Text>
        <Ionicons name="chevron-forward" size={16} color={theme.color.brand} />
      </Pressable>
    </View>
  );
}

function CommercialAwarenessGroup({ icon, title, items, kind, onPress }: {
  icon: any; title: string; items: any[]; kind: 'variation' | 'payment_request' | 'milestone';
  onPress: (x: any) => void;
}) {
  if (items.length === 0) return null;
  const labelFor = (x: any) =>
    kind === 'payment_request' ? `${x.number} — ${formatInrShort(x.amount)}` :
    kind === 'variation' ? x.title : x.name;
  const subtextFor = (x: any) =>
    kind === 'payment_request' ? `Due ${x.due_date?.slice(0, 10) || '—'} · ${x.status}` :
    kind === 'variation' ? `${formatInrShort(x.proposed_cost)} · ${x.status}` :
    `${x.planned_percent}% · ${x.planned_date?.slice(0, 10) || '—'}`;
  return (
    <View style={styles.section}>
      <View style={styles.headerRow}>
        <Ionicons name={icon} size={18} color={theme.color.brand} />
        <Text style={styles.headerText}>{title}</Text>
        <View style={styles.countBadge}><Text style={styles.countBadgeText}>{items.length}</Text></View>
      </View>
      {items.slice(0, 6).map((x) => (
        <Pressable key={x.id} testID={`my-day-commercial-${x.id}`} onPress={() => onPress(x)}
          style={[styles.card, { borderLeftColor: theme.color.brand }]}>
          <View style={{ flex: 1 }}>
            <Text style={styles.cardTitle} numberOfLines={1}>{labelFor(x)}</Text>
            <Text style={styles.cardMeta} numberOfLines={1}>{subtextFor(x)}</Text>
          </View>
          <Ionicons name="chevron-forward" size={18} color={theme.color.textDim} />
        </Pressable>
      ))}
    </View>
  );
}

function formatInrShort(n: number | null | undefined): string {
  if (n === null || n === undefined) return '—';
  const abs = Math.abs(n);
  if (abs >= 10000000) return `₹${(abs / 10000000).toFixed(2)}Cr`;
  if (abs >= 100000) return `₹${(abs / 100000).toFixed(1)}L`;
  return `₹${abs.toLocaleString('en-IN')}`;
}

function MyDayGroup({ icon, title, items, onPress, highlight }: {
  icon: any; title: string; items: any[]; onPress: (x: any) => void; highlight?: boolean;
}) {
  if (items.length === 0) return null;
  return (
    <View style={styles.section}>
      <View style={styles.headerRow}>
        <Ionicons name={icon} size={18} color={theme.color.brand} />
        <Text style={styles.headerText}>{title}</Text>
        <View style={styles.countBadge}><Text style={styles.countBadgeText}>{items.length}</Text></View>
      </View>
      {items.slice(0, 6).map((x) => (
        <MyDayCard key={x.id} item={x} onPress={() => onPress(x)} highlight={highlight} />
      ))}
    </View>
  );
}

// Assigned Activity Highlighting — a colored left border (derived
// urgency) plus an "ASSIGNED TO YOU" badge, so a user never has to
// search for their own work. Same treatment for operational items and
// workflow activities alike, one shared urgency definition.
function MyDayCard({ item, onPress, highlight }: { item: any; onPress: () => void; highlight?: boolean }) {
  const urgency = urgencyOf(item);
  const color = URGENCY_COLOR[urgency];
  const title = item.title || item.name;
  return (
    <Pressable testID={`my-day-card-${item.id}`} onPress={onPress} style={[styles.card, { borderLeftColor: color }]}>
      <View style={{ flex: 1 }}>
        <View style={styles.cardTitleRow}>
          <Text style={styles.cardTitle} numberOfLines={1}>{title}</Text>
          {highlight && (
            <View style={styles.assignedBadge}>
              <Text style={styles.assignedBadgeText}>ASSIGNED TO YOU</Text>
            </View>
          )}
        </View>
        <Text style={styles.cardMeta} numberOfLines={1}>
          {(item.category || item.trade || '').replace(/_/g, ' ')}
          {item.site_name ? ` · ${item.site_name}` : ''}
        </Text>
      </View>
      <View style={[styles.urgencyDot, { backgroundColor: color }]} />
    </Pressable>
  );
}

function StatPill({ label, value, color }: { label: string; value: number; color?: string }) {
  return (
    <View style={styles.pill}>
      <Text style={[styles.pillValue, color ? { color } : null]}>{value}</Text>
      <Text style={styles.pillLabel}>{label}</Text>
    </View>
  );
}

const styles = StyleSheet.create({
  loader: { paddingVertical: theme.spacing.lg, alignItems: 'center' },
  section: { marginBottom: theme.spacing.md },
  headerRow: { flexDirection: 'row', alignItems: 'center', gap: 8, marginBottom: theme.spacing.sm },
  headerText: { color: theme.color.text, fontSize: 13, fontWeight: '900', letterSpacing: 1 },
  countBadge: { backgroundColor: theme.color.brand, borderRadius: 10, paddingHorizontal: 8, paddingVertical: 2 },
  countBadgeText: { color: theme.color.onBrand, fontSize: 11, fontWeight: '800' },
  statsRow: { flexDirection: 'row', flexWrap: 'wrap', gap: theme.spacing.md, marginBottom: theme.spacing.sm },
  pill: { alignItems: 'center', minWidth: 64 },
  pillValue: { color: theme.color.text, fontSize: 20, fontWeight: '900' },
  pillLabel: { color: theme.color.textDim, fontSize: 10, fontWeight: '700', textAlign: 'center' },
  linkRow: { flexDirection: 'row', alignItems: 'center', gap: 6, paddingVertical: 6 },
  linkText: { color: theme.color.brand, fontSize: 13, fontWeight: '700' },
  card: {
    flexDirection: 'row', alignItems: 'center', backgroundColor: theme.color.surface2,
    borderRadius: theme.radius.md, borderLeftWidth: 4, padding: theme.spacing.sm, marginBottom: 8, gap: 8,
    minHeight: 56, // large touch target (item 7 — UX Improvements)
  },
  cardTitleRow: { flexDirection: 'row', alignItems: 'center', gap: 6, flexWrap: 'wrap' },
  cardTitle: { color: theme.color.text, fontSize: 14, fontWeight: '700', flexShrink: 1 },
  cardMeta: { color: theme.color.textDim, fontSize: 12, marginTop: 2 },
  assignedBadge: { backgroundColor: theme.color.brand, borderRadius: 6, paddingHorizontal: 6, paddingVertical: 2 },
  assignedBadgeText: { color: theme.color.onBrand, fontSize: 9, fontWeight: '800' },
  urgencyDot: { width: 10, height: 10, borderRadius: 5 },
});
