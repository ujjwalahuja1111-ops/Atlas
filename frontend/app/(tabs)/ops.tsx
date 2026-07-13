import { useCallback, useState, type Dispatch, type SetStateAction } from 'react';
import {
  View, Text, StyleSheet, FlatList, Pressable, ScrollView,
  ActivityIndicator, RefreshControl, Modal, TextInput, KeyboardAvoidingView, Platform,
} from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import { Ionicons } from '@expo/vector-icons';
import { useRouter, useFocusEffect } from 'expo-router';
import { theme } from '@/src/theme';
import { loadAuth, type User } from '@/src/api';
import { getViewRole, VIEW_PERMS, type ViewRole } from '@/src/roles';
import {
  apiOperationalCenter, apiListItems, apiListUsers, apiAssignItem,
  apiListProposals, apiAcceptProposal, apiRejectProposal,
  type OperationalCenter, type OperationalItem, type AssignableUser, type AiProposal,
} from '@/src/ops_api';

const HEALTH_COLOR: Record<string, string> = {
  on_track: theme.color.success, due_soon: theme.color.warning,
  overdue: theme.color.error, blocked: '#9C27B0',
  waiting_external: theme.color.info, completed: theme.color.textDim,
};
const STATUS_LABEL: Record<string, string> = {
  open: 'OPEN', assigned: 'ASSIGNED', acknowledged: 'ACK',
  in_progress: 'IN PROGRESS', fulfilled: 'FULFILLED',
  verified: 'VERIFIED', closed: 'CLOSED', reopened: 'REOPENED',
  archived: 'ARCHIVED', cancelled: 'CANCELLED', duplicate: 'DUPLICATE',
};
const PRIORITY_COLOR: Record<string, string> = {
  low: theme.color.textDim, normal: theme.color.info,
  high: theme.color.warning, critical: theme.color.error,
};

const TABS = ['proposals', 'overview', 'overdue', 'high_priority', 'awaiting', 'mine'] as const;
type Bucket = typeof TABS[number];
type ProposalEdit = {
  title: string;
  description: string;
  priority: AiProposal['suggested_priority'];
  assigned_to_user_id: string;
};

