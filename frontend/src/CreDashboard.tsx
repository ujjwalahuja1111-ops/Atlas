// CRE Integration — role-based dashboard cards built ONLY from existing
// Construction Reasoning Engine outputs (src/cre_api.ts, itself a thin
// wrapper around routes/reasoning.py, which already existed on the CRE
// branch untouched by this file). This component adds no reasoning of
// its own: every card is a presentation of a field the engine already
// computed. Insight cards render observation/risk/recommendation/
// severity/suggested_* only — never rule_id, confidence, or evidence,
// per "never expose internal CRE evidence... directly."
import { useEffect, useState, type ReactNode } from 'react';
import { View, Text, StyleSheet, Pressable, ActivityIndicator } from 'react-native';
import { Ionicons } from '@expo/vector-icons';
import { useRouter } from 'expo-router';
import { theme } from './theme';
import type { ViewRole } from './roles';
import {
  apiProjectHealth, apiListInsights, apiProjectLookahead, apiProjectBriefing,
  apiExecutiveAnswer, apiRunReasoning, type ProjectHealth, type Insight, type ProjectBriefing,
  type ExecutiveAnswer, type AttentionInsight,
} from './cre_api';

const SEVERITY_COLOR: Record<string, string> = {
  critical: theme.color.error, warning: theme.color.warning,
  advisory: theme.color.info, info: theme.color.textDim,
};

function Card({ title, icon, testID, children }: { title: string; icon: any; testID: string; children: ReactNode }) {
  return (
    <View style={s.card} testID={testID}>
      <View style={s.head}>
        <Ionicons name={icon} size={18} color={theme.color.brand} />
        <Text style={s.title}>{title}</Text>
      </View>
      {children}
    </View>
  );
}

function Empty({ text }: { text: string }) {
  return <Text style={s.muted}>{text}</Text>;
}

/** Platform Consolidation Sprint — wires POST /projects/{id}/reasoning/run,
 * previously an orphaned endpoint with zero frontend callers. This is the
 * only way the persisted reasoning_insights collection (which
 * apiListInsights reads, feeding Highest Risks / Delays / Suggested
 * Actions / Pending Inspections below) ever gets populated for a real
 * project outside of the ACDP seed script. Management/project_manager
 * only, matching the endpoint's own server-side role gate — never
 * rendered for Site Supervisor. */
function RefreshInsightsButton({ onPress, refreshing }: { onPress: () => void; refreshing: boolean }) {
  return (
    <Pressable testID="cre-refresh-insights" onPress={onPress} disabled={refreshing} style={s.refreshBtn}>
      {refreshing ? <ActivityIndicator size="small" color={theme.color.brand} /> : (
        <Ionicons name="refresh-outline" size={16} color={theme.color.brand} />
      )}
      <Text style={s.refreshBtnText}>{refreshing ? 'Refreshing…' : 'Refresh Insights'}</Text>
    </Pressable>
  );
}

function InsightRow({ insight, onPress }: { insight: Insight; onPress?: () => void }) {
  return (
    <Pressable onPress={onPress} style={s.row} testID={`insight-${insight.id}`}>
      <View style={[s.dot, { backgroundColor: SEVERITY_COLOR[insight.severity] || theme.color.textDim }]} />
      <View style={{ flex: 1 }}>
        <Text style={s.rowText} numberOfLines={2}>{insight.observation}</Text>
        {insight.recommendation ? <Text style={s.rowSub} numberOfLines={2}>{insight.recommendation}</Text> : null}
      </View>
    </Pressable>
  );
}

