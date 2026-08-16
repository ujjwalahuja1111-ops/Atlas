// P2-09 — Notification Inbox. In-app only, per this task's own
// explicit scope (no push, email, WhatsApp, or background jobs).
// PX-02 Phase 4 — a Coordination view (the six waiting-state sections
// this phase's own brief specifies) is added as a toggle alongside
// the existing category-filter view, which is fully preserved and
// unmodified — per this task's own "do not introduce a completely
// separate messaging UI paradigm" instruction, this enhances the
// existing Inbox architecture rather than replacing it.
import { useCallback, useEffect, useState } from 'react';
import { View, Text, StyleSheet, ScrollView, Pressable, ActivityIndicator, RefreshControl } from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import { Ionicons } from '@expo/vector-icons';
import { useRouter } from 'expo-router';
import { theme } from '@/src/theme';
import {
  apiListNotifications, apiMarkNotificationRead, apiMarkAllNotificationsRead,
  type Notification,
} from '@/src/notifications_api';
import { apiListProjects, type Project } from '@/src/api';
import { apiGetCoordinationInbox, type CoordinationInbox, type CoordinationCard } from '@/src/inbox_intelligence_api';

const CATEGORY_LABEL: Record<string, string> = {
  all: 'All', assignment: 'Assignments', approval: 'Approvals',
  clarification: 'Clarifications', status_change: 'Status', commercial: 'Commercial',
};

const CATEGORY_ICON: Record<string, any> = {
  assignment: 'person-add-outline', approval: 'checkmark-circle-outline',
  clarification: 'help-circle-outline', status_change: 'sync-outline', commercial: 'cash-outline',
};

const AGING_COLOR: Record<string, string> = { green: theme.color.success, amber: theme.color.warning, red: theme.color.error };

const COORDINATION_SECTIONS: { key: keyof CoordinationInbox; label: string }[] = [
  { key: 'action_required', label: 'Action Required' },
  { key: 'waiting_for_you', label: 'Waiting For You' },
  { key: 'waiting_for_others', label: 'Waiting For Others' },
  { key: 'escalations', label: 'Escalations' },
  { key: 'commercial_attention', label: 'Commercial Attention' },
  { key: 'activity_feed', label: 'Activity Feed' },
];

