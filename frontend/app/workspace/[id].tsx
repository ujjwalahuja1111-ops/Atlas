// EX-01 — Unified Execution Workspace. Every section below reuses an
// existing, already-correct backend computation (apiMyDay,
// apiExplainHealth, apiGetCommercialSummary, apiListInsights,
// apiListCommercialEvents) — no new backend endpoint, no new engine,
// no duplicated business logic. This screen's only job is
// composition: pulling several already-correct reads into one place
// and filtering the portfolio-wide ones (My Day) down to the
// currently selected project.
import { useCallback, useEffect, useMemo, useState } from 'react';
import {
  View, Text, StyleSheet, ScrollView, Pressable, ActivityIndicator,
  RefreshControl, Modal, FlatList,
} from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import { Ionicons } from '@expo/vector-icons';
import { useRouter, useLocalSearchParams } from 'expo-router';
import { theme } from '@/src/theme';
import { getViewRole, type ViewRole } from '@/src/roles';
import { apiMyDay, type MyDayResponse, type MyDayPm, type MyDaySupervisor } from '@/src/ops_api';
import { apiExplainHealth, apiListInsights, apiGetSinceLastVisit, type ExplainedHealth, type Insight, type SinceLastVisit } from '@/src/cre_api';
import { apiGetCommercialSummary, apiListCommercialEvents, type CommercialSummary, type CommercialEvent } from '@/src/commercial_api';
import { apiListProjects, apiSetLifecycleStage, type Project } from '@/src/api';

function formatInr(n: number | null | undefined): string {
  if (n === null || n === undefined) return '—';
  const abs = Math.abs(n);
  const sign = n < 0 ? '-' : '';
  if (abs >= 10000000) return `${sign}₹${(abs / 10000000).toFixed(2)}Cr`;
  if (abs >= 100000) return `${sign}₹${(abs / 100000).toFixed(1)}L`;
  return `${sign}₹${abs.toLocaleString('en-IN')}`;
}

const HEALTH_COLOR: Record<string, string> = {
  green: theme.color.success, amber: theme.color.warning, red: theme.color.error,
  healthy: theme.color.success, attention: theme.color.warning, critical: theme.color.error,
};

// PL-01 — matches backend LIFECYCLE_STAGES exactly (memory_engine.py).
const LIFECYCLE_STAGE_LABELS: [string, string][] = [
  ['planning', 'Planning'], ['mobilization', 'Mobilization'], ['execution', 'Execution'],
  ['commercial_focus', 'Commercial'], ['closeout', 'Closeout'],
];

// A single, unified action item shape every source (operational items,
// workflow activities, pending variations/payment requests) is mapped
// into, so Today's Mission and the Action Queue never need to know
// which source an item came from — this is the actual mechanism that
// prevents duplication rather than a rule stated in a document.
type UnifiedAction = {
  id: string; title: string; kind: string; severity: 'critical' | 'high' | 'normal';
  onPress: () => void;
};

