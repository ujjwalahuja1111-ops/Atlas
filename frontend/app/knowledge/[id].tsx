import { useCallback, useEffect, useState } from 'react';
import {
  View, Text, StyleSheet, ScrollView, Pressable, ActivityIndicator, TextInput, Modal, Alert,
} from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import { Ionicons } from '@expo/vector-icons';
import { useLocalSearchParams, useRouter } from 'expo-router';
import { theme } from '@/src/theme';
import { getViewRole, type ViewRole } from '@/src/roles';
import {
  apiGetKnowledgeItem, apiUpdateKnowledgeItem, apiListKnowledgeVersions, apiKnowledgeMeta,
  apiListKnowledgeItems, apiAddKnowledgeRelationship, apiRemoveKnowledgeRelationship,
  SETTABLE_KNOWLEDGE_STATUSES,
  type KnowledgeItem, type KnowledgeVersion, type KnowledgeMeta, type KnowledgeStatus,
} from '@/src/knowledge_api';

export default function KnowledgeDetail() {
  const { id } = useLocalSearchParams<{ id: string }>();
  const router = useRouter();
  const [viewRole, setViewRole] = useState<ViewRole | null>(null);
  const [item, setItem] = useState<KnowledgeItem | null>(null);
  const [versions, setVersions] = useState<KnowledgeVersion[]>([]);
  const [meta, setMeta] = useState<KnowledgeMeta | null>(null);
  const [candidates, setCandidates] = useState<KnowledgeItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [editingField, setEditingField] = useState<{ name: string; description: string; status: KnowledgeStatus } | null>(null);
  const [addingRel, setAddingRel] = useState(false);
  const [relType, setRelType] = useState('depends_on');
  const [relTarget, setRelTarget] = useState<KnowledgeItem | null>(null);
  const [relTargetPicker, setRelTargetPicker] = useState(false);
  const [relNote, setRelNote] = useState('');
  const [showVersions, setShowVersions] = useState(false);
  const [busy, setBusy] = useState(false);
  const [loadError, setLoadError] = useState<string | null>(null);

  const load = useCallback(async () => {
    if (!id) return;
    setLoading(true);
    setLoadError(null);
    try {
      const [it, vs, m] = await Promise.all([
        apiGetKnowledgeItem(id), apiListKnowledgeVersions(id), apiKnowledgeMeta(),
      ]);
      setItem(it);
      setVersions(vs);
      setMeta(m);
      const others = await apiListKnowledgeItems({});
      setCandidates(others.filter((o) => o.id !== id));
    } catch (e: any) {
      // Sprint 4.1 fix (audit H4): surface load failures instead of
      // silently swallowing them.
      console.warn(e);
      setLoadError(e?.message || 'Could not load this item.');
    }
    finally { setLoading(false); }
  }, [id]);

  useEffect(() => { getViewRole().then(setViewRole); }, []);
  useEffect(() => { if (viewRole === 'admin') load(); }, [viewRole, load]);

  const onSaveEdit = async () => {
    if (!item || !editingField) return;
    setBusy(true);
    try {
      const updated = await apiUpdateKnowledgeItem(item.id, {
        name: editingField.name, description: editingField.description, status: editingField.status,
      });
      setItem(updated);
      setEditingField(null);
      await load();
    } catch (e: any) { Alert.alert('Save failed', String(e?.message || e)); }
    finally { setBusy(false); }
  };

  const onAddRelationship = async () => {
    if (!item || !relTarget) return;
    setBusy(true);
    try {
      const updated = await apiAddKnowledgeRelationship(item.id, {
        type: relType, target_id: relTarget.id,
        metadata: relNote ? { note: relNote } : {},
      });
      setItem(updated);
      setAddingRel(false);
      setRelTarget(null);
      setRelNote('');
      await load();
    } catch (e: any) { Alert.alert('Could not add relationship', String(e?.message || e)); }
    finally { setBusy(false); }
  };

  const onRemoveRelationship = async (relationshipId: string) => {
    if (!item) return;
    setBusy(true);
    try {
      const updated = await apiRemoveKnowledgeRelationship(item.id, relationshipId);
      setItem(updated);
      await load();
    } catch (e: any) { Alert.alert('Could not remove relationship', String(e?.message || e)); }
    finally { setBusy(false); }
  };

  if (viewRole === null || loading) {
    return (
      <SafeAreaView style={styles.safe}><View style={styles.center}>
        <ActivityIndicator color={theme.color.brand} size="large" />
      </View></SafeAreaView>
    );
  }

  if (!item) {
    return (
      <SafeAreaView style={styles.safe}><View style={styles.center}>
        <Ionicons name="warning" size={48} color={theme.color.error} />
        <Text style={{ color: theme.color.error, marginTop: 12, textAlign: 'center', paddingHorizontal: 24 }}>
          {loadError || 'Item not found.'}
        </Text>
        <Pressable testID="knowledge-detail-retry" onPress={load} style={{ marginTop: 16 }}>
          <Text style={{ color: theme.color.brand, fontWeight: '900' }}>TAP TO RETRY</Text>
        </Pressable>
      </View></SafeAreaView>
    );
  }

  if (viewRole !== 'admin') {
    return (
      <SafeAreaView style={styles.safe} edges={['top']}>
        <View style={styles.center}>
          <Ionicons name="lock-closed-outline" size={48} color={theme.color.textDim} />
          <Text style={styles.emptyTitle}>Admin access required</Text>
        </View>
      </SafeAreaView>
    );
  }

  return (
    <SafeAreaView style={styles.safe} edges={['top']}>
      <View style={styles.header}>
        <Pressable testID="knowledge-detail-back" onPress={() => router.back()} style={styles.iconBtn}>
          <Ionicons name="arrow-back" size={24} color={theme.color.text} />
        </Pressable>
        <View style={{ flex: 1 }}>
          <Text style={styles.h1} numberOfLines={1}>{item.name}</Text>
          <Text style={styles.h2}>{item.type.replace('_', ' ').toUpperCase()} · v{item.version} · {item.status.toUpperCase()}</Text>
        </View>
        <Pressable testID="knowledge-edit-open"
          onPress={() => setEditingField({ name: item.name, description: item.description, status: item.status })}
          style={styles.iconBtn}>
          <Ionicons name="pencil" size={20} color={theme.color.info} />
        </Pressable>
      </View>

      <ScrollView contentContainerStyle={{ padding: theme.spacing.md, paddingBottom: 80 }}>
        {item.archived_at && (
          <View style={styles.archivedBanner}>
            <Ionicons name="archive" size={16} color={theme.color.warning} />
            <Text style={styles.archivedBannerText}>Archived on {new Date(item.archived_at).toLocaleDateString()}</Text>
          </View>
        )}

        <Section title="Details">
          <Row label="Description" value={item.description || '—'} />
          <Row label="Code" value={item.code || '—'} />
          {item.category_name && <Row label="Category" value={item.category_name} />}
          {item.phase_name && <Row label="Phase" value={item.phase_name} />}
          {item.default_duration_days != null && <Row label="Default Duration" value={`${item.default_duration_days} day(s)`} />}
          {item.document_kind && <Row label="Document Kind" value={item.document_kind} />}
          <Row label="Tags" value={item.tags.length ? item.tags.join(', ') : '—'} />
          <Row label="AI Keywords" value={item.ai_keywords.length ? item.ai_keywords.join(', ') : '—'} />
          <Row label="Created by" value={`${item.created_by_user_name} · ${new Date(item.created_at).toLocaleDateString()}`} />
          <Row label="Last updated by" value={`${item.updated_by_user_name} · ${new Date(item.updated_at).toLocaleDateString()}`} />
        </Section>

        {item.checklist_items.length > 0 && (
          <Section title="Checklist Items">
            {item.checklist_items.map((c) => (
              <View key={c.id} style={styles.checklistRow}>
                <Ionicons name="checkbox-outline" size={16} color={theme.color.brand} />
                <Text style={styles.checklistText}>{c.text}</Text>
              </View>
            ))}
          </Section>
        )}

        <Section title="Dependency Viewer"
          action={<Pressable testID="knowledge-add-relationship" onPress={() => setAddingRel(true)}>
            <Ionicons name="add-circle" size={22} color={theme.color.brand} />
          </Pressable>}>
          {item.relationships.length === 0 && (
            <Text style={styles.emptyBody}>No relationships yet. Tap + to link a dependency, document, material, etc.</Text>
          )}
          {item.relationships.map((r) => (
            <View key={r.id} style={styles.relRow}>
              <View style={{ flex: 1 }}>
                <Text style={styles.relType}>{r.type.replace('_', ' ').toUpperCase()}</Text>
                <Text style={styles.relTarget}>{r.target_name || r.target_id}</Text>
                {r.metadata?.note ? <Text style={styles.relNote}>{r.metadata.note}</Text> : null}
              </View>
              <Pressable testID={`knowledge-remove-relationship-${r.id}`}
                onPress={() => Alert.alert('Remove relationship?', `${r.type} → ${r.target_name || r.target_id}`,
                  [{ text: 'Cancel' }, { text: 'Remove', style: 'destructive', onPress: () => onRemoveRelationship(r.id) }])}
                style={styles.actionBtn}>
                <Ionicons name="trash-outline" size={16} color={theme.color.error} />
              </Pressable>
            </View>
          ))}
        </Section>

        <Section title={`Version History (${versions.length})`}
          action={<Pressable onPress={() => setShowVersions((v) => !v)}>
            <Ionicons name={showVersions ? 'chevron-up' : 'chevron-down'} size={20} color={theme.color.textDim} />
          </Pressable>}>
          {showVersions && (
            versions.length === 0 ? (
              <Text style={styles.emptyBody}>No edits yet — this is version 1.</Text>
            ) : versions.map((v) => (
              <View key={v.id} style={styles.versionRow}>
                <Text style={styles.versionBadge}>v{v.version}</Text>
                <View style={{ flex: 1 }}>
                  <Text style={styles.versionName}>{v.snapshot.name}</Text>
                  <Text style={styles.versionMeta}>
                    {v.changed_by_user_name} · {new Date(v.created_at).toLocaleString()}
                  </Text>
                </View>
              </View>
            ))
          )}
        </Section>
      </ScrollView>

      {/* Edit modal */}
      <Modal visible={!!editingField} animationType="slide" transparent onRequestClose={() => setEditingField(null)}>
        <View style={styles.modalBack}>
          <View style={styles.modal}>
            <View style={styles.modalHead}>
              <Text style={styles.modalTitle}>EDIT</Text>
              <Pressable onPress={() => setEditingField(null)}>
                <Ionicons name="close" size={26} color={theme.color.textDim} />
              </Pressable>
            </View>
            <Text style={styles.label}>Name</Text>
            <TextInput testID="knowledge-edit-name" value={editingField?.name} style={styles.input}
              onChangeText={(t) => setEditingField((f) => f && { ...f, name: t })} />
            <Text style={[styles.label, { marginTop: 10 }]}>Description</Text>
            <TextInput testID="knowledge-edit-description" value={editingField?.description} multiline
              style={[styles.input, { height: 80, textAlignVertical: 'top' }]}
              onChangeText={(t) => setEditingField((f) => f && { ...f, description: t })} />
            <Text style={[styles.label, { marginTop: 10 }]}>Status</Text>
            <View style={styles.statusRow}>
              {SETTABLE_KNOWLEDGE_STATUSES.map((s) => {
                const active = editingField?.status === s;
                return (
                  <Pressable key={s} testID={`knowledge-edit-status-${s}`}
                    onPress={() => setEditingField((f) => f && { ...f, status: s })}
                    style={[styles.statusChip, active && styles.statusChipActive]}>
                    <Text style={[styles.statusChipText, active && styles.statusChipTextActive]}>
                      {s.toUpperCase()}
                    </Text>
                  </Pressable>
                );
              })}
            </View>
            <Pressable testID="knowledge-edit-save" onPress={onSaveEdit} disabled={busy}
              style={[styles.saveBtn, busy && { opacity: 0.5 }]}>
              <Ionicons name="checkmark" size={22} color={theme.color.onBrand} />
              <Text style={styles.saveBtnText}>SAVE (v{item.version + 1})</Text>
            </Pressable>
          </View>
        </View>
      </Modal>

      {/* Add relationship modal */}
      <Modal visible={addingRel} animationType="slide" transparent onRequestClose={() => setAddingRel(false)}>
        <View style={styles.modalBack}>
          <View style={styles.modal}>
            <View style={styles.modalHead}>
              <Text style={styles.modalTitle}>ADD RELATIONSHIP</Text>
              <Pressable onPress={() => setAddingRel(false)}>
                <Ionicons name="close" size={26} color={theme.color.textDim} />
              </Pressable>
            </View>

            <Text style={styles.label}>Type</Text>
            <ScrollView horizontal showsHorizontalScrollIndicator={false} style={{ marginBottom: 10 }}>
              {(meta?.relationship_types || ['depends_on']).map((t) => (
                <Pressable key={t} testID={`knowledge-rel-type-${t}`} onPress={() => setRelType(t)}
                  style={[styles.relTypeChip, relType === t && styles.relTypeChipActive]}>
                  <Text style={[styles.relTypeChipText, relType === t && styles.relTypeChipTextActive]}>
                    {t.replace('_', ' ')}
                  </Text>
                </Pressable>
              ))}
            </ScrollView>

            <Text style={styles.label}>Target item</Text>
            <Pressable testID="knowledge-rel-target-picker" onPress={() => setRelTargetPicker(true)} style={styles.pickerField}>
              <Text style={relTarget ? styles.pickerFieldText : styles.pickerFieldPlaceholder}>
                {relTarget ? `${relTarget.name} (${relTarget.type})` : 'Select target item…'}
              </Text>
              <Ionicons name="chevron-forward" size={18} color={theme.color.textDim} />
            </Pressable>

            <Text style={[styles.label, { marginTop: 10 }]}>Note (optional)</Text>
            <TextInput testID="knowledge-rel-note" value={relNote} onChangeText={setRelNote} style={styles.input} />

            <Pressable testID="knowledge-rel-save" onPress={onAddRelationship} disabled={busy || !relTarget}
              style={[styles.saveBtn, (busy || !relTarget) && { opacity: 0.5 }]}>
              <Ionicons name="checkmark" size={22} color={theme.color.onBrand} />
              <Text style={styles.saveBtnText}>ADD RELATIONSHIP</Text>
            </Pressable>
          </View>
        </View>
      </Modal>

      <Modal visible={relTargetPicker} animationType="fade" transparent onRequestClose={() => setRelTargetPicker(false)}>
        <View style={styles.modalBack}>
          <View style={styles.modal}>
            <View style={styles.modalHead}>
              <Text style={styles.modalTitle}>SELECT TARGET</Text>
              <Pressable onPress={() => setRelTargetPicker(false)}>
                <Ionicons name="close" size={26} color={theme.color.textDim} />
              </Pressable>
            </View>
            <ScrollView style={{ maxHeight: 360 }}>
              {candidates.map((c) => (
                <Pressable key={c.id} testID={`knowledge-rel-target-${c.id}`}
                  onPress={() => { setRelTarget(c); setRelTargetPicker(false); }} style={styles.pickerOption}>
                  <Text style={styles.pickerOptionText}>{c.name}</Text>
                  <Text style={styles.pickerOptionSub}>{c.type.replace('_', ' ')}</Text>
                </Pressable>
              ))}
            </ScrollView>
          </View>
        </View>
      </Modal>
    </SafeAreaView>
  );
}