export default function OpsScreen() {
  const router = useRouter();
  const [user, setUser] = useState<User | null>(null);
  const [viewRole, setVR] = useState<ViewRole>('supervisor');
  const [center, setCenter] = useState<OperationalCenter | null>(null);
  const [mine, setMine] = useState<OperationalItem[]>([]);
  const [proposals, setProposals] = useState<AiProposal[]>([]);
  const [bucket, setBucket] = useState<Bucket>('proposals');
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [assigningItem, setAssigningItem] = useState<OperationalItem | null>(null);
  const [reviewingProposal, setReviewingProposal] = useState<AiProposal | null>(null);
  const [proposalEdit, setProposalEdit] = useState<ProposalEdit>({
    title: '', description: '', priority: 'normal', assigned_to_user_id: '',
  });
  const [proposalBusyId, setProposalBusyId] = useState<string | null>(null);
  const [users, setUsers] = useState<AssignableUser[]>([]);
  const [loadError, setLoadError] = useState<string | null>(null);

  const loadUsers = useCallback(async () => {
    if (users.length > 0) return users;
    const list = await apiListUsers();
    setUsers(list);
    return list;
  }, [users]);

  const load = useCallback(async () => {
    setLoadError(null);
    try {
      const auth = await loadAuth();
      setUser(auth.user);
      const vr = await getViewRole();
      setVR(vr);
      const p = VIEW_PERMS[vr];
      const [c, m, prList] = await Promise.all([
        p.showOpsBuckets ? apiOperationalCenter() : Promise.resolve(null),
        p.onlyMyItems && auth.user
          ? apiListItems({ assigned_to_me: true })
          : (p.showAssignments && auth.user
              ? apiListItems({ assigned_to_me: true })
              : Promise.resolve([])),
        p.showProposals ? apiListProposals({ status: 'pending' }) : Promise.resolve([]),
      ]);
      setCenter(c);
      // supervisor: also constrain to site_issue if you want a pure "Issues" view — leave general list too
      setMine(m);
      // client: filter proposals to allowed category
      const filteredProps = p.proposalCategoryFilter
        ? prList.filter((x) => x.category === p.proposalCategoryFilter)
        : prList;
      setProposals(filteredProps);
      // pick default bucket per role
      if (!p.showOpsBuckets && !p.showProposals) setBucket('mine');
      else if (!p.showOpsBuckets && p.showProposals) setBucket('proposals');
      else if (bucket === 'proposals' && !p.showProposals) setBucket('mine');
    } catch (e: any) {
      // Sprint 4.1 fix (audit H4): surface load failures instead of
      // silently swallowing them — a failed load used to be visually
      // indistinguishable from "there's genuinely nothing here."
      console.warn(e);
      setLoadError(e?.message || 'Could not load Operations. Pull to retry.');
    }
    finally { setLoading(false); setRefreshing(false); }
  }, [bucket]);

  useFocusEffect(useCallback(() => { load(); }, [load]));

  const dataForBucket = (): OperationalItem[] => {
    // FOUNDER SPRINT — Operational Assignment fix: 'mine' (and any future
    // bucket backed by its own fetch rather than the operational-center
    // summary) must NOT depend on `center` being loaded. Supervisors have
    // showOpsBuckets=false, so `center` is never fetched for them at all
    // (see load() above) - it is always null. The previous ordering here
    // returned [] unconditionally whenever center was null, BEFORE ever
    // checking bucket==='mine', which discarded a supervisor's correctly-
    // fetched assigned items at render time on every single load. This
    // was the actual root cause of "assigned items are not visible" -
    // the assignment itself, the API response, and the fetch call were
    // all already correct; only this render-time check was wrong.
    if (bucket === 'mine') return mine;
    if (!center) return [];
    if (bucket === 'overview') return center.recently_updated;
    if (bucket === 'overdue') return center.overdue;
    if (bucket === 'high_priority') return center.high_priority;
    if (bucket === 'awaiting') return center.awaiting_verification;
    return [];
  };

  const openAssign = async (item: OperationalItem) => {
    try { await loadUsers(); } catch {}
    setAssigningItem(item);
  };

  const openProposalReview = async (proposal: AiProposal) => {
    try { await loadUsers(); } catch {}
    setProposalEdit({
      title: proposal.title,
      description: proposal.description || '',
      priority: proposal.suggested_priority || 'normal',
      assigned_to_user_id: '',
    });
    setReviewingProposal(proposal);
  };

  const acceptProposal = async (proposal: AiProposal) => {
    setProposalBusyId(proposal.id);
    try {
      const payload: any = {};
      if (proposalEdit.title.trim() !== proposal.title) payload.title = proposalEdit.title.trim();
      if (proposalEdit.description !== (proposal.description || '')) payload.description = proposalEdit.description;
      if (proposalEdit.priority !== proposal.suggested_priority) payload.priority = proposalEdit.priority;
      if (proposalEdit.assigned_to_user_id) payload.assigned_to_user_id = proposalEdit.assigned_to_user_id;
      await apiAcceptProposal(proposal.id, payload);
      setReviewingProposal(null);
      setBucket('overview');
      await load();
    } catch (e) { console.warn(e); }
    finally { setProposalBusyId(null); }
  };

  const rejectProposal = async (proposal: AiProposal) => {
    setProposalBusyId(proposal.id);
    try {
      await apiRejectProposal(proposal.id, 'Rejected from Proposal Inbox');
      if (reviewingProposal?.id === proposal.id) setReviewingProposal(null);
      await load();
    } catch (e) { console.warn(e); }
    finally { setProposalBusyId(null); }
  };

  const perms = VIEW_PERMS[viewRole];

  return (
    <SafeAreaView style={styles.safe} edges={['top']}>
      <View style={styles.header}>
        <Text style={styles.h1}>OPS</Text>
        <Text style={styles.h2}>{viewRole === 'supervisor' ? 'My Tasks' : 'Operational Center'}</Text>
      </View>

      {loading ? (
        <View style={styles.center}><ActivityIndicator color={theme.color.brand} size="large" /></View>
      ) : (
        <>
          {loadError && (
            <Pressable testID="ops-load-error" onPress={() => { setLoading(true); load(); }} style={styles.errorBanner}>
              <Ionicons name="warning" size={16} color={theme.color.error} />
              <Text style={styles.errorBannerText} numberOfLines={2}>{loadError} Tap to retry.</Text>
            </Pressable>
          )}
          {/* Sprint 4.1 fix (audit C1): this used to gate on `loading || !center`,
              but `center` is only ever fetched for roles with showOpsBuckets=true
              (see load() above) — for supervisor/client it was permanently null,
              so the entire screen below (including their own `mine`/`proposals`
              list) never rendered. KPIs + the multi-bucket tab strip are
              dashboard furniture that only makes sense when center data
              exists; supervisor/client go straight to their single list. */}
          {perms.showOpsBuckets && center && (
            <>
              <View style={styles.kpiRow}>
                {perms.showProposals ? (
                  <Kpi label="PROPOSALS" value={proposals.length} color={theme.color.info} testID="kpi-proposals" />
                ) : null}
                <Kpi label="OPEN" value={center.counts.open} color={theme.color.brand} testID="kpi-open" />
                <Kpi label="OVERDUE" value={center.counts.overdue} color={theme.color.error} testID="kpi-overdue" />
                <Kpi label="HIGH" value={center.counts.high_priority} color={theme.color.warning} testID="kpi-high" />
                <Kpi label="VERIFY" value={center.counts.awaiting_verification} color={theme.color.info} testID="kpi-verify" />
              </View>

              <View style={styles.chipsContainer}>
                <ScrollView horizontal showsHorizontalScrollIndicator={false} contentContainerStyle={styles.chipsContent}>
                  {TABS.filter((b) => perms.showProposals || b !== 'proposals').map((b) => {
                    const active = b === bucket;
                    return (
                      <Pressable
                        key={b}
                        testID={`bucket-${b}`}
                        onPress={() => setBucket(b)}
                        style={[styles.chip, active && styles.chipActive]}
                      >
                        <Text style={[styles.chipText, active && styles.chipTextActive]}>
                          {b === 'proposals' ? `PROPOSALS ${proposals.length}` :
                           b === 'overview' ? 'RECENT' : b === 'high_priority' ? 'HIGH' :
                           b === 'awaiting' ? 'TO VERIFY' : b === 'mine' ? 'MINE' : b.toUpperCase()}
                        </Text>
                      </Pressable>
                    );
                  })}
                </ScrollView>
              </View>
            </>
          )}

          {bucket === 'proposals' ? (
            <FlatList
              testID="proposal-inbox-list"
              data={proposals}
              keyExtractor={(i) => i.id}
              renderItem={({ item }) => (
                <ProposalCard
                  proposal={item}
                  busy={proposalBusyId === item.id}
                  onReview={() => openProposalReview(item)}
                  onReject={() => rejectProposal(item)}
                />
              )}
              ListEmptyComponent={
                <View style={styles.empty}>
                  <Ionicons name="sparkles" size={64} color={theme.color.brand} />
                  <Text style={styles.emptyTitle}>No pending proposals</Text>
                  <Text style={styles.emptyBody}>New AI proposals will appear here after capture analysis.</Text>
                </View>
              }
              contentContainerStyle={{ padding: theme.spacing.md, paddingBottom: 140 }}
              refreshControl={
                <RefreshControl refreshing={refreshing} tintColor={theme.color.brand}
                  onRefresh={() => { setRefreshing(true); load(); }} />
              }
            />
          ) : (
            <FlatList
              testID="ops-list"
              data={dataForBucket()}
              keyExtractor={(i) => i.id}
              renderItem={({ item }) => (
                <OperationalCard item={item} openAssign={openAssign}
                  openDetail={() => router.push(`/op/${item.id}`)} />
              )}
              ListEmptyComponent={
                <View style={styles.empty}>
                  <Ionicons name="checkmark-done-circle" size={64} color={theme.color.brand} />
                  <Text style={styles.emptyTitle}>Nothing here</Text>
                  <Text style={styles.emptyBody}>
                    {bucket === 'mine' ? 'No items assigned to you.' : 'No items in this view.'}
                  </Text>
                </View>
              }
              contentContainerStyle={{ padding: theme.spacing.md, paddingBottom: 140 }}
              refreshControl={
                <RefreshControl refreshing={refreshing} tintColor={theme.color.brand}
                  onRefresh={() => { setRefreshing(true); load(); }} />
              }
            />
          )}
        </>
      )}

      <ProposalReviewModal
        proposal={reviewingProposal}
        edit={proposalEdit}
        setEdit={setProposalEdit}
        users={users}
        busy={!!reviewingProposal && proposalBusyId === reviewingProposal.id}
        close={() => setReviewingProposal(null)}
        accept={() => reviewingProposal && acceptProposal(reviewingProposal)}
        reject={() => reviewingProposal && rejectProposal(reviewingProposal)}
      />

      <AssignModal
        item={assigningItem}
        users={users}
        close={() => setAssigningItem(null)}
        assign={async (u) => {
          const item = assigningItem;
          setAssigningItem(null);
          if (!item) return;
          try { await apiAssignItem(item.id, u.id); await load(); } catch (e) { console.warn(e); }
        }}
      />
    </SafeAreaView>
  );
}