export default function UnifiedWorkspace() {
  const { id } = useLocalSearchParams<{ id: string }>();
  const router = useRouter();
  const [viewRole, setViewRole] = useState<ViewRole | null>(null);
  const [projects, setProjects] = useState<Project[]>([]);
  const [showProjectPicker, setShowProjectPicker] = useState(false);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [loadError, setLoadError] = useState<string | null>(null);

  const [myDay, setMyDay] = useState<MyDayResponse | null>(null);
  const [health, setHealth] = useState<ExplainedHealth | null>(null);
  const [insights, setInsights] = useState<Insight[]>([]);
  const [commercial, setCommercial] = useState<CommercialSummary>(null);
  const [events, setEvents] = useState<CommercialEvent[]>([]);
  const [stageChanging, setStageChanging] = useState(false);
  const [sinceLastVisit, setSinceLastVisit] = useState<SinceLastVisit | null>(null);

  const currentProject = projects.find((p) => p.id === id);

  const load = useCallback(async () => {
    if (!id) return;
    setLoadError(null);
    try {
      const [md, h, ins, comm, ev, pl] = await Promise.all([
        apiMyDay(),
        apiExplainHealth(id).catch(() => null),
        apiListInsights(id, { status: 'open' }).catch(() => [] as Insight[]),
        apiGetCommercialSummary(id).catch(() => null),
        apiListCommercialEvents(id).catch(() => [] as CommercialEvent[]),
        apiListProjects().catch(() => [] as Project[]),
      ]);
      setMyDay(md); setHealth(h); setInsights(ins); setCommercial(comm); setEvents(ev);
      if (pl.length) setProjects(pl);
    } catch {
      setLoadError('Could not load this project\'s workspace.');
    }
  }, [id]);

  // CM-01 — deliberately separate from load()/onRefresh: this call
  // itself records a fresh visit, so it must fire exactly once per
  // genuine app-open, never on a pull-to-refresh.
  useEffect(() => {
    if (!id) return;
    apiGetSinceLastVisit(id).then(setSinceLastVisit).catch(() => setSinceLastVisit(null));
  }, [id]);

  useEffect(() => {
    getViewRole().then(setViewRole);
    (async () => { setLoading(true); await load(); setLoading(false); })();
  }, [load]);

  const onRefresh = async () => { setRefreshing(true); await load(); setRefreshing(false); };

  // Filters the portfolio-wide My Day payload down to this project
  // only — My Day itself is correctly portfolio-scoped for its own
  // (different) purpose; this screen's job is composing the
  // already-correct data for one project, not recomputing it.
  const projectItems = useMemo(() => {
    if (!myDay || !id) return { pendingApprovals: [], highPriority: [], escalations: [], blocked: [] };
    const inProject = (x: any) => x && x.project_id === id;
    if (myDay.role === 'site_supervisor') {
      const d = myDay as MyDaySupervisor;
      return {
        pendingApprovals: [] as any[],
        highPriority: (d.due_today || []).filter(inProject),
        escalations: [] as any[],
        blocked: (d.blocked || []).filter(inProject),
      };
    }
    if (myDay.role === 'management') return { pendingApprovals: [], highPriority: [], escalations: [], blocked: [] };
    const d = myDay as MyDayPm;
    return {
      pendingApprovals: (d.pending_approvals || []).filter(inProject),
      highPriority: (d.high_priority_work || []).filter(inProject),
      escalations: (d.escalations || []).filter(inProject),
      blocked: (d.blocked_activities || []).filter(inProject),
    };
  }, [myDay, id]);

  const openItem = (x: any) => router.push(x?.title !== undefined ? `/op/${x.id}` : `/workflow/${id}`);
  const openCommercial = () => router.push(`/commercial/${id}`);

  // IN-01 — resolve an insight to the exact place work can be
  // completed, not just the module. Reuses the specific record ID
  // each rule already places in its own evidence (no new backend
  // field) — falls back to generic Commercial navigation only for
  // insights this mapping doesn't cover yet, never a regression.
  const openForInsight = (insight: Insight) => {
    const absenceId = insight.evidence?.absences?.[0]?.id as string | undefined;
    if (insight.rule_id === 'commercial.milestone_ready_for_billing' && absenceId) {
      router.push(`/commercial/${id}?action=raise-payment-request&milestoneId=${absenceId}`);
      return;
    }
    if (insight.rule_id === 'commercial.variation_approved_needs_contract_review' && absenceId) {
      router.push(`/commercial/${id}?action=view-variation&variationId=${absenceId}`);
      return;
    }
    openCommercial();
  };

  const setStage = async (stage: string) => {
    if (!id || stageChanging) return;
    setStageChanging(true);
    try {
      const updated = await apiSetLifecycleStage(id, stage);
      setProjects((ps) => ps.map((p) => (p.id === id ? updated : p)));
    } catch {
      // stage change failure is non-fatal to the rest of the workspace
    } finally {
      setStageChanging(false);
    }
  };

  // Today's Mission — everything genuinely actionable today, one
  // list, no duplicates: each source contributes items once, mapped
  // into the same UnifiedAction shape.
  const mission: UnifiedAction[] = [
    ...projectItems.escalations.map((x: any) => ({ id: `esc-${x.id}`, title: x.title || x.name, kind: 'Escalation', severity: 'critical' as const, onPress: () => openItem(x) })),
    ...projectItems.blocked.map((x: any) => ({ id: `blk-${x.id}`, title: x.title || x.name, kind: 'Blocked', severity: 'critical' as const, onPress: () => openItem(x) })),
    ...projectItems.pendingApprovals.map((x: any) => ({ id: `appr-${x.id}`, title: x.title || x.name, kind: 'Pending Approval', severity: 'high' as const, onPress: () => openItem(x) })),
    ...(commercial?.pending_variations_total ? [{ id: 'var-pending', title: `${formatInr(commercial.pending_variations_total)} in pending variations`, kind: 'Commercial', severity: 'high' as const, onPress: openCommercial }] : []),
    ...insights.filter((i) => i.severity === 'critical').map((i) => ({ id: `ins-${i.id}`, title: i.suggested_operational_action?.title || i.observation, kind: 'Alert', severity: 'critical' as const, onPress: openCommercial })),
    ...projectItems.highPriority.map((x: any) => ({ id: `hp-${x.id}`, title: x.title || x.name, kind: 'High Priority', severity: 'high' as const, onPress: () => openItem(x) })),
  ];

  // AI Suggestions — reuses the existing CRE insight pipeline only;
  // no new AI, no new engine. Each recommendation triggers the exact
  // same screen a person would otherwise have to go find themselves.
  const suggestions = insights.filter((i) => i.suggested_operational_action);

  // Unified Project Feed — chronological, one source (commercial
  // events) for this pass. Reality/operations/workflow events would
  // extend the same feed the same way, not a second timeline.
  const feed = events.slice().sort((a, b) => (a.created_at < b.created_at ? 1 : -1));

  if (loading) {
    return <SafeAreaView style={styles.center} edges={['top']}><ActivityIndicator color={theme.color.brand} size="large" /></SafeAreaView>;
  }

  return (
    <SafeAreaView style={styles.container} edges={['top']}>
      <View style={styles.header}>
        <Pressable testID="workspace-project-switcher" onPress={() => setShowProjectPicker(true)} style={styles.projectSwitcher}>
          <Text style={styles.projectName} numberOfLines={1}>{currentProject?.name || 'Workspace'}</Text>
          <Ionicons name="chevron-down" size={18} color={theme.color.text} />
        </Pressable>
        {(viewRole === 'pm' || viewRole === 'supervisor') && (
          <Pressable testID="workspace-quick-capture" onPress={() => router.push('/capture')} style={styles.captureBtn}>
            <Ionicons name="add" size={22} color={theme.color.onBrand} />
          </Pressable>
        )}
      </View>

      <ScrollView
        contentContainerStyle={styles.content}
        refreshControl={<RefreshControl refreshing={refreshing} onRefresh={onRefresh} tintColor={theme.color.brand} />}
      >
        {loadError && <Text style={styles.errorText} testID="workspace-load-error">{loadError}</Text>}

        {/* SINCE YOU WERE LAST HERE — the first thing this task's own
            mission statement asks for. Every entry reuses IN-01's own
            deep-link URL shapes for "Resume" - no new navigation
            invented, no AI-generated summary, every line derived
            directly from the existing commercial_events ledger. */}
        {sinceLastVisit && !sinceLastVisit.is_first_visit && sinceLastVisit.changes.length > 0 && (
          <View style={styles.sinceLastVisitCard} testID="since-last-visit">
            <Text style={styles.sinceLastVisitTitle}>Since you were last here</Text>
            {sinceLastVisit.changes.slice(0, 6).map((c) => (
              <Pressable
                key={c.event_id}
                testID={`since-last-visit-${c.event_id}`}
                onPress={() => {
                  if (c.entity_type === 'milestone') router.push(`/commercial/${id}?action=edit-milestone&milestoneId=${c.entity_id}`);
                  else if (c.entity_type === 'variation') router.push(`/commercial/${id}?action=view-variation&variationId=${c.entity_id}`);
                  else openCommercial();
                }}
                style={styles.sinceLastVisitRow}>
                <View style={{ flex: 1 }}>
                  <Text style={styles.rowTitle}>{c.what_changed}</Text>
                  <Text style={styles.rowSubtext}>{c.why_it_matters}</Text>
                </View>
                <Text style={styles.resumeLink}>Resume</Text>
              </Pressable>
            ))}
          </View>
        )}

        {/* LIFECYCLE STAGE SELECTOR — a deliberate, PM-set signal
            (Product Decision, PL-01): the workspace adapts to where
            the PM says the project is, not a computed guess. */}
        <View style={styles.stageRow} testID="lifecycle-stage-selector">
          {LIFECYCLE_STAGE_LABELS.map(([stage, label]) => {
            const active = (currentProject?.lifecycle_stage || 'planning') === stage;
            return (
              <Pressable
                key={stage}
                testID={`stage-${stage}`}
                disabled={!(viewRole === 'pm' || viewRole === 'admin') || stageChanging}
                onPress={() => setStage(stage)}
                style={[styles.stageChip, active && styles.stageChipActive]}>
                <Text style={[styles.stageChipText, active && styles.stageChipTextActive]}>{label}</Text>
              </Pressable>
            );
          })}
        </View>

        {/* STAGE FOCUS — the same widget in name, different content by
            stage; every field here is reused from data already loaded
            above, no new API call per stage. */}
        <StageFocus stage={currentProject?.lifecycle_stage || 'planning'} health={health} commercial={commercial}
          plannedCount={commercial?.milestones?.length ?? 0}
          readyCount={projectItems.highPriority.length}
          lastMilestone={commercial?.milestones?.slice().sort((a, b) => b.sequence - a.sequence)[0] || null}
          onPress={() => {
            const stage = currentProject?.lifecycle_stage || 'planning';
            if (stage === 'planning') {
              if (!commercial?.contract) { router.push(`/commercial/${id}?action=create-contract`); return; }
              if (!commercial?.budget) { router.push(`/commercial/${id}?action=create-budget`); return; }
            }
            openCommercial();
          }} />

        {/* HEALTH STRIP — always visible, reuses ExplainedHealth's own
            dimensions plus Commercial's own cash_flow_signal. Two
            categories (Resources, Procurement) have no backend
            computation anywhere in Atlas today — shown honestly as
            placeholders rather than invented. */}
        <View style={styles.healthStrip} testID="health-strip">
          {[
            ['Commercial', commercial?.cash_flow_signal],
            ['Schedule', health?.dimensions?.schedule ? (health.dimensions.schedule.score >= 70 ? 'healthy' : health.dimensions.schedule.score >= 40 ? 'attention' : 'critical') : undefined],
            ['Quality', health?.dimensions?.quality ? (health.dimensions.quality.score >= 70 ? 'healthy' : 'attention') : undefined],
            ['Safety', health?.dimensions?.safety ? (health.dimensions.safety.score >= 70 ? 'healthy' : 'critical') : undefined],
            ['Resources', undefined],
            ['Procurement', undefined],
            ['Labour', undefined],
          ].map(([label, signal]) => (
            <View key={label} style={styles.healthChip}>
              <View style={[styles.healthDot, { backgroundColor: signal ? (HEALTH_COLOR[signal] || theme.color.textDim) : theme.color.border }]} />
              <Text style={styles.healthChipText}>{label}</Text>
            </View>
          ))}
        </View>

        {/* PROJECT PULSE */}
        <View style={styles.pulseCard} testID="project-pulse">
          <View style={styles.pulseRow}>
            <View style={styles.pulseStat}>
              <Text style={styles.pulseValue}>{health?.progress?.percent_complete ?? '—'}%</Text>
              <Text style={styles.pulseLabel}>Progress</Text>
            </View>
            <View style={styles.pulseStat}>
              <Text style={[styles.pulseValue, { color: health ? HEALTH_COLOR[health.status] : theme.color.text }]}>{health?.status?.toUpperCase() || '—'}</Text>
              <Text style={styles.pulseLabel}>Schedule Health</Text>
            </View>
            <Pressable testID="pulse-cash-flow" onPress={openCommercial} style={styles.pulseStat}>
              <Text style={[styles.pulseValue, { color: commercial ? HEALTH_COLOR[commercial.cash_flow_signal] : theme.color.text }]}>{commercial?.cash_flow_signal?.toUpperCase() || '—'}</Text>
              <Text style={styles.pulseLabel}>Cash Flow</Text>
            </Pressable>
          </View>
          <View style={styles.pulseRow}>
            <View style={styles.pulseStat}>
              <Text style={styles.pulseValue}>{projectItems.blocked.length}</Text>
              <Text style={styles.pulseLabel}>Blocked</Text>
            </View>
            <View style={styles.pulseStat}>
              <Text style={styles.pulseValue}>{health?.open_insights ?? insights.length}</Text>
              <Text style={styles.pulseLabel}>Open Risks</Text>
            </View>
            <Pressable testID="pulse-pending-decisions" onPress={openCommercial} style={styles.pulseStat}>
              <Text style={styles.pulseValue}>{commercial?.pending_variations_total ? formatInr(commercial.pending_variations_total) : '—'}</Text>
              <Text style={styles.pulseLabel}>Pending Decisions</Text>
            </Pressable>
          </View>
        </View>

        {/* TODAY'S MISSION */}
        <SectionHeader title="TODAY'S MISSION" icon="flash" count={mission.length} />
        {mission.length === 0 ? (
          <Text style={styles.emptyText}>Nothing urgent right now.</Text>
        ) : (
          mission.slice(0, 8).map((a) => <ActionRow key={a.id} action={a} />)
        )}

        {/* MY ACTION QUEUE — the fuller, priority-sorted list beyond
            what Today's Mission already surfaced; deliberately
            excludes anything already shown above so nothing repeats. */}
        {mission.length > 8 && (
          <>
            <SectionHeader title="MY ACTION QUEUE" icon="list" count={mission.length - 8} />
            {mission.slice(8).map((a) => <ActionRow key={a.id} action={a} />)}
          </>
        )}

        {/* AI SUGGESTIONS */}
        <SectionHeader title="AI SUGGESTIONS" icon="bulb" count={suggestions.length} />
        {suggestions.length === 0 ? (
          <Text style={styles.emptyText}>No suggestions right now.</Text>
        ) : (
          suggestions.slice(0, 5).map((i) => (
            <Pressable key={i.id} testID={`suggestion-${i.id}`} onPress={() => openForInsight(i)} style={styles.suggestionRow}>
              <Ionicons name="bulb-outline" size={16} color={theme.color.brand} />
              <View style={{ flex: 1, marginLeft: 8 }}>
                <Text style={styles.rowTitle}>{i.suggested_operational_action?.title}</Text>
                <Text style={styles.rowSubtext} numberOfLines={2}>{i.suggested_operational_action?.description}</Text>
              </View>
            </Pressable>
          ))
        )}

        {/* UNIFIED PROJECT FEED */}
        <SectionHeader title="PROJECT FEED" icon="time" count={feed.length} />
        {feed.length === 0 ? (
          <Text style={styles.emptyText}>No recent activity.</Text>
        ) : (
          feed.slice(0, 15).map((e) => (
            <View key={e.id} style={styles.feedRow}>
              <View style={styles.feedDot} />
              <View style={{ flex: 1 }}>
                <Text style={styles.rowSubtext}>{e.kind.replace(/_/g, ' ')}</Text>
                <Text style={styles.feedTime}>{new Date(e.created_at).toLocaleString()}</Text>
              </View>
            </View>
          ))
        )}
      </ScrollView>

      <Modal visible={showProjectPicker} animationType="slide" transparent onRequestClose={() => setShowProjectPicker(false)}>
        <View style={styles.modalOverlay}>
          <View style={styles.modalCard}>
            <Text style={styles.modalTitle}>Switch Project</Text>
            <FlatList
              data={projects}
              keyExtractor={(p) => p.id}
              renderItem={({ item }) => (
                <Pressable
                  testID={`switch-project-${item.id}`}
                  onPress={() => { setShowProjectPicker(false); router.replace(`/workspace/${item.id}`); }}
                  style={styles.projectPickRow}>
                  <Text style={styles.rowTitle}>{item.name}</Text>
                  {item.id === id && <Ionicons name="checkmark" size={18} color={theme.color.brand} />}
                </Pressable>
              )}
            />
          </View>
        </View>
      </Modal>
    </SafeAreaView>
  );
}

