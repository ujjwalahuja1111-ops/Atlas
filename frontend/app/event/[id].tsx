import { useEffect, useRef, useState } from 'react';
import { View, Text, StyleSheet, ScrollView, Pressable, ActivityIndicator, TextInput, Modal } from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import { Image as ExpoImage } from 'expo-image';
import { LinearGradient } from 'expo-linear-gradient';
import { Ionicons } from '@expo/vector-icons';
import { useLocalSearchParams, useRouter } from 'expo-router';
import { theme } from '@/src/theme';
import { apiGetEvent, apiGetPlatformStatus, apiRequestApproval, apiSetEventTimeline, apiRegenerateProposals, type TimelineItem } from '@/src/api';
import { getViewRole, type ViewRole } from '@/src/roles';
import {
  apiListProposals, apiAcceptProposal, apiRejectProposal, type AiProposal,
  apiListItems, apiListUsers, apiAssignItem, type OperationalItem, type AssignableUser,
} from '@/src/ops_api';

const TYPE_LABEL: Record<string, string> = {
  voice_note: 'VOICE NOTE', photo: 'PHOTO', material_request: 'MATERIAL REQUEST',
  issue: 'ISSUE REPORTED', work_completed: 'WORK COMPLETED', general: 'SITE NOTE',
};
const URGENCY_COLOR: Record<string, string> = {
  low: theme.color.info, normal: theme.color.success, high: theme.color.error,
};
const AI_STATUS: Record<string, { label: string; color: string; icon: any }> = {
  pending: { label: 'AI ANALYZING…', color: theme.color.brand, icon: 'sync' },
  analyzed: { label: 'AI ANALYZED', color: theme.color.success, icon: 'checkmark-circle' },
  failed: { label: 'AI FAILED', color: theme.color.error, icon: 'warning' },
  skipped: { label: 'NO AI', color: theme.color.textDim, icon: 'remove' },
  // Sprint 6 — distinct from "pending": we positively know AI won't run
  // (no API key configured) rather than "still working on it".
  unavailable: { label: 'AI UNAVAILABLE', color: theme.color.textDim, icon: 'cloud-offline' },
};

// Sprint 6: a defensive cap regardless of the ai_enabled check above — if
// something is wrong we haven't anticipated, this still guarantees the UI
// never polls forever. 20 attempts x 3s = 60s, matching the existing
// interval below.
const MAX_POLL_ATTEMPTS = 20;