function OperationalCard({ item, openAssign, openDetail }: {
  item: OperationalItem;
  openAssign: (item: OperationalItem) => void; openDetail: () => void;
}) {
  return (
    <Pressable testID={`ops-card-${item.id}`} onPress={openDetail} style={styles.card}>
      {(item.project_name || item.site_name) ? (
        <View style={styles.scopeChipRow}>
          <Ionicons name="location" size={11} color={theme.color.brand} />
          <Text style={styles.scopeChipText} numberOfLines={1}>
            {[item.project_name, item.site_name].filter(Boolean).join(' · ')}
          </Text>
        </View>
      ) : null}
      <View style={styles.row}>
        <View style={[styles.healthDot, { backgroundColor: HEALTH_COLOR[item.health] }]} />
        <Text style={styles.title} numberOfLines={2}>{item.title}</Text>
      </View>
      <View style={styles.summary}>
        <SummaryRow icon="help-circle" label="Why" value={
          item.origin_type === 'ai_proposal' ? 'AI-detected from voice/photo' :
          item.origin_type === 'manual' ? 'Manually created' : item.origin_type
        } />
        <SummaryRow icon="cube-outline" label="What"
          value={item.category.replace(/_/g, ' ').replace(/\b\w/g, (l) => l.toUpperCase())} />
        <SummaryRow icon="person" label="Who"
          value={item.assigned_to_user_name || (item.suggested_owner_role
            ? `suggest ${item.suggested_owner_role.replace(/_/g, ' ')}` : 'unassigned')} />
        <SummaryRow icon="time-outline" label="When"
          value={item.required_by ? new Date(item.required_by).toLocaleDateString()
            : (item.metrics.current_age_hours !== null ? `${Math.round(item.metrics.current_age_hours)}h old` : '-')} />
        <SummaryRow icon="alert-circle" label="Blocker"
          value={item.blocker ? humanBlocker(item.blocker.category) : 'none'} />
      </View>
      <View style={styles.tagsRow}>
        <Tag color={PRIORITY_COLOR[item.priority]}>{item.priority.toUpperCase()}</Tag>
        <Tag color={HEALTH_COLOR[item.health]}>{item.health.replace('_', ' ').toUpperCase()}</Tag>
        <Tag color={theme.color.surface3} dim>{STATUS_LABEL[item.status] || item.status.toUpperCase()}</Tag>
        {item.metrics.days_overdue > 0 ? (
          <Tag color={theme.color.error}>{`${item.metrics.days_overdue}d OVERDUE`}</Tag>
        ) : null}
        <View style={{ flex: 1 }} />
        <Pressable testID={`card-assign-${item.id}`}
          onPress={(e) => { e.stopPropagation?.(); openAssign(item); }}
          style={styles.cardAssign}>
          <Ionicons name={item.assigned_to_user_id ? 'swap-horizontal' : 'person-add'} size={14} color={theme.color.info} />
          <Text style={styles.cardAssignText}>
            {item.assigned_to_user_id ? 'REASSIGN' : 'ASSIGN'}
          </Text>
        </Pressable>
      </View>
    </Pressable>
  );
}

