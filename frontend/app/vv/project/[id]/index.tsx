// Visual Validation (VV-01) — Screen 2: Project Command Center.
// "What is happening on this project?" — one card per engine, so a
// broken engine is immediately visually obvious. Read-only throughout.
import { useEffect, useState, useCallback, type ReactNode } from 'react';
import { View, Text, StyleSheet, ScrollView, ActivityIndicator, Pressable } from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import { Ionicons } from '@expo/vector-icons';
import { useLocalSearchParams, useRouter } from 'expo-router';
import { theme } from '@/src/theme';
import { apiListProjects, apiListSites, apiTimeline, type Project, type TimelineItem } from '@/src/api';
import { apiProjectHealth, type ProjectHealth } from '@/src/cre_api';
import { apiGetWorkflow, type WorkflowActivity } from '@/src/workflow_api';
import { apiListItems, type OperationalItem } from '@/src/ops_api';
import { apiGetCommercialReference, type CommercialReference } from '@/src/vv_api';
import { URGENCY_COLOR } from '@/src/urgency';

export default function VVCommandCenter() {
  const { id } = useLocalSearchParams<{ id: string }>();
  const router = useRouter();
  const [project, setProject] = useState<Project | null>(null);
  const [health, setHealth] = useState<ProjectHealth | null>(null);
  const [activities, setActivities] = useState<WorkflowActivity[]>([]);
  const [items, setItems] = useState<OperationalItem[]>([]);
  const [commercial, setCommercial] = useState<CommercialReference>(null);
  const [recentEvents, setRecentEvents] = useState<TimelineItem[]>([]);
  const [eventCount, setEventCount] = useState(0);
  const [loading, setLoading] = useState(true);

  const load = useCallback(async () => {
    if (!id) return;
    setLoading(true);
    try {
      const [projects, h, acts, cRef] = await Promise.all([
        apiListProjects(), apiProjectHealth(id).catch(() => null),
        apiGetWorkflow(id).catch(() => []), apiGetCommercialReference(id).catch(() => null),
      ]);
      setProject(projects.find((p) => p.id === id) || null);
      setHealth(h);
      setActivities(acts);
      setCommercial(cRef);

      const sites = await apiListSites(id).catch(() => []);
      const [allItems, ...timelines] = await Promise.all([
        apiListItems({ exclude_terminal: false }).catch(() => [] as OperationalItem[]),
        ...sites.map((s) => apiTimeline(s.id).catch(() => [] as TimelineItem[])),
      ]);
      const projectItems = allItems.filter((i) => sites.some((s) => s.id === i.site_id));
      setItems(projectItems);
      const merged: TimelineItem[] = timelines.flat().sort(
        (a: TimelineItem, b: TimelineItem) => new Date(b.event.server_created_at).getTime() - new Date(a.event.server_created_at).getTime());
      setEventCount(merged.length);
      setRecentEvents(merged.slice(0, 6));
    } finally {
      setLoading(false);
    }
  }, [id]);

  useEffect(() => { load(); }, [load]);

  if (loading || !project) {
    return <SafeAreaView style={styles.screen}><ActivityIndicator color={theme.color.brand} style={{ marginTop: 80 }} /></SafeAreaView>;
  }

  const workflowCounts = countBy(activities, (a: WorkflowActivity) => a.status);
  const completed = workflowCounts['completed'] || 0;
  const active = (workflowCounts['ready'] || 0) + (workflowCounts['in_progress'] || 0);
  const blocked = workflowCounts['blocked'] || 0;
  const percentComplete = health?.progress.percent_complete;

  const openItems = items.filter((i) => !['fulfilled', 'verified', 'closed', 'archived', 'cancelled', 'duplicate'].includes(i.status));
  const criticalItems = openItems.filter((i) => i.priority === 'critical');

  const healthDot = health?.status === 'green' ? URGENCY_COLOR.on_track
    : health?.status === 'amber' ? URGENCY_COLOR.due_soon : URGENCY_COLOR.overdue;

  return (
    <SafeAreaView style={styles.screen}>
      <ScrollView contentContainerStyle={{ padding: theme.spacing.md }}>
        <Pressable testID="vv-back" onPress={() => router.push('/vv')} style={styles.backRow}>
          <Ionicons name="chevron-back" size={18} color={theme.color.textDim} />
          <Text style={styles.backText}>Project Selector</Text>
        </Pressable>

        {/* Project Header */}
        <View style={styles.headerCard}>
          <Text style={styles.projectName}>{project.name}</Text>
          <View style={styles.headerRow}>
            {percentComplete != null && <Text style={styles.headerStat}>{Math.round(percentComplete)}% Complete</Text>}
            {commercial?.current_day != null && commercial?.contract_duration_days != null && (
              <Text style={styles.headerStat}>Day {commercial.current_day} / {commercial.contract_duration_days}</Text>
            )}
            {commercial?.contract_value != null && (
              <Text style={styles.headerStat}>{formatInr(commercial.contract_value)} Contract</Text>
            )}
            <View style={styles.healthBadge}>
              <View style={[styles.healthDot, { backgroundColor: healthDot }]} />
              <Text style={styles.headerStat}>Health {health ? `${health.status.toUpperCase()} (${health.score})` : '—'}</Text>
            </View>
          </View>
        </View>

        {/* Engine Health Cards */}
        <Text style={styles.sectionLabel}>THIS IS ATLAS — ONE CARD PER ENGINE</Text>
        <View style={styles.cardsGrid}>
          <EngineCard title="WORKFLOW" onPress={() => router.push(`/vv/project/${id}/workflow`)}>
            <StatLine label="Completed" value={completed} />
            <StatLine label="Active" value={active} />
            <StatLine label="Blocked" value={blocked} color={blocked > 0 ? URGENCY_COLOR.overdue : undefined} />
          </EngineCard>
          <EngineCard title="OPERATIONS" onPress={() => router.push(`/vv/project/${id}/operations`)}>
            <StatLine label="Open" value={openItems.length} />
            <StatLine label="Critical" value={criticalItems.length} color={criticalItems.length > 0 ? URGENCY_COLOR.overdue : undefined} />
          </EngineCard>
          <EngineCard title="COMMERCIAL" onPress={() => router.push(`/vv/project/${id}/commercial`)}>
            {commercial ? (
              <>
                <StatLine label="Cash Flow" value={commercial.cash_flow_signal || '—'} />
                <StatLine label="RA Bills" value={commercial.ra_bills_total ?? '—'} />
                <StatLine label="Variations" value={formatInr((commercial.approved_variations || 0) + (commercial.pending_variations || 0))} />
              </>
            ) : <Text style={styles.noData}>No commercial reference data</Text>}
          </EngineCard>
          <EngineCard title="TIMELINE" onPress={() => router.push(`/vv/project/${id}/timeline`)}>
            <StatLine label="Events" value={eventCount} />
          </EngineCard>
          <EngineCard title="CRE">
            <StatLine label="Open Insights" value={health?.open_insights ?? '—'} />
            <StatLine label="Risk" value={health ? riskLabel(health.status) : '—'} />
          </EngineCard>
        </View>

        {/* Recent Timeline */}
        <Text style={styles.sectionLabel}>PROJECT TIMELINE — RECENT EVENTS</Text>
        <View style={styles.panel}>
          {recentEvents.length === 0 ? (
            <Text style={styles.noData}>No events captured yet.</Text>
          ) : recentEvents.map((t) => (
            <View key={t.event.id} style={styles.eventRow}>
              <Ionicons
                name={t.approval_status === 'rejected' ? 'alert-circle' : 'checkmark-circle'}
                size={16}
                color={t.approval_status === 'rejected' ? URGENCY_COLOR.overdue : URGENCY_COLOR.on_track}
              />
              <View style={{ flex: 1, marginLeft: 8 }}>
                <Text style={styles.eventText} numberOfLines={1}>{t.event.text_input || `${t.event.kind} capture`}</Text>
                <Text style={styles.eventMeta}>{relativeDay(t.event.server_created_at)} · {t.event.user_name}</Text>
              </View>
            </View>
          ))}
        </View>

        {/* Operations — critical/open, read-only */}
        <Text style={styles.sectionLabel}>OPERATIONS — READ ONLY</Text>
        <View style={styles.panel}>
          {criticalItems.slice(0, 5).map((i) => (
            <View key={i.id} style={styles.opsRow}>
              <View style={[styles.priorityDot, { backgroundColor: URGENCY_COLOR.overdue }]} />
              <Text style={styles.opsText} numberOfLines={1}>{i.title}</Text>
            </View>
          ))}
          {openItems.filter((i) => i.priority !== 'critical').slice(0, 4).map((i) => (
            <View key={i.id} style={styles.opsRow}>
              <View style={[styles.priorityDot, { backgroundColor: theme.color.textDim }]} />
              <Text style={styles.opsText} numberOfLines={1}>{i.title}</Text>
            </View>
          ))}
          {openItems.length === 0 && <Text style={styles.noData}>No open operational items.</Text>}
        </View>

        {/* Workflow tree preview */}
        <Text style={styles.sectionLabel}>WORKFLOW — SIMPLE TREE</Text>
        <View style={styles.panel}>
          {activities.slice(0, 8).map((a) => (
            <View key={a.id} style={styles.workflowRow}>
              <Ionicons
                name={a.status === 'completed' ? 'checkmark-circle' : a.status === 'blocked' ? 'lock-closed' : 'ellipse-outline'}
                size={16}
                color={a.status === 'completed' ? URGENCY_COLOR.on_track : a.status === 'blocked' ? URGENCY_COLOR.overdue : theme.color.textDim}
              />
              <Text style={styles.workflowText} numberOfLines={1}>{a.name}</Text>
            </View>
          ))}
          {activities.length > 8 && (
            <Pressable onPress={() => router.push(`/vv/project/${id}/workflow`)}>
              <Text style={styles.moreLink}>+ {activities.length - 8} more →</Text>
            </Pressable>
          )}
        </View>
      </ScrollView>
    </SafeAreaView>
  );
}

