// PX-02 Phase 1 — Setup phase. Project foundation: overview, dates,
// team, sites, and a read-only commercial baseline snapshot per this
// task's own explicit "read-only snapshot only" rule for this phase —
// the canonical, detailed commercial owner is Bill, not Setup.
import { View, Text, StyleSheet, Pressable } from 'react-native';
import { useRouter } from 'expo-router';
import { theme } from '@/src/theme';
import type { Project, Site } from '@/src/api';
import type { CommercialSummary } from '@/src/commercial_api';

function formatInr(n?: number | null): string {
  if (n === null || n === undefined) return 'Not set';
  return `₹${n.toLocaleString('en-IN')}`;
}

export function SetupPhase({ projectId, project, sites, summary, onProjectChanged }: {
  projectId: string; project: Project | null; sites: Site[]; summary: CommercialSummary;
  onProjectChanged: () => void;
}) {
  const router = useRouter();
  const activeSites = sites.filter((s) => !s.archived_at);

  return (
    <View style={styles.container} testID="setup-phase">
      <Section title="PROJECT OVERVIEW">
        <Row label="Name" value={project?.name || '—'} />
        <Row label="Location" value={project?.location || 'Not set'} />
        <Row label="Client" value="Not set — no client field exists on Project today" muted />
        <Row label="Status" value={project?.lifecycle_stage ? project.lifecycle_stage.replace('_', ' ') : 'planning'} capitalize />
        <Row label="Created" value={project ? new Date(project.created_at).toLocaleDateString() : '—'} />
      </Section>

      <Section title={`SITES (${activeSites.length})`}>
        {activeSites.length === 0 ? (
          <Text style={styles.muted}>No sites yet.</Text>
        ) : (
          activeSites.map((s) => <Row key={s.id} label={s.name} value={s.location || '—'} />)
        )}
      </Section>

      <Section title="COMMERCIAL BASELINE" subtitle="Read-only snapshot — full detail lives in Bill">
        {summary ? (
          <>
            <Row label="Contract Value" value={formatInr(summary.contract?.current_contract_value)} />
            <Row label="Budget" value={summary.budget ? formatInr(summary.budget.current_budget) : 'Not set'} />
          </>
        ) : (
          <Text style={styles.muted}>No commercial baseline set up yet.</Text>
        )}
      </Section>

      <View style={styles.actionsRow}>
        <Pressable testID="setup-edit-project" onPress={() => router.push(`/projects/${projectId}`)} style={styles.actionBtn}>
          <Text style={styles.actionBtnText}>Edit Project</Text>
        </Pressable>
        <Pressable testID="setup-manage-team" onPress={() => router.push('/projects')} style={styles.actionBtn}>
          <Text style={styles.actionBtnText}>Manage Team</Text>
        </Pressable>
      </View>
      <Text style={styles.muted}>
        &quot;Edit Project&quot; and site management reuse the existing Project screen — a dedicated in-shell edit form was not built this phase, to avoid duplicating that screen&apos;s own working logic.
      </Text>
    </View>
  );
}

function Section({ title, subtitle, children }: { title: string; subtitle?: string; children: React.ReactNode }) {
  return (
    <View style={styles.section}>
      <Text style={styles.sectionTitle}>{title}</Text>
      {subtitle && <Text style={styles.sectionSubtitle}>{subtitle}</Text>}
      {children}
    </View>
  );
}

function Row({ label, value, muted, capitalize }: { label: string; value: string; muted?: boolean; capitalize?: boolean }) {
  return (
    <View style={styles.row}>
      <Text style={styles.rowLabel}>{label}</Text>
      <Text style={[styles.rowValue, muted && styles.muted, capitalize && { textTransform: 'capitalize' }]}>{value}</Text>
    </View>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1, padding: theme.spacing.md },
  section: { marginBottom: theme.spacing.lg },
  sectionTitle: { color: theme.color.textDim, fontSize: 11, fontWeight: '800', letterSpacing: 1, marginBottom: 4 },
  sectionSubtitle: { color: theme.color.textDim, fontSize: 11, fontStyle: 'italic', marginBottom: 8 },
  row: { flexDirection: 'row', justifyContent: 'space-between', paddingVertical: 6 },
  rowLabel: { color: theme.color.textDim, fontSize: 13 },
  rowValue: { color: theme.color.text, fontSize: 13, fontWeight: '600', flexShrink: 1, textAlign: 'right' },
  muted: { color: theme.color.textDim, fontStyle: 'italic', fontSize: 12 },
  actionsRow: { flexDirection: 'row', gap: 10, marginTop: theme.spacing.sm, marginBottom: theme.spacing.sm },
  actionBtn: { flex: 1, backgroundColor: theme.color.surface2, borderRadius: theme.radius.sm, paddingVertical: 12, alignItems: 'center', borderWidth: 1, borderColor: theme.color.border },
  actionBtnText: { color: theme.color.text, fontSize: 13, fontWeight: '700' },
});
