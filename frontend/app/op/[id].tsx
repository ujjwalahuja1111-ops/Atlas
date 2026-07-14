import { useEffect, useRef, useState } from 'react';
import {
  View, Text, StyleSheet, ScrollView, Pressable, ActivityIndicator,
  TextInput, Platform, KeyboardAvoidingView, Modal, Alert,
} from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import { Image as ExpoImage } from 'expo-image';
import { Ionicons } from '@expo/vector-icons';
import { useLocalSearchParams, useRouter } from 'expo-router';
import { theme } from '@/src/theme';
import { getViewRole, ROLE_LABEL, type ViewRole } from '@/src/roles';
import { useVoiceRecorder } from '@/src/useVoiceRecorder';
import type { Role } from '@/src/api';
import {
  apiGetItem, apiTransitionItem, apiCommentItem, apiSetBlocker, apiClearBlocker,
  apiListUsers, apiAssignItem, apiEditItem, apiVoiceUpdate, apiTextUpdate, apiMarkDuplicate, apiListItems,
  type OperationalItem, type OperationalEvent, type AssignableUser,
} from '@/src/ops_api';
import { humanBlocker } from '../(tabs)/ops';

const HEALTH_COLOR: Record<string, string> = {
  on_track: theme.color.success, due_soon: theme.color.warning,
  overdue: theme.color.error, blocked: '#9C27B0',
  waiting_external: theme.color.info, completed: theme.color.textDim,
};
const PRIORITY_COLOR: Record<string, string> = {
  low: theme.color.textDim, normal: theme.color.info,
  high: theme.color.warning, critical: theme.color.error,
};

// What's the next sensible transition? Big primary button.
// Category-aware labels make this feel like a coordinator's playbook.
type PrimaryAction = { to: string; label: string; icon: any } | null;
function primaryFor(item: OperationalItem): PrimaryAction {
  // Unassigned items: prompt to assign first.
  if (item.status === 'open' && !item.assigned_to_user_id) {
    return { to: '__assign__', label: 'ASSIGN OWNER', icon: 'person-add' };
  }
  const cat = item.category;
  const s = item.status;
  if (s === 'open') return { to: 'in_progress', label: 'START WORK', icon: 'play' };
  if (s === 'assigned') return { to: 'acknowledged', label: 'ACCEPT ASSIGNMENT', icon: 'checkmark' };
  if (s === 'acknowledged') return { to: 'in_progress', label: 'START WORK', icon: 'play' };
  if (s === 'in_progress') {
    if (cat === 'material_requirement') return { to: 'fulfilled', label: 'MARK DELIVERED', icon: 'cube' };
    if (cat === 'labour_requirement') return { to: 'fulfilled', label: 'MARK LABOUR ARRIVED', icon: 'people' };
    if (cat === 'equipment_requirement') return { to: 'fulfilled', label: 'MARK ARRIVED', icon: 'construct' };
    if (cat === 'drawing_request') return { to: 'fulfilled', label: 'MARK RECEIVED', icon: 'document' };
    if (cat === 'client_approval') return { to: 'fulfilled', label: 'MARK APPROVED', icon: 'shield-checkmark' };
    if (cat === 'inspection') return { to: 'fulfilled', label: 'INSPECTION DONE', icon: 'eye' };
    return { to: 'fulfilled', label: 'MARK FULFILLED', icon: 'checkmark-done' };
  }
  if (s === 'fulfilled') return { to: 'verified', label: 'VERIFY', icon: 'shield-checkmark' };
  if (s === 'verified') return { to: 'closed', label: 'CLOSE', icon: 'lock-closed' };
  if (s === 'reopened') return { to: 'in_progress', label: 'RESUME', icon: 'play' };
  return null;
}

const BLOCKERS = [
  'awaiting_client_approval', 'vendor_payment_pending', 'material_not_delivered',
  'drawing_revision_pending', 'labour_unavailable', 'weather_delay',
];