function StageFocus({ stage, health, commercial, plannedCount, readyCount, lastMilestone, onPress }: {
  stage: string; health: ExplainedHealth | null; commercial: CommercialSummary;
  plannedCount: number; readyCount: number; lastMilestone: any; onPress: () => void;
}) {
  let icon: any = 'compass';
  let title = 'Focus';
  let body = '';

  if (stage === 'planning') {
    icon = 'construct-outline'; title = 'Planning Focus';
    const hasContract = !!commercial?.contract;
    const hasBudget = !!commercial?.budget;
    body = hasContract && hasBudget && plannedCount > 0
      ? `Setup complete — Contract, Budget, and ${plannedCount} milestone(s) in place.`
      : `Setup in progress — ${hasContract ? 'Contract set' : 'Contract needed'}, ${hasBudget ? 'Budget set' : 'Budget needed'}, ${plannedCount} milestone(s) defined.`;
  } else if (stage === 'mobilization') {
    icon = 'people-outline'; title = 'Mobilization Focus';
    body = `${readyCount} item(s) flagged high priority to get moving on before full execution.`;
  } else if (stage === 'execution') {
    icon = 'hammer-outline'; title = 'Execution Focus';
    body = 'Today\'s Mission below is your execution focus — nothing duplicated here.';
  } else if (stage === 'commercial_focus') {
    icon = 'cash-outline'; title = 'Commercial Focus';
    body = commercial
      ? `Cash flow: ${commercial.cash_flow_signal.toUpperCase()} — outstanding ${formatInr(commercial.outstanding_payments.outstanding)}.`
      : 'No commercial data yet for this project.';
  } else if (stage === 'closeout') {
    icon = 'checkmark-done-outline'; title = 'Closeout Focus';
    body = lastMilestone
      ? `Final milestone "${lastMilestone.name}" is ${lastMilestone.status.replace(/_/g, ' ')}. Atlas has no snagging/defect tracking today — this is the closest real signal available.`
      : 'No milestones defined yet to track closeout against.';
  }

  return (
    <Pressable onPress={onPress} style={styles.stageFocusCard} testID="stage-focus">
      <Ionicons name={icon} size={18} color={theme.color.brand} />
      <View style={{ flex: 1, marginLeft: 10 }}>
        <Text style={styles.stageFocusTitle}>{title}</Text>
        <Text style={styles.stageFocusBody}>{body}</Text>
      </View>
      <Ionicons name="chevron-forward" size={16} color={theme.color.textDim} />
    </Pressable>
  );
}

