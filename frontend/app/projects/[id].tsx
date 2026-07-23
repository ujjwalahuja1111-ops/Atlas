import { useCallback, useEffect, useState } from 'react';
import {
  View, Text, StyleSheet, ScrollView, Pressable, ActivityIndicator,
  TextInput, Modal, Alert, RefreshControl, KeyboardAvoidingView, Platform,
} from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import { Ionicons } from '@expo/vector-icons';
import { useRouter, useLocalSearchParams } from 'expo-router';
import { theme } from '@/src/theme';
import { getViewRole, VIEW_PERMS } from '@/src/roles';
import {
  apiListSites, apiCreateSite, apiUpdateSite, apiArchiveSite, apiUnarchiveSite, apiDeleteSite,
  apiProjectSummary, apiListProjects, setActiveSite, setActiveProject, loadAuth,
  type Site, type Project, type ProjectSummary, type User,
} from '@/src/api';
import { apiListKnowledgeItems, type KnowledgeItem } from '@/src/knowledge_api';
import { apiGetWorkflow, apiGenerateWorkflow, type WorkflowActivity } from '@/src/workflow_api';

export default function ProjectDetail() {
  const router = useRouter();
  const { id } = useLocalSearchParams<{ id: string }>();
  const [user, setUser] = useState<User | null>(null);
  const [canManage, setCanManage] = useState(false);
  const [project, setProject] = useState<Project | null>(null);
  const [summary, setSummary] = useState<ProjectSummary | null>(null);
  const [sites, setSites] = useState<Site[]>([]);
  const [showArchived, setShowArchived] = useState(false);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [editing, setEditing] = useState<Partial<Site> | null>(null);
  const [busy, setBusy] = useState(false);
  const [loadError, setLoadError] = useState<string | null>(null);
  // Sprint 5 — Construction Workflow Engine
  const [workflowCount, setWorkflowCount] = useState<number | null>(null);
  const [templates, setTemplates] = useState<KnowledgeItem[]>([]);
  const [pickingTemplate, setPickingTemplate] = useState(false);
  const [generating, setGenerating] = useState(false);

  const load = useCallback(async () => {
    if (!id) return;
    setLoadError(null);
    try {
      const auth = await loadAuth();
      setUser(auth.user);
      const vr = await getViewRole();
      setCanManage(VIEW_PERMS[vr].canManageProjects);  // Sprint 4.1 fix (audit M3)
      const projs = await apiListProjects(true);
      const p = projs.find((x) => x.id === id) || null;
      setProject(p);
      const [s, sm, wf] = await Promise.all([
        apiListSites(id, showArchived),
        apiProjectSummary(id).catch(() => null),
        apiGetWorkflow(id).catch(() => []),
      ]);
      setSites(s);
      setSummary(sm);
      setWorkflowCount(wf.length);
    } catch (e: any) {
      // Sprint 4.1 fix (audit H4): surface load failures instead of
      // silently swallowing them.
      console.warn(e);
      setLoadError(e?.message || 'Could not load this project. Pull to retry.');
    }
    finally { setLoading(false); setRefreshing(false); }
  }, [id, showArchived]);

  useEffect(() => { load(); }, [load]);

  const onPickSite = async (s: Site) => {
    if ((s as any).archived_at) return;
    await setActiveProject(id!);
    await setActiveSite(s.id);
    router.replace('/(tabs)');
  };

  const onSave = async () => {
    if (!editing) return;
    if (!editing.name?.trim()) return;
    setBusy(true);
    try {
      if (editing.id) {
        await apiUpdateSite(editing.id, {
          name: editing.name, location: editing.location, image_url: editing.image_url,
        });
      } else {
        await apiCreateSite({
          project_id: id!, name: editing.name!,
          location: editing.location, image_url: editing.image_url,
        });
      }
      setEditing(null);
      await load();
    } catch (e: any) {
      Alert.alert('Save failed', String(e?.message || e));
    } finally { setBusy(false); }
  };

  const onArchive = async (s: Site) => {
    setBusy(true);
    try { await apiArchiveSite(s.id); await load(); }
    catch (e: any) { Alert.alert('Archive failed', String(e?.message || e)); }
    finally { setBusy(false); }
  };

  const onUnarchive = async (s: Site) => {
    setBusy(true);
    try { await apiUnarchiveSite(s.id); await load(); }
    catch (e: any) { Alert.alert('Unarchive failed', String(e?.message || e)); }
    finally { setBusy(false); }
  };

  const onDelete = async (s: Site) => {
    setBusy(true);
    try {
      const res = await apiDeleteSite(s.id);
      if (!res.deleted && res.refs) {
        const bits = Object.entries(res.refs)
          .filter(([, v]) => (v as number) > 0)
          .map(([k, v]) => `${k}: ${v}`).join(', ');
        Alert.alert('Cannot delete', `Site has dependent records (${bits}). Archive it instead.`);
      } else {
        await load();
      }
    } catch (e: any) { Alert.alert('Delete failed', String(e?.message || e)); }
    finally { setBusy(false); }
  };

  // Sprint 5 — Construction Workflow Engine
  const onOpenTemplatePicker = async () => {
    setBusy(true);
    try {
      const list = await apiListKnowledgeItems({ type: 'workflow_template' });
      setTemplates(list);
      setPickingTemplate(true);
    } catch (e: any) {
      Alert.alert('Could not load workflow templates', String(e?.message || e));
    } finally { setBusy(false); }
  };

  const onGenerateWorkflow = async (templateId: string) => {
    if (!id) return;
    setGenerating(true);
    try {
      await apiGenerateWorkflow(id, templateId);
      setPickingTemplate(false);
      await load();
      router.push(`/workflow/${id}`);
    } catch (e: any) {
      Alert.alert('Could not generate workflow', String(e?.message || e));
    } finally { setGenerating(false); }
  };

  return (
    <SafeAreaView style={styles.safe} edges={['top']}>
      <View style={styles.header}>
        <Pressable testID="project-back" onPress={() => router.back()} style={styles.iconBtn}>
          <Ionicons name="arrow-back" size={24} color={theme.color.text} />
        </Pressable>
        <View style={{ flex: 1 }}>
          <Text style={styles.h1} numberOfLines={1}>{project?.name || 'PROJECT'}</Text>
          <Text style={styles.h2} numberOfLines={1}>
            {project?.code ? `${project.code} · ` : ''}{project?.location || '—'}
          </Text>
        </View>
        {canManage && (
          <Pressable testID="site-new" onPress={() => setEditing({})} style={[styles.iconBtn, styles.primary]}>
            <Ionicons name="add" size={26} color={theme.color.onBrand} />
          </Pressable>
        )}
      </View>

      {loadError && (
        <Pressable testID="project-detail-load-error" onPress={() => { setLoading(true); load(); }} style={styles.errorBanner}>
          <Ionicons name="warning" size={16} color={theme.color.error} />
          <Text style={styles.errorBannerText} numberOfLines={2}>{loadError} Tap to retry.</Text>
        </Pressable>
      )}

      {loading ? (
        <View style={styles.center}><ActivityIndicator size="large" color={theme.color.brand} /></View>
      ) : (
        <ScrollView
          contentContainerStyle={{ padding: theme.spacing.md, paddingBottom: 80 }}
          refreshControl={<RefreshControl refreshing={refreshing} onRefresh={() => { setRefreshing(true); load(); }} />}>

          {/* Summary card */}
          {summary && (
            <View style={styles.summary}>
              <Text style={styles.sectionLabel}>PROJECT SUMMARY</Text>
              <View style={styles.summaryRow}>
                <SummaryTile icon="business" label="Active Sites"
                  value={summary.active_sites} sub={summary.total_sites !== summary.active_sites
                    ? `of ${summary.total_sites}` : undefined} testID="sum-active-sites" />
                <SummaryTile icon="list" label="Open Tasks"
                  value={summary.open_tasks} testID="sum-open-tasks" />
              </View>
              <View style={styles.summaryRow}>
                <SummaryTile icon="cube" label="Pending Material"
                  value={summary.pending_material_requests} testID="sum-pending-material" />
                <SummaryTile icon="people" label="Pending Labour"
                  value={summary.pending_labour_requests} testID="sum-pending-labour" />
              </View>
            </View>
          )}

          {/* Sprint 6 — Project Workspace: quick-links into existing screens,
              pre-scoped to this project's site. No new screens — reuses
              Timeline (Home tab), Operations (materials/labour/approvals/AI
              proposals), and Knowledge exactly as they already exist. */}
          <View style={styles.workflowCard}>
            <Text style={styles.sectionLabel}>PROJECT WORKSPACE</Text>
            <Pressable testID="project-open-timeline" disabled={sites.length === 0}
              onPress={async () => {
                await setActiveProject(project!.id);
                await setActiveSite(sites[0].id);
                router.push('/(tabs)');
              }}
              style={styles.workflowBtn}>
              <Ionicons name="time-outline" size={20} color={theme.color.brand} />
              <Text style={styles.workflowBtnText}>TIMELINE &amp; EVENTS</Text>
              <Ionicons name="chevron-forward" size={18} color={theme.color.textDim} />
            </Pressable>
            <Pressable testID="project-open-operations" disabled={sites.length === 0}
              onPress={async () => {
                await setActiveProject(project!.id);
                await setActiveSite(sites[0].id);
                router.push('/(tabs)/ops');
              }}
              style={styles.workflowBtn}>
              <Ionicons name="clipboard-outline" size={20} color={theme.color.brand} />
              <Text style={styles.workflowBtnText}>OPERATIONS, APPROVALS &amp; AI PROPOSALS</Text>
              <Ionicons name="chevron-forward" size={18} color={theme.color.textDim} />
            </Pressable>
            {canManage && (
              <Pressable testID="project-open-knowledge" onPress={() => router.push('/knowledge')} style={styles.workflowBtn}>
                <Ionicons name="library-outline" size={20} color={theme.color.brand} />
                <Text style={styles.workflowBtnText}>CONSTRUCTION KNOWLEDGE</Text>
                <Ionicons name="chevron-forward" size={18} color={theme.color.textDim} />
              </Pressable>
            )}
            {sites.length === 0 && (
              <Text style={styles.emptyBody}>Add a site first to view timeline and operations for this project.</Text>
            )}
          </View>

          {/* Sprint 5 — Construction Workflow */}
          <View style={styles.workflowCard}>
            <Text style={styles.sectionLabel}>CONSTRUCTION WORKFLOW</Text>
            {workflowCount === null ? null : workflowCount > 0 ? (
              <Pressable testID="view-workflow" onPress={() => router.push(`/workflow/${id}`)} style={styles.workflowBtn}>
                <Ionicons name="git-network" size={20} color={theme.color.brand} />
                <Text style={styles.workflowBtnText}>VIEW WORKFLOW ({workflowCount} activities)</Text>
                <Ionicons name="chevron-forward" size={18} color={theme.color.textDim} />
              </Pressable>
            ) : canManage ? (
              <Pressable testID="generate-workflow" onPress={onOpenTemplatePicker} disabled={busy} style={styles.workflowBtn}>
                <Ionicons name="add-circle-outline" size={20} color={theme.color.brand} />
                <Text style={styles.workflowBtnText}>GENERATE WORKFLOW FROM TEMPLATE</Text>
              </Pressable>
            ) : (
              <Text style={styles.emptyBody}>No workflow generated yet.</Text>
            )}
          </View>

          {/* Sites section */}
          <View style={styles.sitesHead}>
            <Text style={styles.sectionLabel}>SITES</Text>
            <Pressable testID="toggle-archived-sites" onPress={() => setShowArchived((v) => !v)} style={styles.toggle}>
              <Ionicons name={showArchived ? 'archive' : 'archive-outline'} size={14} color={theme.color.brand} />
              <Text style={styles.toggleText}>{showArchived ? 'HIDE ARCHIVED' : 'SHOW ARCHIVED'}</Text>
            </Pressable>
          </View>

          {sites.length === 0 ? (
            <View style={styles.empty}>
              <Ionicons name="business-outline" size={48} color={theme.color.brand} />
              <Text style={styles.emptyTitle}>No sites</Text>
              {canManage && <Text style={styles.emptyBody}>Tap + to add the first site.</Text>}
            </View>
          ) : sites.map((s) => {
            const archived = !!(s as any).archived_at;
            return (
              <Pressable key={s.id} testID={`site-row-${s.id}`}
                onPress={() => onPickSite(s)}
                style={[styles.row, archived && styles.rowArchived]}>
                <View style={[styles.icon, archived && { opacity: 0.4 }]}>
                  <Ionicons name="business" size={22} color={archived ? theme.color.textDim : theme.color.brand} />
                </View>
                <View style={{ flex: 1 }}>
                  <Text style={[styles.title, archived && { color: theme.color.textDim }]} numberOfLines={1}>{s.name}</Text>
                  <Text style={styles.meta} numberOfLines={1}>{s.location || '—'}</Text>
                  {archived && (
                    <View style={styles.badge}><Text style={styles.badgeText}>ARCHIVED</Text></View>
                  )}
                </View>
                {canManage && (
                  <View style={styles.actions}>
                    <Pressable testID={`site-edit-${s.id}`} onPress={() => setEditing(s)} style={styles.actionBtn}>
                      <Ionicons name="pencil" size={16} color={theme.color.info} />
                    </Pressable>
                    {archived ? (
                      <>
                        <Pressable testID={`site-unarchive-${s.id}`} onPress={() => onUnarchive(s)} style={styles.actionBtn}>
                          <Ionicons name="refresh" size={16} color={theme.color.success} />
                        </Pressable>
                        <Pressable testID={`site-delete-${s.id}`}
                          onPress={() => Alert.alert('Delete site?', 'This is permanent. Only works if no events / items / proposals reference this site.', [{ text: 'Cancel' }, { text: 'Delete', style: 'destructive', onPress: () => onDelete(s) }])}
                          style={styles.actionBtn}>
                          <Ionicons name="trash" size={16} color={theme.color.error} />
                        </Pressable>
                      </>
                    ) : (
                      <Pressable testID={`site-archive-${s.id}`}
                        onPress={() => Alert.alert('Archive site?', `Hide "${s.name}" from active list.`, [{ text: 'Cancel' }, { text: 'Archive', style: 'destructive', onPress: () => onArchive(s) }])}
                        style={styles.actionBtn}>
                        <Ionicons name="archive" size={16} color={theme.color.warning} />
                      </Pressable>
                    )}
                  </View>
                )}
              </Pressable>
            );
          })}
        </ScrollView>
      )}

      <Modal visible={!!editing} animationType="slide" transparent>
        <KeyboardAvoidingView style={{ flex: 1 }} behavior={Platform.OS === 'ios' ? 'padding' : undefined}>
        <View style={styles.modalBack}>
          <View style={styles.modal}>
            <View style={styles.modalHead}>
              <Text style={styles.modalTitle}>{editing?.id ? 'EDIT SITE' : 'NEW SITE'}</Text>
              <Pressable testID="site-modal-close" onPress={() => setEditing(null)}>
                <Ionicons name="close" size={26} color={theme.color.textDim} />
              </Pressable>
            </View>
            <Field label="Name" value={editing?.name || ''} testID="site-input-name"
              onChangeText={(t: string) => setEditing({ ...(editing || {}), name: t })} />
            <Field label="Location" value={editing?.location || ''} testID="site-input-location"
              onChangeText={(t: string) => setEditing({ ...(editing || {}), location: t })} />
            <Field label="Image URL (optional)" value={editing?.image_url || ''} testID="site-input-image"
              onChangeText={(t: string) => setEditing({ ...(editing || {}), image_url: t })} />
            <Pressable testID="site-save" onPress={onSave} disabled={busy || !editing?.name?.trim()}
              style={[styles.saveBtn, (busy || !editing?.name?.trim()) && { opacity: 0.5 }]}>
              <Ionicons name="checkmark" size={22} color={theme.color.onBrand} />
              <Text style={styles.saveBtnText}>{editing?.id ? 'SAVE CHANGES' : 'CREATE SITE'}</Text>
            </Pressable>
          </View>
        </View>
        </KeyboardAvoidingView>
      </Modal>

      {/* Sprint 5 — Workflow Template picker */}
      <Modal visible={pickingTemplate} animationType="slide" transparent onRequestClose={() => setPickingTemplate(false)}>
        <View style={styles.modalBack}>
          <View style={styles.modal}>
            <View style={styles.modalHead}>
              <Text style={styles.modalTitle}>SELECT A WORKFLOW TEMPLATE</Text>
              <Pressable onPress={() => setPickingTemplate(false)}>
                <Ionicons name="close" size={26} color={theme.color.textDim} />
              </Pressable>
            </View>
            <ScrollView style={{ maxHeight: 400 }}>
              {templates.length === 0 && (
                <Text style={styles.emptyBody}>
                  No workflow templates exist yet. Create one in Construction Knowledge first.
                </Text>
              )}
              {templates.map((t) => (
                <Pressable key={t.id} testID={`template-option-${t.id}`}
                  onPress={() => onGenerateWorkflow(t.id)} disabled={generating}
                  style={styles.templateOption}>
                  <View style={{ flex: 1 }}>
                    <Text style={styles.templateOptionText}>{t.name}</Text>
                    {t.description ? <Text style={styles.templateOptionSub} numberOfLines={2}>{t.description}</Text> : null}
                  </View>
                  {generating ? <ActivityIndicator size="small" color={theme.color.brand} />
                    : <Ionicons name="chevron-forward" size={18} color={theme.color.textDim} />}
                </Pressable>
              ))}
            </ScrollView>
          </View>
        </View>
      </Modal>
    </SafeAreaView>
  );
}

