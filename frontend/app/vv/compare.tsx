// Visual Validation (VV-01) — Screen 3: Compare Projects.
// "Now every engine becomes testable." Directly renders
// GET /api/portfolio/compare's own response — no client-side
// recomputation of anything, since the whole point is validating the
// backend's own comparison output, not producing a second one.
import { useEffect, useState } from 'react';
import { View, Text, StyleSheet, ScrollView, ActivityIndicator, Pressable } from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import { Ionicons } from '@expo/vector-icons';
import { useRouter } from 'expo-router';
import { theme } from '@/src/theme';
import { apiListProjects, type Project } from '@/src/api';
import { apiCompareProjects, type ComparisonRow } from '@/src/vv_api';
import { URGENCY_COLOR } from '@/src/urgency';

export default function VVCompareProjects() {
  const router = useRouter();
  const [projects, setProjects] = useState<Project[]>([]);
  const [selectedIds, setSelectedIds] = useState<string[]>([]);
  const [rows, setRows] = useState<ComparisonRow[] | null>(null);
  const [loading, setLoading] = useState(true);
  const [comparing, setComparing] = useState(false);
  const [error, setError] = useState('');

  useEffect(() => {
    apiListProjects().then((p) => {
      setProjects(p);
      const rp = p.filter((x) => ['ACDP-VILLA', 'RP-002-NEOTERIC'].includes(x.code));
      if (rp.length === 2) setSelectedIds(rp.map((x) => x.id));
      setLoading(false);
    }).catch(() => setLoading(false));
  }, []);

  const runCompare = async (ids: string[]) => {
    if (ids.length < 2) { setError('Select at least two projects.'); return; }
    setError(''); setComparing(true);
    try {
      const res = await apiCompareProjects(ids);
      setRows(res.projects);
    } catch {
      setError('Comparison failed.');
    } finally {
      setComparing(false);
    }
  };

  useEffect(() => { if (selectedIds.length >= 2) runCompare(selectedIds); }, [selectedIds.join(',')]);

  const toggle = (id: string) => {
    setSelectedIds((prev) => prev.includes(id) ? prev.filter((x) => x !== id) : [...prev, id]);
  };

  if (loading) {
    return <SafeAreaView style={styles.screen}><ActivityIndicator color={theme.color.brand} style={{ marginTop: 80 }} /></SafeAreaView>;
  }

  return (
    <SafeAreaView style={styles.screen}>
      <ScrollView contentContainerStyle={{ padding: theme.spacing.md }}>
        <Pressable testID="vv-back" onPress={() => router.push('/vv')} style={styles.backRow}>
          <Ionicons name="chevron-back" size={18} color={theme.color.textDim} />
          <Text style={styles.backText}>Project Selector</Text>
        </Pressable>
        <Text style={styles.title}>COMPARE PROJECTS</Text>

        <View style={styles.pickerRow}>
          {projects.map((p) => (
            <Pressable key={p.id} testID={`vv-compare-toggle-${p.id}`} onPress={() => toggle(p.id)}
              style={[styles.chip, selectedIds.includes(p.id) && styles.chipSelected]}>
              <Text style={[styles.chipText, selectedIds.includes(p.id) && styles.chipTextSelected]}>{p.name}</Text>
            </Pressable>
          ))}
        </View>
        {error ? <Text style={styles.error}>{error}</Text> : null}

        {comparing ? (
          <ActivityIndicator color={theme.color.brand} style={{ marginTop: theme.spacing.lg }} />
        ) : rows && rows.length >= 2 ? (
          <View style={styles.table}>
            <View style={styles.tableRow}>
              <Text style={styles.rowLabel} />
              {rows.map((r) => (
                <Text key={r.project_id} style={styles.colHeader} numberOfLines={2}>{r.project_name}</Text>
              ))}
            </View>

            <MetricRow label="Health" values={rows.map((r) => ({
              text: r.health.status, color: healthColor(r.health.status),
            }))} />
            <MetricRow label="Workflow" values={rows.map((r) => ({
              text: r.workflow.blocked > 0 ? `${r.workflow.blocked} blocked` : 'Healthy',
              color: r.workflow.blocked > 0 ? URGENCY_COLOR.overdue : URGENCY_COLOR.on_track,
            }))} />
            <MetricRow label="Operations" values={rows.map((r) => ({
              text: String(r.operations.open_items), color: r.operations.critical_open > 0 ? URGENCY_COLOR.overdue : undefined,
            }))} />
            <MetricRow label="Commercial" values={rows.map((r) => ({
              text: r.commercial ? (r.cash_flow_signal === 'healthy' ? 'Healthy' : 'Pressure') : 'No data',
              color: r.commercial ? (r.cash_flow_signal === 'healthy' ? URGENCY_COLOR.on_track : URGENCY_COLOR.due_soon) : theme.color.textDim,
            }))} />
            <MetricRow label="Timeline" values={rows.map((r) => ({ text: String(r.timeline.event_count) }))} />
            <MetricRow label="Variation Exposure" values={rows.map((r) => ({
              text: r.variation_exposure_percent != null ? `${r.variation_exposure_percent}%` : '—',
            }))} />
            <MetricRow label="Risk" values={rows.map((r) => ({
              text: r.health.explanation?.length ? String(r.health.explanation.length) : '0',
              color: (r.health.explanation?.length || 0) > 0 ? URGENCY_COLOR.due_soon : URGENCY_COLOR.on_track,
            }))} />
          </View>
        ) : (
          <Text style={styles.hint}>Select two or more projects above to compare.</Text>
        )}

        {rows && (
          <View style={styles.explanationsBlock}>
            <Text style={styles.sectionLabel}>HEALTH EXPLANATIONS — WHY, NOT JUST A COLOUR</Text>
            {rows.map((r) => (
              <View key={r.project_id} style={styles.explanationCard}>
                <Text style={styles.explanationTitle}>{r.project_name}</Text>
                {r.health.explanation?.length ? r.health.explanation.map((e, i) => (
                  <Text key={i} style={styles.explanationLine}>• {e}</Text>
                )) : <Text style={styles.explanationLine}>No findings.</Text>}
              </View>
            ))}
          </View>
        )}
      </ScrollView>
    </SafeAreaView>
  );
}