/** Management: Portfolio Health, Project Health, Executive Briefing, Highest Risks. */
export function ManagementCreCards({ projectId }: { projectId: string | null }) {
  const router = useRouter();
  const [health, setHealth] = useState<ProjectHealth | null>(null);
  const [risks, setRisks] = useState<Insight[] | null>(null);
  const [attention, setAttention] = useState<ExecutiveAnswer | null>(null);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  const load = async () => {
    setErr(null);
    try {
      const att = await apiExecutiveAnswer('attention_today').catch(() => null);
      setAttention(att);
      if (projectId) {
        const [h, ins] = await Promise.all([
          apiProjectHealth(projectId).catch(() => null),
          apiListInsights(projectId, { status: 'open' }).catch(() => [] as Insight[]),
        ]);
        setHealth(h);
        setRisks((ins || []).slice().sort((a, b) => {
          const rank: Record<string, number> = { critical: 0, warning: 1, advisory: 2, info: 3 };
          return (rank[a.severity] ?? 9) - (rank[b.severity] ?? 9);
        }).slice(0, 5));
      }
    } catch (e: any) {
      setErr(e?.message || 'Could not load portfolio insights');
    }
  };

  const refresh = async () => {
    if (!projectId) return;
    setRefreshing(true);
    try { await apiRunReasoning(projectId); await load(); }
    catch (e: any) { setErr(e?.message || 'Could not refresh insights'); }
    finally { setRefreshing(false); }
  };

  useEffect(() => {
    let cancelled = false;
    (async () => { setLoading(true); await load(); if (!cancelled) setLoading(false); })();
    return () => { cancelled = true; };
  }, [projectId]);

  if (loading) return <View style={s.loader}><ActivityIndicator color={theme.color.brand} /></View>;

  return (
    <>
      {projectId && <RefreshInsightsButton onPress={refresh} refreshing={refreshing} />}
      <Card title="PORTFOLIO HEALTH" icon="pulse" testID="cre-portfolio-health">
        {err ? <Empty text={err} /> : attention ? (
          <Text style={s.body}>
            {attention.answer?.total_open_urgent
              ? `${attention.answer.total_open_urgent} urgent item${attention.answer.total_open_urgent === 1 ? '' : 's'} across your portfolio need attention today.`
              : 'Nothing urgent across your portfolio today.'}
          </Text>
        ) : <Empty text="Portfolio-level attention items will appear here once projects have reasoning data." />}
      </Card>

      <Card title="PROJECT HEALTH" icon="fitness" testID="cre-project-health">
        {!projectId ? <Empty text="Select a project to see its health." /> :
          !health ? <Empty text="No health data yet for this project." /> : (
          <>
            <View style={s.healthRow}>
              <Text style={[s.healthScore, { color: health.status === 'green' ? theme.color.success : health.status === 'amber' ? theme.color.warning : theme.color.error }]}>
                {health.score}
              </Text>
              <Text style={s.healthStatus}>{health.status?.toUpperCase()}</Text>
            </View>
            {Object.entries(health.dimensions || {}).map(([dim, d]: [string, any]) => (
              <View key={dim} style={s.dimRow}>
                <Text style={s.dimLabel}>{dim.toUpperCase()}</Text>
                <Text style={s.dimScore}>{d.score}</Text>
              </View>
            ))}
          </>
        )}
      </Card>

      <Card title="HIGHEST RISKS" icon="warning" testID="cre-highest-risks">
        {!projectId ? <Empty text="Select a project to see its risks." /> :
          !risks || risks.length === 0 ? <Empty text="No open risks right now." /> :
          risks.map((r) => <InsightRow key={r.id} insight={r} onPress={() => router.push(`/(tabs)/ops`)} />)}
      </Card>

      <Card title="EXECUTIVE BRIEFING" icon="document-text" testID="cre-executive-briefing">
        {attention ? (
          <Text style={s.body}>
            {(() => {
              const items = attention.answer?.items || [];
              const projectCount = new Set(items.map((i: AttentionInsight) => i.project_id)).size;
              return projectCount > 0
                ? `${projectCount} project${projectCount === 1 ? '' : 's'} need attention today.`
                : 'Nothing urgent across your portfolio today.';
            })()}
          </Text>
        ) : <Empty text="Briefing will appear once reasoning runs have been triggered." />}
      </Card>
    </>
  );
}

