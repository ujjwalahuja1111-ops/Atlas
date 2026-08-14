// PX-02 Phase 1 — Review phase. Answers "what changed, what is at
// risk, and what needs attention?" per this task's own explicit
// framing. Health via Explain Health, AI insights via CRE, recent
// changes via CM-01's own Since Last Visit — all existing, reused
// engines, no new computation.
import { useState } from 'react';
import { View, Text, StyleSheet, Pressable, ActivityIndicator, Share } from 'react-native';
import { Ionicons } from '@expo/vector-icons';
import { theme } from '@/src/theme';
import type { ExplainedHealth, Insight, SinceLastVisit } from '@/src/cre_api';
import type { ViewRole } from '@/src/roles';
import { apiGetTodaysDailyReport, apiExportDailyReportMarkdown, type DailyReport } from '@/src/daily_report_api';

const SEVERITY_COLOR: Record<string, string> = {
  critical: '#D32F2F', warning: '#F57C00', advisory: '#1976D2', info: '#616161',
};

export function ReviewPhase({ projectId, health, insights, sinceLastVisit, viewRole }: {
  projectId: string; health: ExplainedHealth | null; insights: Insight[]; sinceLastVisit: SinceLastVisit | null; viewRole: ViewRole;
}) {
  // PX-02 Phase 1 Section 5 — clients see a restricted Review: progress
  // and health only, never the full AI insight/driver detail internal
  // roles get, matching this task's own explicit client restriction.
  const isClient = viewRole === 'client';

  return (
    <View style={styles.container} testID="review-phase">
      <Section title="PROJECT HEALTH">
        {health ? (
          <>
            <View style={styles.healthRow}>
              <View style={[styles.healthBadge, { backgroundColor: STATUS_COLOR[health.status] }]}>
                <Text style={styles.healthBadgeText}>{health.status.toUpperCase()}</Text>
              </View>
              <Text style={styles.healthScore}>{health.score}/100</Text>
            </View>
            {!isClient && health.drivers.length > 0 && (
              <View style={{ marginTop: 8 }}>
                {health.drivers.slice(0, 3).map((d, i) => <Text key={i} style={styles.driverText}>• {d}</Text>)}
              </View>
            )}
          </>
        ) : (
          <Text style={styles.muted}>Health not yet computed for this project.</Text>
        )}
      </Section>

      <DailyReportCard projectId={projectId} clientSafe={isClient} />

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

      <Section title="RECENTLY CHANGED">
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
    </View>
  );
}

// PX-02 Phase 3 Section 4 — the Daily Site Report card. Lives here in
// Review, never Execute, per this task's own explicit "do not clutter
// Execute with full reporting controls" instruction. A Client's own
// card automatically requests the client-safe transformation (the
// existing clientSafe query param the backend already supports) —
// no separate toggle needed, since a client only ever sees one mode.
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
  healthScore: { color: theme.color.text, fontSize: 16, fontWeight: '800' },
  driverText: { color: theme.color.textDim, fontSize: 12, marginTop: 2 },
  row: { flexDirection: 'row', alignItems: 'flex-start', paddingVertical: 8, borderBottomWidth: 1, borderBottomColor: theme.color.border },
  severityDot: { width: 8, height: 8, borderRadius: 4, marginTop: 5 },
  rowTitle: { color: theme.color.text, fontSize: 13, fontWeight: '600' },
  rowSubtext: { color: theme.color.textDim, fontSize: 11, marginTop: 2 },
  muted: { color: theme.color.textDim, fontStyle: 'italic', fontSize: 12 },
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