function MetricRow({ label, values }: { label: string; values: { text: string; color?: string }[] }) {
  return (
    <View style={styles.tableRow}>
      <Text style={styles.rowLabel}>{label}</Text>
      {values.map((v, i) => (
        <Text key={i} style={[styles.cellText, v.color ? { color: v.color } : null]} numberOfLines={1}>{v.text}</Text>
      ))}
    </View>
  );
}

function healthColor(status: string): string {
  return status === 'Healthy' ? URGENCY_COLOR.on_track
    : status === 'Attention' ? URGENCY_COLOR.due_soon : URGENCY_COLOR.overdue;
}

const styles = StyleSheet.create({
  screen: { flex: 1, backgroundColor: theme.color.surface },
  backRow: { flexDirection: 'row', alignItems: 'center', marginBottom: theme.spacing.sm },
  backText: { color: theme.color.textDim, fontSize: 13 },
  title: { color: theme.color.text, fontSize: theme.font.lg, fontWeight: '900', letterSpacing: 1, marginBottom: theme.spacing.md },
  pickerRow: { flexDirection: 'row', flexWrap: 'wrap', gap: 8, marginBottom: theme.spacing.sm },
  chip: {
    borderWidth: 1, borderColor: theme.color.border, borderRadius: theme.radius.pill,
    paddingHorizontal: theme.spacing.sm, paddingVertical: 8, backgroundColor: theme.color.surface2,
  },
  chipSelected: { borderColor: theme.color.brand, backgroundColor: theme.color.brandTint },
  chipText: { color: theme.color.textDim, fontSize: 12, fontWeight: '700' },
  chipTextSelected: { color: theme.color.brand },
  error: { color: theme.color.error, fontSize: 12, marginBottom: theme.spacing.sm },
  hint: { color: theme.color.textDim, fontSize: 13, fontStyle: 'italic', marginTop: theme.spacing.lg },
  table: { marginTop: theme.spacing.md, backgroundColor: theme.color.surface2, borderRadius: theme.radius.md, borderWidth: 1, borderColor: theme.color.border, padding: theme.spacing.sm },
  tableRow: { flexDirection: 'row', alignItems: 'center', paddingVertical: 8, borderBottomWidth: 1, borderBottomColor: theme.color.border },
  rowLabel: { width: 110, color: theme.color.textDim, fontSize: 12, fontWeight: '800' },
  colHeader: { flex: 1, color: theme.color.text, fontSize: 12, fontWeight: '900', textAlign: 'center' },
  cellText: { flex: 1, color: theme.color.text, fontSize: 13, fontWeight: '700', textAlign: 'center' },
  sectionLabel: { color: theme.color.textDim, fontSize: 11, fontWeight: '800', letterSpacing: 1, marginTop: theme.spacing.lg, marginBottom: theme.spacing.sm },
  explanationsBlock: {},
  explanationCard: { backgroundColor: theme.color.surface2, borderRadius: theme.radius.md, padding: theme.spacing.sm, borderWidth: 1, borderColor: theme.color.border, marginBottom: 8 },
  explanationTitle: { color: theme.color.text, fontSize: 13, fontWeight: '800', marginBottom: 4 },
  explanationLine: { color: theme.color.textMuted, fontSize: 12, marginBottom: 2 },
});