function Section({ title, children, action }: { title: string; children: any; action?: any }) {
  return (
    <View style={styles.section}>
      <View style={styles.sectionHead}>
        <Text style={styles.sectionTitle}>{title.toUpperCase()}</Text>
        {action}
      </View>
      {children}
    </View>
  );
}

function Row({ label, value }: { label: string; value: string }) {
  return (
    <View style={styles.infoRow}>
      <Text style={styles.infoLabel}>{label}</Text>
      <Text style={styles.infoValue}>{value}</Text>
    </View>
  );
}

const styles = StyleSheet.create({
  safe: { flex: 1, backgroundColor: theme.color.surface },
  header: { flexDirection: 'row', alignItems: 'center', padding: theme.spacing.md, gap: theme.spacing.sm },
  h1: { color: theme.color.text, fontSize: 18, fontWeight: '900' },
  h2: { color: theme.color.brand, fontSize: 11, fontWeight: '700', marginTop: 2 },
  iconBtn: { width: 44, height: 44, borderRadius: 22, backgroundColor: theme.color.surface2,
            alignItems: 'center', justifyContent: 'center' },
  center: { flex: 1, alignItems: 'center', justifyContent: 'center', gap: 8, padding: theme.spacing.lg },
  emptyTitle: { color: theme.color.text, fontSize: 18, fontWeight: '900', marginTop: 8 },
  emptyBody: { color: theme.color.textMuted, fontSize: 13 },
  archivedBanner: { flexDirection: 'row', alignItems: 'center', gap: 8, backgroundColor: theme.color.surface2,
                    borderWidth: 1, borderColor: theme.color.warning, borderRadius: theme.radius.sm,
                    padding: 10, marginBottom: theme.spacing.md },
  archivedBannerText: { color: theme.color.warning, fontSize: 12, fontWeight: '700' },
  section: { backgroundColor: theme.color.surface2, borderRadius: theme.radius.md, borderWidth: 1,
            borderColor: theme.color.border, padding: theme.spacing.md, marginBottom: theme.spacing.md },
  sectionHead: { flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between', marginBottom: 8 },
  sectionTitle: { color: theme.color.brand, fontSize: 12, fontWeight: '900', letterSpacing: 1 },
  infoRow: { paddingVertical: 6, borderBottomWidth: 1, borderBottomColor: theme.color.border },
  infoLabel: { color: theme.color.textDim, fontSize: 11, fontWeight: '700', letterSpacing: 0.5 },
  infoValue: { color: theme.color.text, fontSize: 14, marginTop: 2 },
  checklistRow: { flexDirection: 'row', alignItems: 'center', gap: 8, paddingVertical: 6 },
  checklistText: { color: theme.color.text, fontSize: 14 },
  relRow: { flexDirection: 'row', alignItems: 'center', gap: 10, paddingVertical: 8,
           borderBottomWidth: 1, borderBottomColor: theme.color.border },
  relType: { color: theme.color.brand, fontSize: 10, fontWeight: '900', letterSpacing: 1 },
  relTarget: { color: theme.color.text, fontSize: 14, fontWeight: '700', marginTop: 2 },
  relNote: { color: theme.color.textDim, fontSize: 12, marginTop: 2 },
  actionBtn: { width: 32, height: 32, borderRadius: 16, backgroundColor: theme.color.surface3,
              alignItems: 'center', justifyContent: 'center' },
  versionRow: { flexDirection: 'row', alignItems: 'center', gap: 10, paddingVertical: 8,
               borderBottomWidth: 1, borderBottomColor: theme.color.border },
  versionBadge: { color: theme.color.onBrand, backgroundColor: theme.color.brand, fontSize: 11, fontWeight: '900',
                 paddingHorizontal: 8, paddingVertical: 3, borderRadius: theme.radius.pill },
  versionName: { color: theme.color.text, fontSize: 13, fontWeight: '700' },
  versionMeta: { color: theme.color.textDim, fontSize: 11, marginTop: 2 },
  modalBack: { flex: 1, backgroundColor: 'rgba(0,0,0,0.6)', justifyContent: 'flex-end' },
  modal: { backgroundColor: theme.color.surface, borderTopLeftRadius: 18, borderTopRightRadius: 18,
          padding: theme.spacing.lg, gap: 6, maxHeight: '85%' },
  modalHead: { flexDirection: 'row', alignItems: 'center', marginBottom: theme.spacing.sm },
  modalTitle: { flex: 1, color: theme.color.brand, fontSize: 14, fontWeight: '900', letterSpacing: 2 },
  label: { color: theme.color.textDim, fontSize: 11, fontWeight: '800', letterSpacing: 1, marginBottom: 4 },
  input: { color: theme.color.text, backgroundColor: theme.color.surface2,
          borderRadius: theme.radius.sm, borderWidth: 1, borderColor: theme.color.border,
          paddingHorizontal: 12, paddingVertical: 10, fontSize: 15 },
  pickerField: { flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between',
                backgroundColor: theme.color.surface2, borderRadius: theme.radius.sm,
                borderWidth: 1, borderColor: theme.color.border, paddingHorizontal: 12, height: 44 },
  pickerFieldText: { color: theme.color.text, fontSize: 15 },
  pickerFieldPlaceholder: { color: theme.color.textDim, fontSize: 15 },
  pickerOption: { paddingVertical: 12, borderBottomWidth: 1, borderBottomColor: theme.color.border },
  pickerOptionText: { color: theme.color.text, fontSize: 15, fontWeight: '600' },
  pickerOptionSub: { color: theme.color.textDim, fontSize: 11, marginTop: 2 },
  relTypeChip: { paddingHorizontal: 12, paddingVertical: 8, borderRadius: theme.radius.pill,
                backgroundColor: theme.color.surface2, borderWidth: 1, borderColor: theme.color.border, marginRight: 8 },
  relTypeChipActive: { backgroundColor: theme.color.brand, borderColor: theme.color.brand },
  relTypeChipText: { color: theme.color.brand, fontSize: 12, fontWeight: '800' },
  relTypeChipTextActive: { color: theme.color.onBrand },
  statusRow: { flexDirection: 'row', gap: 8, marginBottom: theme.spacing.sm },
  statusChip: { flex: 1, paddingVertical: 10, borderRadius: theme.radius.sm, alignItems: 'center',
               backgroundColor: theme.color.surface2, borderWidth: 1, borderColor: theme.color.border },
  statusChipActive: { backgroundColor: theme.color.brand, borderColor: theme.color.brand },
  statusChipText: { color: theme.color.brand, fontSize: 11, fontWeight: '900', letterSpacing: 0.5 },
  statusChipTextActive: { color: theme.color.onBrand },
  saveBtn: { marginTop: theme.spacing.md, flexDirection: 'row', alignItems: 'center', justifyContent: 'center',
            gap: 8, height: 52, borderRadius: theme.radius.md, backgroundColor: theme.color.brand },
  saveBtnText: { color: theme.color.onBrand, fontSize: 16, fontWeight: '900', letterSpacing: 1 },
});
