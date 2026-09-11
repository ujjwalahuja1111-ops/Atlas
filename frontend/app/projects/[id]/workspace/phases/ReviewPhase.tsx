// Atlas Intelligent Project Workspace — Phase B. This is now every
// role's own default landing when opening a project (see
// workspace/index.tsx's own DEFAULT_PHASE_FOR_ROLE), redesigned
// around the brief's own explicit hierarchy: Ask Atlas -> Attention
// -> Health -> What's Happening -> What's Next -> deep workspaces.
// Every field rendered here comes from the same engines already
// fetched by the parent shell (explain-health, insights,
// since-last-visit, lookahead) - zero new backend calculations, zero
// fabricated values. The existing Daily Site Report card is kept
// exactly as it was.
import { useState } from 'react';
import { View, Text, StyleSheet, Pressable, ActivityIndicator, Share } from 'react-native';
import { Ionicons } from '@expo/vector-icons';
import { useRouter } from 'expo-router';
import { theme } from '@/src/theme';
import type { ExplainedHealth, Insight, SinceLastVisit, ProjectLookahead, RecommendedAction } from '@/src/cre_api';
import type { ViewRole } from '@/src/roles';
import { apiGetTodaysDailyReport, apiExportDailyReportMarkdown, type DailyReport } from '@/src/daily_report_api';
import { AtlasShell } from '@/src/AtlasShell';

const SEVERITY_COLOR: Record<string, string> = {
  critical: '#D32F2F', warning: '#F57C00', advisory: '#1976D2', info: '#616161',
};
// The real severity vocabulary (RecommendedAction['severity']) mapped
// to the brief's own CRITICAL / HIGH / MEDIUM labels — a presentation
// mapping only, never a second severity calculation.
const SEVERITY_LABEL: Record<string, string> = {
  critical: 'CRITICAL', warning: 'HIGH', advisory: 'MEDIUM', info: 'INFO',
};

type Router = ReturnType<typeof useRouter>;