export default function OpDetail() {
  const { id } = useLocalSearchParams<{ id: string }>();
  const router = useRouter();
  const [item, setItem] = useState<OperationalItem | null>(null);
  const [history, setHistory] = useState<OperationalEvent[]>([]);
  const [evidence, setEvidence] = useState<any | null>(null);
  const [busy, setBusy] = useState(false);
  const [commentText, setCommentText] = useState('');
  const [showBlockerPicker, setShowBlockerPicker] = useState(false);
  const [showAssignPicker, setShowAssignPicker] = useState(false);
  const [users, setUsers] = useState<AssignableUser[]>([]);
  // V3.3 additions
  const [editing, setEditing] = useState<any | null>(null);
  const [showDupPicker, setShowDupPicker] = useState(false);
  const [dupCandidates, setDupCandidates] = useState<OperationalItem[]>([]);
  // FAC-OPS-06 — shared with app/(tabs)/capture.tsx, instead of a second,
  // separate recording flow.
  const { recording, elapsed, start: startRecordRaw, stop: stopRecordRaw, cancel: cancelRecordRaw } = useVoiceRecorder();
  const [uploadingVoice, setUploadingVoice] = useState(false);
  const [showTextUpdate, setShowTextUpdate] = useState(false);
  const [textUpdateNote, setTextUpdateNote] = useState('');
  // Sprint 6.2 Client Permissions
  const [viewRole, setViewRole] = useState<ViewRole | null>(null);
  const [clientNote, setClientNote] = useState('');

  const load = async () => {
    if (!id) return;
    try {
      const r = await apiGetItem(id);
      setItem(r.item); setHistory(r.history); setEvidence(r.evidence);
    } catch (e) { console.warn(e); }
  };
  useEffect(() => { load(); }, [id]);
  useEffect(() => { getViewRole().then(setViewRole); }, []);

  if (!item) {
    return (
      <SafeAreaView style={styles.safe}><View style={styles.center}>
        <ActivityIndicator size="large" color={theme.color.brand} />
      </View></SafeAreaView>
    );
  }

  const onTransition = async (to: string) => {
    if (to === '__assign__') { await openAssign(); return; }
    setBusy(true);
    try { await apiTransitionItem(item.id, to); await load(); }
    catch (e: any) { console.warn(e); }
    finally { setBusy(false); }
  };
  // Sprint 6.2 Client Permissions — approve/reject a client_approval item,
  // with an optional comment that becomes part of the item's (and so the
  // project's) history via the existing transition `note` field.
  const onClientDecision = async (to: 'fulfilled' | 'cancelled') => {
    setBusy(true);
    try {
      await apiTransitionItem(item.id, to, clientNote.trim() || undefined);
      setClientNote('');
      await load();
    } catch (e: any) {
      Alert.alert('Could not submit your decision', String(e?.message || e));
    } finally { setBusy(false); }
  };
  const openAssign = async () => {
    // FAC-OPS-06 fix — see the identical fix + full rationale in
    // (tabs)/ops.tsx's loadUsers(): the previous `if (users.length ===
    // 0)` guard cached the assignee list for this screen's entire
    // lifetime, showing a stale role for anyone whose role changed
    // after the picker was first opened. Also scopes to eligible
    // (same-project) users only.
    try { setUsers(await apiListUsers(undefined, item.project_id)); } catch {}
    setShowAssignPicker(true);
  };
  const onAssign = async (u: AssignableUser) => {
    setShowAssignPicker(false);
    setBusy(true);
    try { await apiAssignItem(item.id, u.id); await load(); }
    catch (e) { console.warn(e); }
    finally { setBusy(false); }
  };
  const onComment = async () => {
    if (!commentText.trim()) return;
    setBusy(true);
    try { await apiCommentItem(item.id, commentText.trim()); setCommentText(''); await load(); }
    catch (e) { console.warn(e); }
    finally { setBusy(false); }
  };
  const onBlocker = async (cat: string) => {
    setShowBlockerPicker(false);
    setBusy(true);
    try { await apiSetBlocker(item.id, cat); await load(); }
    finally { setBusy(false); }
  };
  const onClearBlocker = async () => {
    setBusy(true);
    try { await apiClearBlocker(item.id); await load(); }
    finally { setBusy(false); }
  };

  // V3.3: edit / voice-update / duplicate / archive / cancel
  const openEdit = () => {
    setEditing({
      title: item.title, description: item.description,
      priority: item.priority, required_by: item.required_by || '',
      quantity: (item.ai_details as any)?.quantity || '',
      unit: (item.ai_details as any)?.unit || '',
    });
  };
  const onSaveEdit = async () => {
    if (!editing) return;
    setBusy(true);
    try {
      const patch: any = {};
      if (editing.title !== item.title) patch.title = editing.title;
      if (editing.description !== item.description) patch.description = editing.description;
      if (editing.priority !== item.priority) patch.priority = editing.priority;
      if ((editing.required_by || null) !== item.required_by) {
        patch.required_by = editing.required_by ? editing.required_by : null;
      }
      const curQty = (item.ai_details as any)?.quantity || '';
      const curUnit = (item.ai_details as any)?.unit || '';
      if (editing.quantity !== curQty && editing.quantity !== '') patch.quantity = editing.quantity;
      if (editing.unit !== curUnit && editing.unit !== '') patch.unit = editing.unit;
      // strip null required_by (PATCH model rejects null) — server treats absent as no-change
      if (patch.required_by === null) delete patch.required_by;
      if (Object.keys(patch).length === 0) { setEditing(null); return; }
      await apiEditItem(item.id, patch);
      setEditing(null);
      await load();
    } catch (e: any) { Alert.alert('Edit failed', String(e?.message || e)); }
    finally { setBusy(false); }
  };

  const startRecord = async () => {
    const ok = await startRecordRaw();
    if (!ok) Alert.alert('Recording failed', 'Could not start recording');
  };
  const stopAndUpload = async () => {
    try {
      const uri = await stopRecordRaw();
      if (!uri) return;
      setUploadingVoice(true);
      await apiVoiceUpdate(item.id, uri);
      await load();
    } catch (e: any) { Alert.alert('Voice update failed', String(e?.message || e)); }
    finally { setUploadingVoice(false); }
  };
  const cancelRecord = async () => {
    await cancelRecordRaw();
  };
  // FAC-OPS-06 — text sibling of the voice update, same ledger entry,
  // same "Support: Voice, Text" requirement as Capture's own text option.
  const submitTextUpdate = async () => {
    if (!textUpdateNote.trim()) return;
    setUploadingVoice(true);
    try {
      await apiTextUpdate(item.id, textUpdateNote.trim());
      setTextUpdateNote('');
      setShowTextUpdate(false);
      await load();
    } catch (e: any) { Alert.alert('Text update failed', String(e?.message || e)); }
    finally { setUploadingVoice(false); }
  };

  const openDuplicatePicker = async () => {
    try {
      const list = await apiListItems({ site_id: item.site_id });
      setDupCandidates(list.filter((x) => x.id !== item.id && x.status !== 'duplicate'));
      setShowDupPicker(true);
    } catch (e: any) { Alert.alert('Load failed', String(e?.message || e)); }
  };
  const onPickDuplicate = async (target: OperationalItem) => {
    setShowDupPicker(false);
    setBusy(true);
    try { await apiMarkDuplicate(item.id, target.id); await load(); }
    catch (e: any) { Alert.alert('Mark duplicate failed', String(e?.message || e)); }
    finally { setBusy(false); }
  };

  const onArchive = async () => {
    setBusy(true);
    try { await apiTransitionItem(item.id, 'archived'); await load(); }
    catch (e: any) { Alert.alert('Archive failed', String(e?.message || e)); }
    finally { setBusy(false); }
  };
  const onCancel = async () => {
    setBusy(true);
    try { await apiTransitionItem(item.id, 'cancelled'); await load(); }
    catch (e: any) { Alert.alert('Cancel failed', String(e?.message || e)); }
    finally { setBusy(false); }
  };

  const next = primaryFor(item);
  const evPhoto = evidence?.photo_thumbs?.[0]?.base64 || null;
  const evTranscript = evidence?.analysis?.transcript || evidence?.event?.text_input || null;

  return (
    <KeyboardAvoidingView style={{ flex: 1 }} behavior={Platform.OS === 'ios' ? 'padding' : undefined}>
    <SafeAreaView style={styles.safe} edges={['top']}>
      <View style={styles.topBar}>
        <Pressable testID="op-back" onPress={() => router.back()} style={styles.backBtn}>
          <Ionicons name="arrow-back" size={26} color={theme.color.text} />
        </Pressable>
        <Text style={styles.barTitle} numberOfLines={1}>OPERATIONAL ITEM</Text>
        <View style={{ width: 40 }} />
      </View>

      <ScrollView contentContainerStyle={{ paddingBottom: 200 }}>
        <View style={styles.body}>
          {/* tags */}
          <View style={styles.tagsRow}>
            <Tag color={PRIORITY_COLOR[item.priority]}>{item.priority.toUpperCase()}</Tag>
            <Tag color={HEALTH_COLOR[item.health]}>{item.health.replace('_', ' ').toUpperCase()}</Tag>
            <Tag color={theme.color.surface3} dim>{item.status.toUpperCase()}</Tag>
            {item.metrics.days_overdue > 0 && (
              <Tag color={theme.color.error}>{`${item.metrics.days_overdue}d OVERDUE`}</Tag>
            )}
          </View>

          <Text style={styles.title}>{item.title}</Text>
          {(item.project_name || item.site_name) ? (
            <View style={{ flexDirection: 'row', alignItems: 'center', gap: 4, marginTop: 4 }}>
              <Ionicons name="location" size={12} color={theme.color.brand} />
              <Text style={{ color: theme.color.brand, fontSize: 11, fontWeight: '900', letterSpacing: 1 }} numberOfLines={1}>
                {[item.project_name, item.site_name].filter(Boolean).join(' · ')}
              </Text>
            </View>
          ) : null}
          {item.description ? <Text style={styles.desc}>{item.description}</Text> : null}

          {/* THREE QUESTIONS — always visible */}
          <View style={styles.threeQuestions}>
            <Q icon="help-circle" question="Why does this exist?"
               answer={item.origin_type === 'ai_proposal' ? 'AI detected this from a site capture'
                       : item.origin_type === 'manual' ? `Created by ${item.created_by_user_name}`
                       : `Origin: ${item.origin_type}`} />
            <Q icon="person" question="Who currently owns it?"
               answer={item.assigned_to_user_name || 'No one assigned yet'} />
            <Q icon="alert-circle" question="What is preventing completion?"
               answer={item.blocker ? humanBlocker(item.blocker.category) : 'No blocker'}
               accent={!!item.blocker} />
          </View>

          {/* Sprint 6.2 Client Permissions: clients get a dedicated
              approve/reject/comment UI instead of the operational action
              set below — never assignment, editing, blockers, escalation,
              archiving, or cancelling-as-an-operational-action. */}
          {viewRole === 'client' ? (
            item.category === 'client_approval' ? (
              <View style={styles.clientDecisionBox}>
                {(item.status === 'fulfilled' || item.status === 'cancelled' || item.status === 'verified' || item.status === 'closed') ? (
                  <View style={[styles.primary, { backgroundColor: theme.color.surface3 }]}>
                    <Ionicons name={item.status === 'cancelled' ? 'close-circle' : 'checkmark-circle'}
                      size={24} color={item.status === 'cancelled' ? theme.color.error : theme.color.success} />
                    <Text style={[styles.primaryText, { color: theme.color.textDim }]}>
                      {item.status === 'cancelled' ? 'REJECTED' : 'APPROVED'}
                    </Text>
                  </View>
                ) : (
                  <>
                    <Text style={styles.clientDecisionLabel}>Add a comment (optional)</Text>
                    <TextInput
                      testID="client-decision-comment"
                      value={clientNote} onChangeText={setClientNote}
                      placeholder="Any notes for the project team…" placeholderTextColor={theme.color.textDim}
                      style={styles.clientDecisionInput} multiline
                    />
                    <View style={{ flexDirection: 'row', gap: theme.spacing.sm, marginTop: theme.spacing.sm }}>
                      <Pressable testID="client-approve" disabled={busy} onPress={() => onClientDecision('fulfilled')}
                        style={[styles.primary, { flex: 1, backgroundColor: theme.color.success }]}>
                        <Ionicons name="checkmark-circle" size={22} color={theme.color.onBrand} />
                        <Text style={styles.primaryText}>APPROVE</Text>
                      </Pressable>
                      <Pressable testID="client-reject" disabled={busy} onPress={() => onClientDecision('cancelled')}
                        style={[styles.primary, { flex: 1, backgroundColor: theme.color.error }]}>
                        <Ionicons name="close-circle" size={22} color={theme.color.onBrand} />
                        <Text style={styles.primaryText}>REJECT</Text>
                      </Pressable>
                    </View>
                  </>
                )}
              </View>
            ) : (
              <View style={[styles.primary, { backgroundColor: theme.color.surface3 }]}>
                <Ionicons name="eye" size={22} color={theme.color.textDim} />
                <Text style={[styles.primaryText, { color: theme.color.textDim }]}>VIEW ONLY</Text>
              </View>
            )
          ) : (
            <>
              {/* Primary action */}
              {next ? (
                <Pressable testID={`primary-${next.to}`} disabled={busy}
                  onPress={() => onTransition(next.to)} style={[styles.primary, busy && { opacity: 0.5 }]}>
                  <Ionicons name={next.icon} size={24} color={theme.color.onBrand} />
                  <Text style={styles.primaryText}>{next.label}</Text>
                </Pressable>
              ) : (
                <View style={[styles.primary, { backgroundColor: theme.color.surface3 }]}>
                  <Ionicons name="checkmark-circle" size={24} color={theme.color.textDim} />
                  <Text style={[styles.primaryText, { color: theme.color.textDim }]}>CLOSED</Text>
                </View>
              )}

              <View style={styles.actionRow}>
                {!item.assigned_to_user_id && item.status !== 'closed' && (
                  <Pressable testID="reassign" onPress={openAssign} disabled={busy}
                    style={[styles.actionBtn, { borderColor: theme.color.info }]}>
                    <Ionicons name="person-add" size={18} color={theme.color.info} />
                    <Text style={[styles.actionLabel, { color: theme.color.info }]}>ASSIGN</Text>
                  </Pressable>
                )}
                {item.assigned_to_user_id && item.status !== 'closed' && (
                  <Pressable testID="reassign" onPress={openAssign} disabled={busy}
                    style={[styles.actionBtn, { borderColor: theme.color.info }]}>
                    <Ionicons name="swap-horizontal" size={18} color={theme.color.info} />
                    <Text style={[styles.actionLabel, { color: theme.color.info }]}>REASSIGN</Text>
                  </Pressable>
                )}
                <Pressable testID="edit-item" onPress={openEdit} disabled={busy}
                  style={[styles.actionBtn, { borderColor: theme.color.brand }]}>
                  <Ionicons name="pencil" size={18} color={theme.color.brand} />
                  <Text style={[styles.actionLabel, { color: theme.color.brand }]}>EDIT</Text>
                </Pressable>
                {item.blocker ? (
                  <Pressable testID="clear-blocker" onPress={onClearBlocker} disabled={busy}
                    style={[styles.actionBtn, { borderColor: theme.color.success }]}>
                    <Ionicons name="checkmark" size={18} color={theme.color.success} />
                    <Text style={[styles.actionLabel, { color: theme.color.success }]}>CLEAR BLOCK</Text>
                  </Pressable>
                ) : (
                  <Pressable testID="set-blocker" onPress={() => setShowBlockerPicker(true)} disabled={busy}
                    style={[styles.actionBtn, { borderColor: '#9C27B0' }]}>
                    <Ionicons name="warning" size={18} color="#9C27B0" />
                    <Text style={[styles.actionLabel, { color: '#9C27B0' }]}>FLAG BLOCKER</Text>
                  </Pressable>
                )}
              </View>

              {/* V3.3 secondary actions row */}
              <View style={styles.actionRow}>
                {recording ? (
                  <>
                    <Pressable testID="voice-stop" onPress={stopAndUpload}
                      style={[styles.actionBtn, { borderColor: theme.color.error, backgroundColor: theme.color.surface3 }]}>
                      <Ionicons name="stop-circle" size={20} color={theme.color.error} />
                      <Text style={[styles.actionLabel, { color: theme.color.error }]}>{`STOP · ${elapsed}s`}</Text>
                    </Pressable>
                    <Pressable testID="voice-cancel" onPress={cancelRecord}
                      style={[styles.actionBtn, { borderColor: theme.color.textDim }]}>
                      <Ionicons name="close" size={18} color={theme.color.textDim} />
                      <Text style={[styles.actionLabel, { color: theme.color.textDim }]}>CANCEL</Text>
                    </Pressable>
                  </>
                ) : (
                  <>
                    <Pressable testID="voice-update" onPress={startRecord}
                      disabled={busy || uploadingVoice || item.status === 'closed'}
                      style={[styles.actionBtn, { borderColor: theme.color.brand, backgroundColor: theme.color.surface2 }]}>
                      <Ionicons name={uploadingVoice ? 'sync' : 'mic'} size={18} color={theme.color.brand} />
                      <Text style={[styles.actionLabel, { color: theme.color.brand }]}>
                        {uploadingVoice ? 'TRANSCRIBING…' : 'VOICE UPDATE'}
                      </Text>
                    </Pressable>
                    <Pressable testID="text-update-toggle" onPress={() => setShowTextUpdate((v) => !v)}
                      disabled={busy || uploadingVoice || item.status === 'closed'}
                      style={[styles.actionBtn, showTextUpdate
                        ? { borderColor: theme.color.brand, backgroundColor: theme.color.brand }
                        : { borderColor: theme.color.brand, backgroundColor: theme.color.surface2 }]}>
                      <Ionicons name="create-outline" size={18} color={showTextUpdate ? theme.color.onBrand : theme.color.brand} />
                      <Text style={[styles.actionLabel, { color: showTextUpdate ? theme.color.onBrand : theme.color.brand }]}>
                        TEXT UPDATE
                      </Text>
                    </Pressable>
                  </>
                )}
                {item.status !== 'duplicate' && item.status !== 'closed' && item.status !== 'archived' && (
                  <Pressable testID="mark-duplicate" onPress={openDuplicatePicker} disabled={busy}
                    style={[styles.actionBtn, { borderColor: theme.color.textMuted }]}>
                    <Ionicons name="copy" size={18} color={theme.color.textMuted} />
                    <Text style={[styles.actionLabel, { color: theme.color.textMuted }]}>DUPLICATE</Text>
                  </Pressable>
                )}
                {item.status !== 'archived' && (
                  <Pressable testID="archive-item" onPress={() => Alert.alert('Archive item?', 'It will be hidden from active lists. History is preserved.', [{ text: 'Cancel' }, { text: 'Archive', style: 'destructive', onPress: onArchive }])} disabled={busy}
                    style={[styles.actionBtn, { borderColor: theme.color.warning }]}>
                    <Ionicons name="archive" size={18} color={theme.color.warning} />
                    <Text style={[styles.actionLabel, { color: theme.color.warning }]}>ARCHIVE</Text>
                  </Pressable>
                )}
                {item.status !== 'cancelled' && item.status !== 'closed' && item.status !== 'archived' && (
                  <Pressable testID="cancel-item" onPress={() => Alert.alert('Cancel item?', 'Marks it cancelled. History is preserved.', [{ text: 'Back' }, { text: 'Cancel item', style: 'destructive', onPress: onCancel }])} disabled={busy}
                    style={[styles.actionBtn, { borderColor: theme.color.error }]}>
                    <Ionicons name="close-circle" size={18} color={theme.color.error} />
                    <Text style={[styles.actionLabel, { color: theme.color.error }]}>CANCEL</Text>
                  </Pressable>
                )}
              </View>

              {showTextUpdate && (
                <View style={styles.clientDecisionBox}>
                  <TextInput
                    testID="text-update-input"
                    value={textUpdateNote}
                    onChangeText={setTextUpdateNote}
                    placeholder="Type an update…"
                    placeholderTextColor={theme.color.textDim}
                    style={styles.clientDecisionInput}
                    multiline
                    autoFocus
                  />
                  <Pressable testID="text-update-send" onPress={submitTextUpdate}
                    disabled={uploadingVoice || !textUpdateNote.trim()}
                    style={[styles.primary, { height: 44 }, (uploadingVoice || !textUpdateNote.trim()) && { opacity: 0.4 }]}>
                    {uploadingVoice ? <ActivityIndicator size="small" color={theme.color.onBrand} /> : (
                      <Text style={[styles.primaryText, { fontSize: 14 }]}>ADD UPDATE</Text>
                    )}
                  </Pressable>
                </View>
              )}
            </>
          )}

          {showBlockerPicker && (
            <View style={styles.blockerPicker}>
              <Text style={styles.blockerTitle}>What is blocking this?</Text>
              {BLOCKERS.map((b) => (
                <Pressable key={b} testID={`pick-blocker-${b}`} onPress={() => onBlocker(b)} style={styles.blockerRow}>
                  <Ionicons name="warning-outline" size={16} color="#9C27B0" />
                  <Text style={styles.blockerLabel}>{humanBlocker(b)}</Text>
                </Pressable>
              ))}
            </View>
          )}

          {showAssignPicker && (
            <View style={styles.blockerPicker}>
              <Text style={styles.blockerTitle}>Assign to whom?</Text>
              {users.length === 0 ? (
                <Text style={{ color: theme.color.textDim, fontSize: 13 }}>No users available</Text>
              ) : (
                users.map((u) => {
                  const suggested = item.suggested_owner_role &&
                    (u.role === item.suggested_owner_role ||
                     item.suggested_owner_role.includes(u.role));
                  return (
                    <Pressable key={u.id} testID={`pick-assignee-${u.id}`}
                      onPress={() => onAssign(u)} style={styles.blockerRow}>
                      <Ionicons name="person-circle-outline" size={18}
                        color={suggested ? theme.color.brand : theme.color.textMuted} />
                      <Text style={styles.blockerLabel}>{u.name}</Text>
                      <Text style={{ color: theme.color.textDim, fontSize: 11, marginLeft: 'auto' }}>
                        {ROLE_LABEL[u.role as Role] || u.role}{suggested ? '  ★' : ''}
                      </Text>
                    </Pressable>
                  );
                })
              )}
            </View>
          )}

          {/* Why does this exist? — Evidence */}
          {evidence ? (
            <Section icon="document-attach" title="WHY DOES THIS OPERATIONAL ITEM EXIST?">
              <Text style={styles.evHeading}>Original Construction Event</Text>
              <Text style={styles.evMeta}>
                {evidence.event?.user_name} · {new Date(evidence.event?.server_created_at).toLocaleString()}
              </Text>
              {evTranscript ? (
                <View style={styles.transcriptBox}>
                  <Ionicons name="mic" size={14} color={theme.color.brand} />
                  <Text style={styles.transcriptText} numberOfLines={6}>{evTranscript}</Text>
                </View>
              ) : null}
              {evPhoto ? (
                <ExpoImage source={{ uri: `data:image/jpeg;base64,${evPhoto}` }}
                  style={styles.evidencePhoto} contentFit="cover" />
              ) : null}
              {evidence.event?.gps ? (
                <View style={styles.evGps}>
                  <Ionicons name="location" size={14} color={theme.color.brand} />
                  <Text style={styles.evGpsText}>
                    {evidence.event.gps.lat.toFixed(4)}, {evidence.event.gps.lng.toFixed(4)}
                  </Text>
                </View>
              ) : null}
              <Pressable testID="open-event"
                onPress={() => router.push(`/event/${evidence.event.id}`)}
                style={styles.linkBtn}>
                <Text style={styles.linkText}>OPEN ORIGINAL EVENT →</Text>
              </Pressable>
            </Section>
          ) : null}

          {/* Time intelligence */}
          <Section icon="speedometer" title="TIME">
            <View style={styles.metricsGrid}>
              <Metric label="Age" value={fmtHours(item.metrics.current_age_hours)} />
              <Metric label="Remaining" value={fmtHours(item.metrics.time_remaining_hours)} />
              <Metric label="Time to complete" value={fmtHours(item.metrics.time_to_complete_hours)} />
              <Metric label="Verification delay" value={fmtHours(item.metrics.verification_delay_hours)} />
            </View>
          </Section>

          {/* Activity feed — unified, append-only */}
          <Section icon="git-network" title="ACTIVITY">
            {history.length === 0 ? (
              <Text style={{ color: theme.color.textDim, fontSize: 13 }}>No activity yet.</Text>
            ) : history.map((h) => (
              <View key={h.id} style={styles.histRow} testID={`activity-${h.kind}-${h.id}`}>
                <View style={[styles.histDot, { backgroundColor: kindColor(h.kind) }]} />
                <View style={{ flex: 1 }}>
                  <Text style={styles.histKind}>{humanActivityKind(h.kind)}</Text>
                  <Text style={styles.histMeta}>
                    {h.actor_user_name} · {new Date(h.created_at).toLocaleString()}
                  </Text>
                  {/* generic text/note payloads */}
                  {h.payload?.text ? <Text style={styles.histText}>{h.payload.text}</Text> : null}
                  {h.payload?.note ? <Text style={styles.histText}>{h.payload.note}</Text> : null}
                  {/* edited: render compact diff */}
                  {h.kind === 'edited' && h.payload?.changes ? (
                    <View style={styles.diffBox}>
                      {Object.entries(h.payload.changes as Record<string, any>).map(([k, d]) => (
                        <Text key={k} style={styles.diffLine}>
                          <Text style={styles.diffField}>{k}</Text>
                          {`: ${fmtDiffVal(d.from)} → ${fmtDiffVal(d.to_name ?? d.to)}`}
                        </Text>
                      ))}
                      {h.payload.details_changes ? Object.entries(h.payload.details_changes as Record<string, any>).map(([k, d]) => (
                        <Text key={`d-${k}`} style={styles.diffLine}>
                          <Text style={styles.diffField}>{k}</Text>
                          {`: ${fmtDiffVal(d.from)} → ${fmtDiffVal(d.to)}`}
                        </Text>
                      )) : null}
                    </View>
                  ) : null}
                  {/* voice update: transcript + AI summary */}
                  {h.kind === 'voice_update' ? (
                    <View style={styles.voiceCard}>
                      <View style={styles.voiceHead}>
                        <Ionicons name="mic" size={14} color={theme.color.brand} />
                        <Text style={styles.voiceHeadText}>VOICE</Text>
                        {h.payload?.language ? <Text style={styles.voiceLang}>{h.payload.language}</Text> : null}
                      </View>
                      {h.payload?.transcript ? (
                        <Text style={styles.voiceTranscript} numberOfLines={6}>{h.payload.transcript}</Text>
                      ) : null}
                      {h.payload?.summary ? (
                        <Text style={styles.voiceSummary}>↳ {h.payload.summary}</Text>
                      ) : null}
                    </View>
                  ) : null}
                  {/* assignment payload */}
                  {h.kind === 'assigned' && h.payload?.assigned_to_user_name ? (
                    <Text style={styles.histText}>→ {h.payload.assigned_to_user_name}</Text>
                  ) : null}
                  {/* duplicate of */}
                  {h.kind === 'duplicate_of' && h.payload?.duplicate_of_title ? (
                    <Text style={styles.histText}>↪ {h.payload.duplicate_of_title}</Text>
                  ) : null}
                  {/* blocker */}
                  {h.kind === 'blocker_set' && h.payload?.category ? (
                    <Text style={styles.histText}>{humanBlocker(h.payload.category)}</Text>
                  ) : null}
                </View>
              </View>
            ))}
          </Section>
        </View>
      </ScrollView>

      {/* Comment composer */}
      <View style={styles.composer}>
        <TextInput
          testID="comment-input"
          value={commentText}
          onChangeText={setCommentText}
          placeholder="Add update or comment…"
          placeholderTextColor={theme.color.textDim}
          style={styles.commentInput}
          multiline
        />
        <Pressable testID="send-comment" onPress={onComment} disabled={busy || !commentText.trim()}
          style={[styles.sendBtn, (!commentText.trim() || busy) && { opacity: 0.4 }]}>
          <Ionicons name="send" size={20} color={theme.color.onBrand} />
        </Pressable>
      </View>

      {/* Edit modal */}
      <Modal visible={!!editing} animationType="slide" transparent>
        <View style={styles.modalBack}>
          <View style={styles.modal}>
            <View style={styles.modalHead}>
              <Text style={styles.modalTitle}>EDIT ITEM</Text>
              <Pressable testID="edit-modal-close" onPress={() => setEditing(null)}>
                <Ionicons name="close" size={26} color={theme.color.textDim} />
              </Pressable>
            </View>
            <EditField label="Title" value={editing?.title} testID="edit-input-title"
              onChangeText={(t: string) => setEditing({ ...(editing || {}), title: t })} />
            <EditField label="Description" value={editing?.description} testID="edit-input-description"
              multiline
              onChangeText={(t: string) => setEditing({ ...(editing || {}), description: t })} />
            <EditField label="Quantity" value={editing?.quantity} testID="edit-input-quantity"
              onChangeText={(t: string) => setEditing({ ...(editing || {}), quantity: t })} />
            <EditField label="Unit" value={editing?.unit} testID="edit-input-unit"
              onChangeText={(t: string) => setEditing({ ...(editing || {}), unit: t })} />
            <EditField label="Required by (YYYY-MM-DD)" value={editing?.required_by} testID="edit-input-required-by"
              onChangeText={(t: string) => setEditing({ ...(editing || {}), required_by: t })} />
            <Text style={styles.label}>Priority</Text>
            <View style={{ flexDirection: 'row', gap: 6, marginBottom: 12 }}>
              {(['low', 'normal', 'high', 'critical'] as const).map((p) => (
                <Pressable key={p} testID={`edit-priority-${p}`}
                  onPress={() => setEditing({ ...(editing || {}), priority: p })}
                  style={[styles.prioBtn, editing?.priority === p && { backgroundColor: PRIORITY_COLOR[p], borderColor: PRIORITY_COLOR[p] }]}>
                  <Text style={[styles.prioTxt, editing?.priority === p && { color: '#fff' }]}>{p.toUpperCase()}</Text>
                </Pressable>
              ))}
            </View>
            <Pressable testID="edit-save" onPress={onSaveEdit} disabled={busy}
              style={[styles.saveBtn, busy && { opacity: 0.5 }]}>
              <Ionicons name="checkmark" size={22} color={theme.color.onBrand} />
              <Text style={styles.saveBtnText}>SAVE</Text>
            </Pressable>
          </View>
        </View>
      </Modal>

      {/* Duplicate picker modal */}
      <Modal visible={showDupPicker} animationType="slide" transparent>
        <View style={styles.modalBack}>
          <View style={styles.modal}>
            <View style={styles.modalHead}>
              <Text style={styles.modalTitle}>MARK DUPLICATE OF…</Text>
              <Pressable testID="dup-modal-close" onPress={() => setShowDupPicker(false)}>
                <Ionicons name="close" size={26} color={theme.color.textDim} />
              </Pressable>
            </View>
            <ScrollView style={{ maxHeight: 360 }}>
              {dupCandidates.length === 0 ? (
                <Text style={{ color: theme.color.textDim, fontSize: 13 }}>No other items in this site.</Text>
              ) : dupCandidates.map((c) => (
                <Pressable key={c.id} testID={`dup-pick-${c.id}`} onPress={() => onPickDuplicate(c)} style={styles.dupRow}>
                  <Ionicons name="copy-outline" size={18} color={theme.color.brand} />
                  <View style={{ flex: 1 }}>
                    <Text style={styles.dupTitle} numberOfLines={1}>{c.title}</Text>
                    <Text style={styles.dupMeta}>{c.category.replace(/_/g, ' ')} · {c.status}</Text>
                  </View>
                </Pressable>
              ))}
            </ScrollView>
          </View>
        </View>
      </Modal>
    </SafeAreaView>
    </KeyboardAvoidingView>
  );
}