function EngineCard({ title, children, onPress }: { title: string; children: ReactNode; onPress?: () => void }) {
  const Wrapper = onPress ? Pressable : View;
  return (
    <Wrapper testID={`vv-engine-card-${title.toLowerCase()}`} onPress={onPress} style={styles.engineCard}>
      <Text style={styles.engineCardTitle}>{title}</Text>
      {children}
      {onPress && <Ionicons name="chevron-forward" size={14} color={theme.color.textDim} style={styles.engineCardChevron} />}
    </Wrapper>
  );
}

function StatLine({ label, value, color }: { label: string; value: string | number; color?: string }) {
  return (
    <View style={styles.statLine}>
      <Text style={[styles.statValue, color ? { color } : null]}>{value}</Text>
      <Text style={styles.statLabel}>{label}</Text>
    </View>
  );
}

function countBy<T>(arr: T[], fn: (t: T) => string): Record<string, number> {
  const out: Record<string, number> = {};
  for (const item of arr) { const k = fn(item); out[k] = (out[k] || 0) + 1; }
  return out;
}

function riskLabel(status: string): string {
  return status === 'green' ? 'Low Risk' : status === 'amber' ? 'Medium Risk' : 'High Risk';
}

function formatInr(n: number): string {
  if (n >= 10000000) return `₹${(n / 10000000).toFixed(2)} Cr`;
  if (n >= 100000) return `₹${(n / 100000).toFixed(1)}L`;
  return `₹${n.toLocaleString('en-IN')}`;
}

