// PX-02 Phase 1 — Lifecycle Workspace Shell. The single canonical
// entry point for a project, organized around Setup -> Plan ->
// Execute -> Review -> Bill -> Close, per this task's own explicit
// phase list (no invented terminology).
//
// Reuse strategy, stated plainly: Execute embeds the existing
// UnifiedWorkspace component (workspace/[id].tsx) and Bill embeds the
// existing CommercialWorkspaceScreen component (commercial/[id].tsx)
// directly, unmodified. Both read their own `id` via
// useLocalSearchParams(), which resolves from the current route's
// dynamic segments regardless of which file originally defined the
// route — so embedding them here, under /projects/[id]/workspace/,
// works correctly without touching either file. This reuses ~1780
// lines of existing, already-verified functionality rather than
// rebuilding it, matching this task's own explicit "reuse existing
// screens and components" instruction. One known, minor, accepted
// trade-off: both embedded screens render their own SafeAreaView
// with top edges, producing a small amount of extra top padding when
// nested inside this shell's own header — not fixed here, since doing
// so would mean modifying those two screens, which this task
// explicitly asks not to do ("do not redesign unrelated screens").
import { useCallback, useEffect, useState } from 'react';
import { View, Text, StyleSheet, ScrollView, Pressable, ActivityIndicator } from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import { Ionicons } from '@expo/vector-icons';
import { useRouter, useLocalSearchParams } from 'expo-router';
import { theme } from '@/src/theme';
import { getViewRole, type ViewRole } from '@/src/roles';
import { apiListProjects, apiListSites, type Project, type Site } from '@/src/api';
import { apiGetCommercialSummary, type CommercialSummary } from '@/src/commercial_api';
import { apiExplainHealth, apiListInsights, apiGetSinceLastVisit, type ExplainedHealth, type Insight, type SinceLastVisit } from '@/src/cre_api';

import UnifiedWorkspace from '../../../workspace/[id]';
import CommercialWorkspaceScreen from '../../../commercial/[id]';

import { SetupPhase } from './phases/SetupPhase';
import { PlanPhase } from './phases/PlanPhase';
import { ReviewPhase } from './phases/ReviewPhase';
import { ClosePhase } from './phases/ClosePhase';

type Phase = 'setup' | 'plan' | 'execute' | 'review' | 'bill' | 'close';

const PHASES: { key: Phase; label: string }[] = [
  { key: 'setup', label: 'Setup' },
  { key: 'plan', label: 'Plan' },
  { key: 'execute', label: 'Execute' },
  { key: 'review', label: 'Review' },
  { key: 'bill', label: 'Bill' },
  { key: 'close', label: 'Close' },
];

// PX-02 Phase 1 Section 5 — role-aware default phase on open.
const DEFAULT_PHASE_FOR_ROLE: Record<ViewRole, Phase> = {
  admin: 'review',
  pm: 'execute',
  supervisor: 'execute',
  client: 'review',
};

