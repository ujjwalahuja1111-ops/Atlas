import { useEffect, useRef, useState } from 'react';
import { View, Text, StyleSheet, ScrollView, Pressable, ActivityIndicator, TextInput } from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import { Image as ExpoImage } from 'expo-image';
import { LinearGradient } from 'expo-linear-gradient';
import { Ionicons } from '@expo/vector-icons';
import { useLocalSearchParams, useRouter } from 'expo-router';
import { theme } from '@/src/theme';
import { apiGetEvent, apiGetPlatformStatus, apiRequestApproval, apiSetEventTimeline, type TimelineItem } from '@/src/api';
import { getViewRole, type ViewRole } from '@/src/roles';

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
  // Timeline Planning (Canonical Event UX patch) — Record Time stays
  // immutable; this is separate, editable planning info.
  const [showTimelineEdit, setShowTimelineEdit] = useState(false);
  const [timelineDraft, setTimelineDraft] = useState({ planned_start: '', planned_finish: '', actual_start: '', actual_finish: '' });
  const [savingTimeline, setSavingTimeline] = useState(false);
  useEffect(() => { getViewRole().then(setViewRole); }, []);
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
