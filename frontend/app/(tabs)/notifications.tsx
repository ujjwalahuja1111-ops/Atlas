// P2-09 — Notification Inbox. In-app only, per this task's own
// explicit scope (no push, email, WhatsApp, or background jobs).
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

const CATEGORY_LABEL: Record<string, string> = {
  all: 'All', assignment: 'Assignments', approval: 'Approvals',
  clarification: 'Clarifications', status_change: 'Status', commercial: 'Commercial',
};

const CATEGORY_ICON: Record<string, any> = {
  assignment: 'person-add-outline', approval: 'checkmark-circle-outline',
  clarification: 'help-circle-outline', status_change: 'sync-outline', commercial: 'cash-outline',
};

export default function NotificationInboxScreen() {
  const router = useRouter();
  const [filter, setFilter] = useState<'all' | 'assignment' | 'approval' | 'clarification' | 'commercial'>('all');
  const [notifications, setNotifications] = useState<Notification[]>([]);
  const [projectNames, setProjectNames] = useState<Record<string, string>>({});
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [loadError, setLoadError] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoadError(null);
    try {
      const [list, projects] = await Promise.all([
        apiListNotifications(filter),
        apiListProjects().catch(() => [] as Project[]),
      ]);
      setNotifications(list);
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
    } else if (n.project_id && (n.entity_type === 'payment_request' || n.entity_type === 'payment')) {
      router.push(`/commercial/${n.project_id}`);
    } else if (n.project_id) {
      router.push(`/workspace/${n.project_id}`);
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

      <ScrollView horizontal showsHorizontalScrollIndicator={false} style={styles.filterRow} contentContainerStyle={{ paddingHorizontal: theme.spacing.md, gap: 8 }}>
        {(['all', 'assignment', 'approval', 'commercial', 'clarification'] as const).map((c) => (
          <Pressable key={c} testID={`inbox-filter-${c}`} onPress={() => setFilter(c)}
            style={[styles.filterChip, filter === c && styles.filterChipActive]}>
            <Text style={[styles.filterChipText, filter === c && styles.filterChipTextActive]}>{CATEGORY_LABEL[c]}</Text>
          </Pressable>
        ))}
      </ScrollView>

      <ScrollView
        contentContainerStyle={styles.content}
        refreshControl={<RefreshControl refreshing={refreshing} onRefresh={onRefresh} tintColor={theme.color.brand} />}
      >
        {loadError && <Text style={styles.errorText}>{loadError}</Text>}
        {sortedNotifications.length === 0 ? (
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