export default function ProjectWorkspaceShell() {
  const { id } = useLocalSearchParams<{ id: string }>();
  const router = useRouter();
  const [viewRole, setViewRole] = useState<ViewRole | null>(null);
  const [phase, setPhase] = useState<Phase | null>(null);

  const [project, setProject] = useState<Project | null>(null);
  const [sites, setSites] = useState<Site[]>([]);
  const [summary, setSummary] = useState<CommercialSummary>(null);
  const [health, setHealth] = useState<ExplainedHealth | null>(null);
  const [insights, setInsights] = useState<Insight[]>([]);
  const [sinceLastVisit, setSinceLastVisit] = useState<SinceLastVisit | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    getViewRole().then((vr) => {
      setViewRole(vr);
      setPhase((prev) => prev ?? DEFAULT_PHASE_FOR_ROLE[vr]);
    });
  }, []);

  const load = useCallback(async () => {
    if (!id) return;
    const [projects, siteList, commercialSummary, healthResult, insightList, svl] = await Promise.all([
      apiListProjects(true).catch(() => []),
      apiListSites(id).catch(() => []),
      apiGetCommercialSummary(id).catch(() => null),
      apiExplainHealth(id).catch(() => null),
      apiListInsights(id).catch(() => []),
      apiGetSinceLastVisit(id).catch(() => null),
    ]);
    setProject(projects.find((p) => p.id === id) || null);
    setSites(siteList);
    setSummary(commercialSummary);
    setHealth(healthResult);
    setInsights(insightList);
    setSinceLastVisit(svl);
  }, [id]);

  useEffect(() => { (async () => { setLoading(true); await load(); setLoading(false); })(); }, [load]);

  if (loading || !phase || !viewRole) {
    return (
      <SafeAreaView style={styles.center} edges={['top']}>
        <ActivityIndicator color={theme.color.brand} size="large" />
      </SafeAreaView>
    );
  }

  // Client restriction, per this task's own Section 5 — a client sees
  // only Review, never the internal lifecycle rail. Existing
  // permission scoping (Client Dashboard's own data functions) is
  // reused, not re-implemented — this shell just narrows which phase
  // tabs render for this role.
  const visiblePhases = viewRole === 'client' ? PHASES.filter((p) => p.key === 'review') : PHASES;

  return (
    <SafeAreaView style={styles.container} edges={['top']}>
      <WorkspaceHeader
        project={project}
        health={health}
        onBack={() => router.back()}
      />

      {visiblePhases.length > 1 && (
        <ScrollView horizontal showsHorizontalScrollIndicator={false} style={styles.railScroll}
          contentContainerStyle={styles.railContent}>
          {visiblePhases.map((p) => (
            <Pressable key={p.key} testID={`phase-tab-${p.key}`} onPress={() => setPhase(p.key)}
              style={[styles.railTab, phase === p.key && styles.railTabActive]}>
              <Text style={[styles.railTabText, phase === p.key && styles.railTabTextActive]}>{p.label}</Text>
            </Pressable>
          ))}
        </ScrollView>
      )}

      <View style={styles.phaseContent}>
        {phase === 'setup' && id && <SetupPhase projectId={id} project={project} sites={sites} summary={summary} onProjectChanged={load} />}
        {phase === 'plan' && <PlanPhase summary={summary} />}
        {phase === 'execute' && <UnifiedWorkspace />}
        {phase === 'review' && id && <ReviewPhase projectId={id} health={health} insights={insights} sinceLastVisit={sinceLastVisit} viewRole={viewRole} />}
        {phase === 'bill' && <CommercialWorkspaceScreen />}
        {phase === 'close' && id && <ClosePhase projectId={id} project={project} onArchived={() => router.replace('/projects')} />}
      </View>
    </SafeAreaView>
  );
}

function WorkspaceHeader({ project, health, onBack }: {
  project: Project | null; health: ExplainedHealth | null; onBack: () => void;
}) {
  const healthColor = health
    ? (health.status === 'green' ? theme.color.success : health.status === 'amber' ? theme.color.warning : theme.color.error)
    : theme.color.textDim;
  return (
    <View style={styles.header} testID="workspace-shell-header">
      <Pressable testID="workspace-shell-back" onPress={onBack} hitSlop={12}>
        <Ionicons name="arrow-back" size={22} color={theme.color.text} />
      </Pressable>
      <View style={{ flex: 1, marginLeft: 10 }}>
        <Text style={styles.headerTitle} numberOfLines={1}>{project?.name || 'Loading…'}</Text>
        <Text style={styles.headerSubtitle} numberOfLines={1}>
          {project?.lifecycle_stage ? project.lifecycle_stage.replace('_', ' ') : 'Client not set'}
        </Text>
      </View>
      <View style={[styles.healthDot, { backgroundColor: healthColor }]} />
    </View>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1, backgroundColor: theme.color.surface },
  center: { flex: 1, backgroundColor: theme.color.surface, alignItems: 'center', justifyContent: 'center' },
  header: {
    flexDirection: 'row', alignItems: 'center', paddingHorizontal: theme.spacing.lg,
    paddingVertical: theme.spacing.md, borderBottomWidth: 1, borderBottomColor: theme.color.border,
  },
  headerTitle: { color: theme.color.text, fontSize: 16, fontWeight: '800' },
  headerSubtitle: { color: theme.color.textDim, fontSize: 12, marginTop: 2, textTransform: 'capitalize' },
  healthDot: { width: 12, height: 12, borderRadius: 6 },
  railScroll: { flexGrow: 0, borderBottomWidth: 1, borderBottomColor: theme.color.border },
  railContent: { paddingHorizontal: theme.spacing.md, paddingVertical: theme.spacing.sm, gap: 8 },
  railTab: { paddingVertical: 8, paddingHorizontal: 16, borderRadius: 18, backgroundColor: theme.color.surface2 },
  railTabActive: { backgroundColor: theme.color.brand },
  railTabText: { color: theme.color.textDim, fontSize: 13, fontWeight: '700' },
  railTabTextActive: { color: theme.color.onBrand },
  phaseContent: { flex: 1 },
});
