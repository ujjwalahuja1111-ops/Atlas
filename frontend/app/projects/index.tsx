import { useCallback, useEffect, useState } from 'react';
import {
  View, Text, StyleSheet, ScrollView, Pressable, ActivityIndicator,
  TextInput, Modal, Alert,
} from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import { Ionicons } from '@expo/vector-icons';
import { useRouter } from 'expo-router';
import { theme } from '@/src/theme';
import {
  apiListProjects, apiCreateProject, apiUpdateProject, apiArchiveProject, apiUnarchiveProject,
  apiListSites, setActiveSite, loadAuth, type Project, type Site, type User,
} from '@/src/api';

export default function ProjectsScreen() {
  const router = useRouter();
  const [user, setUser] = useState<User | null>(null);
  const [projects, setProjects] = useState<Project[]>([]);
  const [sitesByProject, setSitesByProject] = useState<Record<string, Site[]>>({});
  const [showArchived, setShowArchived] = useState(false);
  const [loading, setLoading] = useState(true);
  const [editing, setEditing] = useState<Partial<Project> | null>(null);
  const [busy, setBusy] = useState(false);

  const load = useCallback(async () => {
    try {
      const auth = await loadAuth();
      setUser(auth.user);
      const ps = await apiListProjects(showArchived);
      setProjects(ps);
      const sites = await apiListSites();
      const map: Record<string, Site[]> = {};
      for (const s of sites) (map[s.project_id] ||= []).push(s);
      setSitesByProject(map);
    } catch (e) { console.warn(e); }
    finally { setLoading(false); }
  }, [showArchived]);

  useEffect(() => { load(); }, [load]);

  const canManage = user?.role !== 'supervisor';

  const onPickProject = async (p: Project) => {
    if ((p as any).archived_at) return;
    const sites = sitesByProject[p.id] || [];
    if (sites.length > 0) {
      await setActiveSite(sites[0].id);
    }
    router.replace('/(tabs)');
  };

  const onSave = async () => {
    if (!editing) return;
    if (!editing.name?.trim()) return;
    setBusy(true);
    try {
      if (editing.id) {
        await apiUpdateProject(editing.id, {
          name: editing.name, code: editing.code, location: editing.location, image_url: editing.image_url,
        });
      } else {
        await apiCreateProject({
          name: editing.name!, code: editing.code, location: editing.location, image_url: editing.image_url,
        });
      }
      setEditing(null);
      await load();
    } catch (e: any) {
      Alert.alert('Save failed', String(e?.message || e));
    } finally { setBusy(false); }
  };

  const onArchive = async (p: Project) => {
    setBusy(true);
    try { await apiArchiveProject(p.id); await load(); }
    catch (e: any) { Alert.alert('Archive failed', String(e?.message || e)); }
    finally { setBusy(false); }
  };

  const onUnarchive = async (p: Project) => {
    setBusy(true);
    try { await apiUnarchiveProject(p.id); await load(); }
    catch (e: any) { Alert.alert('Unarchive failed', String(e?.message || e)); }
    finally { setBusy(false); }
  };

  return (
    <SafeAreaView style={styles.safe} edges={['top']}>
      <View style={styles.header}>
        <Pressable testID="projects-back" onPress={() => router.back()} style={styles.iconBtn}>
          <Ionicons name="arrow-back" size={24} color={theme.color.text} />
        </Pressable>
        <View style={{ flex: 1 }}>
          <Text style={styles.h1}>PROJECTS</Text>
          <Text style={styles.h2}>{showArchived ? 'All projects' : 'Active projects'}</Text>
        </View>
        {canManage && (
          <Pressable testID="projects-new" onPress={() => setEditing({})} style={[styles.iconBtn, styles.primary]}>
            <Ionicons name="add" size={26} color={theme.color.onBrand} />
          </Pressable>
        )}
      </View>

      <View style={styles.toolbar}>
        <Pressable testID="toggle-archived" onPress={() => setShowArchived(v => !v)} style={styles.toggle}>
          <Ionicons name={showArchived ? 'archive' : 'archive-outline'} size={16} color={theme.color.brand} />
          <Text style={styles.toggleText}>{showArchived ? 'HIDE ARCHIVED' : 'SHOW ARCHIVED'}</Text>
        </Pressable>
      </View>

      {loading ? (
        <View style={styles.center}><ActivityIndicator size="large" color={theme.color.brand} /></View>
      ) : (
        <ScrollView contentContainerStyle={{ padding: theme.spacing.md, paddingBottom: 80 }}>
          {projects.length === 0 && (
            <View style={styles.empty}>
              <Ionicons name="business-outline" size={56} color={theme.color.brand} />
              <Text style={styles.emptyTitle}>No projects</Text>
              {canManage && <Text style={styles.emptyBody}>Tap + to add your first project.</Text>}
            </View>
          )}
          {projects.map((p) => {
            const archived = !!(p as any).archived_at;
            const siteCount = (sitesByProject[p.id] || []).length;
            return (
              <Pressable key={p.id} testID={`project-row-${p.id}`}
                onPress={() => onPickProject(p)}
                style={[styles.row, archived && styles.rowArchived]}>
                <View style={[styles.icon, archived && { opacity: 0.4 }]}>
                  <Ionicons name="business" size={24} color={archived ? theme.color.textDim : theme.color.brand} />
                </View>
                <View style={{ flex: 1 }}>
                  <Text style={[styles.title, archived && { color: theme.color.textDim }]} numberOfLines={1}>
                    {p.name}
                  </Text>
                  <Text style={styles.meta} numberOfLines={1}>
                    {p.code ? `${p.code} · ` : ''}{p.location || '—'} · {siteCount} site{siteCount === 1 ? '' : 's'}
                  </Text>
                  {archived ? (
                    <View style={styles.badgeArchived}>
                      <Text style={styles.badgeArchivedText}>ARCHIVED</Text>
                    </View>
                  ) : null}
                </View>
                {canManage && (
                  <View style={styles.actions}>
                    <Pressable testID={`project-edit-${p.id}`} onPress={() => setEditing(p)} style={styles.actionBtn}>
                      <Ionicons name="pencil" size={18} color={theme.color.info} />
                    </Pressable>
                    {archived ? (
                      <Pressable testID={`project-unarchive-${p.id}`} onPress={() => onUnarchive(p)} style={styles.actionBtn}>
                        <Ionicons name="refresh" size={18} color={theme.color.success} />
                      </Pressable>
                    ) : (
                      <Pressable testID={`project-archive-${p.id}`}
                        onPress={() => Alert.alert('Archive project?', `Hide "${p.name}" from active list. You can unarchive later.`,
                          [{ text: 'Cancel' }, { text: 'Archive', style: 'destructive', onPress: () => onArchive(p) }])}
                        style={styles.actionBtn}>
                        <Ionicons name="archive" size={18} color={theme.color.warning} />
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
        <View style={styles.modalBack}>
          <View style={styles.modal}>
            <View style={styles.modalHead}>
              <Text style={styles.modalTitle}>{editing?.id ? 'EDIT PROJECT' : 'NEW PROJECT'}</Text>
              <Pressable testID="project-modal-close" onPress={() => setEditing(null)}>
                <Ionicons name="close" size={26} color={theme.color.textDim} />
              </Pressable>
            </View>
            <Field label="Name" value={editing?.name || ''} testID="project-input-name"
              onChangeText={(t) => setEditing({ ...(editing || {}), name: t })} />
            <Field label="Code" value={editing?.code || ''} testID="project-input-code"
              onChangeText={(t) => setEditing({ ...(editing || {}), code: t })} />
            <Field label="Location" value={editing?.location || ''} testID="project-input-location"
              onChangeText={(t) => setEditing({ ...(editing || {}), location: t })} />
            <Field label="Image URL (optional)" value={editing?.image_url || ''} testID="project-input-image"
              onChangeText={(t) => setEditing({ ...(editing || {}), image_url: t })} />
            <Pressable testID="project-save" onPress={onSave} disabled={busy || !editing?.name?.trim()}
              style={[styles.saveBtn, (busy || !editing?.name?.trim()) && { opacity: 0.5 }]}>
              <Ionicons name="checkmark" size={22} color={theme.color.onBrand} />
              <Text style={styles.saveBtnText}>{editing?.id ? 'SAVE CHANGES' : 'CREATE PROJECT'}</Text>
            </Pressable>
          </View>
        </View>
      </Modal>
    </SafeAreaView>
  );
}

function Field({ label, value, onChangeText, testID }: any) {
  return (
    <View style={{ marginBottom: theme.spacing.sm }}>
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
  h1: { color: theme.color.text, fontSize: 26, fontWeight: '900', letterSpacing: 2 },
  h2: { color: theme.color.brand, fontSize: 12, fontWeight: '700', marginTop: 2 },
  iconBtn: { width: 44, height: 44, borderRadius: 22, backgroundColor: theme.color.surface2,
            alignItems: 'center', justifyContent: 'center' },
  primary: { backgroundColor: theme.color.brand },
  toolbar: { flexDirection: 'row', paddingHorizontal: theme.spacing.md, paddingBottom: theme.spacing.sm, gap: 8 },
  toggle: { flexDirection: 'row', alignItems: 'center', gap: 6, paddingHorizontal: 12, paddingVertical: 6,
            borderRadius: theme.radius.pill, backgroundColor: theme.color.surface2,
            borderWidth: 1, borderColor: theme.color.border },
  toggleText: { color: theme.color.brand, fontSize: 11, fontWeight: '900', letterSpacing: 1 },
  center: { flex: 1, alignItems: 'center', justifyContent: 'center' },
  empty: { alignItems: 'center', padding: theme.spacing.xl, gap: theme.spacing.sm },
  emptyTitle: { color: theme.color.text, fontSize: 20, fontWeight: '900', letterSpacing: 1, marginTop: 8 },
  emptyBody: { color: theme.color.textMuted, textAlign: 'center' },
  row: { flexDirection: 'row', alignItems: 'center', gap: 12, padding: theme.spacing.md,
         backgroundColor: theme.color.surface2, borderRadius: theme.radius.md,
         borderWidth: 1, borderColor: theme.color.border, marginBottom: theme.spacing.sm },
  rowArchived: { opacity: 0.7 },
  icon: { width: 40, height: 40, borderRadius: 20, backgroundColor: theme.color.surface3,
          alignItems: 'center', justifyContent: 'center' },
  title: { color: theme.color.text, fontSize: 16, fontWeight: '800' },
  meta: { color: theme.color.textDim, fontSize: 12, marginTop: 2 },
  badgeArchived: { alignSelf: 'flex-start', paddingHorizontal: 6, paddingVertical: 2, borderRadius: 4,
                   backgroundColor: theme.color.surface3, marginTop: 4 },
  badgeArchivedText: { color: theme.color.warning, fontSize: 10, fontWeight: '900', letterSpacing: 1 },
  actions: { flexDirection: 'row', gap: 6 },
  actionBtn: { width: 36, height: 36, borderRadius: 18, backgroundColor: theme.color.surface3,
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
