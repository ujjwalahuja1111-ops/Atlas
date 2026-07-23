import { useCallback, useEffect, useState } from 'react';
import {
  View, Text, StyleSheet, ScrollView, Pressable, ActivityIndicator,
  TextInput, Modal, Alert, KeyboardAvoidingView, Platform,
} from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import { Ionicons } from '@expo/vector-icons';
import { useRouter } from 'expo-router';
import { theme } from '@/src/theme';
import { getViewRole, type ViewRole } from '@/src/roles';
import {
  apiListKnowledgeItems, apiCreateKnowledgeItem, apiArchiveKnowledgeItem, apiUnarchiveKnowledgeItem,
  type KnowledgeItem, type KnowledgeType, type KnowledgeItemInput, type KnowledgeStatus,
  SETTABLE_KNOWLEDGE_STATUSES,
} from '@/src/knowledge_api';

const TYPE_TABS: { key: KnowledgeType; label: string; icon: any }[] = [
  { key: 'category', label: 'CATEGORIES', icon: 'pricetags' },
  { key: 'phase', label: 'PHASES', icon: 'layers' },
  { key: 'activity', label: 'ACTIVITIES', icon: 'hammer' },
  { key: 'checklist_template', label: 'CHECKLISTS', icon: 'checkbox' },
  { key: 'required_document', label: 'DOCUMENTS', icon: 'document-text' },
  { key: 'workflow_template', label: 'WORKFLOW TEMPLATES', icon: 'git-network' },
];

// draft/active/deprecated only — 'archived' is a distinct action (archive
// button), not a status choice, so it's kept out of this creation/edit chip
// list on purpose (mirrors the backend's SETTABLE_STATUSES).
const STATUS_OPTIONS = SETTABLE_KNOWLEDGE_STATUSES;

function statusColor(status: KnowledgeStatus): string {
  switch (status) {
    case 'active': return theme.color.success;
    case 'deprecated': return theme.color.warning;
    case 'archived': return theme.color.textDim;
    default: return theme.color.info; // draft
  }
}

function csv(v: string): string[] {
  return v.split(',').map((s) => s.trim()).filter(Boolean);
}