function SummaryTile({ icon, label, value, sub, testID }: any) {
  return (
    <View testID={testID} style={styles.tile}>
      <View style={styles.tileHead}>
        <Ionicons name={icon} size={16} color={theme.color.brand} />
        <Text style={styles.tileLabel}>{label}</Text>
      </View>
      <Text style={styles.tileValue}>{value}</Text>
      {sub ? <Text style={styles.tileSub}>{sub}</Text> : null}
    </View>
  );
}

function Field({ label, value, onChangeText, testID }: any) {
  return (
    <View style={{ marginBottom: 10 }}>
      <Text style={styles.label}>{label}</Text>
      <TextInput
        testID={testID}
        value={value} onChangeText={onChangeText}
        placeholderTextColor={theme.color.textDim}
        style={styles.input}
      />
    </View>
  );
}

const styles = StyleSheet.create({
  safe: { flex: 1, backgroundColor: theme.color.surface },
  header: { flexDirection: 'row', alignItems: 'center', padding: theme.spacing.md, gap: theme.spacing.sm },
  h1: { color: theme.color.text, fontSize: 22, fontWeight: '900', letterSpacing: 1 },
  h2: { color: theme.color.brand, fontSize: 12, fontWeight: '700', marginTop: 2 },
  iconBtn: { width: 44, height: 44, borderRadius: 22, backgroundColor: theme.color.surface2,
            alignItems: 'center', justifyContent: 'center' },
  primary: { backgroundColor: theme.color.brand },
  center: { flex: 1, alignItems: 'center', justifyContent: 'center' },
  sectionLabel: { color: theme.color.brand, fontSize: 11, fontWeight: '900', letterSpacing: 2, marginBottom: 8 },
  errorBanner: {
    flexDirection: 'row', alignItems: 'center', gap: 8, marginHorizontal: theme.spacing.md,
    marginBottom: theme.spacing.sm, padding: 10, borderRadius: theme.radius.sm,
    backgroundColor: theme.color.surface2, borderWidth: 1, borderColor: theme.color.error,
  },
  errorBannerText: { flex: 1, color: theme.color.error, fontSize: 12, fontWeight: '700' },
  summary: { marginBottom: theme.spacing.md, padding: theme.spacing.md,
             backgroundColor: theme.color.surface2, borderRadius: theme.radius.md,
             borderWidth: 1, borderColor: theme.color.border },
  workflowCard: { marginBottom: theme.spacing.md, padding: theme.spacing.md,
                 backgroundColor: theme.color.surface2, borderRadius: theme.radius.md,
                 borderWidth: 1, borderColor: theme.color.border },
  workflowBtn: { flexDirection: 'row', alignItems: 'center', gap: 10, height: 48,
                paddingHorizontal: 4 },
  workflowBtnText: { flex: 1, color: theme.color.text, fontSize: 13, fontWeight: '800' },
  templateOption: { flexDirection: 'row', alignItems: 'center', gap: 10, paddingVertical: 14,
                    borderBottomWidth: 1, borderBottomColor: theme.color.border },
  templateOptionText: { color: theme.color.text, fontSize: 16, fontWeight: '700' },
  templateOptionSub: { color: theme.color.textDim, fontSize: 12, marginTop: 2 },
  summaryRow: { flexDirection: 'row', gap: 10, marginBottom: 8 },
  tile: { flex: 1, backgroundColor: theme.color.surface3, borderRadius: theme.radius.sm, padding: 12 },
  tileHead: { flexDirection: 'row', alignItems: 'center', gap: 6, marginBottom: 8 },
  tileLabel: { color: theme.color.textDim, fontSize: 11, fontWeight: '800', letterSpacing: 1 },
  tileValue: { color: theme.color.text, fontSize: 28, fontWeight: '900' },
  tileSub: { color: theme.color.textDim, fontSize: 11, marginTop: 2 },
  sitesHead: { flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between', marginBottom: 8 },
  toggle: { flexDirection: 'row', alignItems: 'center', gap: 4, paddingHorizontal: 10, paddingVertical: 4,
            borderRadius: theme.radius.pill, backgroundColor: theme.color.surface2,
            borderWidth: 1, borderColor: theme.color.border },
  toggleText: { color: theme.color.brand, fontSize: 10, fontWeight: '900', letterSpacing: 1 },
  empty: { alignItems: 'center', padding: theme.spacing.lg, gap: 6 },
  emptyTitle: { color: theme.color.text, fontSize: 16, fontWeight: '900', marginTop: 6 },
  emptyBody: { color: theme.color.textMuted, fontSize: 13 },
  row: { flexDirection: 'row', alignItems: 'center', gap: 12, padding: theme.spacing.md,
         backgroundColor: theme.color.surface2, borderRadius: theme.radius.md,
         borderWidth: 1, borderColor: theme.color.border, marginBottom: 8 },
  rowArchived: { opacity: 0.75 },
  icon: { width: 40, height: 40, borderRadius: 20, backgroundColor: theme.color.surface3,
          alignItems: 'center', justifyContent: 'center' },
  title: { color: theme.color.text, fontSize: 15, fontWeight: '800' },
  meta: { color: theme.color.textDim, fontSize: 12, marginTop: 2 },
  badge: { alignSelf: 'flex-start', paddingHorizontal: 6, paddingVertical: 2, borderRadius: 4,
           backgroundColor: theme.color.surface3, marginTop: 4 },
  badgeText: { color: theme.color.warning, fontSize: 9, fontWeight: '900', letterSpacing: 1 },
  actions: { flexDirection: 'row', gap: 4 },
  actionBtn: { width: 32, height: 32, borderRadius: 16, backgroundColor: theme.color.surface3,
              alignItems: 'center', justifyContent: 'center' },
  modalBack: { flex: 1, backgroundColor: 'rgba(0,0,0,0.6)', justifyContent: 'flex-end' },
  modal: { backgroundColor: theme.color.surface, borderTopLeftRadius: 18, borderTopRightRadius: 18,
           padding: theme.spacing.lg, gap: 6 },
  modalHead: { flexDirection: 'row', alignItems: 'center', marginBottom: theme.spacing.sm },
  modalTitle: { flex: 1, color: theme.color.brand, fontSize: 14, fontWeight: '900', letterSpacing: 2 },
  label: { color: theme.color.textDim, fontSize: 11, fontWeight: '800', letterSpacing: 1, marginBottom: 4 },
  input: { color: theme.color.text, backgroundColor: theme.color.surface2,
           borderRadius: theme.radius.sm, borderWidth: 1, borderColor: theme.color.border,
           paddingHorizontal: 12, paddingVertical: 10, fontSize: 15 },
  saveBtn: { marginTop: theme.spacing.md, flexDirection: 'row', alignItems: 'center', justifyContent: 'center',
            gap: 8, height: 52, borderRadius: theme.radius.md, backgroundColor: theme.color.brand },
  saveBtnText: { color: theme.color.onBrand, fontSize: 16, fontWeight: '900', letterSpacing: 1 },
});