export default function EventDetail() {
  const { id } = useLocalSearchParams<{ id: string }>();
  const router = useRouter();
  const [item, setItem] = useState<TimelineItem | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [aiUnavailable, setAiUnavailable] = useState(false);
  // Client Approval Workflow — "send later from Event Details" path.
  const [viewRole, setViewRole] = useState<ViewRole | null>(null);
  const [sendingApproval, setSendingApproval] = useState(false);
  const [approvalMessage, setApprovalMessage] = useState('');
  const [showApprovalForm, setShowApprovalForm] = useState(false);
  // Proposal Review + Related Operational Items (Canonical Event UX
  // patch, follow-up) — these sections live inside Event Detail now;
  // Proposal Inbox and Operations Center both navigate here rather
  // than showing their own review/assignment UI.
  const [proposals, setProposals] = useState<AiProposal[]>([]);
  const [proposalEdits, setProposalEdits] = useState<Record<string, { title: string; description: string; priority: AiProposal['suggested_priority'] }>>({});
  const [proposalBusyId, setProposalBusyId] = useState<string | null>(null);
  const [regenerating, setRegenerating] = useState(false);
  const [relatedItems, setRelatedItems] = useState<OperationalItem[]>([]);
  const [assignForItemId, setAssignForItemId] = useState<string | null>(null);
  const [assignableUsers, setAssignableUsers] = useState<AssignableUser[]>([]);
  const [assignBusy, setAssignBusy] = useState(false);
  // Timeline Planning (Canonical Event UX patch) — Record Time stays
  // immutable; this is separate, editable planning info.
  const [showTimelineEdit, setShowTimelineEdit] = useState(false);
  const [timelineDraft, setTimelineDraft] = useState({ planned_start: '', planned_finish: '', actual_start: '', actual_finish: '' });
  const [savingTimeline, setSavingTimeline] = useState(false);
  useEffect(() => { getViewRole().then(setViewRole); }, []);

  const loadRelated = async () => {
    if (!id) return;
    try {
      const items = await apiListItems({ event_id: id });
      setRelatedItems(items);
    } catch (e) { console.warn(e); }
  };

  useEffect(() => {
    if (!id || viewRole === null) return;
    loadRelated();
    // Proposal Review (Canonical Event UX patch) — Management/PM only,
    // matching "Review AI proposal" in the RBAC table below.
    if (viewRole === 'admin' || viewRole === 'pm') {
      apiListProposals({ event_id: id }).then((props) => {
        setProposals(props);
        const edits: typeof proposalEdits = {};
        for (const p of props) {
          edits[p.id] = { title: p.title, description: p.description || '', priority: p.suggested_priority };
        }
        setProposalEdits(edits);
      }).catch((e) => console.warn(e));
    }
  }, [id, viewRole]);

  // Sprint 4.1 fix (audit H1): the interval below used to read `item` from
  // a closure captured once at effect-creation time — since the effect's
  // dependency array never actually changed (the old `tick` state was never
  // incremented anywhere), that closure stayed frozen at `item === null`
  // forever, so `!item` was permanently true and the poll never stopped,
  // even long after ai_status resolved. A ref sidesteps the stale-closure
  // problem entirely: the interval always reads the CURRENT status.
  const aiStatusRef = useRef<string | null>(null);

  useEffect(() => {
    if (!id) return;
    let cancelled = false;
    let attempts = 0;
    const load = async () => {
      try {
        const i = await apiGetEvent(id);
        if (cancelled) return;
        setItem(i);
        setLoadError(null);
        aiStatusRef.current = i.event.ai_status;
      } catch (e: any) {
        if (!cancelled) setLoadError(e?.message || 'Could not load this event.');
      }
    };
    load();

    // Sprint 6: check once, upfront, whether AI is even running — if it
    // isn't (no API key configured, Sprint 5.0.2's optional-AI mode), we
    // already know a "pending" status will never resolve, so skip polling
    // entirely and say so immediately instead of showing "AI ANALYZING…"
    // forever. Fails open (assumes AI is available) if the check itself
    // fails, falling back to the existing poll-with-a-cap behaviour below.
    apiGetPlatformStatus().then(({ ai_enabled }) => {
      if (!cancelled && !ai_enabled) setAiUnavailable(true);
    });

    const t = setInterval(() => {
      attempts += 1;
      const stillPending = aiStatusRef.current === 'pending' || aiStatusRef.current === null;
      if (stillPending && attempts < MAX_POLL_ATTEMPTS) {
        load();
      } else {
        if (stillPending) setAiUnavailable(true);  // timed out — never spin forever
        clearInterval(t);
      }
    }, 3000);
    return () => { cancelled = true; clearInterval(t); };
  }, [id]);

  // Client Approval Workflow — the SAME apiRequestApproval call the
  // Capture screen's "send immediately" path uses (see capture.tsx).
  const sendForApproval = async () => {
    if (!id) return;
    setSendingApproval(true);
    try {
      await apiRequestApproval(id, approvalMessage.trim() || undefined);
      const fresh = await apiGetEvent(id);
      setItem(fresh);
      setShowApprovalForm(false);
      setApprovalMessage('');
    } catch (e: any) {
      setLoadError(e?.message || 'Could not send for approval');
    } finally {
      setSendingApproval(false);
    }
  };

  const openTimelineEdit = () => {
    if (!item) return;
    const t = item.timeline;
    setTimelineDraft({
      planned_start: t.planned_start || '', planned_finish: t.planned_finish || '',
      actual_start: t.actual_start || '', actual_finish: t.actual_finish || '',
    });
    setShowTimelineEdit(true);
  };

  const saveTimeline = async () => {
    if (!id) return;
    setSavingTimeline(true);
    try {
      // Empty strings clear a field (send null), matching the backend's
      // "None clears that field" convention for both the standalone
      // event path and the linked-workflow-activity path.
      await apiSetEventTimeline(id, {
        planned_start: timelineDraft.planned_start.trim() || null,
        planned_finish: timelineDraft.planned_finish.trim() || null,
        actual_start: timelineDraft.actual_start.trim() || null,
        actual_finish: timelineDraft.actual_finish.trim() || null,
      });
      const fresh = await apiGetEvent(id);
      setItem(fresh);
      setShowTimelineEdit(false);
    } catch (e: any) {
      setLoadError(e?.message || 'Could not save timeline');
    } finally {
      setSavingTimeline(false);
    }
  };

  // Proposal Review — same apiAcceptProposal/apiRejectProposal calls
  // Operations Center's Proposal Inbox already used; only the UI that
  // wires them moved.
  const acceptProposal = async (proposal: AiProposal) => {
    setProposalBusyId(proposal.id);
    try {
      const edit = proposalEdits[proposal.id];
      const payload: any = {};
      if (edit && edit.title.trim() !== proposal.title) payload.title = edit.title.trim();
      if (edit && edit.description !== (proposal.description || '')) payload.description = edit.description;
      if (edit && edit.priority !== proposal.suggested_priority) payload.priority = edit.priority;
      await apiAcceptProposal(proposal.id, payload);
      setProposals((prev) => prev.filter((p) => p.id !== proposal.id));
      await loadRelated();
    } catch (e: any) {
      setLoadError(e?.message || 'Could not accept proposal');
    } finally {
      setProposalBusyId(null);
    }
  };

  const rejectProposal = async (proposal: AiProposal) => {
    setProposalBusyId(proposal.id);
    try {
      await apiRejectProposal(proposal.id, 'Rejected from Event Detail');
      setProposals((prev) => prev.filter((p) => p.id !== proposal.id));
    } catch (e: any) {
      setLoadError(e?.message || 'Could not reject proposal');
    } finally {
      setProposalBusyId(null);
    }
  };

  const regenerateProposals = async () => {
    if (!id) return;
    setRegenerating(true);
    try {
      await apiRegenerateProposals(id, true);
      const props = await apiListProposals({ event_id: id });
      setProposals(props);
      const edits: typeof proposalEdits = {};
      for (const p of props) {
        edits[p.id] = { title: p.title, description: p.description || '', priority: p.suggested_priority };
      }
      setProposalEdits(edits);
    } catch (e: any) {
      setLoadError(e?.message || 'Could not regenerate proposals');
    } finally {
      setRegenerating(false);
    }
  };

  // Related Operational Items — Assignment. Same apiAssignItem the
  // Operations Center's AssignModal already calls; this is a
  // responsibility-only assign (no target timeline fields here — the
  // full Assignment Timeline UI stays on the Operations Center, this
  // section deliberately does not touch that implementation).
  const openAssignFor = async (itemId: string) => {
    if (!item) return;
    try {
      const users = await apiListUsers(undefined, item.event.project_id);
      setAssignableUsers(users);
      setAssignForItemId(itemId);
    } catch (e: any) {
      setLoadError(e?.message || 'Could not load assignable users');
    }
  };

  const doAssign = async (user: AssignableUser) => {
    if (!assignForItemId) return;
    setAssignBusy(true);
    try {
      await apiAssignItem(assignForItemId, user.id);
      setAssignForItemId(null);
      await loadRelated();
    } catch (e: any) {
      setLoadError(e?.message || 'Could not assign item');
    } finally {
      setAssignBusy(false);
    }
  };

  if (loadError && !item) {
    return (
      <SafeAreaView style={styles.safe}>
        <View style={styles.center}>
          <Ionicons name="warning" size={48} color={theme.color.error} />
          <Text style={{ color: theme.color.error, marginTop: 12, textAlign: 'center', paddingHorizontal: 24 }}>
            {loadError}
          </Text>
        </View>
      </SafeAreaView>
    );
  }

  if (!item) {
    return (
      <SafeAreaView style={styles.safe}>
        <View style={styles.center}><ActivityIndicator color={theme.color.brand} size="large" /></View>
      </SafeAreaView>
    );
  }

  const evt = item.event;
  const a = item.analysis;
  const struct = a?.structured || {};
  const urgency = (struct.urgency as string) || 'normal';
  const aiBadge = (aiUnavailable && evt.ai_status === 'pending')
    ? AI_STATUS.unavailable
    : (AI_STATUS[evt.ai_status] || AI_STATUS.pending);
  const firstPhoto = item.photo_thumbs?.[0]?.base64 || null;

  return (
    <View style={styles.safe}>
      <ScrollView contentContainerStyle={{ paddingBottom: 120 }}>
        {firstPhoto ? (
          <View style={styles.heroWrap}>
            <ExpoImage source={{ uri: `data:image/jpeg;base64,${firstPhoto}` }}
              style={styles.hero} contentFit="cover" />
            <LinearGradient
              colors={['rgba(18,18,18,0.6)', 'rgba(18,18,18,0)', 'rgba(18,18,18,0.95)']}
              style={StyleSheet.absoluteFill}
            />
            <SafeAreaView style={styles.heroBar} edges={['top']}>
              <Pressable testID="event-back" onPress={() => router.back()} style={styles.backBtn}>
                <Ionicons name="arrow-back" size={28} color="#fff" />
              </Pressable>
            </SafeAreaView>
          </View>
        ) : (
          <SafeAreaView style={styles.barNoHero} edges={['top']}>
            <Pressable testID="event-back" onPress={() => router.back()} style={styles.backBtn}>
              <Ionicons name="arrow-back" size={28} color={theme.color.text} />
            </Pressable>
          </SafeAreaView>
        )}

        <View style={styles.body}>
          <View style={styles.tagsRow}>
            <View style={[styles.typeTag, { backgroundColor: theme.color.brand }]}>
              <Text style={styles.typeTagText}>{TYPE_LABEL[struct.type || evt.kind] || 'EVENT'}</Text>
            </View>
            <View style={[styles.urgencyTag, { backgroundColor: URGENCY_COLOR[urgency] }]}>
              <Text style={styles.urgencyText}>{urgency.toUpperCase()}</Text>
            </View>
            <View style={[styles.aiTag, { borderColor: aiBadge.color }]}>
              <Ionicons name={aiBadge.icon} size={12} color={aiBadge.color} />
              <Text style={[styles.aiText, { color: aiBadge.color }]}>{aiBadge.label}</Text>
            </View>
          </View>

          {struct.title ? <Text style={styles.title}>{struct.title}</Text> : null}
          {struct.summary ? <Text style={styles.summary}>{struct.summary}</Text> : null}

          <View style={styles.metaRow}>
            <Ionicons name="person-circle" size={20} color={theme.color.textDim} />
            <Text style={styles.metaText}>{evt.user_name}</Text>
            <Text style={styles.dot}>•</Text>
            <Ionicons name="time-outline" size={18} color={theme.color.textDim} />
            <Text style={styles.metaText}>{new Date(evt.server_created_at).toLocaleString()}</Text>
            {evt.gps ? (
              <>
                <Text style={styles.dot}>•</Text>
                <Ionicons name="location" size={16} color={theme.color.textDim} />
                <Text style={styles.metaText}>{evt.gps.lat.toFixed(4)}, {evt.gps.lng.toFixed(4)}</Text>
              </>
            ) : null}
          </View>
          {a?.language_detected ? (
            <View style={styles.langTag}>
              <Ionicons name="globe-outline" size={14} color={theme.color.brand} />
              <Text style={styles.langText}>{a.language_detected}</Text>
            </View>
          ) : null}

          {/* Client Approval Workflow */}
          {viewRole && viewRole !== 'client' && (
            item.approval_status ? (
              <View style={[styles.approvalBadge, {
                borderColor: item.approval_status === 'fulfilled' ? theme.color.success
                  : item.approval_status === 'cancelled' ? theme.color.error : theme.color.brand,
              }]} testID="approval-status-badge">
                <Ionicons
                  name={item.approval_status === 'fulfilled' ? 'checkmark-circle' : item.approval_status === 'cancelled' ? 'close-circle' : 'time'}
                  size={16}
                  color={item.approval_status === 'fulfilled' ? theme.color.success : item.approval_status === 'cancelled' ? theme.color.error : theme.color.brand}
                />
                <Text style={styles.approvalBadgeText}>
                  Approval: {item.approval_status === 'fulfilled' ? 'Approved' : item.approval_status === 'cancelled' ? 'Rejected' : 'Pending'}
                </Text>
              </View>
            ) : showApprovalForm ? (
              <View style={styles.approvalForm}>
                <TextInput
                  testID="approval-message-input"
                  value={approvalMessage}
                  onChangeText={setApprovalMessage}
                  placeholder="Optional message for the client…"
                  placeholderTextColor={theme.color.textDim}
                  style={styles.approvalInput}
                  multiline
                />
                <Pressable testID="send-approval-confirm" onPress={sendForApproval} disabled={sendingApproval}
                  style={[styles.approvalSendBtn, sendingApproval && { opacity: 0.5 }]}>
                  {sendingApproval ? <ActivityIndicator size="small" color={theme.color.onBrand} /> : (
                    <Text style={styles.approvalSendBtnText}>SEND FOR APPROVAL</Text>
                  )}
                </Pressable>
              </View>
            ) : (
              <Pressable testID="send-approval-toggle" onPress={() => setShowApprovalForm(true)} style={styles.approvalRequestLink}>
                <Ionicons name="paper-plane-outline" size={16} color={theme.color.brand} />
                <Text style={styles.approvalRequestLinkText}>Send for Client Approval</Text>
              </Pressable>
            )
          )}

          {/* Timeline Planning (Canonical Event UX patch). Record Time
              (server_created_at, shown elsewhere) stays untouched;
              these are separate, editable planning fields. Reads from
              the linked workflow activity when this event has one -
              "Workflow remains the scheduling source of truth" - never
              a second, disagreeing copy. */}
          {item.timeline && (
            <Section icon="calendar-outline" title="TIMELINE PLANNING">
              {item.timeline.source === 'workflow_activity' && (
                <Text style={styles.timelineSourceNote}>
                  From linked workflow activity: {item.timeline.activity_name}
                </Text>
              )}
              {!showTimelineEdit ? (
                <>
                  <View style={styles.timelineGrid}>
                    <TimelineField label="PLANNED START" value={item.timeline.planned_start} />
                    <TimelineField label="PLANNED FINISH" value={item.timeline.planned_finish} />
                  </View>
                  <View style={styles.timelineGrid}>
                    <TimelineField label="ACTUAL START" value={item.timeline.actual_start} />
                    <TimelineField label="ACTUAL FINISH" value={item.timeline.actual_finish} />
                  </View>
                  {(viewRole === 'admin' || viewRole === 'pm') && (
                    <Pressable testID="timeline-edit-toggle" onPress={openTimelineEdit} style={styles.timelineEditLink}>
                      <Ionicons name="create-outline" size={16} color={theme.color.brand} />
                      <Text style={styles.approvalRequestLinkText}>Edit Timeline</Text>
                    </Pressable>
                  )}
                </>
              ) : (
                <View style={{ gap: theme.spacing.sm }}>
                  <TimelineInput label="Planned Start" value={timelineDraft.planned_start}
                    onChangeText={(v) => setTimelineDraft((d) => ({ ...d, planned_start: v }))} />
                  <TimelineInput label="Planned Finish" value={timelineDraft.planned_finish}
                    onChangeText={(v) => setTimelineDraft((d) => ({ ...d, planned_finish: v }))} />
                  <TimelineInput label="Actual Start" value={timelineDraft.actual_start}
                    onChangeText={(v) => setTimelineDraft((d) => ({ ...d, actual_start: v }))} />
                  <TimelineInput label="Actual Finish" value={timelineDraft.actual_finish}
                    onChangeText={(v) => setTimelineDraft((d) => ({ ...d, actual_finish: v }))} />
                  <View style={{ flexDirection: 'row', gap: theme.spacing.sm }}>
                    <Pressable testID="timeline-cancel" onPress={() => setShowTimelineEdit(false)}
                      style={[styles.approvalSendBtn, { flex: 1, backgroundColor: theme.color.surface3 }]}>
                      <Text style={[styles.approvalSendBtnText, { color: theme.color.text }]}>CANCEL</Text>
                    </Pressable>
                    <Pressable testID="timeline-save" onPress={saveTimeline} disabled={savingTimeline}
                      style={[styles.approvalSendBtn, { flex: 1 }, savingTimeline && { opacity: 0.5 }]}>
                      {savingTimeline ? <ActivityIndicator size="small" color={theme.color.onBrand} /> : (
                        <Text style={styles.approvalSendBtnText}>SAVE</Text>
                      )}
                    </Pressable>
                  </View>
                </View>
              )}
            </Section>
          )}

          {/* AI Proposal Review (Canonical Event UX patch, follow-up) —
              Management/PM only. Same accept/reject calls the
              Operations Center's Proposal Inbox already used; that
              screen now links here instead of showing its own review
              UI. Regenerate Proposals (Platform Consolidation Sprint) —
              wires the previously orphaned POST /events/{id}/
              regenerate-proposals endpoint; shown even with zero
              proposals, since that's exactly when regenerating matters
              most (AI produced nothing usable the first time). */}
          {(viewRole === 'admin' || viewRole === 'pm') && (
            <Section icon="sparkles-outline" title="AI PROPOSAL">
              <Pressable testID="event-regenerate-proposals" onPress={regenerateProposals} disabled={regenerating}
                style={[styles.approvalRequestLink, regenerating && { opacity: 0.5 }]}>
                {regenerating ? <ActivityIndicator size="small" color={theme.color.brand} /> : (
                  <Ionicons name="refresh-outline" size={16} color={theme.color.brand} />
                )}
                <Text style={styles.approvalRequestLinkText}>
                  {regenerating ? 'Regenerating…' : proposals.length > 0 ? 'Regenerate Proposals' : 'No AI proposals yet — Regenerate'}
                </Text>
              </Pressable>
              {proposals.map((p) => {
                const edit = proposalEdits[p.id] || { title: p.title, description: p.description || '', priority: p.suggested_priority };
                const busy = proposalBusyId === p.id;
                return (
                  <View key={p.id} style={styles.proposalBox} testID={`event-proposal-${p.id}`}>
                    <TextInput
                      testID={`event-proposal-title-${p.id}`}
                      value={edit.title}
                      onChangeText={(t) => setProposalEdits((prev) => ({ ...prev, [p.id]: { ...edit, title: t } }))}
                      style={styles.proposalTitleInput}
                    />
                    <TextInput
                      testID={`event-proposal-description-${p.id}`}
                      value={edit.description}
                      onChangeText={(t) => setProposalEdits((prev) => ({ ...prev, [p.id]: { ...edit, description: t } }))}
                      placeholder="Description"
                      placeholderTextColor={theme.color.textDim}
                      style={styles.proposalDescInput}
                      multiline
                    />
                    <View style={styles.prioRow}>
                      {(['low', 'normal', 'high', 'critical'] as const).map((priority) => (
                        <Pressable key={priority} testID={`event-proposal-priority-${p.id}-${priority}`}
                          onPress={() => setProposalEdits((prev) => ({ ...prev, [p.id]: { ...edit, priority } }))}
                          style={[styles.prioBtn, edit.priority === priority && { backgroundColor: theme.color.brand, borderColor: theme.color.brand }]}>
                          <Text style={[styles.prioText, edit.priority === priority && { color: theme.color.onBrand }]}>{priority.toUpperCase()}</Text>
                        </Pressable>
                      ))}
                    </View>
                    <View style={{ flexDirection: 'row', gap: theme.spacing.sm, marginTop: theme.spacing.sm }}>
                      <Pressable testID={`event-proposal-accept-${p.id}`} onPress={() => acceptProposal(p)} disabled={busy}
                        style={[styles.approvalSendBtn, { flex: 1, backgroundColor: theme.color.success }, busy && { opacity: 0.5 }]}>
                        {busy ? <ActivityIndicator size="small" color={theme.color.onBrand} /> : <Text style={styles.approvalSendBtnText}>ACCEPT</Text>}
                      </Pressable>
                      <Pressable testID={`event-proposal-reject-${p.id}`} onPress={() => rejectProposal(p)} disabled={busy}
                        style={[styles.approvalSendBtn, { flex: 1, backgroundColor: theme.color.error }, busy && { opacity: 0.5 }]}>
                        <Text style={styles.approvalSendBtnText}>REJECT</Text>
                      </Pressable>
                    </View>
                  </View>
                );
              })}
            </Section>
          )}

          {/* Related Operational Items (Canonical Event UX patch,
              follow-up) — view for everyone with page access; Assign is
              Management/PM only. Links to the existing Operational
              Item detail page rather than duplicating its UI. */}
          {relatedItems.length > 0 && (
            <Section icon="link-outline" title="RELATED OPERATIONAL ITEMS">
              {relatedItems.map((ri) => (
                <View key={ri.id} style={styles.relatedItemRow} testID={`event-related-item-${ri.id}`}>
                  <Pressable style={{ flex: 1 }} onPress={() => router.push(`/op/${ri.id}`)}>
                    <Text style={styles.relatedItemTitle} numberOfLines={1}>{ri.title}</Text>
                    <Text style={styles.relatedItemMeta}>
                      {ri.category.replace(/_/g, ' ')} · {ri.status.toUpperCase()}
                      {ri.assigned_to_user_name ? ` · ${ri.assigned_to_user_name}` : ''}
                    </Text>
                  </Pressable>
                  {(viewRole === 'admin' || viewRole === 'pm') && (
                    <Pressable testID={`event-related-item-assign-${ri.id}`} onPress={() => openAssignFor(ri.id)} style={styles.relatedItemAssignBtn}>
                      <Ionicons name="person-add-outline" size={16} color={theme.color.brand} />
                    </Pressable>
                  )}
                  <Ionicons name="chevron-forward" size={18} color={theme.color.textDim} />
                </View>
              ))}
            </Section>
          )}

          {a?.transcript ? (
            <Section icon="mic" title="TRANSCRIPT">
              <Text style={styles.transcript}>{a.transcript}</Text>
            </Section>
          ) : null}

          {evt.text_input ? (
            <Section icon="text" title="TYPED INPUT">
              <Text style={styles.transcript}>{evt.text_input}</Text>
            </Section>
          ) : null}

          {struct.materials && struct.materials.length > 0 ? (
            <Section icon="cube" title="MATERIALS">
              <View style={styles.chipsWrap}>
                {struct.materials.map((m, i) => (
                  <View key={i} style={styles.matChip}>
                    <Text style={styles.matName}>{m.name}</Text>
                    <Text style={styles.matQty}>{m.quantity} {m.unit}</Text>
                  </View>
                ))}
              </View>
            </Section>
          ) : null}

          {struct.issues && struct.issues.length > 0 ? (
            <Section icon="warning" title="ISSUES" color={theme.color.error}>
              {struct.issues.map((it, i) => (
                <View key={i} style={styles.bullet}>
                  <View style={[styles.dotMark, { backgroundColor: theme.color.error }]} />
                  <Text style={styles.bulletText}>{it}</Text>
                </View>
              ))}
            </Section>
          ) : null}

          {struct.work_done && struct.work_done.length > 0 ? (
            <Section icon="checkmark-done" title="WORK DONE" color={theme.color.success}>
              {struct.work_done.map((it, i) => (
                <View key={i} style={styles.bullet}>
                  <View style={[styles.dotMark, { backgroundColor: theme.color.success }]} />
                  <Text style={styles.bulletText}>{it}</Text>
                </View>
              ))}
            </Section>
          ) : null}

          {item.photo_thumbs && item.photo_thumbs.length > 1 ? (
            <Section icon="images" title="PHOTOS">
              <View style={styles.galleryRow}>
                {item.photo_thumbs.slice(1).map((p, i) => (
                  <ExpoImage key={i}
                    source={{ uri: `data:image/jpeg;base64,${p.base64}` }}
                    style={styles.galleryThumb} contentFit="cover" />
                ))}
              </View>
            </Section>
          ) : null}

          {/* EVIDENCE — every AI conclusion is explainable */}
          {a?.evidence && a.evidence.length > 0 ? (
            <Section icon="document-attach" title="EVIDENCE">
              {a.evidence.map((e, i) => (
                <View key={i} style={styles.evidenceRow}>
                  <View style={styles.evidenceIcon}>
                    <Ionicons
                      name={e.kind === 'audio' ? 'mic' : e.kind === 'photo' ? 'image' : 'text'}
                      size={14} color={theme.color.brand} />
                  </View>
                  <View style={{ flex: 1 }}>
                    <Text style={styles.evidenceKind}>{e.kind.toUpperCase()}</Text>
                    {e.value ? <Text style={styles.evidenceValue} numberOfLines={2}>{e.value}</Text> : null}
                    {e.asset_id ? <Text style={styles.evidenceRef}>asset: {e.asset_id.slice(0, 16)}…</Text> : null}
                  </View>
                </View>
              ))}
              <Text style={styles.provenance}>
                Model: {a.model_versions.llm || '—'}
                {a.model_versions.stt ? ` + ${a.model_versions.stt}` : ''}
                {' · '}Prompt: {a.prompt_name} v{a.prompt_version}
              </Text>
            </Section>
          ) : null}

          {item.corrections && item.corrections.length > 0 ? (
            <Section icon="create" title="CORRECTIONS">
              {item.corrections.map((c) => (
                <View key={c.id} style={styles.correction}>
                  <Text style={styles.correctionBy}>
                    {c.corrected_by_user_name} · {new Date(c.created_at).toLocaleString()}
                  </Text>
                  <Text style={styles.correctionNote}>{c.payload.note}</Text>
                </View>
              ))}
            </Section>
          ) : null}

          {evt.ai_status === 'failed' && a?.error ? (
            <Section icon="warning" title="AI ERROR" color={theme.color.error}>
              <Text style={styles.errorText}>{a.error}</Text>
              <Text style={styles.errorHint}>The event itself is safely stored. AI can be retried later.</Text>
            </Section>
          ) : null}

          {aiUnavailable && evt.ai_status === 'pending' ? (
            <Section icon="cloud-offline" title="AI UNAVAILABLE" color={theme.color.textDim}>
              <Text style={styles.errorHint}>
                AI processing is not configured on this server. Your event, photos, and text are
                safely stored and already appear in the timeline and operational history — nothing
                is blocked. AI analysis will run automatically once it's configured.
              </Text>
            </Section>
          ) : null}
        </View>
      </ScrollView>

      <View style={styles.footer}>
        <Pressable testID="event-close-bottom" onPress={() => router.back()} style={styles.closeBtn}>
          <Ionicons name="checkmark" size={28} color={theme.color.onBrand} />
          <Text style={styles.closeBtnText}>BACK TO TIMELINE</Text>
        </Pressable>
      </View>

      {/* Assignment (Canonical Event UX patch, follow-up) — Assign
          Operational Item without leaving the Event. */}
      <Modal visible={!!assignForItemId} animationType="fade" transparent>
        <Pressable style={styles.modalBack} onPress={() => setAssignForItemId(null)}>
          <View style={styles.assignModal} onStartShouldSetResponder={() => true}>
            <Text style={styles.approvalRequestLinkText}>ASSIGN TO</Text>
            <ScrollView style={{ maxHeight: 320, marginTop: theme.spacing.sm }}>
              {assignableUsers.length === 0 ? (
                <Text style={{ color: theme.color.textDim, fontSize: 13 }}>No eligible users found</Text>
              ) : assignableUsers.map((u) => (
                <Pressable key={u.id} testID={`event-assign-pick-${u.id}`} onPress={() => doAssign(u)}
                  disabled={assignBusy} style={styles.assignPickRow}>
                  <Ionicons name="person-circle-outline" size={20} color={theme.color.textMuted} />
                  <Text style={styles.relatedItemTitle}>{u.name}</Text>
                  <Text style={styles.relatedItemMeta}>{u.role.replace(/_/g, ' ')}</Text>
                </Pressable>
              ))}
            </ScrollView>
          </View>
        </Pressable>
      </Modal>
    </View>
  );
}

