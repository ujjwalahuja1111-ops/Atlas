// PX-02 Phase 1 — Review phase. Answers "what changed, what is at
// risk, and what needs attention?" per this task's own explicit
// framing. Health via Explain Health, AI insights via CRE, recent
// changes via CM-01's own Since Last Visit — all existing, reused
// engines, no new computation.
import { View, Text, StyleSheet } from 'react-native';
import { theme } from '@/src/theme';
import type { ExplainedHealth, Insight, SinceLastVisit } from '@/src/cre_api';
import type { ViewRole } from '@/src/roles';

const SEVERITY_COLOR: Record<string, string> = {
  critical: '#D32F2F', warning: '#F57C00', advisory: '#1976D2', info: '#616161',
};

export function ReviewPhase({ health, insights, sinceLastVisit, viewRole }: {
  health: ExplainedHealth | null; insights: Insight[]; sinceLastVisit: SinceLastVisit | null; viewRole: ViewRole;
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
});