function EditField({ label, value, onChangeText, testID, multiline }: any) {
  return (
    <View style={{ marginBottom: 10 }}>
      <Text style={styles.label}>{label}</Text>
      <TextInput
        testID={testID}
        value={value || ''}
        onChangeText={onChangeText}
        placeholderTextColor={theme.color.textDim}
        multiline={multiline}
        style={[styles.input, multiline && { minHeight: 64, textAlignVertical: 'top' }]}
      />
    </View>
  );
}

function fmtDiffVal(v: any): string {
  if (v === null || v === undefined || v === '') return '∅';
  return String(v);
}

function humanActivityKind(k: string): string {
  const map: Record<string, string> = {
    created: 'CREATED', edited: 'EDITED', voice_update: 'VOICE UPDATE',
    comment: 'COMMENT', assigned: 'ASSIGNMENT', reassigned: 'REASSIGNMENT',
    acknowledged: 'ACKNOWLEDGED', started: 'STARTED',
    fulfilled: 'FULFILLED', verified: 'VERIFIED', closed: 'CLOSED',
    reopened: 'REOPENED', archived: 'ARCHIVED', cancelled: 'CANCELLED',
    duplicate: 'DUPLICATE', duplicate_of: 'MARKED DUPLICATE',
    blocker_set: 'BLOCKER', blocker_cleared: 'BLOCKER CLEARED',
    due_set: 'DUE DATE SET', escalated: 'ESCALATED',
  };
  return map[k] || k.replace(/_/g, ' ').toUpperCase();
}