function Section({ icon, title, color, children }: any) {
  return (
    <View style={styles.section}>
      <View style={styles.sectionHead}>
        <Ionicons name={icon} size={18} color={color || theme.color.brand} />
        <Text style={[styles.sectionTitle, color && { color }]}>{title}</Text>
      </View>
      {children}
    </View>
  );
}

function TimelineField({ label, value }: { label: string; value: string | null }) {
  const formatted = value ? new Date(value).toLocaleDateString(undefined, { year: 'numeric', month: 'short', day: 'numeric' }) : '—';
  return (
    <View style={{ flex: 1 }}>
      <Text style={styles.timelineFieldLabel}>{label}</Text>
      <Text style={styles.timelineFieldValue}>{formatted}</Text>
    </View>
  );
}

function TimelineInput({ label, value, onChangeText }: { label: string; value: string; onChangeText: (v: string) => void }) {
  return (
    <View>
      <Text style={styles.timelineFieldLabel}>{label}</Text>
      <TextInput
        testID={`timeline-input-${label.toLowerCase().replace(/\s+/g, '-')}`}
        value={value}
        onChangeText={onChangeText}
        placeholder="YYYY-MM-DD (blank to clear)"
        placeholderTextColor={theme.color.textDim}
        style={styles.timelineInput}
      />
    </View>
  );
}