function SectionHeader({ title, icon, count }: { title: string; icon: any; count: number }) {
  return (
    <View style={styles.sectionHeader}>
      <Ionicons name={icon} size={16} color={theme.color.brand} />
      <Text style={styles.sectionTitle}>{title}</Text>
      {count > 0 && <Text style={styles.sectionCount}>{count}</Text>}
    </View>
  );
}

function ActionRow({ action }: { action: UnifiedAction }) {
  const color = action.severity === 'critical' ? theme.color.error : action.severity === 'high' ? theme.color.warning : theme.color.textDim;
  return (
    <Pressable testID={`action-${action.id}`} onPress={action.onPress} style={styles.actionRow}>
      <View style={[styles.actionDot, { backgroundColor: color }]} />
      <View style={{ flex: 1 }}>
        <Text style={styles.rowTitle} numberOfLines={1}>{action.title}</Text>
        <Text style={styles.rowSubtext}>{action.kind}</Text>
      </View>
      <Ionicons name="chevron-forward" size={16} color={theme.color.textDim} />
    </Pressable>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1, backgroundColor: theme.color.surface },
  center: { flex: 1, backgroundColor: theme.color.surface, alignItems: 'center', justifyContent: 'center' },
  header: {
    flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between',
    paddingHorizontal: theme.spacing.lg, paddingVertical: theme.spacing.md,
  },
  projectSwitcher: { flexDirection: 'row', alignItems: 'center', gap: 6, flex: 1 },
  projectName: { color: theme.color.text, fontSize: 18, fontWeight: '800', flexShrink: 1 },
  captureBtn: {
    width: 40, height: 40, borderRadius: 20, backgroundColor: theme.color.brand,
    alignItems: 'center', justifyContent: 'center',
  },
  content: { padding: theme.spacing.md, paddingBottom: 40 },
  errorText: { color: theme.color.error, marginBottom: theme.spacing.sm },
  stageRow: { flexDirection: 'row', gap: 6, marginBottom: theme.spacing.sm },
  stageChip: {
    flex: 1, paddingVertical: 8, borderRadius: theme.radius.sm, alignItems: 'center',
    backgroundColor: theme.color.surface2, borderWidth: 1, borderColor: theme.color.border,
  },
  stageChipActive: { backgroundColor: theme.color.brand, borderColor: theme.color.brand },
  stageChipText: { color: theme.color.textDim, fontSize: 10, fontWeight: '700' },
  stageChipTextActive: { color: theme.color.onBrand },
  stageFocusCard: {
    flexDirection: 'row', alignItems: 'center', backgroundColor: theme.color.surface2,
    borderRadius: theme.radius.md, borderWidth: 1, borderColor: theme.color.border,
    padding: theme.spacing.md, marginBottom: theme.spacing.md,
  },
  stageFocusTitle: { color: theme.color.text, fontSize: 13, fontWeight: '800' },
  stageFocusBody: { color: theme.color.textDim, fontSize: 12, marginTop: 2 },
  sinceLastVisitCard: {
    backgroundColor: theme.color.surface2, borderRadius: theme.radius.md, borderWidth: 1,
    borderColor: theme.color.brand, padding: theme.spacing.md, marginBottom: theme.spacing.md,
  },
  sinceLastVisitTitle: { color: theme.color.text, fontSize: 14, fontWeight: '800', marginBottom: theme.spacing.sm },
  sinceLastVisitRow: {
    flexDirection: 'row', alignItems: 'center', paddingVertical: 8,
    borderTopWidth: 1, borderTopColor: theme.color.border,
  },
  resumeLink: { color: theme.color.brand, fontSize: 12, fontWeight: '700', marginLeft: 8 },
  healthStrip: { flexDirection: 'row', flexWrap: 'wrap', gap: 10, marginBottom: theme.spacing.md },
  healthChip: { flexDirection: 'row', alignItems: 'center', gap: 4 },
  healthDot: { width: 8, height: 8, borderRadius: 4 },
  healthChipText: { color: theme.color.textDim, fontSize: 11, fontWeight: '700' },
  pulseCard: {
    backgroundColor: theme.color.surface2, borderRadius: theme.radius.md, borderWidth: 1,
    borderColor: theme.color.border, padding: theme.spacing.md, marginBottom: theme.spacing.lg, gap: theme.spacing.sm,
  },
  pulseRow: { flexDirection: 'row', justifyContent: 'space-between' },
  pulseStat: { alignItems: 'center', flex: 1 },
  pulseValue: { color: theme.color.text, fontSize: 16, fontWeight: '800' },
  pulseLabel: { color: theme.color.textDim, fontSize: 11, marginTop: 2 },
  sectionHeader: {
    flexDirection: 'row', alignItems: 'center', gap: 8, marginTop: theme.spacing.lg, marginBottom: theme.spacing.sm,
  },
  sectionTitle: { color: theme.color.text, fontSize: 13, fontWeight: '800', letterSpacing: 0.5 },
  sectionCount: {
    color: theme.color.textDim, fontSize: 11, fontWeight: '700', backgroundColor: theme.color.surface2,
    paddingHorizontal: 6, paddingVertical: 2, borderRadius: 8,
  },
  emptyText: { color: theme.color.textDim, fontSize: 13, fontStyle: 'italic' },
  actionRow: {
    flexDirection: 'row', alignItems: 'center', gap: 10, paddingVertical: 10,
    borderBottomWidth: 1, borderBottomColor: theme.color.border,
  },
  actionDot: { width: 8, height: 8, borderRadius: 4 },
  rowTitle: { color: theme.color.text, fontSize: 14, fontWeight: '700' },
  rowSubtext: { color: theme.color.textDim, fontSize: 12, marginTop: 2 },
  suggestionRow: {
    flexDirection: 'row', alignItems: 'flex-start', paddingVertical: 10,
    borderBottomWidth: 1, borderBottomColor: theme.color.border,
  },
  feedRow: { flexDirection: 'row', alignItems: 'center', gap: 10, paddingVertical: 8 },
  feedDot: { width: 6, height: 6, borderRadius: 3, backgroundColor: theme.color.textDim },
  feedTime: { color: theme.color.textDim, fontSize: 11, marginTop: 1 },
  modalOverlay: { flex: 1, backgroundColor: 'rgba(0,0,0,0.5)', justifyContent: 'flex-end' },
  modalCard: {
    backgroundColor: theme.color.surface2, borderTopLeftRadius: theme.radius.lg,
    borderTopRightRadius: theme.radius.lg, padding: theme.spacing.lg, maxHeight: '70%',
  },
  modalTitle: { color: theme.color.text, fontSize: 17, fontWeight: '800', marginBottom: theme.spacing.md },
  projectPickRow: {
    flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between',
    paddingVertical: 14, borderBottomWidth: 1, borderBottomColor: theme.color.border,
  },
});