function ProposalCard({ proposal, busy, onReview, onReject }: {
  proposal: AiProposal; busy: boolean; onReview: () => void; onReject: () => void;
}) {
  return (
    <Pressable testID={`proposal-card-${proposal.id}`} onPress={onReview} style={styles.card}>
      {(proposal.project_name || proposal.site_name) ? (
        <View style={styles.scopeChipRow}>
          <Ionicons name="location" size={11} color={theme.color.brand} />
          <Text style={styles.scopeChipText} numberOfLines={1}>
            {[proposal.project_name, proposal.site_name].filter(Boolean).join(' · ')}
          </Text>
        </View>
      ) : null}
      <View style={styles.row}>
        <View style={[styles.healthDot, { backgroundColor: PRIORITY_COLOR[proposal.suggested_priority] }]} />
        <Text style={styles.title} numberOfLines={2}>{proposal.title}</Text>
      </View>
      <View style={styles.summary}>
        <SummaryRow icon="cube-outline" label="What"
          value={proposal.category.replace(/_/g, ' ').replace(/\b\w/g, (l) => l.toUpperCase())} />
        <SummaryRow icon="person" label="Who"
          value={proposal.suggested_owner_role ? `suggest ${proposal.suggested_owner_role.replace(/_/g, ' ')}` : 'unassigned'} />
        <SummaryRow icon="document-text-outline" label="Why"
          value={proposal.source_snippet || proposal.description || 'AI proposal'} />
      </View>
      <View style={styles.tagsRow}>
        <Tag color={PRIORITY_COLOR[proposal.suggested_priority]}>{proposal.suggested_priority.toUpperCase()}</Tag>
        <Tag color={theme.color.info}>{proposal.confidence.toUpperCase()}</Tag>
        <Tag color={theme.color.surface3} dim>PENDING</Tag>
        <View style={{ flex: 1 }} />
        <Pressable testID={`proposal-review-${proposal.id}`} onPress={onReview} disabled={busy}
          style={styles.cardAssign}>
          <Ionicons name="create-outline" size={14} color={theme.color.info} />
          <Text style={styles.cardAssignText}>REVIEW</Text>
        </Pressable>
        <Pressable testID={`proposal-reject-${proposal.id}`} onPress={onReject} disabled={busy}
          style={[styles.cardAssign, { borderColor: theme.color.error }]}>
          <Ionicons name="close" size={14} color={theme.color.error} />
          <Text style={[styles.cardAssignText, { color: theme.color.error }]}>REJECT</Text>
        </Pressable>
      </View>
    </Pressable>
  );
}

