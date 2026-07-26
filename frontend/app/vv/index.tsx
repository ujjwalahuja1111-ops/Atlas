// Visual Validation (VV-01) — Screen 1: Project Selector.
// Internal engineering dashboard: the goal is validating that every
// engine behaves correctly, not UI polish. Reference Portfolio
// projects (RP-001/RP-002) are surfaced first since they're the
// canonical, always-available regression datasets; any other real
// project appears below them automatically as it's created — this
// list is never hardcoded to just the two reference projects.
import { useEffect, useState } from 'react';
import { View, Text, StyleSheet, Pressable, ActivityIndicator, ScrollView } from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import { Ionicons } from '@expo/vector-icons';
import { useRouter } from 'expo-router';
import { theme } from '@/src/theme';
import { apiListProjects, type Project } from '@/src/api';

const REFERENCE_CODES = ['ACDP-VILLA', 'RP-002-NEOTERIC'];
const REFERENCE_LABELS: Record<string, string> = {
  'ACDP-VILLA': 'Residential Villa (RP-001)',
  'RP-002-NEOTERIC': 'Commercial Office (RP-002)',
};

export default function VVProjectSelector() {
  const router = useRouter();
  const [projects, setProjects] = useState<Project[]>([]);
  const [loading, setLoading] = useState(true);
  const [selected, setSelected] = useState<string | null>(null);

  useEffect(() => {
    apiListProjects().then((p) => { setProjects(p); setLoading(false); }).catch(() => setLoading(false));
  }, []);

  const reference = projects.filter((p) => REFERENCE_CODES.includes(p.code));
  const other = projects.filter((p) => !REFERENCE_CODES.includes(p.code));

  const openProject = () => {
    if (selected) router.push(`/vv/project/${selected}`);
  };

  return (
    <SafeAreaView style={styles.screen}>
      <ScrollView contentContainerStyle={{ padding: theme.spacing.md }}>
        <View style={styles.header}>
          <Ionicons name="pulse" size={22} color={theme.color.brand} />
          <Text style={styles.title}>ATLAS VISUAL VALIDATION</Text>
        </View>
        <Text style={styles.subtitle}>Internal engineering dashboard — validate every engine, read-only.</Text>

        {loading ? (
          <ActivityIndicator color={theme.color.brand} style={{ marginTop: theme.spacing.xl }} />
        ) : (
          <>
            <Text style={styles.sectionLabel}>REFERENCE PORTFOLIO</Text>
            {reference.map((p) => (
              <ProjectRow key={p.id} project={p} label={REFERENCE_LABELS[p.code]}
                selected={selected === p.id} onSelect={() => setSelected(p.id)} />
            ))}
            {reference.length === 0 && (
              <Text style={styles.empty}>Reference Portfolio not seeded in this environment.</Text>
            )}

            {other.length > 0 && (
              <>
                <Text style={[styles.sectionLabel, { marginTop: theme.spacing.lg }]}>OTHER PROJECTS</Text>
                {other.map((p) => (
                  <ProjectRow key={p.id} project={p} label={p.name}
                    selected={selected === p.id} onSelect={() => setSelected(p.id)} />
                ))}
              </>
            )}
          </>
        )}
      </ScrollView>

      <View style={styles.footer}>
        <Pressable
          testID="vv-open-project"
          disabled={!selected}
          onPress={openProject}
          style={[styles.openButton, !selected && styles.openButtonDisabled]}
        >
          <Text style={styles.openButtonText}>OPEN PROJECT</Text>
          <Ionicons name="arrow-forward" size={20} color={theme.color.onBrand} />
        </Pressable>
        {projects.length >= 2 && (
          <Pressable testID="vv-compare-link" onPress={() => router.push('/vv/compare')} style={styles.compareLink}>
            <Text style={styles.compareLinkText}>Compare Projects →</Text>
          </Pressable>
        )}
      </View>
    </SafeAreaView>
  );
}

function ProjectRow({ project, label, selected, onSelect }: {
  project: Project; label: string; selected: boolean; onSelect: () => void;
}) {
  return (
    <Pressable testID={`vv-project-${project.id}`} onPress={onSelect} style={[styles.row, selected && styles.rowSelected]}>
      <Ionicons name={selected ? 'radio-button-on' : 'radio-button-off'} size={22} color={selected ? theme.color.brand : theme.color.textDim} />
      <View style={{ flex: 1, marginLeft: theme.spacing.sm }}>
        <Text style={styles.rowTitle}>{label}</Text>
        <Text style={styles.rowMeta}>{project.code} · {project.location || 'No location set'}</Text>
      </View>
    </Pressable>
  );
}

const styles = StyleSheet.create({
  screen: { flex: 1, backgroundColor: theme.color.surface },
  header: { flexDirection: 'row', alignItems: 'center', gap: 8, marginBottom: 4 },
  title: { color: theme.color.text, fontSize: theme.font.lg, fontWeight: '900', letterSpacing: 1 },
  subtitle: { color: theme.color.textDim, fontSize: theme.font.sm, marginBottom: theme.spacing.lg },
  sectionLabel: { color: theme.color.textDim, fontSize: 11, fontWeight: '800', letterSpacing: 1, marginBottom: theme.spacing.sm },
  empty: { color: theme.color.textDim, fontSize: theme.font.sm, fontStyle: 'italic' },
  row: {
    flexDirection: 'row', alignItems: 'center', backgroundColor: theme.color.surface2,
    borderRadius: theme.radius.md, borderWidth: 1, borderColor: theme.color.border,
    padding: theme.spacing.sm, marginBottom: 8, minHeight: theme.touch,
  },
  rowSelected: { borderColor: theme.color.brand, backgroundColor: theme.color.brandTint },
  rowTitle: { color: theme.color.text, fontSize: theme.font.base, fontWeight: '700' },
  rowMeta: { color: theme.color.textDim, fontSize: 12, marginTop: 2 },
  footer: {
    padding: theme.spacing.md, borderTopWidth: 1, borderTopColor: theme.color.border,
    gap: theme.spacing.sm,
  },
  openButton: {
    flexDirection: 'row', alignItems: 'center', justifyContent: 'center', gap: 8,
    backgroundColor: theme.color.brand, borderRadius: theme.radius.md, paddingVertical: theme.spacing.sm,
    minHeight: theme.touch,
  },
  openButtonDisabled: { opacity: 0.4 },
  openButtonText: { color: theme.color.onBrand, fontWeight: '800', fontSize: theme.font.base, letterSpacing: 0.5 },
  compareLink: { alignItems: 'center', paddingVertical: theme.spacing.xs },
  compareLinkText: { color: theme.color.brand, fontWeight: '700', fontSize: theme.font.sm },
});