export default function KnowledgeWorkspace() {
  const router = useRouter();
  const [viewRole, setViewRole] = useState<ViewRole | null>(null);
  const [type, setType] = useState<KnowledgeType>('activity');
  const [items, setItems] = useState<KnowledgeItem[]>([]);
  const [categories, setCategories] = useState<KnowledgeItem[]>([]);
  const [phases, setPhases] = useState<KnowledgeItem[]>([]);
  const [query, setQuery] = useState('');
  // Sprint 4.1 fix (audit L2): debounce search input so typing doesn't
  // trigger a network request on every keystroke.
  const [debouncedQuery, setDebouncedQuery] = useState('');
  const [showArchived, setShowArchived] = useState(false);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [editing, setEditing] = useState<Partial<KnowledgeItemInput> | null>(null);
  const [busy, setBusy] = useState(false);
  const [pickerFor, setPickerFor] = useState<'category_id' | 'phase_id' | null>(null);

  useEffect(() => { getViewRole().then(setViewRole); }, []);

  useEffect(() => {
    const t = setTimeout(() => setDebouncedQuery(query), 300);
    return () => clearTimeout(t);
  }, [query]);

  const load = useCallback(async () => {
    setLoading(true);
    setLoadError(null);
    try {
      const list = await apiListKnowledgeItems({ type, q: debouncedQuery || undefined, include_archived: showArchived });
      setItems(list);
    } catch (e: any) {
      // Sprint 4.1 fix (audit H4): surface load failures instead of
      // silently swallowing them.
      console.warn(e);
      setLoadError(e?.message || 'Could not load Construction Knowledge. Tap to retry.');
    }
    finally { setLoading(false); }
  }, [type, debouncedQuery, showArchived]);

  // Sprint 4.1 fix: categories/phases (used only for the activity picker
  // fields) no longer refetch on every keystroke — they only change when a
  // category/phase itself is created elsewhere, so loading them once per
  // admin session is enough. Previously load() refetched all three lists
  // together on every debounced-search-worthy change, including ones that
  // only affected the activity/checklist/document list, not the pickers.
  const loadPickerLists = useCallback(async () => {
    try {
      const [cats, phs] = await Promise.all([
        apiListKnowledgeItems({ type: 'category' }),
        apiListKnowledgeItems({ type: 'phase' }),
      ]);
      setCategories(cats);
      setPhases(phs);
    } catch (e) { console.warn(e); }
  }, []);

  useEffect(() => { if (viewRole === 'admin') { load(); loadPickerLists(); } }, [viewRole, load, loadPickerLists]);


  const onSave = async () => {
    if (!editing || !editing.name?.trim()) return;
    setBusy(true);
    try {
      await apiCreateKnowledgeItem({
        type: editing.type || type,
        name: editing.name!,
        description: editing.description || '',
        code: editing.code || '',
        category_id: editing.category_id || null,
        phase_id: editing.phase_id || null,
        tags: editing.tags || [],
        ai_keywords: editing.ai_keywords || [],
        default_duration_days: editing.default_duration_days ?? null,
        checklist_items: editing.checklist_items || [],
        document_kind: editing.document_kind || null,
        status: editing.status || 'draft',
        trade: editing.trade || null,
        unit: editing.unit || null,
        requires_inspection: !!editing.requires_inspection,
      });
      setEditing(null);
      await load(); await loadPickerLists();
    } catch (e: any) {
      Alert.alert('Save failed', String(e?.message || e));
    } finally { setBusy(false); }
  };

  const onArchive = async (item: KnowledgeItem) => {
    setBusy(true);
    try { await apiArchiveKnowledgeItem(item.id); await load(); await loadPickerLists(); }
    catch (e: any) { Alert.alert('Archive failed', String(e?.message || e)); }
    finally { setBusy(false); }
  };

  const onUnarchive = async (item: KnowledgeItem) => {
    setBusy(true);
    try { await apiUnarchiveKnowledgeItem(item.id); await load(); await loadPickerLists(); }
    catch (e: any) { Alert.alert('Unarchive failed', String(e?.message || e)); }
    finally { setBusy(false); }
  };

  if (viewRole === null) {
    return (
      <SafeAreaView style={styles.safe}><View style={styles.center}>
        <ActivityIndicator color={theme.color.brand} />
      </View></SafeAreaView>
    );
  }

  if (viewRole !== 'admin') {
    return (
      <SafeAreaView style={styles.safe} edges={['top']}>
        <View style={styles.header}>
          <Pressable onPress={() => router.back()} style={styles.iconBtn}>
            <Ionicons name="arrow-back" size={24} color={theme.color.text} />
          </Pressable>
        </View>
        <View style={styles.center}>
          <Ionicons name="lock-closed-outline" size={48} color={theme.color.textDim} />
          <Text style={styles.emptyTitle}>Admin access required</Text>
          <Text style={styles.emptyBody}>Construction Knowledge is an Admin-only workspace.</Text>
        </View>
      </SafeAreaView>
    );
  }

  const showCategoryPhase = (editing?.type || type) === 'activity';
  const showDuration = (editing?.type || type) === 'activity';
  const showChecklist = (editing?.type || type) === 'checklist_template';
  const showDocKind = (editing?.type || type) === 'required_document';

  return (
    <SafeAreaView style={styles.safe} edges={['top']}>
      <View style={styles.header}>
        <Pressable testID="knowledge-back" onPress={() => router.back()} style={styles.iconBtn}>
          <Ionicons name="arrow-back" size={24} color={theme.color.text} />
        </Pressable>
        <View style={{ flex: 1 }}>
          <Text style={styles.h1}>CONSTRUCTION KNOWLEDGE</Text>
          <Text style={styles.h2}>Admin workspace · reusable master definitions</Text>
        </View>
        <Pressable testID="knowledge-new" onPress={() => setEditing({ type })} style={[styles.iconBtn, styles.primary]}>
          <Ionicons name="add" size={26} color={theme.color.onBrand} />
        </Pressable>
      </View>

      <ScrollView horizontal showsHorizontalScrollIndicator={false} style={styles.tabsRow}
        contentContainerStyle={{ gap: 8, paddingHorizontal: theme.spacing.md }}>
        {TYPE_TABS.map((t) => (
          <Pressable key={t.key} testID={`knowledge-tab-${t.key}`} onPress={() => setType(t.key)}
            style={[styles.tab, type === t.key && styles.tabActive]}>
            <Ionicons name={t.icon} size={14} color={type === t.key ? theme.color.onBrand : theme.color.brand} />
            <Text style={[styles.tabText, type === t.key && styles.tabTextActive]}>{t.label}</Text>
          </Pressable>
        ))}
      </ScrollView>

      <View style={styles.toolbar}>
        <View style={styles.searchBox}>
          <Ionicons name="search" size={16} color={theme.color.textDim} />
          <TextInput
            testID="knowledge-search"
            value={query} onChangeText={setQuery}
            placeholder="Search name, tags, keywords…"
            placeholderTextColor={theme.color.textDim}
            style={styles.searchInput}
            onSubmitEditing={load}
          />
        </View>
        <Pressable testID="knowledge-toggle-archived" onPress={() => setShowArchived((v) => !v)} style={styles.toggle}>
          <Ionicons name={showArchived ? 'archive' : 'archive-outline'} size={16} color={theme.color.brand} />
        </Pressable>
      </View>

      {loadError && (
        <Pressable testID="knowledge-load-error" onPress={load} style={styles.errorBanner}>
          <Ionicons name="warning" size={16} color={theme.color.error} />
          <Text style={styles.errorBannerText} numberOfLines={2}>{loadError} Tap to retry.</Text>
        </Pressable>
      )}

      {loading ? (
        <View style={styles.center}><ActivityIndicator size="large" color={theme.color.brand} /></View>
      ) : (
        <ScrollView contentContainerStyle={{ padding: theme.spacing.md, paddingBottom: 80 }}>
          {items.length === 0 && (
            <View style={styles.empty}>
              <Ionicons name="library-outline" size={56} color={theme.color.brand} />
              <Text style={styles.emptyTitle}>Nothing here yet</Text>
              <Text style={styles.emptyBody}>Tap + to create the first entry.</Text>
            </View>
          )}
          {items.map((item) => {
            const archived = !!item.archived_at;
            return (
              <Pressable key={item.id} testID={`knowledge-row-${item.id}`}
                onPress={() => router.push(`/knowledge/${item.id}`)}
                style={[styles.row, archived && styles.rowArchived]}>
                <View style={{ flex: 1 }}>
                  <Text style={[styles.title, archived && { color: theme.color.textDim }]} numberOfLines={1}>
                    {item.name}
                  </Text>
                  <Text style={styles.meta} numberOfLines={1}>
                    {item.code ? `${item.code} · ` : ''}v{item.version}
                    {item.category_name ? ` · ${item.category_name}` : ''}
                    {item.phase_name ? ` · ${item.phase_name}` : ''}
                    {item.trade ? ` · ${item.trade}` : ''}
                    {item.tags?.length ? ` · ${item.tags.join(', ')}` : ''}
                  </Text>
                  <View style={{ flexDirection: 'row', gap: 6, marginTop: 4 }}>
                    {!archived && (
                      <View style={[styles.badgeStatus, { borderColor: statusColor(item.status) }]}>
                        <Text style={[styles.badgeStatusText, { color: statusColor(item.status) }]}>
                          {item.status.toUpperCase()}
                        </Text>
                      </View>
                    )}
                    {archived ? (
                      <View style={styles.badgeArchived}><Text style={styles.badgeArchivedText}>ARCHIVED</Text></View>
                    ) : null}
                  </View>
                </View>
                <View style={styles.actions}>
                  {archived ? (
                    <Pressable testID={`knowledge-unarchive-${item.id}`} onPress={() => onUnarchive(item)} style={styles.actionBtn}>
                      <Ionicons name="refresh" size={18} color={theme.color.success} />
                    </Pressable>
                  ) : (
                    <Pressable testID={`knowledge-archive-${item.id}`}
                      onPress={() => Alert.alert('Archive?', `Hide "${item.name}" from active list.`,
                        [{ text: 'Cancel' }, { text: 'Archive', style: 'destructive', onPress: () => onArchive(item) }])}
                      style={styles.actionBtn}>
                      <Ionicons name="archive" size={18} color={theme.color.warning} />
                    </Pressable>
                  )}
                </View>
              </Pressable>
            );
          })}
        </ScrollView>
      )}

      <Modal visible={!!editing} animationType="slide" transparent onRequestClose={() => setEditing(null)}>
        <KeyboardAvoidingView style={{ flex: 1 }} behavior={Platform.OS === 'ios' ? 'padding' : undefined}>
        <View style={styles.modalBack}>
          <ScrollView style={styles.modal} contentContainerStyle={{ paddingBottom: theme.spacing.lg }}>
            <View style={styles.modalHead}>
              <Text style={styles.modalTitle}>NEW {(editing?.type || type).replace('_', ' ').toUpperCase()}</Text>
              <Pressable testID="knowledge-modal-close" onPress={() => setEditing(null)}>
                <Ionicons name="close" size={26} color={theme.color.textDim} />
              </Pressable>
            </View>

            <Field label="Name" value={editing?.name || ''} testID="knowledge-input-name"
              onChangeText={(t: string) => setEditing({ ...(editing || {}), name: t })} />
            <Field label="Description" value={editing?.description || ''} testID="knowledge-input-description"
              onChangeText={(t: string) => setEditing({ ...(editing || {}), description: t })} multiline />
            <Field label="Code (optional)" value={editing?.code || ''} testID="knowledge-input-code"
              onChangeText={(t: string) => setEditing({ ...(editing || {}), code: t })} />

            <Text style={styles.label}>Status</Text>
            <View style={styles.statusRow}>
              {STATUS_OPTIONS.map((s) => {
                const active = (editing?.status || 'draft') === s;
                return (
                  <Pressable key={s} testID={`knowledge-status-${s}`}
                    onPress={() => setEditing({ ...(editing || {}), status: s })}
                    style={[styles.statusChip, active && styles.statusChipActive]}>
                    <Text style={[styles.statusChipText, active && styles.statusChipTextActive]}>
                      {s.toUpperCase()}
                    </Text>
                  </Pressable>
                );
              })}
            </View>

            {showCategoryPhase && (
              <>
                <PickerRow label="Category" value={categories.find((c) => c.id === editing?.category_id)?.name}
                  onPress={() => setPickerFor('category_id')} testID="knowledge-pick-category" />
                <PickerRow label="Phase" value={phases.find((p) => p.id === editing?.phase_id)?.name}
                  onPress={() => setPickerFor('phase_id')} testID="knowledge-pick-phase" />
              </>
            )}

            <Field label="Tags (comma separated)" value={(editing?.tags || []).join(', ')} testID="knowledge-input-tags"
              onChangeText={(t: string) => setEditing({ ...(editing || {}), tags: csv(t) })} />
            <Field label="AI Keywords (comma separated)" value={(editing?.ai_keywords || []).join(', ')} testID="knowledge-input-keywords"
              onChangeText={(t: string) => setEditing({ ...(editing || {}), ai_keywords: csv(t) })} />

            {showDuration && (
              <>
                <Field label="Default Duration (days)" value={editing?.default_duration_days?.toString() || ''}
                  testID="knowledge-input-duration" keyboardType="numeric"
                  onChangeText={(t: string) => setEditing({ ...(editing || {}), default_duration_days: t ? Number(t) : null })} />
                <Field label="Trade (e.g. Civil, Electrical, Plumbing)" value={editing?.trade || ''}
                  testID="knowledge-input-trade"
                  onChangeText={(t: string) => setEditing({ ...(editing || {}), trade: t })} />
                <Field label="Unit (e.g. sqm, cum, each, lumpsum)" value={editing?.unit || ''}
                  testID="knowledge-input-unit"
                  onChangeText={(t: string) => setEditing({ ...(editing || {}), unit: t })} />
                <Pressable testID="knowledge-input-requires-inspection"
                  onPress={() => setEditing({ ...(editing || {}), requires_inspection: !editing?.requires_inspection })}
                  style={styles.checkboxRow}>
                  <Ionicons name={editing?.requires_inspection ? 'checkbox' : 'square-outline'} size={22}
                    color={editing?.requires_inspection ? theme.color.brand : theme.color.textDim} />
                  <Text style={styles.checkboxLabel}>Inspection Required</Text>
                </Pressable>
              </>
            )}

            {showChecklist && (
              <Field label="Checklist items (one per line)" multiline
                value={(editing?.checklist_items || []).map((c) => c.text).join('\n')}
                testID="knowledge-input-checklist"
                onChangeText={(t: string) => setEditing({
                  ...(editing || {}),
                  checklist_items: t.split('\n').map((s: string) => s.trim()).filter(Boolean)
                    .map((text: string, i: number) => ({ id: String(i + 1), text })),
                })} />
            )}

            {showDocKind && (
              <Field label="Document kind (e.g. drawing, certificate)" value={editing?.document_kind || ''}
                testID="knowledge-input-dockind"
                onChangeText={(t: string) => setEditing({ ...(editing || {}), document_kind: t })} />
            )}

            <Pressable testID="knowledge-save" onPress={onSave} disabled={busy || !editing?.name?.trim()}
              style={[styles.saveBtn, (busy || !editing?.name?.trim()) && { opacity: 0.5 }]}>
              <Ionicons name="checkmark" size={22} color={theme.color.onBrand} />
              <Text style={styles.saveBtnText}>CREATE</Text>
            </Pressable>
          </ScrollView>
        </View>
        </KeyboardAvoidingView>
      </Modal>

      <Modal visible={!!pickerFor} animationType="fade" transparent onRequestClose={() => setPickerFor(null)}>
        <View style={styles.modalBack}>
          <View style={styles.modal}>
            <View style={styles.modalHead}>
              <Text style={styles.modalTitle}>SELECT {pickerFor === 'category_id' ? 'CATEGORY' : 'PHASE'}</Text>
              <Pressable onPress={() => setPickerFor(null)}>
                <Ionicons name="close" size={26} color={theme.color.textDim} />
              </Pressable>
            </View>
            <ScrollView style={{ maxHeight: 320 }}>
              {(pickerFor === 'category_id' ? categories : phases).map((opt) => (
                <Pressable key={opt.id} testID={`knowledge-pick-option-${opt.id}`}
                  onPress={() => { setEditing({ ...(editing || {}), [pickerFor as string]: opt.id }); setPickerFor(null); }}
                  style={styles.pickerOption}>
                  <Text style={styles.pickerOptionText}>{opt.name}</Text>
                </Pressable>
              ))}
              {(pickerFor === 'category_id' ? categories : phases).length === 0 && (
                <Text style={styles.emptyBody}>
                  None yet — create a {pickerFor === 'category_id' ? 'Category' : 'Phase'} first.
                </Text>
              )}
            </ScrollView>
          </View>
        </View>
      </Modal>
    </SafeAreaView>
  );
}

