import { useCallback, useEffect, useState } from 'react';
import {
  View, Text, StyleSheet, FlatList, Pressable, ScrollView,
  ActivityIndicator, RefreshControl, Modal,
} from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import { Ionicons } from '@expo/vector-icons';
import { useRouter, useFocusEffect } from 'expo-router';
import { theme } from '@/src/theme';
import { loadAuth, type User } from '@/src/api';
import {
  apiOperationalCenter, apiListItems, apiListUsers, apiAssignItem,
  type OperationalCenter, type OperationalItem, type AssignableUser,
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

const TABS = ['overview', 'overdue', 'high_priority', 'awaiting', 'mine'] as const;
type Bucket = typeof TABS[number];

export default function OpsScreen() {
  const router = useRouter();
  const [user, setUser] = useState<User | null>(null);
  const [center, setCenter] = useState<OperationalCenter | null>(null);
  const [mine, setMine] = useState<OperationalItem[]>([]);
  const [bucket, setBucket] = useState<Bucket>('overview');
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [assigningItem, setAssigningItem] = useState<OperationalItem | null>(null);
  const [users, setUsers] = useState<AssignableUser[]>([]);

  const load = useCallback(async () => {
    try {
      const { user } = await loadAuth();
      setUser(user);
      const [c, m] = await Promise.all([
        apiOperationalCenter(),
        user ? apiListItems({ assigned_to_me: true }) : Promise.resolve([]),
      ]);
      setCenter(c);
      setMine(m);
    } catch (e) { console.warn(e); }
    finally { setLoading(false); setRefreshing(false); }
  }, []);

  useFocusEffect(useCallback(() => { load(); }, [load]));

  const dataForBucket = (): OperationalItem[] => {
    if (!center) return [];
    if (bucket === 'overview') return center.recently_updated;
    if (bucket === 'overdue') return center.overdue;
    if (bucket === 'high_priority') return center.high_priority;
    if (bucket === 'awaiting') return center.awaiting_verification;
    if (bucket === 'mine') return mine;
    return [];
  };

  return (
    <SafeAreaView style={styles.safe} edges={['top']}>
      <View style={styles.header}>
        <Text style={styles.h1}>OPS</Text>
        <Text style={styles.h2}>{user?.role === 'supervisor' ? 'My Tasks' : 'Operational Center'}</Text>
      </View>

      {loading || !center ? (
        <View style={styles.center}><ActivityIndicator color={theme.color.brand} size="large" /></View>
      ) : (
        <>
          <View style={styles.kpiRow}>
            <Kpi label="OPEN" value={center.counts.open} color={theme.color.brand} testID="kpi-open" />
            <Kpi label="OVERDUE" value={center.counts.overdue} color={theme.color.error} testID="kpi-overdue" />
            <Kpi label="HIGH" value={center.counts.high_priority} color={theme.color.warning} testID="kpi-high" />
            <Kpi label="VERIFY" value={center.counts.awaiting_verification} color={theme.color.info} testID="kpi-verify" />
            <Kpi label="BLOCKED" value={center.counts.blocked} color="#9C27B0" testID="kpi-blocked" />
          </View>

          <View style={styles.chipsContainer}>
            <ScrollView horizontal showsHorizontalScrollIndicator={false} contentContainerStyle={styles.chipsContent}>
              {TABS.map((b) => {
                const active = b === bucket;
                return (
                  <Pressable
                    key={b}
                    testID={`bucket-${b}`}
                    onPress={() => setBucket(b)}
                    style={[styles.chip, active && styles.chipActive]}
                  >
                    <Text style={[styles.chipText, active && styles.chipTextActive]}>
                      {b === 'overview' ? 'RECENT' : b === 'high_priority' ? 'HIGH' :
                       b === 'awaiting' ? 'TO VERIFY' : b === 'mine' ? 'MINE' : b.toUpperCase()}
                    </Text>
                  </Pressable>
                );
              })}
            </ScrollView>
          </View>

          <FlatList
            testID="ops-list"
            data={dataForBucket()}
            keyExtractor={(i) => i.id}
            renderItem={({ item }) => (
              <Pressable
                testID={`ops-card-${item.id}`}
                onPress={() => router.push(`/op/${item.id}`)}
                style={styles.card}
              >
                <View style={styles.row}>
                  <View style={[styles.healthDot, { backgroundColor: HEALTH_COLOR[item.health] }]} />
                  <Text style={styles.title} numberOfLines={2}>{item.title}</Text>
                </View>
                {/* Three-question summary + WHEN */}
                <View style={styles.summary}>
                  <SummaryRow icon="help-circle" label="Why" value={
                    item.origin_type === 'ai_proposal' ? 'AI-detected from voice/photo' :
                    item.origin_type === 'manual' ? 'Manually created' :
                    item.origin_type
                  } />
                  <SummaryRow icon="cube-outline" label="What"
                    value={item.category.replace(/_/g, ' ').replace(/\b\w/g, (l) => l.toUpperCase())} />
                  <SummaryRow icon="person" label="Who"
                    value={item.assigned_to_user_name || (item.suggested_owner_role
                      ? `— suggest ${item.suggested_owner_role.replace(/_/g,' ')} —`
                      : '— unassigned —')} />
                  <SummaryRow icon="time-outline" label="When"
                    value={item.required_by
                      ? new Date(item.required_by).toLocaleDateString()
                      : (item.metrics.current_age_hours !== null
                          ? `${Math.round(item.metrics.current_age_hours)}h old`
                          : '—')} />
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
                    onPress={async (e) => {
                      e.stopPropagation?.();
                      if (users.length === 0) { try { setUsers(await apiListUsers()); } catch {} }
                      setAssigningItem(item);
                    }}
                    style={styles.cardAssign}>
                    <Ionicons name={item.assigned_to_user_id ? 'swap-horizontal' : 'person-add'} size={14} color={theme.color.info} />
                    <Text style={styles.cardAssignText}>
                      {item.assigned_to_user_id ? 'REASSIGN' : 'ASSIGN'}
                    </Text>
                  </Pressable>
                </View>
              </Pressable>
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
        </>
      )}

      {/* V3.3 — quick-assign picker (per-card) */}
      <Modal visible={!!assigningItem} animationType="fade" transparent>
        <Pressable style={styles.modalBack} onPress={() => setAssigningItem(null)}>
          <View style={styles.modal} onStartShouldSetResponder={() => true}>
            <Text style={styles.modalTitle}>ASSIGN TO</Text>
            <ScrollView style={{ maxHeight: 360 }}>
              {users.length === 0 ? (
                <Text style={{ color: theme.color.textDim, fontSize: 13 }}>No users available</Text>
              ) : users.map((u) => {
                const suggested = assigningItem?.suggested_owner_role &&
                  (u.role === assigningItem.suggested_owner_role ||
                   assigningItem.suggested_owner_role.includes(u.role));
                return (
                  <Pressable key={u.id} testID={`card-pick-assignee-${u.id}`}
                    onPress={async () => {
                      const t = assigningItem;
                      setAssigningItem(null);
                      try { await apiAssignItem(t!.id, u.id); await load(); } catch (e) { console.warn(e); }
                    }}
                    style={styles.pickRow}>
                    <Ionicons name="person-circle-outline" size={20}
                      color={suggested ? theme.color.brand : theme.color.textMuted} />
                    <Text style={styles.pickName}>{u.name}</Text>
                    <Text style={styles.pickRole}>{u.role}{suggested ? '  ★' : ''}</Text>
                  </Pressable>
                );
              })}
            </ScrollView>
          </View>
        </Pressable>
      </Modal>
    </SafeAreaView>
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

export function humanBlocker(c: string) {
  return c.replace(/_/g, ' ').replace(/\b\w/g, (l) => l.toUpperCase());
}

const styles = StyleSheet.create({
  safe: { flex: 1, backgroundColor: theme.color.surface },
  header: { paddingHorizontal: theme.spacing.lg, paddingTop: theme.spacing.md, paddingBottom: theme.spacing.sm },
  h1: { color: theme.color.text, fontSize: 32, fontWeight: '900', letterSpacing: 2 },
  h2: { color: theme.color.brand, fontSize: 14, fontWeight: '700', marginTop: 2 },
  center: { flex: 1, alignItems: 'center', justifyContent: 'center' },
  kpiRow: { flexDirection: 'row', gap: 8, paddingHorizontal: theme.spacing.md, paddingVertical: theme.spacing.sm },
  kpi: {
    flex: 1, backgroundColor: theme.color.surface2, borderRadius: theme.radius.md,
    paddingVertical: 12, alignItems: 'center', borderWidth: 1, borderColor: theme.color.border,
  },
  kpiValue: { fontSize: 22, fontWeight: '900' },
  kpiLabel: { color: theme.color.textDim, fontSize: 10, fontWeight: '800', letterSpacing: 1, marginTop: 2 },
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
  modal: { width: '100%', maxWidth: 360, backgroundColor: theme.color.surface, padding: theme.spacing.md,
           borderRadius: theme.radius.md, borderWidth: 1, borderColor: theme.color.border },
  modalTitle: { color: theme.color.brand, fontSize: 12, fontWeight: '900', letterSpacing: 2, marginBottom: theme.spacing.sm },
  pickRow: { flexDirection: 'row', alignItems: 'center', gap: 10, paddingVertical: 10 },
  pickName: { color: theme.color.text, fontSize: 14, fontWeight: '700' },
  pickRole: { marginLeft: 'auto', color: theme.color.textDim, fontSize: 11 },
});