function ProposalReviewModal({ proposal, edit, setEdit, users, busy, close, accept, reject }: {
  proposal: AiProposal | null;
  edit: ProposalEdit;
  setEdit: Dispatch<SetStateAction<ProposalEdit>>;
  users: AssignableUser[];
  busy: boolean;
  close: () => void;
  accept: () => void;
  reject: () => void;
}) {
  return (
    <Modal visible={!!proposal} animationType="slide" transparent>
      <KeyboardAvoidingView style={{ flex: 1 }} behavior={Platform.OS === 'ios' ? 'padding' : undefined}>
      <View style={styles.modalBack}>
        <View style={styles.modal} onStartShouldSetResponder={() => true}>
          <View style={styles.modalHead}>
            <Text style={styles.modalTitle}>REVIEW PROPOSAL</Text>
            <Pressable testID="proposal-review-close" onPress={close}>
              <Ionicons name="close" size={24} color={theme.color.textDim} />
            </Pressable>
          </View>
          {proposal ? (
            <>
              <EditField label="Title" value={edit.title} testID="proposal-edit-title"
                onChangeText={(t: string) => setEdit((p) => ({ ...p, title: t }))} />
              <EditField label="Description" value={edit.description} testID="proposal-edit-description"
                onChangeText={(t: string) => setEdit((p) => ({ ...p, description: t }))} />
              <Text style={styles.fieldLabel}>Priority</Text>
              <View style={styles.prioRow}>
                {(['low', 'normal', 'high', 'critical'] as const).map((priority) => (
                  <Pressable key={priority} testID={`proposal-priority-${priority}`}
                    onPress={() => setEdit((p) => ({ ...p, priority }))}
                    style={[styles.prioBtn, edit.priority === priority && {
                      backgroundColor: PRIORITY_COLOR[priority], borderColor: PRIORITY_COLOR[priority],
                    }]}>
                    <Text style={[styles.prioText, edit.priority === priority && { color: '#fff' }]}>{priority.toUpperCase()}</Text>
                  </Pressable>
                ))}
              </View>
              <Text style={styles.fieldLabel}>Assign during acceptance</Text>
              <ScrollView style={{ maxHeight: 180 }}>
                <Pressable testID="proposal-assignee-none"
                  onPress={() => setEdit((p) => ({ ...p, assigned_to_user_id: '' }))}
                  style={styles.pickRow}>
                  <Ionicons name="remove-circle-outline" size={20} color={theme.color.textMuted} />
                  <Text style={styles.pickName}>Unassigned</Text>
                </Pressable>
                {users.map((u) => (
                  <Pressable key={u.id} testID={`proposal-pick-assignee-${u.id}`}
                    onPress={() => setEdit((p) => ({ ...p, assigned_to_user_id: u.id }))}
                    style={styles.pickRow}>
                    <Ionicons
                      name={edit.assigned_to_user_id === u.id ? 'checkmark-circle' : 'person-circle-outline'}
                      size={20}
                      color={edit.assigned_to_user_id === u.id ? theme.color.brand : theme.color.textMuted}
                    />
                    <Text style={styles.pickName}>{u.name}</Text>
                    <Text style={styles.pickRole}>{u.role}</Text>
                  </Pressable>
                ))}
              </ScrollView>
              <View style={styles.reviewActions}>
                <Pressable testID="proposal-reject" disabled={busy} onPress={reject}
                  style={[styles.reviewBtn, styles.rejectBtn]}>
                  <Ionicons name="close" size={18} color={theme.color.error} />
                  <Text style={[styles.reviewBtnText, { color: theme.color.error }]}>REJECT</Text>
                </Pressable>
                <Pressable testID="proposal-accept" disabled={busy || !edit.title.trim()} onPress={accept}
                  style={[styles.reviewBtn, styles.acceptBtn, (busy || !edit.title.trim()) && { opacity: 0.5 }]}>
                  <Ionicons name="checkmark" size={18} color={theme.color.onBrand} />
                  <Text style={[styles.reviewBtnText, { color: theme.color.onBrand }]}>ACCEPT</Text>
                </Pressable>
              </View>
            </>
          ) : null}
        </View>
      </View>
      </KeyboardAvoidingView>
    </Modal>
  );
}