function Field({ label, value, onChangeText, testID, multiline, keyboardType }: any) {
  return (
    <View style={{ marginBottom: theme.spacing.sm }}>
      <Text style={styles.label}>{label}</Text>
      <TextInput
        testID={testID}
        value={value} onChangeText={onChangeText}
        placeholderTextColor={theme.color.textDim}
        style={[styles.input, multiline && { height: 80, textAlignVertical: 'top' }]}
        multiline={multiline}
        keyboardType={keyboardType}
      />
    </View>
  );
}

function PickerRow({ label, value, onPress, testID }: { label: string; value?: string; onPress: () => void; testID: string }) {
  return (
    <View style={{ marginBottom: theme.spacing.sm }}>
      <Text style={styles.label}>{label}</Text>
      <Pressable testID={testID} onPress={onPress} style={styles.pickerField}>
        <Text style={value ? styles.pickerFieldText : styles.pickerFieldPlaceholder}>
          {value || `Select ${label.toLowerCase()}…`}
        </Text>
        <Ionicons name="chevron-forward" size={18} color={theme.color.textDim} />
      </Pressable>
    </View>
  );
}

const styles = StyleSheet.create({
  safe: { flex: 1, backgroundColor: theme.color.surface },
  header: { flexDirection: 'row', alignItems: 'center', padding: theme.spacing.md, gap: theme.spacing.sm },
  h1: { color: theme.color.text, fontSize: 20, fontWeight: '900', letterSpacing: 1 },
  h2: { color: theme.color.brand, fontSize: 11, fontWeight: '700', marginTop: 2 },
  iconBtn: { width: 44, height: 44, borderRadius: 22, backgroundColor: theme.color.surface2,
            alignItems: 'center', justifyContent: 'center' },
  primary: { backgroundColor: theme.color.brand },
  tabsRow: { flexGrow: 0, marginBottom: theme.spacing.sm },
  tab: { flexDirection: 'row', alignItems: 'center', gap: 6, paddingHorizontal: 12, paddingVertical: 8,
        borderRadius: theme.radius.pill, backgroundColor: theme.color.surface2,
        borderWidth: 1, borderColor: theme.color.border },
  tabActive: { backgroundColor: theme.color.brand, borderColor: theme.color.brand },
  tabText: { color: theme.color.brand, fontSize: 11, fontWeight: '900', letterSpacing: 0.5 },
  tabTextActive: { color: theme.color.onBrand },
  toolbar: { flexDirection: 'row', paddingHorizontal: theme.spacing.md, paddingBottom: theme.spacing.sm, gap: 8 },
  searchBox: { flex: 1, flexDirection: 'row', alignItems: 'center', gap: 8, paddingHorizontal: 12,
              height: 40, borderRadius: theme.radius.md, backgroundColor: theme.color.surface2,
              borderWidth: 1, borderColor: theme.color.border },
  searchInput: { flex: 1, color: theme.color.text, fontSize: 14 },
  toggle: { width: 40, height: 40, borderRadius: theme.radius.md, alignItems: 'center', justifyContent: 'center',
           backgroundColor: theme.color.surface2, borderWidth: 1, borderColor: theme.color.border },
  center: { flex: 1, alignItems: 'center', justifyContent: 'center', gap: 8, padding: theme.spacing.lg },
  errorBanner: {
    flexDirection: 'row', alignItems: 'center', gap: 8, marginHorizontal: theme.spacing.md,
    marginBottom: theme.spacing.sm, padding: 10, borderRadius: theme.radius.sm,
    backgroundColor: theme.color.surface2, borderWidth: 1, borderColor: theme.color.error,
  },
  errorBannerText: { flex: 1, color: theme.color.error, fontSize: 12, fontWeight: '700' },
  empty: { alignItems: 'center', padding: theme.spacing.xl, gap: theme.spacing.sm },
  emptyTitle: { color: theme.color.text, fontSize: 18, fontWeight: '900', letterSpacing: 1, marginTop: 8 },
  emptyBody: { color: theme.color.textMuted, textAlign: 'center' },
  row: { flexDirection: 'row', alignItems: 'center', gap: 12, padding: theme.spacing.md,
        backgroundColor: theme.color.surface2, borderRadius: theme.radius.md,
        borderWidth: 1, borderColor: theme.color.border, marginBottom: theme.spacing.sm },
  rowArchived: { opacity: 0.7 },
  title: { color: theme.color.text, fontSize: 16, fontWeight: '800' },
  meta: { color: theme.color.textDim, fontSize: 12, marginTop: 2 },
  badgeArchived: { alignSelf: 'flex-start', paddingHorizontal: 6, paddingVertical: 2, borderRadius: 4,
                  backgroundColor: theme.color.surface3, marginTop: 4 },
  badgeArchivedText: { color: theme.color.warning, fontSize: 10, fontWeight: '900', letterSpacing: 1 },
  badgeStatus: { alignSelf: 'flex-start', paddingHorizontal: 6, paddingVertical: 2, borderRadius: 4,
                borderWidth: 1, backgroundColor: theme.color.surface3 },
  badgeStatusText: { fontSize: 10, fontWeight: '900', letterSpacing: 1 },
  statusRow: { flexDirection: 'row', gap: 8, marginBottom: theme.spacing.sm },
  statusChip: { flex: 1, paddingVertical: 10, borderRadius: theme.radius.sm, alignItems: 'center',
               backgroundColor: theme.color.surface2, borderWidth: 1, borderColor: theme.color.border },
  statusChipActive: { backgroundColor: theme.color.brand, borderColor: theme.color.brand },
  statusChipText: { color: theme.color.brand, fontSize: 11, fontWeight: '900', letterSpacing: 0.5 },
  statusChipTextActive: { color: theme.color.onBrand },
  actions: { flexDirection: 'row', gap: 6 },
  actionBtn: { width: 36, height: 36, borderRadius: 18, backgroundColor: theme.color.surface3,
              alignItems: 'center', justifyContent: 'center' },
  modalBack: { flex: 1, backgroundColor: 'rgba(0,0,0,0.6)', justifyContent: 'flex-end' },
  modal: { backgroundColor: theme.color.surface, borderTopLeftRadius: 18, borderTopRightRadius: 18,
          padding: theme.spacing.lg, gap: 6, maxHeight: '85%' },
  modalHead: { flexDirection: 'row', alignItems: 'center', marginBottom: theme.spacing.sm },
  modalTitle: { flex: 1, color: theme.color.brand, fontSize: 14, fontWeight: '900', letterSpacing: 2 },
  label: { color: theme.color.textDim, fontSize: 11, fontWeight: '800', letterSpacing: 1, marginBottom: 4 },
  input: { color: theme.color.text, backgroundColor: theme.color.surface2,
          borderRadius: theme.radius.sm, borderWidth: 1, borderColor: theme.color.border,
          paddingHorizontal: 12, paddingVertical: 10, fontSize: 15 },
  checkboxRow: { flexDirection: 'row', alignItems: 'center', gap: 10,
                paddingVertical: 10, marginBottom: theme.spacing.sm },
  checkboxLabel: { color: theme.color.text, fontSize: 14, fontWeight: '700' },
  pickerField: { flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between',
                backgroundColor: theme.color.surface2, borderRadius: theme.radius.sm,
                borderWidth: 1, borderColor: theme.color.border, paddingHorizontal: 12, height: 44 },
  pickerFieldText: { color: theme.color.text, fontSize: 15 },
  pickerFieldPlaceholder: { color: theme.color.textDim, fontSize: 15 },
  pickerOption: { paddingVertical: 14, borderBottomWidth: 1, borderBottomColor: theme.color.border },
  pickerOptionText: { color: theme.color.text, fontSize: 15, fontWeight: '600' },
  saveBtn: { marginTop: theme.spacing.md, flexDirection: 'row', alignItems: 'center', justifyContent: 'center',
            gap: 8, height: 52, borderRadius: theme.radius.md, backgroundColor: theme.color.brand },
  saveBtnText: { color: theme.color.onBrand, fontSize: 16, fontWeight: '900', letterSpacing: 1 },
});
