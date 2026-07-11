import { useCallback, useEffect, useState } from 'react';
import { View, Text, StyleSheet, ScrollView, Pressable, ActivityIndicator, Alert, TextInput } from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import { Ionicons } from '@expo/vector-icons';
import { useLocalSearchParams, useRouter } from 'expo-router';
import { theme } from '@/src/theme';
import { apiListKnowledgeItems } from '@/src/knowledge_api';
import {
  apiGetWorkflow, apiSetWorkflowActivityStatus, apiSetWorkflowActivitySchedule,
  type WorkflowActivity, type WorkflowStatus, type WorkflowScheduleInput,
} from '@/src/workflow_api';

const STATUS_ORDER: WorkflowStatus[] = ['not_started', 'ready', 'in_progress', 'blocked', 'completed'];

const STATUS_LABEL: Record<WorkflowStatus, string> = {
  not_started: 'NOT STARTED', ready: 'READY', in_progress: 'IN PROGRESS',
  blocked: 'BLOCKED', completed: 'COMPLETED',
};

function statusColor(status: WorkflowStatus): string {
  switch (status) {
    case 'completed': return theme.color.success;
    case 'in_progress': return theme.color.info;
    case 'blocked': return theme.color.error;
    case 'ready': return theme.color.brand;
    default: return theme.color.textDim; // not_started
  }
}