function Q({ icon, question, answer, accent }: any) {
  return (
    <View style={styles.qRow}>
      <View style={[styles.qIcon, accent && { backgroundColor: '#9C27B0' }]}>
        <Ionicons name={icon} size={14} color="#fff" />
      </View>
      <View style={{ flex: 1 }}>
        <Text style={styles.qQuestion}>{question}</Text>
        <Text style={styles.qAnswer}>{answer}</Text>
      </View>
    </View>
  );
}
function Tag({ children, color, dim }: any) {
  return (
    <View style={[styles.tag, { backgroundColor: dim ? 'transparent' : color, borderColor: color }]}>
      <Text style={[styles.tagText, { color: dim ? theme.color.textMuted : '#fff' }]}>{children}</Text>
    </View>
  );
}
function Section({ icon, title, children }: any) {
  return (
    <View style={styles.section}>
      <View style={styles.sectionHead}>
        <Ionicons name={icon} size={16} color={theme.color.brand} />
        <Text style={styles.sectionTitle}>{title}</Text>
      </View>
      {children}
    </View>
  );
}
function Metric({ label, value }: any) {
  return (
    <View style={styles.metric}>
      <Text style={styles.metricLabel}>{label}</Text>
      <Text style={styles.metricValue}>{value}</Text>
    </View>
  );
}
function fmtHours(h: number | null): string {
  if (h === null || h === undefined) return '—';
  if (Math.abs(h) < 1) return `${Math.round(h * 60)} min`;
  if (Math.abs(h) < 48) return `${h.toFixed(1)} h`;
  return `${(h / 24).toFixed(1)} d`;
}
function kindColor(k: string): string {
  if (k === 'created') return theme.color.brand;
  if (k === 'assigned' || k === 'reassigned') return theme.color.info;
  if (k === 'started') return theme.color.warning;
  if (k === 'fulfilled' || k === 'verified' || k === 'closed') return theme.color.success;
  if (k === 'blocker_set') return '#9C27B0';
  if (k === 'blocker_cleared') return theme.color.success;
  if (k === 'comment') return theme.color.textDim;
  if (k === 'escalated') return theme.color.error;
  return theme.color.textMuted;
}