export function ReviewPhase({
  projectId, projectName, health, insights, sinceLastVisit, lookahead, viewRole, router, onGoDeeper,
}: {
  projectId: string; projectName: string | null; health: ExplainedHealth | null; insights: Insight[];
  sinceLastVisit: SinceLastVisit | null; lookahead: ProjectLookahead | null; viewRole: ViewRole;
  router: Router; onGoDeeper: (phase: 'setup' | 'plan' | 'execute' | 'bill' | 'close') => void;
}) {
  // Existing, unchanged restriction (PX-02 Phase 1 Section 5) — a
  // Client never sees the full AI insight/driver/recommended-action
  // detail internal roles get. Extended to the new Attention section
  // below, not weakened.
  const isClient = viewRole === 'client';

  return (
    <View style={styles.container} testID="review-phase">
      <Section title="ASK ATLAS">
        <AtlasShell role={viewRole} activeProjectId={projectId} activeProjectName={projectName} />
      </Section>

      {!isClient && (
        <Section title="NEEDS ATTENTION">
          <AttentionList actions={health?.recommended_actions || []} />
        </Section>
      )}

      {!isClient && (
        <Section title="PROJECT HEALTH">
          {health ? (
            <>
              <View style={styles.healthRow}>
                <View style={[styles.healthBadge, { backgroundColor: STATUS_COLOR[health.status] }]}>
                  <Text style={styles.healthBadgeText}>{health.status === 'green' ? 'HEALTHY' : health.status === 'amber' ? 'NEEDS ATTENTION' : 'AT RISK'}</Text>
                </View>
                <Text style={styles.healthScore}>{health.score}</Text>
              </View>
              {health.drivers.length > 0 && (
                <View style={{ marginTop: 8 }}>
                  <Text style={styles.subLabel}>Main reasons:</Text>
                  {health.drivers.slice(0, 3).map((d, i) => <Text key={i} style={styles.driverText}>• {d}</Text>)}
                </View>
              )}
              <Pressable testID="review-understand-health" style={styles.linkBtn} onPress={() => router.push(`/explain-health/${projectId}`)}>
                <Text style={styles.linkBtnText}>Understand why</Text>
                <Ionicons name="chevron-forward" size={13} color={theme.color.brand} />
              </Pressable>
            </>
          ) : (
            <Text style={styles.muted}>Health not yet computed for this project.</Text>
          )}
        </Section>
      )}

      <DailyReportCard projectId={projectId} clientSafe={isClient} />

      <Section title="WHAT'S HAPPENING">
        {!sinceLastVisit || sinceLastVisit.is_first_visit ? (
          <Text style={styles.muted}>{sinceLastVisit?.is_first_visit ? 'This is your first visit — nothing to compare yet.' : 'Nothing recorded yet.'}</Text>
        ) : sinceLastVisit.changes.length === 0 ? (
          <Text style={styles.muted}>No changes since your last visit.</Text>
        ) : (
          sinceLastVisit.changes.slice(0, 6).map((c) => (
            <View key={c.event_id} style={styles.row}>
              <Text style={styles.rowTitle}>{c.what_changed}</Text>
              <Text style={styles.rowSubtext}>{c.why_it_matters}</Text>
            </View>
          ))
        )}
      </Section>

      {!isClient && (
        <Section title="WHAT'S NEXT">
          <WhatsNext lookahead={lookahead} />
        </Section>
      )}

      {!isClient && (
        <Section title="GO DEEPER">
          <View style={styles.deeperRow}>
            <DeeperLink label="Schedule" icon="calendar-outline" onPress={() => onGoDeeper('execute')} />
            <DeeperLink label="Operations" icon="list-outline" onPress={() => onGoDeeper('execute')} />
            <DeeperLink label="Commercial" icon="cash-outline" onPress={() => onGoDeeper('bill')} />
            <DeeperLink label="Full Schedule" icon="git-network-outline" onPress={() => router.push(`/workflow/${projectId}`)} />
          </View>
        </Section>
      )}

      {!isClient && (
        <Section title={`AI INSIGHTS (${insights.length})`}>
          {insights.length === 0 ? (
            <Text style={styles.muted}>No open insights right now.</Text>
          ) : (
            insights.slice(0, 8).map((ins) => (
              <View key={ins.id} style={styles.row}>
                <View style={[styles.severityDot, { backgroundColor: SEVERITY_COLOR[ins.severity] }]} />
                <View style={{ flex: 1, marginLeft: 8 }}>
                  <Text style={styles.rowTitle}>{ins.observation}</Text>
                  <Text style={styles.rowSubtext}>{ins.recommendation}</Text>
                </View>
              </View>
            ))
          )}
        </Section>
      )}
    </View>
  );
}

// Section 3's own WHAT / WHY / WHAT CAN I DO structure, built directly
// from RecommendedAction's own real fields (observation, suggested_action)
// - never fabricated. suggested_action is a nested object
// ({category, title, description}), not a plain string - confirmed
// against the real type before rendering, not assumed.
function AttentionList({ actions }: { actions: RecommendedAction[] }) {
  if (actions.length === 0) {
    return <Text style={styles.muted}>Nothing needs your attention right now.</Text>;
  }
  return (
    <View>
      {actions.slice(0, 5).map((a) => (
        <View key={a.insight_id} style={styles.attentionRow}>
          <View style={[styles.severityPill, { backgroundColor: SEVERITY_COLOR[a.severity] }]}>
            <Text style={styles.severityPillText}>{SEVERITY_LABEL[a.severity] || a.severity.toUpperCase()}</Text>
          </View>
          <Text style={styles.rowTitle}>{a.observation}</Text>
          {a.suggested_action && (
            <Text style={styles.rowSubtext}>{a.suggested_action.title}{a.suggested_action.description ? ` — ${a.suggested_action.description}` : ''}</Text>
          )}
        </View>
      ))}
    </View>
  );
}

// Reuses the exact same real fields (name, trade, ready,
// possible_blockers) already verified live against the backend for
// AtlasResponseCard's own schedule-impact rendering in Phase A - same
// data, same trust, no new assumptions made here.
function WhatsNext({ lookahead }: { lookahead: ProjectLookahead | null }) {
  if (!lookahead || lookahead.upcoming.length === 0) {
    return <Text style={styles.muted}>No upcoming activity data available for this project yet.</Text>;
  }
  return (
    <View>
      {lookahead.upcoming.slice(0, 4).map((a) => (
        <View key={a.activity_id} style={styles.row}>
          <View style={{ flexDirection: 'row', alignItems: 'flex-start', gap: 8 }}>
            <Text style={{ fontSize: 12, marginTop: 2 }}>{a.ready ? '🟢' : '🔴'}</Text>
            <View style={{ flex: 1 }}>
              <Text style={styles.rowTitle}>{a.name}</Text>
              {!a.ready && a.possible_blockers[0] && a.possible_blockers[0] !== 'none identified in Atlas' && (
                <Text style={styles.rowSubtext}>Blocked: {a.possible_blockers[0]}</Text>
              )}
            </View>
          </View>
        </View>
      ))}
    </View>
  );
}