export default function NotificationInboxScreen() {
  const router = useRouter();
  const [view, setView] = useState<'coordination' | 'all'>('coordination');
  const [filter, setFilter] = useState<'all' | 'assignment' | 'approval' | 'clarification' | 'commercial'>('all');
  const [notifications, setNotifications] = useState<Notification[]>([]);
  const [coordination, setCoordination] = useState<CoordinationInbox | null>(null);
  const [expandedSections, setExpandedSections] = useState<Record<string, boolean>>({ action_required: true, waiting_for_you: true, escalations: true });
  const [projectNames, setProjectNames] = useState<Record<string, string>>({});
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [loadError, setLoadError] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoadError(null);
    try {
      const [list, projects, coord] = await Promise.all([
        apiListNotifications(filter),
        apiListProjects().catch(() => [] as Project[]),
        apiGetCoordinationInbox().catch(() => null),
      ]);
      setNotifications(list);
      setCoordination(coord);
      if (projects.length) {
        setProjectNames(Object.fromEntries(projects.map((p) => [p.id, p.name])));
      }
    } catch {
      setLoadError('Could not load your inbox. Pull to retry.');
    }
  }, [filter]);

  // Unread pinned above read; newest-first within each group — the
  // backend already returns newest-first, so this sort only needs to
  // move unread items ahead without disturbing that existing order.
  const sortedNotifications = [...notifications].sort((a, b) => {
    if (a.read !== b.read) return a.read ? 1 : -1;
    return 0;
  });

  useEffect(() => { (async () => { setLoading(true); await load(); setLoading(false); })(); }, [load]);

  const onRefresh = async () => { setRefreshing(true); await load(); setRefreshing(false); };

  const onOpen = async (n: Notification) => {
    if (!n.read) {
      setNotifications((prev) => prev.map((x) => (x.id === n.id ? { ...x, read: true } : x)));
      apiMarkNotificationRead(n.id).catch(() => {});
    }
    if (n.project_id && n.entity_type === 'operational_item') {
      router.push(`/op/${n.entity_id}`);
    } else if (n.entity_type === 'event' && n.entity_id) {
      router.push(`/event/${n.entity_id}`);
    } else if (n.project_id && (n.entity_type === 'payment_request' || n.entity_type === 'payment')) {
      router.push(`/commercial/${n.project_id}`);
    } else if (n.project_id) {
      router.push(`/workspace/${n.project_id}`);
    }
  };

  // PX-02 Phase 4 Section 7 — deep-link into the correct Workspace
  // phase, using target_phase directly rather than re-deriving it
  // (the backend's own ENTITY_TYPE_TO_PHASE table is the one source
  // of truth). router.back() from the destination naturally returns
  // here, since this is a normal push, not a replace.
  const onOpenCoordinationCard = async (card: CoordinationCard) => {
    if (card.notification_ids.length) {
      setCoordination((prev) => {
        if (!prev) return prev;
        const updated = { ...prev } as CoordinationInbox;
        for (const key of Object.keys(updated) as (keyof CoordinationInbox)[]) {
          updated[key] = updated[key].map((c) => (c.entity_id === card.entity_id ? { ...c, read: true } : c));
        }
        return updated;
      });
      await Promise.all(card.notification_ids.map((id) => apiMarkNotificationRead(id).catch(() => {})));
    }
    if (card.project_id) {
      router.push(`/projects/${card.project_id}/workspace`);
    }
  };

  const onMarkAllRead = async () => {
    setNotifications((prev) => prev.map((x) => ({ ...x, read: true })));
    await apiMarkAllNotificationsRead(filter).catch(() => {});
    await load();
  };

  const unreadCount = notifications.filter((n) => !n.read).length;

  if (loading) {
    return <SafeAreaView style={styles.center} edges={['top']}><ActivityIndicator color={theme.color.brand} size="large" /></SafeAreaView>;
  }

  return (
    <SafeAreaView style={styles.container} edges={['top']}>
      <View style={styles.header}>
        <Pressable testID="inbox-back" onPress={() => router.back()} hitSlop={12}>
          <Ionicons name="arrow-back" size={22} color={theme.color.text} />
        </Pressable>
        <Text style={styles.headerTitle}>Inbox</Text>
        <Pressable testID="inbox-mark-all-read" onPress={onMarkAllRead} disabled={unreadCount === 0} hitSlop={12}>
          <Text style={[styles.markAllText, unreadCount === 0 && styles.markAllTextDisabled]}>Mark all read</Text>
        </Pressable>
      </View>

      <View style={styles.viewToggleRow}>
        <Pressable testID="inbox-view-coordination" onPress={() => setView('coordination')} style={[styles.viewToggle, view === 'coordination' && styles.viewToggleActive]}>
          <Text style={[styles.viewToggleText, view === 'coordination' && styles.viewToggleTextActive]}>Coordination</Text>
        </Pressable>
        <Pressable testID="inbox-view-all" onPress={() => setView('all')} style={[styles.viewToggle, view === 'all' && styles.viewToggleActive]}>
          <Text style={[styles.viewToggleText, view === 'all' && styles.viewToggleTextActive]}>All Notifications</Text>
        </Pressable>
      </View>

      {view === 'all' && (
        <ScrollView horizontal showsHorizontalScrollIndicator={false} style={styles.filterRow} contentContainerStyle={{ paddingHorizontal: theme.spacing.md, gap: 8 }}>
          {(['all', 'assignment', 'approval', 'commercial', 'clarification'] as const).map((c) => (
            <Pressable key={c} testID={`inbox-filter-${c}`} onPress={() => setFilter(c)}
              style={[styles.filterChip, filter === c && styles.filterChipActive]}>
              <Text style={[styles.filterChipText, filter === c && styles.filterChipTextActive]}>{CATEGORY_LABEL[c]}</Text>
            </Pressable>
          ))}
        </ScrollView>
      )}

      <ScrollView
        contentContainerStyle={styles.content}
        refreshControl={<RefreshControl refreshing={refreshing} onRefresh={onRefresh} tintColor={theme.color.brand} />}
      >
        {loadError && <Text style={styles.errorText}>{loadError}</Text>}

        {view === 'coordination' ? (
          !coordination ? (
            <Text style={styles.emptyText}>Could not load coordination data.</Text>
          ) : (
            COORDINATION_SECTIONS.map(({ key, label }) => {
              const cards = coordination[key];
              const expanded = expandedSections[key] ?? false;
              return (
                <View key={key} style={styles.coordSection}>
                  <Pressable testID={`inbox-section-${key}`} onPress={() => setExpandedSections((p) => ({ ...p, [key]: !expanded }))} style={styles.coordSectionHeader}>
                    <Text style={styles.coordSectionTitle}>{label} ({cards.length})</Text>
                    <Ionicons name={expanded ? 'chevron-up' : 'chevron-down'} size={16} color={theme.color.textDim} />
                  </Pressable>
                  {expanded && (
                    cards.length === 0 ? (
                      <Text style={styles.emptyText}>Nothing here.</Text>
                    ) : (
                      cards.map((card) => (
                        <Pressable key={`${card.entity_type}-${card.entity_id}-${card.created_at}`} testID={`inbox-coord-card-${card.entity_id}`}
                          onPress={() => onOpenCoordinationCard(card)} style={[styles.row, !card.read && styles.rowUnread]}>
                          <View style={[styles.agingDot, { backgroundColor: AGING_COLOR[card.aging_signal] }]} />
                          <View style={{ flex: 1, marginLeft: 10 }}>
                            <Text style={[styles.rowTitle, !card.read && styles.rowTitleUnread]}>
                              {card.count > 1 ? `${card.latest_title} — updated ${card.count} times` : card.latest_title}
                            </Text>
                            <Text style={styles.rowBody} numberOfLines={2}>Latest: {card.latest_body}</Text>
                            <View style={styles.rowMetaRow}>
                              {card.project_id && projectNames[card.project_id] && (
                                <Text style={styles.rowProject}>{projectNames[card.project_id]} · </Text>
                              )}
                              <Text style={styles.rowTime}>{new Date(card.created_at).toLocaleString()}</Text>
                            </View>
                          </View>
                        </Pressable>
                      ))
                    )
                  )}
                </View>
              );
            })
          )
        ) : (
          sortedNotifications.length === 0 ? (
            <Text style={styles.emptyText}>Nothing here yet.</Text>
          ) : (
            sortedNotifications.map((n) => (
              <Pressable key={n.id} testID={`inbox-item-${n.id}`} onPress={() => onOpen(n)}
                style={[styles.row, !n.read && styles.rowUnread]}>
                {!n.read && <View style={styles.unreadDot} />}
                <Ionicons name={CATEGORY_ICON[n.category] || 'notifications-outline'} size={18} color={theme.color.brand} style={{ marginLeft: n.read ? 14 : 0 }} />
                <View style={{ flex: 1, marginLeft: 10 }}>
                  <Text style={[styles.rowTitle, !n.read && styles.rowTitleUnread]}>{n.title}</Text>
                  <Text style={styles.rowBody} numberOfLines={2}>{n.body}</Text>
                  <View style={styles.rowMetaRow}>
                    {n.project_id && projectNames[n.project_id] && (
                      <Text style={styles.rowProject}>{projectNames[n.project_id]} · </Text>
                    )}
                    <Text style={styles.rowTime}>{new Date(n.created_at).toLocaleString()}</Text>
                  </View>
                </View>
              </Pressable>
            ))
          )
        )}
      </ScrollView>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1, backgroundColor: theme.color.surface },
  center: { flex: 1, backgroundColor: theme.color.surface, alignItems: 'center', justifyContent: 'center' },
  header: {
    flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between',
    paddingHorizontal: theme.spacing.lg, paddingVertical: theme.spacing.md,
  },
  headerTitle: { color: theme.color.text, fontSize: 16, fontWeight: '800' },
  markAllText: { color: theme.color.brand, fontSize: 13, fontWeight: '700' },
  markAllTextDisabled: { color: theme.color.textDim },
  viewToggleRow: { flexDirection: 'row', paddingHorizontal: theme.spacing.lg, gap: 8, marginBottom: theme.spacing.sm },
  viewToggle: { flex: 1, paddingVertical: 8, borderRadius: theme.radius.sm, backgroundColor: theme.color.surface2, alignItems: 'center', borderWidth: 1, borderColor: theme.color.border },
  viewToggleActive: { backgroundColor: theme.color.brand, borderColor: theme.color.brand },
  viewToggleText: { color: theme.color.textDim, fontSize: 12, fontWeight: '700' },
  viewToggleTextActive: { color: theme.color.onBrand },
  coordSection: { marginBottom: theme.spacing.md },
  coordSectionHeader: { flexDirection: 'row', justifyContent: 'space-between', alignItems: 'center', paddingVertical: 8 },
  coordSectionTitle: { color: theme.color.text, fontSize: 13, fontWeight: '800' },
  agingDot: { width: 10, height: 10, borderRadius: 5, marginTop: 6 },
  filterRow: { flexGrow: 0, marginBottom: theme.spacing.sm },
  filterChip: {
    paddingVertical: 6, paddingHorizontal: 14, borderRadius: 16,
    backgroundColor: theme.color.surface2, borderWidth: 1, borderColor: theme.color.border,
  },
  filterChipActive: { backgroundColor: theme.color.brand, borderColor: theme.color.brand },
  filterChipText: { color: theme.color.textDim, fontSize: 12, fontWeight: '700' },
  filterChipTextActive: { color: theme.color.onBrand },
  content: { padding: theme.spacing.md, paddingBottom: 40 },
  errorText: { color: theme.color.error, marginBottom: theme.spacing.sm },
  emptyText: { color: theme.color.textDim, fontSize: 13, fontStyle: 'italic', marginTop: theme.spacing.lg },
  row: {
    flexDirection: 'row', alignItems: 'flex-start', backgroundColor: theme.color.surface2,
    borderRadius: theme.radius.md, borderWidth: 1, borderColor: theme.color.border,
    padding: theme.spacing.md, marginBottom: theme.spacing.sm,
  },
  rowUnread: { borderColor: theme.color.brand },
  unreadDot: { width: 8, height: 8, borderRadius: 4, backgroundColor: theme.color.brand, marginTop: 6 },
  rowTitle: { color: theme.color.text, fontSize: 14, fontWeight: '600' },
  rowTitleUnread: { fontWeight: '800' },
  rowBody: { color: theme.color.textDim, fontSize: 12, marginTop: 2 },
  rowMetaRow: { flexDirection: 'row', alignItems: 'center', marginTop: 4 },
  rowProject: { color: theme.color.brand, fontSize: 11, fontWeight: '700' },
  rowTime: { color: theme.color.textDim, fontSize: 11 },
});
