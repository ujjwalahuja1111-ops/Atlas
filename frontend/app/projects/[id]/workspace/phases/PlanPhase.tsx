// PX-02 Phase 1 — Plan phase. Milestones, pending approvals, upcoming
// due dates — all read directly from the existing Commercial Summary
// (summary.milestones, summary.variations), no new API call and no
// new data model.
import { View, Text, StyleSheet } from 'react-native';
import { theme } from '@/src/theme';
import type { CommercialSummary } from '@/src/commercial_api';

function formatDate(d: string | null): string {
  if (!d) return 'Not set';
  return new Date(d).toLocaleDateString();
}

export function PlanPhase({ summary }: { summary: CommercialSummary }) {
  const milestones = summary?.milestones || [];
  const pendingVariations = (summary?.variations || []).filter((v) => v.status === 'draft' || v.status === 'submitted' || v.status === 'client_review');

  return (
    <View style={styles.container} testID="plan-phase">
      <Section title={`MILESTONES (${milestones.length})`}>
        {milestones.length === 0 ? (
          <Text style={styles.muted}>No milestones set up yet — add one from Bill.</Text>
        ) : (
          milestones
            .slice()
            .sort((a, b) => a.sequence - b.sequence)
            .map((m) => (
              <View key={m.id} style={styles.row}>
                <View style={{ flex: 1 }}>
                  <Text style={styles.rowTitle}>{m.name}</Text>
                  <Text style={styles.rowSubtext}>Planned: {formatDate(m.planned_date)}</Text>
                </View>
                <View style={styles.statusBadge}>
                  <Text style={styles.statusBadgeText}>{m.status.replace('_', ' ')}</Text>
                </View>
              </View>
            ))
        )}
      </Section>

      <Section title={`PENDING APPROVALS (${pendingVariations.length})`}>
        {pendingVariations.length === 0 ? (
          <Text style={styles.muted}>Nothing awaiting approval.</Text>
        ) : (
          pendingVariations.map((v) => (
            <View key={v.id} style={styles.row}>
              <Text style={styles.rowTitle}>{v.title}</Text>
              <View style={styles.statusBadge}>
                <Text style={styles.statusBadgeText}>{v.status.replace('_', ' ')}</Text>
              </View>
            </View>
          ))
        )}
      </Section>

      <Section title="DEPENDENCIES">
        <View style={styles.placeholderCard}>
          <Text style={styles.placeholderText}>Dependency tracking planned for a future phase.</Text>
        </View>
      </Section>
    </View>
  );
}

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
  row: { flexDirection: 'row', alignItems: 'center', paddingVertical: 8, borderBottomWidth: 1, borderBottomColor: theme.color.border },
  rowTitle: { color: theme.color.text, fontSize: 13, fontWeight: '600' },
  rowSubtext: { color: theme.color.textDim, fontSize: 11, marginTop: 2 },
  statusBadge: { backgroundColor: theme.color.surface2, paddingHorizontal: 8, paddingVertical: 3, borderRadius: 10 },
  statusBadgeText: { color: theme.color.textDim, fontSize: 10, fontWeight: '700', textTransform: 'capitalize' },
  muted: { color: theme.color.textDim, fontStyle: 'italic', fontSize: 12 },
  placeholderCard: { backgroundColor: theme.color.surface2, borderRadius: theme.radius.sm, padding: theme.spacing.md, borderWidth: 1, borderColor: theme.color.border, borderStyle: 'dashed' },
  placeholderText: { color: theme.color.textDim, fontSize: 13, fontStyle: 'italic', textAlign: 'center' },
});