function DeeperLink({ label, icon, onPress }: { label: string; icon: any; onPress: () => void }) {
  return (
    <Pressable style={styles.deeperCard} onPress={onPress}>
      <Ionicons name={icon} size={20} color={theme.color.brand} />
      <Text style={styles.deeperCardText}>{label}</Text>
    </Pressable>
  );
}

// PX-02 Phase 3 Section 4 — the Daily Site Report card, unchanged.
function DailyReportCard({ projectId, clientSafe }: { projectId: string; clientSafe: boolean }) {
  const [report, setReport] = useState<DailyReport | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [expanded, setExpanded] = useState(false);

  const generate = async () => {
    setLoading(true);
    setError(null);
    try {
      const r = await apiGetTodaysDailyReport(projectId, clientSafe);
      setReport(r);
      setExpanded(true);
    } catch {
      setError('Could not generate the report. Please try again.');
    } finally {
      setLoading(false);
    }
  };

  const exportMarkdown = async () => {
    try {
      const md = await apiExportDailyReportMarkdown(projectId, new Date().toISOString().slice(0, 10), clientSafe);
      await Share.share({ message: md, title: 'Atlas Daily Site Report' });
    } catch {
      setError('Could not export the report.');
    }
  };

  const copySummary = async () => {
    if (!report) return;
    await Share.share({ message: report.executive_summary });
  };

  return (
    <View style={styles.section}>
      <Text style={styles.sectionTitle}>DAILY SITE REPORT</Text>
      {!report ? (
        <Pressable testID="daily-report-generate" onPress={generate} disabled={loading} style={styles.reportBtn}>
          {loading ? <ActivityIndicator color={theme.color.onBrand} /> : <Text style={styles.reportBtnText}>Generate Today&apos;s Report</Text>}
        </Pressable>
      ) : (
        <View>
          <Pressable testID="daily-report-toggle" onPress={() => setExpanded(!expanded)} style={styles.reportSummaryRow}>
            <View style={{ flex: 1 }}>
              <Text style={styles.rowTitle}>{report.date}</Text>
              <Text style={styles.rowSubtext} numberOfLines={expanded ? undefined : 2}>{report.executive_summary}</Text>
            </View>
            <Ionicons name={expanded ? 'chevron-up' : 'chevron-down'} size={18} color={theme.color.textDim} />
          </Pressable>

          {expanded && (
            <View style={styles.reportDetail}>
              <Text style={styles.reportSubheading}>Work Completed Today</Text>
              {report.work_completed_today.length === 0 ? (
                <Text style={styles.muted}>No activity recorded.</Text>
              ) : (
                report.work_completed_today.map((w, i) => <Text key={i} style={styles.driverText}>• {w}</Text>)
              )}

              <Text style={styles.reportSubheading}>Blockers & Risks</Text>
              {report.blockers_and_risks.length === 0 ? (
                <Text style={styles.muted}>No open blockers.</Text>
              ) : (
                report.blockers_and_risks.map((b, i) => (
                  <Text key={i} style={styles.driverText}>
                    • {b.title} — open {b.age}{b.owner ? ` (${b.owner})` : ''}
                  </Text>
                ))
              )}

              <Text style={styles.reportSubheading}>AI Forecast Impact</Text>
              <Text style={styles.rowSubtext}>{report.ai_forecast_impact.statement}</Text>
              <Text style={styles.muted}>({report.ai_forecast_impact.confidence})</Text>

              <View style={styles.reportActionsRow}>
                <Pressable testID="daily-report-refresh" onPress={generate} style={styles.reportActionBtn}>
                  <Text style={styles.reportActionBtnText}>Regenerate</Text>
                </Pressable>
                <Pressable testID="daily-report-export" onPress={exportMarkdown} style={styles.reportActionBtn}>
                  <Text style={styles.reportActionBtnText}>Export Markdown</Text>
                </Pressable>
                <Pressable testID="daily-report-copy" onPress={copySummary} style={styles.reportActionBtn}>
                  <Text style={styles.reportActionBtnText}>Copy Summary</Text>
                </Pressable>
              </View>
            </View>
          )}
        </View>
      )}
      {error && <Text style={{ color: theme.color.error, fontSize: 12, marginTop: 6 }}>{error}</Text>}
    </View>
  );
}