function AssignModal({ item, users, close, assign }: {
  item: OperationalItem | null;
  users: AssignableUser[];
  close: () => void;
  assign: (u: AssignableUser) => void;
}) {
  return (
    <Modal visible={!!item} animationType="fade" transparent>
      <Pressable style={styles.modalBack} onPress={close}>
        <View style={styles.modal} onStartShouldSetResponder={() => true}>
          <Text style={styles.modalTitle}>ASSIGN TO</Text>
          <ScrollView style={{ maxHeight: 360 }}>
            {users.length === 0 ? (
              <Text style={{ color: theme.color.textDim, fontSize: 13 }}>No users available</Text>
            ) : users.map((u) => {
              const suggested = item?.suggested_owner_role &&
                (u.role === item.suggested_owner_role ||
                 item.suggested_owner_role.includes(u.role));
              return (
                <Pressable key={u.id} testID={`card-pick-assignee-${u.id}`}
                  onPress={() => assign(u)}
                  style={styles.pickRow}>
                  <Ionicons name="person-circle-outline" size={20}
                    color={suggested ? theme.color.brand : theme.color.textMuted} />
                  <Text style={styles.pickName}>{u.name}</Text>
                  <Text style={styles.pickRole}>{u.role}{suggested ? ' *' : ''}</Text>
                </Pressable>
              );
            })}
          </ScrollView>
        </View>
      </Pressable>
    </Modal>
  );
}