/** Project Manager: Today's Priorities, Look Ahead, Delays, Blockers, Suggested Actions. */
export function PmCreCards({ projectId }: { projectId: string | null }) {
  const [briefing, setBriefing] = useState<ProjectBriefing | null>(null);
  const [insights, setInsights] = useState<Insight[]>([]);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);

  const load = async () => {
    if (!projectId) return;
    const [b, ins] = await Promise.all([
      apiProjectBriefing(projectId).catch(() => null),
      apiListInsights(projectId, { status: 'open' }).catch(() => [] as Insight[]),
    ]);
    setBriefing(b);
    setInsights(ins);
  };

  const refresh = async () => {
    if (!projectId) return;
    setRefreshing(true);
    try { await apiRunReasoning(projectId); await load(); }
    finally { setRefreshing(false); }
  };

  useEffect(() => {
    let cancelled = false;
    (async () => {
      if (!projectId) { setLoading(false); return; }
      setLoading(true);
      try { await load(); } finally { if (!cancelled) setLoading(false); }
    })();
    return () => { cancelled = true; };
  }, [projectId]);

  if (!projectId) return <Card title="TODAY'S PRIORITIES" icon="today" testID="cre-pm-priorities"><Empty text="Select a project to see reasoning-driven priorities." /></Card>;
  if (loading) return <View style={s.loader}><ActivityIndicator color={theme.color.brand} /></View>;

  const actionable = insights.filter((i) => i.suggested_operational_action);

  return (
    <>
      <RefreshInsightsButton onPress={refresh} refreshing={refreshing} />
      <Card title="TODAY'S PRIORITIES" icon="today" testID="cre-pm-priorities">
        {!briefing || briefing.todays_priorities.length === 0 ? <Empty text="Nothing flagged as a priority today." /> :
          briefing.todays_priorities.slice(0, 5).map((p, i) => (
            <View key={p.insight_id || i} style={s.row}>
              <View style={[s.dot, { backgroundColor: SEVERITY_COLOR[p.severity] || theme.color.textDim }]} />
              <Text style={s.rowText} numberOfLines={2}>{p.observation}</Text>
            </View>
          ))}
      </Card>

      <Card title="LOOK AHEAD" icon="telescope" testID="cre-pm-lookahead">
        {!briefing || briefing.upcoming_milestones.length === 0 ? <Empty text="No upcoming milestones modelled yet." /> :
          briefing.upcoming_milestones.slice(0, 5).map((m) => (
            <Text key={m.activity_id} style={s.rowText}>• {m.name}</Text>
          ))}
      </Card>

      <Card title="BLOCKERS" icon="hand-left" testID="cre-pm-blockers">
        {!briefing || briefing.blocked_activities.length === 0 ? <Empty text="Nothing blocked right now." /> :
          briefing.blocked_activities.map((b) => <Text key={b.activity_id} style={s.rowText}>• {b.name}</Text>)}
      </Card>

      <Card title="DELAYS" icon="time" testID="cre-pm-delays">
        {insights.filter((i) => i.domain === 'schedule').length === 0 ? <Empty text="No schedule delays reasoned currently." /> :
          insights.filter((i) => i.domain === 'schedule').slice(0, 4).map((i) => <InsightRow key={i.id} insight={i} />)}
      </Card>

      <Card title="SUGGESTED ACTIONS" icon="bulb" testID="cre-pm-suggested-actions">
        {actionable.length === 0 ? <Empty text="No suggested actions right now." /> :
          actionable.slice(0, 5).map((i) => (
            <View key={i.id} style={s.row}>
              <Ionicons name="arrow-forward-circle-outline" size={16} color={theme.color.brand} />
              <Text style={s.rowText} numberOfLines={2}>{i.suggested_operational_action?.title}</Text>
            </View>
          ))}
      </Card>
    </>
  );
}