const STATUS_COLOR: Record<string, string> = { green: '#2E7D32', amber: '#F57C00', red: '#D32F2F' };

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <View style={styles.section}>
      <Text style={styles.sectionTitle}>{title}</Text>
      {children}
    </View>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1, padding: theme.spacing.md },
  section: { marginBottom: theme.spacing.lg },
  sectionTitle: { color: theme.color.textDim, fontSize: 11, fontWeight: '800', letterSpacing: 1, marginBottom: 8 },
  healthRow: { flexDirection: 'row', alignItems: 'center', gap: 12 },
  healthBadge: { paddingHorizontal: 12, paddingVertical: 4, borderRadius: 12 },
  healthBadgeText: { color: '#fff', fontSize: 12, fontWeight: '800' },
  healthScore: { color: theme.color.text, fontSize: 20, fontWeight: '900' },
  subLabel: { color: theme.color.textDim, fontSize: 11, fontWeight: '700' },
  driverText: { color: theme.color.textDim, fontSize: 12, marginTop: 2 },
  row: { flexDirection: 'row', alignItems: 'flex-start', paddingVertical: 8, borderBottomWidth: 1, borderBottomColor: theme.color.border },
  severityDot: { width: 8, height: 8, borderRadius: 4, marginTop: 5 },
  rowTitle: { color: theme.color.text, fontSize: 13, fontWeight: '600' },
  rowSubtext: { color: theme.color.textDim, fontSize: 11, marginTop: 2 },
  muted: { color: theme.color.textDim, fontStyle: 'italic', fontSize: 12 },
  linkBtn: { flexDirection: 'row', alignItems: 'center', gap: 4, marginTop: 10, alignSelf: 'flex-start' },
  linkBtnText: { color: theme.color.brand, fontSize: 12, fontWeight: '700' },
  attentionRow: {
    backgroundColor: theme.color.surface2, borderRadius: theme.radius.sm, padding: 12, marginBottom: 8,
    borderWidth: 1, borderColor: theme.color.border,
  },
  severityPill: { alignSelf: 'flex-start', borderRadius: theme.radius.pill, paddingVertical: 2, paddingHorizontal: 8, marginBottom: 6 },
  severityPillText: { color: '#fff', fontSize: 10, fontWeight: '800' },
  deeperRow: { flexDirection: 'row', flexWrap: 'wrap', gap: 10 },
  deeperCard: {
    width: '47%', backgroundColor: theme.color.surface2, borderRadius: theme.radius.md, paddingVertical: 16,
    alignItems: 'center', gap: 6, borderWidth: 1, borderColor: theme.color.border,
  },
  deeperCardText: { color: theme.color.text, fontSize: 12, fontWeight: '700' },
  reportBtn: {
    backgroundColor: theme.color.brand, borderRadius: theme.radius.sm, paddingVertical: 12,
    alignItems: 'center',
  },
  reportBtnText: { color: theme.color.onBrand, fontSize: 14, fontWeight: '800' },
  reportSummaryRow: {
    flexDirection: 'row', alignItems: 'flex-start', backgroundColor: theme.color.surface2,
    borderRadius: theme.radius.sm, padding: 12, borderWidth: 1, borderColor: theme.color.border,
  },
  reportDetail: { marginTop: 10, paddingLeft: 4 },
  reportSubheading: { color: theme.color.text, fontSize: 12, fontWeight: '800', marginTop: 10, marginBottom: 4 },
  reportActionsRow: { flexDirection: 'row', gap: 8, marginTop: 14 },
  reportActionBtn: {
    flex: 1, backgroundColor: theme.color.surface2, borderRadius: theme.radius.sm, paddingVertical: 10,
    alignItems: 'center', borderWidth: 1, borderColor: theme.color.border,
  },
  reportActionBtnText: { color: theme.color.text, fontSize: 11, fontWeight: '700' },
});
