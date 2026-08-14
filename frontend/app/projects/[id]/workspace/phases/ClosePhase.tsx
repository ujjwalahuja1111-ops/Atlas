// PX-02 Phase 1 — Close phase. Snags, Handover, and Lessons Learned
// are all confirmed absent from Atlas's current data model (no
// snagging/punch-list engine, no handover checklist, no notes
// collection exist anywhere in this codebase) — shown honestly as
// "Coming Soon," per this task's own explicit instruction, rather
// than fabricated with placeholder data or non-functional buttons.
// The one real, working action on this screen is Archive, which
// already exists (PILOT-02's own archive isolation work).
import { useState } from 'react';
import { View, Text, StyleSheet, Pressable, ActivityIndicator, Alert } from 'react-native';
import { theme } from '@/src/theme';
import { apiArchiveProject, type Project } from '@/src/api';

export function ClosePhase({ projectId, project, onArchived }: {
  projectId: string; project: Project | null; onArchived: () => void;
}) {
  const [archiving, setArchiving] = useState(false);

  const onArchive = () => {
    Alert.alert(
      'Archive Project',
      `Archive "${project?.name || 'this project'}"? It will disappear from active views but remain reachable in archived views.`,
      [
        { text: 'Cancel', style: 'cancel' },
        {
          text: 'Archive', style: 'destructive', onPress: async () => {
            setArchiving(true);
            try {
              await apiArchiveProject(projectId);
              onArchived();
            } catch {
              Alert.alert('Could not archive', 'Please try again.');
            } finally {
              setArchiving(false);
            }
          },
        },
      ],
    );
  };

  return (
    <View style={styles.container} testID="close-phase">
      <ComingSoonSection title="SNAG / PUNCH LIST" />
      <ComingSoonSection title="HANDOVER CHECKLIST" />
      <ComingSoonSection title="LESSONS LEARNED" />

      <View style={styles.section}>
        <Text style={styles.sectionTitle}>ARCHIVE</Text>
        <Text style={styles.muted}>
          Once a project is truly finished, archiving removes it from active Capture, Ops, and project lists — its data remains fully reachable, per PILOT-02&apos;s own archive isolation design.
        </Text>
        <Pressable testID="close-archive-project" onPress={onArchive} disabled={archiving} style={styles.archiveBtn}>
          {archiving ? <ActivityIndicator color="#fff" /> : <Text style={styles.archiveBtnText}>Archive Project</Text>}
        </Pressable>
      </View>
    </View>
  );
}

function ComingSoonSection({ title }: { title: string }) {
  return (
    <View style={styles.section}>
      <Text style={styles.sectionTitle}>{title}</Text>
      <View style={styles.comingSoonCard}>
        <Text style={styles.comingSoonText}>Coming Soon</Text>
      </View>
    </View>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1, padding: theme.spacing.md },
  section: { marginBottom: theme.spacing.lg },
  sectionTitle: { color: theme.color.textDim, fontSize: 11, fontWeight: '800', letterSpacing: 1, marginBottom: 8 },
  comingSoonCard: { backgroundColor: theme.color.surface2, borderRadius: theme.radius.sm, padding: theme.spacing.md, borderWidth: 1, borderColor: theme.color.border, borderStyle: 'dashed', alignItems: 'center' },
  comingSoonText: { color: theme.color.textDim, fontSize: 13, fontWeight: '700' },
  muted: { color: theme.color.textDim, fontSize: 12, marginBottom: theme.spacing.sm },
  archiveBtn: { backgroundColor: theme.color.error, borderRadius: theme.radius.sm, paddingVertical: 12, alignItems: 'center' },
  archiveBtnText: { color: '#fff', fontSize: 14, fontWeight: '800' },
});