/** Site Supervisor: Today's Assignments, Activities Ready, Pending Inspections, Overdue Activities. */
export function SupervisorCreCards({ projectId }: { projectId: string | null }) {
  const [look, setLook] = useState<Awaited<ReturnType<typeof apiProjectLookahead>> | null>(null);
  const [insights, setInsights] = useState<Insight[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      if (!projectId) { setLoading(false); return; }
      setLoading(true);
      try {
        const [l, ins] = await Promise.all([
          apiProjectLookahead(projectId).catch(() => null),
          apiListInsights(projectId, { status: 'open' }).catch(() => [] as Insight[]),
        ]);
        if (cancelled) return;
        setLook(l); setInsights(ins);
      } finally { if (!cancelled) setLoading(false); }
    })();
    return () => { cancelled = true; };
  }, [projectId]);

  if (!projectId) return <Card title="TODAY'S ASSIGNMENTS" icon="hammer" testID="cre-sup-assignments"><Empty text="Select a project to see readiness and inspections." /></Card>;
  if (loading) return <View style={s.loader}><ActivityIndicator color={theme.color.brand} /></View>;

  const inspections = insights.filter((i) => i.domain === 'quality');
  const overdue = insights.filter((i) => i.domain === 'schedule' && i.severity !== 'info');

  return (
    <>
      <Card title="ACTIVITIES READY" icon="checkmark-circle" testID="cre-sup-ready">
        {!look || look.ready_now.length === 0 ? <Empty text="Nothing is ready to start yet." /> :
          look.ready_now.slice(0, 5).map((r, i) => <Text key={i} style={s.rowText}>• {r}</Text>)}
      </Card>

      <Card title="PENDING INSPECTIONS" icon="clipboard" testID="cre-sup-inspections">
        {inspections.length === 0 ? <Empty text="No pending inspection concerns." /> :
          inspections.slice(0, 5).map((i) => <InsightRow key={i.id} insight={i} />)}
      </Card>

      <Card title="OVERDUE ACTIVITIES" icon="alert-circle" testID="cre-sup-overdue">
        {overdue.length === 0 ? <Empty text="Nothing overdue right now." /> :
          overdue.slice(0, 5).map((i) => <InsightRow key={i.id} insight={i} />)}
      </Card>
    </>
  );
}

const s = StyleSheet.create({
  refreshBtn: {
    flexDirection: 'row', alignItems: 'center', gap: 6, alignSelf: 'flex-start',
    marginBottom: theme.spacing.sm, paddingVertical: 4,
  },
  refreshBtnText: { color: theme.color.brand, fontSize: 13, fontWeight: '700' },
  card: {
    backgroundColor: theme.color.surface2, borderRadius: theme.radius.md,
    borderWidth: 1, borderColor: theme.color.border, padding: theme.spacing.md,
    gap: theme.spacing.sm, marginBottom: theme.spacing.md,
  },
  head: { flexDirection: 'row', alignItems: 'center', gap: 8, marginBottom: 4 },
  title: { color: theme.color.text, fontSize: 13, fontWeight: '900', letterSpacing: 1 },
  muted: { color: theme.color.textMuted, fontSize: 14, lineHeight: 20 },
  body: { color: theme.color.text, fontSize: 14, lineHeight: 20 },
  loader: { paddingVertical: theme.spacing.lg, alignItems: 'center' },
  row: { flexDirection: 'row', alignItems: 'flex-start', gap: 8, paddingVertical: 6 },
  rowText: { color: theme.color.text, fontSize: 14, flex: 1 },
  rowSub: { color: theme.color.textDim, fontSize: 12, marginTop: 2 },
  dot: { width: 8, height: 8, borderRadius: 4, marginTop: 6 },
  healthRow: { flexDirection: 'row', alignItems: 'baseline', gap: 8 },
  healthScore: { fontSize: 32, fontWeight: '900' },
  healthStatus: { fontSize: 13, fontWeight: '800', color: theme.color.textDim, letterSpacing: 1 },
  dimRow: { flexDirection: 'row', justifyContent: 'space-between', paddingVertical: 3 },
  dimLabel: { color: theme.color.textDim, fontSize: 11, fontWeight: '700', letterSpacing: 0.5 },
  dimScore: { color: theme.color.text, fontSize: 13, fontWeight: '700' },
});