export default function WorkflowViewer() {
  const router = useRouter();
  const { id } = useLocalSearchParams<{ id: string }>();
  const [activities, setActivities] = useState<WorkflowActivity[]>([]);
  const [phaseNames, setPhaseNames] = useState<Record<string, string>>({});
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [busyId, setBusyId] = useState<string | null>(null);
  // Sprint 6.1 — Planned/Actual Start/Finish. Collapsed by default per
  // activity (minimal footprint on the existing simple list); draft
  // values are edited locally and saved as a single call.
  const [expandedSchedule, setExpandedSchedule] = useState<string | null>(null);
  const [scheduleDraft, setScheduleDraft] = useState<WorkflowScheduleInput>({});

  const load = useCallback(async () => {
    if (!id) return;
    setLoading(true);
    setLoadError(null);
    try {
      const [wf, phases] = await Promise.all([
        apiGetWorkflow(id),
        apiListKnowledgeItems({ type: 'phase' }),
      ]);
      setActivities(wf);
      const names: Record<string, string> = {};
      for (const p of phases) names[p.id] = p.name;
      setPhaseNames(names);
    } catch (e: any) {
      console.warn(e);
      setLoadError(e?.message || 'Could not load this workflow. Tap to retry.');
    } finally { setLoading(false); }
  }, [id]);

  useEffect(() => { load(); }, [load]);

  const onSetStatus = async (activity: WorkflowActivity, status: WorkflowStatus) => {
    setBusyId(activity.id);
    try {
      await apiSetWorkflowActivityStatus(activity.id, status);
      await load();
    } catch (e: any) {
      Alert.alert('Could not update status', String(e?.message || e));
    } finally { setBusyId(null); }
  };

  // Sprint 6.1 — Planned/Actual Start/Finish
  const toggleSchedule = (activity: WorkflowActivity) => {
    if (expandedSchedule === activity.id) {
      setExpandedSchedule(null);
      return;
    }
    setExpandedSchedule(activity.id);
    setScheduleDraft({
      planned_start: activity.planned_start, planned_finish: activity.planned_finish,
      actual_start: activity.actual_start, actual_finish: activity.actual_finish,
    });
  };

  const saveSchedule = async (activity: WorkflowActivity) => {
    setBusyId(activity.id);
    try {
      await apiSetWorkflowActivitySchedule(activity.id, scheduleDraft);
      setExpandedSchedule(null);
      await load();
    } catch (e: any) {
      Alert.alert('Could not save schedule', String(e?.message || e));
    } finally { setBusyId(null); }
  };

  // Simple grouping by phase — "tree/list", no Gantt, no dates.
  const groups: { phaseId: string; phaseName: string; items: WorkflowActivity[] }[] = [];
  const byPhase: Record<string, WorkflowActivity[]> = {};
  for (const a of activities) {
    const key = a.phase_id || '__none__';
    (byPhase[key] ||= []).push(a);
  }
  for (const [phaseId, items] of Object.entries(byPhase)) {
    groups.push({
      phaseId,
      phaseName: phaseId === '__none__' ? 'No Phase' : (phaseNames[phaseId] || 'Unknown Phase'),
      items: items.sort((a, b) => a.order - b.order),
    });
  }

  return (
    <SafeAreaView style={styles.safe} edges={['top']}>
      <View style={styles.header}>
        <Pressable testID="workflow-back" onPress={() => router.back()} style={styles.iconBtn}>
          <Ionicons name="arrow-back" size={24} color={theme.color.text} />
        </Pressable>
        <View style={{ flex: 1 }}>
          <Text style={styles.h1}>CONSTRUCTION WORKFLOW</Text>
          <Text style={styles.h2}>{activities.length} activities · no scheduling, status only</Text>
        </View>
        <Pressable testID="workflow-refresh" onPress={load} style={styles.iconBtn}>
          <Ionicons name="refresh" size={22} color={theme.color.brand} />
        </Pressable>
      </View>

      {loadError && (
        <Pressable testID="workflow-load-error" onPress={load} style={styles.errorBanner}>
          <Ionicons name="warning" size={16} color={theme.color.error} />
          <Text style={styles.errorBannerText} numberOfLines={2}>{loadError} Tap to retry.</Text>
        </Pressable>
      )}

      {loading ? (
        <View style={styles.center}><ActivityIndicator size="large" color={theme.color.brand} /></View>
      ) : activities.length === 0 ? (
        <View style={styles.center}>
          <Ionicons name="git-network-outline" size={56} color={theme.color.brand} />
          <Text style={styles.emptyTitle}>No workflow yet</Text>
          <Text style={styles.emptyBody}>Generate one from a template on the Project screen.</Text>
        </View>
      ) : (
        <ScrollView contentContainerStyle={{ padding: theme.spacing.md, paddingBottom: 80 }}>
          {groups.map((g) => (
            <View key={g.phaseId} style={styles.group}>
              <Text style={styles.groupTitle}>{g.phaseName.toUpperCase()}</Text>
              {g.items.map((a) => (
                <View key={a.id} testID={`workflow-activity-${a.id}`} style={styles.activityRow}>
                  <View style={styles.activityHead}>
                    <View style={{ flex: 1 }}>
                      <Text style={styles.activityName}>{a.name}</Text>
                      <Text style={styles.activityMeta}>
                        {a.trade ? `${a.trade} · ` : ''}{a.unit || ''}
                        {a.default_duration_days != null ? ` · ${a.default_duration_days}d` : ''}
                        {a.requires_inspection ? ' · Inspection required' : ''}
                      </Text>
                    </View>
                    <View style={[styles.statusBadge, { borderColor: statusColor(a.status) }]}>
                      <Text style={[styles.statusBadgeText, { color: statusColor(a.status) }]}>
                        {STATUS_LABEL[a.status]}
                      </Text>
                    </View>
                  </View>

                  {a.depends_on.length > 0 && (
                    <View style={styles.depsRow}>
                      <Ionicons name="link" size={12} color={theme.color.textDim} />
                      <Text style={styles.depsText} numberOfLines={2}>
                        Depends on: {a.depends_on.map((d) => `${d.name} (${STATUS_LABEL[d.status]})`).join(', ')}
                      </Text>
                    </View>
                  )}

                  {/* Sprint 6.1 — Planned/Actual Start/Finish */}
                  <Pressable testID={`workflow-schedule-toggle-${a.id}`} onPress={() => toggleSchedule(a)}
                    style={styles.scheduleToggle}>
                    <Ionicons name="calendar-outline" size={14} color={theme.color.textDim} />
                    <Text style={styles.scheduleToggleText} numberOfLines={1}>
                      {(a.planned_start || a.planned_finish || a.actual_start || a.actual_finish)
                        ? `Planned ${a.planned_start || '—'} → ${a.planned_finish || '—'} · Actual ${a.actual_start || '—'} → ${a.actual_finish || '—'}`
                        : 'No schedule set — tap to add planned/actual dates'}
                    </Text>
                    <Ionicons name={expandedSchedule === a.id ? 'chevron-up' : 'chevron-down'} size={14} color={theme.color.textDim} />
                  </Pressable>

                  {expandedSchedule === a.id && (
                    <View style={styles.scheduleBox}>
                      <View style={styles.scheduleRow}>
                        <View style={styles.scheduleField}>
                          <Text style={styles.scheduleLabel}>PLANNED START</Text>
                          <TextInput testID={`schedule-planned-start-${a.id}`}
                            value={scheduleDraft.planned_start || ''}
                            onChangeText={(t) => setScheduleDraft((d) => ({ ...d, planned_start: t || null }))}
                            placeholder="YYYY-MM-DD" placeholderTextColor={theme.color.textDim}
                            style={styles.scheduleInput} />
                        </View>
                        <View style={styles.scheduleField}>
                          <Text style={styles.scheduleLabel}>PLANNED FINISH</Text>
                          <TextInput testID={`schedule-planned-finish-${a.id}`}
                            value={scheduleDraft.planned_finish || ''}
                            onChangeText={(t) => setScheduleDraft((d) => ({ ...d, planned_finish: t || null }))}
                            placeholder="YYYY-MM-DD" placeholderTextColor={theme.color.textDim}
                            style={styles.scheduleInput} />
                        </View>
                      </View>
                      <View style={styles.scheduleRow}>
                        <View style={styles.scheduleField}>
                          <Text style={styles.scheduleLabel}>ACTUAL START</Text>
                          <TextInput testID={`schedule-actual-start-${a.id}`}
                            value={scheduleDraft.actual_start || ''}
                            onChangeText={(t) => setScheduleDraft((d) => ({ ...d, actual_start: t || null }))}
                            placeholder="YYYY-MM-DD" placeholderTextColor={theme.color.textDim}
                            style={styles.scheduleInput} />
                        </View>
                        <View style={styles.scheduleField}>
                          <Text style={styles.scheduleLabel}>ACTUAL FINISH</Text>
                          <TextInput testID={`schedule-actual-finish-${a.id}`}
                            value={scheduleDraft.actual_finish || ''}
                            onChangeText={(t) => setScheduleDraft((d) => ({ ...d, actual_finish: t || null }))}
                            placeholder="YYYY-MM-DD" placeholderTextColor={theme.color.textDim}
                            style={styles.scheduleInput} />
                        </View>
                      </View>
                      <Pressable testID={`schedule-save-${a.id}`} onPress={() => saveSchedule(a)}
                        disabled={busyId === a.id} style={styles.scheduleSaveBtn}>
                        {busyId === a.id ? <ActivityIndicator size="small" color={theme.color.onBrand} /> : (
                          <Text style={styles.scheduleSaveBtnText}>SAVE SCHEDULE</Text>
                        )}
                      </Pressable>
                    </View>
                  )}

                  <ScrollView horizontal showsHorizontalScrollIndicator={false} style={styles.statusChipsRow}>
                    {STATUS_ORDER.map((s) => {
                      const active = a.status === s;
                      return (
                        <Pressable key={s} testID={`workflow-set-status-${a.id}-${s}`}
                          onPress={() => onSetStatus(a, s)} disabled={busyId === a.id || active}
                          style={[styles.statusChip, active && { backgroundColor: statusColor(s), borderColor: statusColor(s) }]}>
                          {busyId === a.id ? <ActivityIndicator size="small" color={theme.color.brand} /> : (
                            <Text style={[styles.statusChipText, active && { color: theme.color.onBrand }]}>
                              {STATUS_LABEL[s]}
                            </Text>
                          )}
                        </Pressable>
                      );
                    })}
                  </ScrollView>
                </View>
              ))}
            </View>
          ))}
        </ScrollView>
      )}
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  safe: { flex: 1, backgroundColor: theme.color.surface },
  header: { flexDirection: 'row', alignItems: 'center', padding: theme.spacing.md, gap: theme.spacing.sm },
  h1: { color: theme.color.text, fontSize: 18, fontWeight: '900', letterSpacing: 1 },
  h2: { color: theme.color.brand, fontSize: 11, fontWeight: '700', marginTop: 2 },
  iconBtn: { width: 44, height: 44, borderRadius: 22, backgroundColor: theme.color.surface2,
            alignItems: 'center', justifyContent: 'center' },
  center: { flex: 1, alignItems: 'center', justifyContent: 'center', gap: 8, padding: theme.spacing.lg },
  emptyTitle: { color: theme.color.text, fontSize: 18, fontWeight: '900', letterSpacing: 1, marginTop: 8 },
  emptyBody: { color: theme.color.textMuted, textAlign: 'center' },
  errorBanner: {
    flexDirection: 'row', alignItems: 'center', gap: 8, marginHorizontal: theme.spacing.md,
    marginBottom: theme.spacing.sm, padding: 10, borderRadius: theme.radius.sm,
    backgroundColor: theme.color.surface2, borderWidth: 1, borderColor: theme.color.error,
  },
  errorBannerText: { flex: 1, color: theme.color.error, fontSize: 12, fontWeight: '700' },
  group: { marginBottom: theme.spacing.lg },
  groupTitle: { color: theme.color.brand, fontSize: 12, fontWeight: '900', letterSpacing: 1.5, marginBottom: 8 },
  activityRow: { backgroundColor: theme.color.surface2, borderRadius: theme.radius.md, borderWidth: 1,
                borderColor: theme.color.border, padding: theme.spacing.md, marginBottom: theme.spacing.sm, gap: 8 },
  activityHead: { flexDirection: 'row', alignItems: 'flex-start', gap: 8 },
  activityName: { color: theme.color.text, fontSize: 15, fontWeight: '800' },
  activityMeta: { color: theme.color.textDim, fontSize: 12, marginTop: 2 },
  statusBadge: { paddingHorizontal: 8, paddingVertical: 3, borderRadius: 6, borderWidth: 1 },
  statusBadgeText: { fontSize: 10, fontWeight: '900', letterSpacing: 0.5 },
  depsRow: { flexDirection: 'row', alignItems: 'flex-start', gap: 6 },
  depsText: { flex: 1, color: theme.color.textDim, fontSize: 11 },
  scheduleToggle: { flexDirection: 'row', alignItems: 'center', gap: 6, paddingVertical: 4 },
  scheduleToggleText: { flex: 1, color: theme.color.textDim, fontSize: 11 },
  scheduleBox: { backgroundColor: theme.color.surface3, borderRadius: theme.radius.sm,
                padding: theme.spacing.sm, gap: theme.spacing.sm },
  scheduleRow: { flexDirection: 'row', gap: theme.spacing.sm },
  scheduleField: { flex: 1, gap: 4 },
  scheduleLabel: { color: theme.color.textDim, fontSize: 9, fontWeight: '800', letterSpacing: 0.5 },
  scheduleInput: { color: theme.color.text, backgroundColor: theme.color.surface2,
                  borderRadius: theme.radius.sm, borderWidth: 1, borderColor: theme.color.border,
                  paddingHorizontal: 8, paddingVertical: 6, fontSize: 12 },
  scheduleSaveBtn: { height: 36, borderRadius: theme.radius.sm, backgroundColor: theme.color.brand,
                    alignItems: 'center', justifyContent: 'center' },
  scheduleSaveBtnText: { color: theme.color.onBrand, fontSize: 11, fontWeight: '900', letterSpacing: 1 },
  statusChipsRow: { flexGrow: 0, marginTop: 4 },
  statusChip: { paddingHorizontal: 10, paddingVertical: 6, borderRadius: theme.radius.pill,
               backgroundColor: theme.color.surface3, borderWidth: 1, borderColor: theme.color.border, marginRight: 6 },
  statusChipText: { color: theme.color.textMuted, fontSize: 10, fontWeight: '900', letterSpacing: 0.5 },
});