function Kpi({ label, value, color, testID }: any) {
  return (
    <View style={styles.kpi} testID={testID}>
      <Text style={[styles.kpiValue, { color }]}>{value}</Text>
      <Text style={styles.kpiLabel}>{label}</Text>
    </View>
  );
}

function SummaryRow({ icon, label, value }: any) {
  return (
    <View style={styles.sumRow}>
      <Ionicons name={icon} size={14} color={theme.color.brand} />
      <Text style={styles.sumLabel}>{label}:</Text>
      <Text style={styles.sumValue} numberOfLines={1}>{value}</Text>
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

function EditField({ label, value, onChangeText, testID }: any) {
  return (
    <View style={{ marginBottom: 10 }}>
      <Text style={styles.fieldLabel}>{label}</Text>
      <TextInput
        testID={testID}
        value={value}
        onChangeText={onChangeText}
        placeholderTextColor={theme.color.textDim}
        style={styles.input}
      />
    </View>
  );
}

export function humanBlocker(c: string) {
  return c.replace(/_/g, ' ').replace(/\b\w/g, (l) => l.toUpperCase());
}

const styles = StyleSheet.create({
  safe: { flex: 1, backgroundColor: theme.color.surface },
  header: { paddingHorizontal: theme.spacing.lg, paddingTop: theme.spacing.md, paddingBottom: theme.spacing.sm },
  h1: { color: theme.color.text, fontSize: 32, fontWeight: '900', letterSpacing: 2 },
  h2: { color: theme.color.brand, fontSize: 14, fontWeight: '700', marginTop: 2 },
  center: { flex: 1, alignItems: 'center', justifyContent: 'center' },
  errorBanner: {
    flexDirection: 'row', alignItems: 'center', gap: 8, marginHorizontal: theme.spacing.md,
    marginTop: theme.spacing.sm, padding: 10, borderRadius: theme.radius.sm,
    backgroundColor: theme.color.surface2, borderWidth: 1, borderColor: theme.color.error,
  },
  errorBannerText: { flex: 1, color: theme.color.error, fontSize: 12, fontWeight: '700' },
  kpiRow: { flexDirection: 'row', gap: 8, paddingHorizontal: theme.spacing.md, paddingVertical: theme.spacing.sm },
  kpi: {
    flex: 1, backgroundColor: theme.color.surface2, borderRadius: theme.radius.md,
    paddingVertical: 12, alignItems: 'center', borderWidth: 1, borderColor: theme.color.border,
  },
  kpiValue: { fontSize: 20, fontWeight: '900' },
  kpiLabel: { color: theme.color.textDim, fontSize: 9, fontWeight: '800', letterSpacing: 1, marginTop: 2 },
  chipsContainer: { height: 56 },
  chipsContent: { paddingHorizontal: theme.spacing.md, gap: 8, alignItems: 'center', height: 56 },
  chip: {
    height: 40, paddingHorizontal: theme.spacing.md, borderRadius: theme.radius.pill,
    backgroundColor: theme.color.surface2, borderWidth: 1, borderColor: theme.color.border,
    flexDirection: 'row', alignItems: 'center', flexShrink: 0,
  },
  chipActive: { backgroundColor: theme.color.brand, borderColor: theme.color.brand },
  chipText: { color: theme.color.textMuted, fontSize: 12, fontWeight: '800', letterSpacing: 1 },
  chipTextActive: { color: theme.color.onBrand },
  card: {
    backgroundColor: theme.color.surface2, padding: theme.spacing.md,
    borderRadius: theme.radius.md, marginBottom: theme.spacing.sm,
    borderWidth: 1, borderColor: theme.color.border, gap: 8,
  },
  row: { flexDirection: 'row', alignItems: 'flex-start', gap: 8 },
  healthDot: { width: 12, height: 12, borderRadius: 6, marginTop: 6 },
  title: { color: theme.color.text, fontSize: 17, fontWeight: '800', flex: 1 },
  summary: { gap: 4, marginTop: 4 },
  sumRow: { flexDirection: 'row', alignItems: 'center', gap: 6 },
  sumLabel: { color: theme.color.textDim, fontSize: 12, fontWeight: '700' },
  sumValue: { color: theme.color.text, fontSize: 13, flex: 1, fontWeight: '600' },
  tagsRow: { flexDirection: 'row', flexWrap: 'wrap', alignItems: 'center', gap: 6, marginTop: 6 },
  scopeChipRow: { flexDirection: 'row', alignItems: 'center', gap: 4, marginBottom: 6 },
  scopeChipText: { color: theme.color.brand, fontSize: 10, fontWeight: '900', letterSpacing: 1 },
  tag: { paddingHorizontal: 8, paddingVertical: 3, borderRadius: 6, borderWidth: 1 },
  tagText: { fontSize: 10, fontWeight: '900', letterSpacing: 1 },
  cardAssign: { flexDirection: 'row', alignItems: 'center', gap: 4, paddingHorizontal: 8, paddingVertical: 4,
                borderRadius: theme.radius.pill, borderWidth: 1, borderColor: theme.color.info,
                backgroundColor: theme.color.surface2 },
  cardAssignText: { color: theme.color.info, fontSize: 10, fontWeight: '900', letterSpacing: 1 },
  empty: { alignItems: 'center', padding: theme.spacing.xl, gap: theme.spacing.sm },
  emptyTitle: { color: theme.color.text, fontSize: 18, fontWeight: '900', letterSpacing: 1 },
  emptyBody: { color: theme.color.textMuted, textAlign: 'center' },
  modalBack: { flex: 1, backgroundColor: 'rgba(0,0,0,0.6)', alignItems: 'center', justifyContent: 'center', padding: 24 },
  modal: { width: '100%', maxWidth: 380, backgroundColor: theme.color.surface, padding: theme.spacing.md,
           borderRadius: theme.radius.md, borderWidth: 1, borderColor: theme.color.border },
  modalHead: { flexDirection: 'row', alignItems: 'center', marginBottom: theme.spacing.sm },
  modalTitle: { flex: 1, color: theme.color.brand, fontSize: 12, fontWeight: '900', letterSpacing: 2, marginBottom: theme.spacing.sm },
  pickRow: { flexDirection: 'row', alignItems: 'center', gap: 10, paddingVertical: 10 },
  pickName: { color: theme.color.text, fontSize: 14, fontWeight: '700' },
  pickRole: { marginLeft: 'auto', color: theme.color.textDim, fontSize: 11 },
  fieldLabel: { color: theme.color.textDim, fontSize: 11, fontWeight: '800', letterSpacing: 1, marginBottom: 4 },
  input: { color: theme.color.text, backgroundColor: theme.color.surface2,
           borderRadius: theme.radius.sm, borderWidth: 1, borderColor: theme.color.border,
           paddingHorizontal: 12, paddingVertical: 10, fontSize: 15 },
  prioRow: { flexDirection: 'row', gap: 6, marginBottom: theme.spacing.sm },
  prioBtn: { flex: 1, paddingVertical: 8, borderRadius: theme.radius.sm,
             borderWidth: 1, borderColor: theme.color.border, alignItems: 'center',
             backgroundColor: theme.color.surface2 },
  prioText: { color: theme.color.textDim, fontSize: 10, fontWeight: '900', letterSpacing: 1 },
  reviewActions: { flexDirection: 'row', gap: theme.spacing.sm, marginTop: theme.spacing.md },
  reviewBtn: { flex: 1, height: 48, borderRadius: theme.radius.md, borderWidth: 1,
               flexDirection: 'row', alignItems: 'center', justifyContent: 'center', gap: 6 },
  acceptBtn: { backgroundColor: theme.color.brand, borderColor: theme.color.brand },
  rejectBtn: { backgroundColor: theme.color.surface2, borderColor: theme.color.error },
  reviewBtnText: { fontSize: 12, fontWeight: '900', letterSpacing: 1 },
});