const styles = StyleSheet.create({
  safe: { flex: 1, backgroundColor: theme.color.surface },
  center: { flex: 1, alignItems: 'center', justifyContent: 'center' },
  topBar: { flexDirection: 'row', alignItems: 'center', padding: theme.spacing.md, gap: theme.spacing.sm },
  backBtn: { width: 40, height: 40, borderRadius: 20, backgroundColor: theme.color.surface2,
            alignItems: 'center', justifyContent: 'center' },
  barTitle: { flex: 1, color: theme.color.brand, fontSize: 14, fontWeight: '900', letterSpacing: 2, textAlign: 'center' },
  body: { padding: theme.spacing.lg, gap: theme.spacing.md },
  tagsRow: { flexDirection: 'row', flexWrap: 'wrap', gap: 6 },
  tag: { paddingHorizontal: 10, paddingVertical: 4, borderRadius: 6, borderWidth: 1 },
  tagText: { fontSize: 10, fontWeight: '900', letterSpacing: 1 },
  title: { color: theme.color.text, fontSize: 24, fontWeight: '900' },
  desc: { color: theme.color.textMuted, fontSize: 15, lineHeight: 22 },
  threeQuestions: { gap: 10, padding: theme.spacing.md, backgroundColor: theme.color.surface2,
                    borderRadius: theme.radius.md, borderWidth: 1, borderColor: theme.color.border },
  qRow: { flexDirection: 'row', gap: 10, alignItems: 'flex-start' },
  qIcon: { width: 26, height: 26, borderRadius: 13, backgroundColor: theme.color.brand,
           alignItems: 'center', justifyContent: 'center', marginTop: 1 },
  qQuestion: { color: theme.color.textDim, fontSize: 11, fontWeight: '800', letterSpacing: 1 },
  qAnswer: { color: theme.color.text, fontSize: 15, fontWeight: '700', marginTop: 2 },
  clientDecisionBox: { gap: theme.spacing.sm, marginTop: theme.spacing.sm },
  clientDecisionLabel: { color: theme.color.textMuted, fontSize: 12, fontWeight: '800', letterSpacing: 0.5 },
  clientDecisionInput: {
    minHeight: 70, backgroundColor: theme.color.surface2, borderRadius: theme.radius.md,
    borderWidth: 1, borderColor: theme.color.border, padding: theme.spacing.sm,
    color: theme.color.text, fontSize: 14, textAlignVertical: 'top',
  },
  primary: { height: 64, borderRadius: theme.radius.md, backgroundColor: theme.color.brand,
             flexDirection: 'row', alignItems: 'center', justifyContent: 'center', gap: theme.spacing.sm },
  primaryText: { color: theme.color.onBrand, fontSize: 18, fontWeight: '900', letterSpacing: 2 },
  actionRow: { flexDirection: 'row', flexWrap: 'wrap', gap: theme.spacing.xs },
  actionBtn: { flex: 1, minWidth: 100, height: 44, borderRadius: theme.radius.sm, borderWidth: 1.5,
               flexDirection: 'row', alignItems: 'center', justifyContent: 'center', gap: 5,
               paddingHorizontal: 8 },
  actionLabel: { fontSize: 11, fontWeight: '900', letterSpacing: 0.5 },
  blockerPicker: { padding: theme.spacing.md, backgroundColor: theme.color.surface2, borderRadius: theme.radius.md,
                  borderWidth: 1, borderColor: theme.color.border, gap: 6 },
  blockerTitle: { color: theme.color.brand, fontSize: 12, fontWeight: '900', letterSpacing: 1, marginBottom: 4 },
  blockerRow: { flexDirection: 'row', alignItems: 'center', gap: 8, paddingVertical: 10 },
  blockerLabel: { color: theme.color.text, fontSize: 14, fontWeight: '700' },
  section: { padding: theme.spacing.md, backgroundColor: theme.color.surface2, borderRadius: theme.radius.md,
             borderWidth: 1, borderColor: theme.color.border, gap: theme.spacing.sm },
  sectionHead: { flexDirection: 'row', alignItems: 'center', gap: 8 },
  sectionTitle: { color: theme.color.brand, fontSize: 12, fontWeight: '900', letterSpacing: 2 },
  evHeading: { color: theme.color.text, fontSize: 14, fontWeight: '800' },
  evMeta: { color: theme.color.textDim, fontSize: 12, marginTop: 2 },
  transcriptBox: { flexDirection: 'row', gap: 8, padding: 10, backgroundColor: theme.color.surface3,
                   borderRadius: theme.radius.sm, alignItems: 'flex-start' },
  transcriptText: { color: theme.color.text, fontSize: 13, flex: 1, lineHeight: 20 },
  evidencePhoto: { width: '100%', height: 160, borderRadius: theme.radius.sm },
  evGps: { flexDirection: 'row', alignItems: 'center', gap: 4 },
  evGpsText: { color: theme.color.textMuted, fontSize: 12 },
  linkBtn: { paddingVertical: 8 },
  linkText: { color: theme.color.brand, fontSize: 13, fontWeight: '900', letterSpacing: 1 },
  metricsGrid: { flexDirection: 'row', flexWrap: 'wrap', gap: 8 },
  metric: { flex: 1, minWidth: '45%', padding: 10, backgroundColor: theme.color.surface3, borderRadius: theme.radius.sm },
  metricLabel: { color: theme.color.textDim, fontSize: 10, fontWeight: '700', letterSpacing: 1 },
  metricValue: { color: theme.color.text, fontSize: 16, fontWeight: '800', marginTop: 2 },
  histRow: { flexDirection: 'row', gap: 10 },
  histDot: { width: 10, height: 10, borderRadius: 5, marginTop: 5 },
  histKind: { color: theme.color.brand, fontSize: 11, fontWeight: '900', letterSpacing: 1 },
  histMeta: { color: theme.color.textDim, fontSize: 11, marginTop: 1 },
  histText: { color: theme.color.text, fontSize: 13, marginTop: 4 },
  composer: { flexDirection: 'row', gap: 8, padding: theme.spacing.sm,
              backgroundColor: theme.color.surface2, borderTopWidth: 1, borderTopColor: theme.color.border,
              position: 'absolute', left: 0, right: 0, bottom: 0 },
  commentInput: { flex: 1, minHeight: 48, maxHeight: 120, color: theme.color.text,
                  backgroundColor: theme.color.surface3, paddingHorizontal: 12, paddingVertical: 12,
                  borderRadius: theme.radius.md, fontSize: 15 },
  sendBtn: { width: 48, height: 48, borderRadius: 24, backgroundColor: theme.color.brand,
             alignItems: 'center', justifyContent: 'center' },

  // V3.3 — edit modal + voice + dup picker + diff
  modalBack: { flex: 1, backgroundColor: 'rgba(0,0,0,0.6)', justifyContent: 'flex-end' },
  modal: { backgroundColor: theme.color.surface, borderTopLeftRadius: 18, borderTopRightRadius: 18,
           padding: theme.spacing.lg, gap: 6 },
  modalHead: { flexDirection: 'row', alignItems: 'center', marginBottom: theme.spacing.sm },
  modalTitle: { flex: 1, color: theme.color.brand, fontSize: 14, fontWeight: '900', letterSpacing: 2 },
  label: { color: theme.color.textDim, fontSize: 11, fontWeight: '800', letterSpacing: 1, marginBottom: 4 },
  input: { color: theme.color.text, backgroundColor: theme.color.surface2,
           borderRadius: theme.radius.sm, borderWidth: 1, borderColor: theme.color.border,
           paddingHorizontal: 12, paddingVertical: 10, fontSize: 15 },
  prioBtn: { flex: 1, paddingVertical: 8, borderRadius: theme.radius.sm,
             borderWidth: 1, borderColor: theme.color.border, alignItems: 'center',
             backgroundColor: theme.color.surface2 },
  prioTxt: { color: theme.color.textDim, fontSize: 10, fontWeight: '900', letterSpacing: 1 },
  saveBtn: { marginTop: theme.spacing.md, flexDirection: 'row', alignItems: 'center', justifyContent: 'center',
            gap: 8, height: 52, borderRadius: theme.radius.md, backgroundColor: theme.color.brand },
  saveBtnText: { color: theme.color.onBrand, fontSize: 16, fontWeight: '900', letterSpacing: 1 },
  diffBox: { marginTop: 6, padding: 8, backgroundColor: theme.color.surface3,
             borderRadius: theme.radius.sm, gap: 2 },
  diffField: { color: theme.color.brand, fontWeight: '900' },
  diffLine: { color: theme.color.text, fontSize: 12 },
  voiceCard: { marginTop: 6, padding: 10, borderLeftWidth: 3, borderLeftColor: theme.color.brand,
               backgroundColor: theme.color.surface3, borderRadius: theme.radius.sm, gap: 6 },
  voiceHead: { flexDirection: 'row', alignItems: 'center', gap: 6 },
  voiceHeadText: { color: theme.color.brand, fontSize: 10, fontWeight: '900', letterSpacing: 2 },
  voiceLang: { marginLeft: 'auto', color: theme.color.textDim, fontSize: 10, fontWeight: '700' },
  voiceTranscript: { color: theme.color.text, fontSize: 13, lineHeight: 19 },
  voiceSummary: { color: theme.color.textMuted, fontSize: 12, fontStyle: 'italic' },
  dupRow: { flexDirection: 'row', alignItems: 'center', gap: 10, paddingVertical: 10,
            borderBottomWidth: 1, borderBottomColor: theme.color.border },
  dupTitle: { color: theme.color.text, fontSize: 14, fontWeight: '700' },
  dupMeta: { color: theme.color.textDim, fontSize: 11, marginTop: 2 },
});