const styles = StyleSheet.create({
  safe: { flex: 1, backgroundColor: theme.color.surface },
  center: { flex: 1, alignItems: 'center', justifyContent: 'center' },
  heroWrap: { width: '100%', height: 280, position: 'relative' },
  hero: { width: '100%', height: '100%' },
  heroBar: { paddingHorizontal: theme.spacing.md },
  barNoHero: { paddingHorizontal: theme.spacing.md, paddingVertical: theme.spacing.sm, backgroundColor: theme.color.surface },
  backBtn: {
    width: 48, height: 48, borderRadius: 24, backgroundColor: 'rgba(0,0,0,0.5)',
    alignItems: 'center', justifyContent: 'center', marginTop: theme.spacing.sm,
  },
  body: { padding: theme.spacing.lg, gap: theme.spacing.md },
  tagsRow: { flexDirection: 'row', gap: theme.spacing.sm, flexWrap: 'wrap' },
  typeTag: { paddingHorizontal: 12, paddingVertical: 6, borderRadius: theme.radius.sm },
  typeTagText: { color: '#fff', fontSize: 11, fontWeight: '900', letterSpacing: 1 },
  urgencyTag: { paddingHorizontal: 12, paddingVertical: 6, borderRadius: theme.radius.sm },
  urgencyText: { color: '#fff', fontSize: 11, fontWeight: '900', letterSpacing: 1 },
  aiTag: { flexDirection: 'row', alignItems: 'center', gap: 4, paddingHorizontal: 10, paddingVertical: 5, borderRadius: theme.radius.sm, borderWidth: 1 },
  aiText: { fontSize: 11, fontWeight: '900', letterSpacing: 1 },
  title: { color: theme.color.text, fontSize: 26, fontWeight: '900', letterSpacing: 0.5 },
  summary: { color: theme.color.textMuted, fontSize: 17, lineHeight: 26 },
  metaRow: { flexDirection: 'row', alignItems: 'center', gap: 4, flexWrap: 'wrap' },
  metaText: { color: theme.color.textDim, fontSize: 13, fontWeight: '600' },
  dot: { color: theme.color.textDim, marginHorizontal: 4 },
  langTag: {
    alignSelf: 'flex-start', flexDirection: 'row', alignItems: 'center', gap: 4,
    backgroundColor: theme.color.brandTint || '#3E1800', borderRadius: theme.radius.sm,
    paddingHorizontal: 10, paddingVertical: 4,
  },
  langText: { color: theme.color.brand, fontSize: 12, fontWeight: '800', letterSpacing: 1 },
  approvalBadge: {
    flexDirection: 'row', alignItems: 'center', gap: 6, alignSelf: 'flex-start',
    borderWidth: 1, borderRadius: theme.radius.sm, paddingHorizontal: 10, paddingVertical: 6, marginTop: 10,
  },
  approvalBadgeText: { color: theme.color.text, fontSize: 13, fontWeight: '700' },
  approvalRequestLink: { flexDirection: 'row', alignItems: 'center', gap: 6, marginTop: 10 },
  approvalRequestLinkText: { color: theme.color.brand, fontSize: 14, fontWeight: '700' },
  approvalForm: { marginTop: 10, gap: 8 },
  approvalInput: {
    color: theme.color.text, backgroundColor: theme.color.surface2, borderRadius: theme.radius.sm,
    borderWidth: 1, borderColor: theme.color.border, padding: 10, minHeight: 44, fontSize: 14,
  },
  approvalSendBtn: {
    backgroundColor: theme.color.brand, borderRadius: theme.radius.sm, paddingVertical: 10,
    alignItems: 'center', justifyContent: 'center',
  },
  approvalSendBtnText: { color: theme.color.onBrand, fontSize: 13, fontWeight: '800', letterSpacing: 0.5 },
  timelineSourceNote: { color: theme.color.textDim, fontSize: 12, fontStyle: 'italic', marginBottom: 8 },
  timelineGrid: { flexDirection: 'row', gap: theme.spacing.md, marginBottom: 10 },
  timelineFieldLabel: { color: theme.color.textDim, fontSize: 10, fontWeight: '800', letterSpacing: 0.5, marginBottom: 2 },
  timelineFieldValue: { color: theme.color.text, fontSize: 14, fontWeight: '700' },
  timelineEditLink: { flexDirection: 'row', alignItems: 'center', gap: 6, marginTop: 4 },
  timelineInput: {
    color: theme.color.text, backgroundColor: theme.color.surface2, borderRadius: theme.radius.sm,
    borderWidth: 1, borderColor: theme.color.border, padding: 10, fontSize: 14,
  },
  proposalBox: {
    backgroundColor: theme.color.surface3, borderRadius: theme.radius.sm, padding: theme.spacing.sm,
    marginBottom: theme.spacing.sm, gap: 8,
  },
  proposalTitleInput: { color: theme.color.text, fontSize: 15, fontWeight: '700', padding: 0 },
  proposalDescInput: { color: theme.color.textMuted, fontSize: 13, padding: 0, minHeight: 40 },
  prioRow: { flexDirection: 'row', gap: 6 },
  prioBtn: {
    flex: 1, borderWidth: 1, borderColor: theme.color.border, borderRadius: theme.radius.sm,
    paddingVertical: 6, alignItems: 'center',
  },
  prioText: { color: theme.color.textMuted, fontSize: 10, fontWeight: '800' },
  relatedItemRow: {
    flexDirection: 'row', alignItems: 'center', gap: 8, paddingVertical: 8,
    borderBottomWidth: 1, borderBottomColor: theme.color.border,
  },
  relatedItemTitle: { color: theme.color.text, fontSize: 14, fontWeight: '700' },
  relatedItemMeta: { color: theme.color.textDim, fontSize: 12, marginTop: 2 },
  relatedItemAssignBtn: {
    width: 32, height: 32, borderRadius: 16, backgroundColor: theme.color.surface3,
    alignItems: 'center', justifyContent: 'center',
  },
  modalBack: { flex: 1, backgroundColor: 'rgba(0,0,0,0.6)', justifyContent: 'flex-end' },
  assignModal: {
    backgroundColor: theme.color.surface2, borderTopLeftRadius: theme.radius.lg, borderTopRightRadius: theme.radius.lg,
    padding: theme.spacing.md, maxHeight: '70%',
  },
  assignPickRow: { flexDirection: 'row', alignItems: 'center', gap: 10, paddingVertical: 10 },
  section: {
    marginTop: theme.spacing.sm, padding: theme.spacing.md, borderRadius: theme.radius.md,
    backgroundColor: theme.color.surface2, borderWidth: 1, borderColor: theme.color.border, gap: theme.spacing.sm,
  },
  sectionHead: { flexDirection: 'row', alignItems: 'center', gap: 8 },
  sectionTitle: { color: theme.color.brand, fontSize: 13, fontWeight: '900', letterSpacing: 2 },
  transcript: { color: theme.color.text, fontSize: 16, lineHeight: 24 },
  chipsWrap: { flexDirection: 'row', flexWrap: 'wrap', gap: 8 },
  matChip: {
    backgroundColor: theme.color.surface3, paddingHorizontal: theme.spacing.md, paddingVertical: 10,
    borderRadius: theme.radius.md, gap: 2,
  },
  matName: { color: theme.color.text, fontSize: 15, fontWeight: '800' },
  matQty: { color: theme.color.brand, fontSize: 13, fontWeight: '700' },
  bullet: { flexDirection: 'row', alignItems: 'flex-start', gap: 10 },
  dotMark: { width: 8, height: 8, borderRadius: 4, marginTop: 8 },
  bulletText: { color: theme.color.text, fontSize: 16, flex: 1, lineHeight: 24 },
  galleryRow: { flexDirection: 'row', gap: 8, flexWrap: 'wrap' },
  galleryThumb: { width: 100, height: 100, borderRadius: theme.radius.sm },
  evidenceRow: {
    flexDirection: 'row', alignItems: 'flex-start', gap: 10,
    backgroundColor: theme.color.surface3, padding: 10, borderRadius: theme.radius.sm,
  },
  evidenceIcon: {
    width: 28, height: 28, borderRadius: 14, backgroundColor: theme.color.surface2,
    alignItems: 'center', justifyContent: 'center',
  },
  evidenceKind: { color: theme.color.brand, fontSize: 11, fontWeight: '900', letterSpacing: 1 },
  evidenceValue: { color: theme.color.text, fontSize: 13, marginTop: 2 },
  evidenceRef: { color: theme.color.textDim, fontSize: 11, fontFamily: 'monospace', marginTop: 2 },
  provenance: { color: theme.color.textDim, fontSize: 11, fontStyle: 'italic', marginTop: 4 },
  correction: { padding: 10, backgroundColor: theme.color.surface3, borderRadius: theme.radius.sm, gap: 4 },
  correctionBy: { color: theme.color.textDim, fontSize: 11, fontWeight: '700' },
  correctionNote: { color: theme.color.text, fontSize: 14 },
  errorText: { color: theme.color.error, fontSize: 13, fontFamily: 'monospace' },
  errorHint: { color: theme.color.textMuted, fontSize: 13, marginTop: 4 },
  footer: {
    position: 'absolute', left: 0, right: 0, bottom: 0, padding: theme.spacing.md,
    backgroundColor: theme.color.surface, borderTopWidth: 1, borderTopColor: theme.color.border,
  },
  closeBtn: {
    height: 64, borderRadius: theme.radius.md, backgroundColor: theme.color.brand,
    flexDirection: 'row', alignItems: 'center', justifyContent: 'center', gap: theme.spacing.sm,
  },
  closeBtnText: { color: theme.color.onBrand, fontSize: 18, fontWeight: '900', letterSpacing: 2 },
});