function relativeDay(iso: string): string {
  const d = new Date(iso);
  const now = new Date();
  const diffDays = Math.floor((now.setHours(0, 0, 0, 0) - new Date(d).setHours(0, 0, 0, 0)) / 86400000);
  if (diffDays === 0) return 'Today';
  if (diffDays === 1) return 'Yesterday';
  return d.toLocaleDateString();
}

const styles = StyleSheet.create({
  screen: { flex: 1, backgroundColor: theme.color.surface },
  backRow: { flexDirection: 'row', alignItems: 'center', marginBottom: theme.spacing.sm },
  backText: { color: theme.color.textDim, fontSize: 13 },
  headerCard: {
    backgroundColor: theme.color.surface2, borderRadius: theme.radius.lg, padding: theme.spacing.md,
    marginBottom: theme.spacing.md, borderWidth: 1, borderColor: theme.color.border,
  },
  projectName: { color: theme.color.text, fontSize: theme.font.xl, fontWeight: '900', marginBottom: 8 },
  headerRow: { flexDirection: 'row', flexWrap: 'wrap', gap: theme.spacing.md, alignItems: 'center' },
  headerStat: { color: theme.color.textMuted, fontSize: 13, fontWeight: '700' },
  healthBadge: { flexDirection: 'row', alignItems: 'center', gap: 6 },
  healthDot: { width: 10, height: 10, borderRadius: 5 },
  sectionLabel: { color: theme.color.textDim, fontSize: 11, fontWeight: '800', letterSpacing: 1, marginTop: theme.spacing.md, marginBottom: theme.spacing.sm },
  cardsGrid: { flexDirection: 'row', flexWrap: 'wrap', gap: theme.spacing.sm },
  engineCard: {
    backgroundColor: theme.color.surface2, borderRadius: theme.radius.md, padding: theme.spacing.sm,
    borderWidth: 1, borderColor: theme.color.border, width: '48%', minHeight: 90,
  },
  engineCardTitle: { color: theme.color.brand, fontSize: 11, fontWeight: '900', letterSpacing: 1, marginBottom: 6 },
  engineCardChevron: { position: 'absolute', top: 8, right: 8 },
  statLine: { flexDirection: 'row', justifyContent: 'space-between', marginBottom: 2 },
  statValue: { color: theme.color.text, fontSize: 13, fontWeight: '800' },
  statLabel: { color: theme.color.textDim, fontSize: 11 },
  noData: { color: theme.color.textDim, fontSize: 12, fontStyle: 'italic' },
  panel: { backgroundColor: theme.color.surface2, borderRadius: theme.radius.md, padding: theme.spacing.sm, borderWidth: 1, borderColor: theme.color.border },
  eventRow: { flexDirection: 'row', alignItems: 'center', paddingVertical: 6 },
  eventText: { color: theme.color.text, fontSize: 13, fontWeight: '600' },
  eventMeta: { color: theme.color.textDim, fontSize: 11, marginTop: 1 },
  opsRow: { flexDirection: 'row', alignItems: 'center', paddingVertical: 6, gap: 8 },
  priorityDot: { width: 8, height: 8, borderRadius: 4 },
  opsText: { color: theme.color.text, fontSize: 13, flex: 1 },
  workflowRow: { flexDirection: 'row', alignItems: 'center', paddingVertical: 6, gap: 8 },
  workflowText: { color: theme.color.text, fontSize: 13, flex: 1 },
  moreLink: { color: theme.color.brand, fontSize: 12, fontWeight: '700', paddingTop: 6 },
});
