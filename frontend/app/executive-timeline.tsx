import { useCallback, useEffect, useState } from 'react';
import { View, Text, StyleSheet, ScrollView, Pressable, ActivityIndicator, RefreshControl } from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import { Ionicons } from '@expo/vector-icons';
import { useRouter } from 'expo-router';
import { theme } from '@/src/theme';
import { apiExecutiveTimeline, type ExecutiveTimeline, type ExecutiveTimelineEvent } from '@/src/cre_api';

const SOURCE_ICON: Record<string, any> = { reality: 'camera', operations: 'construct', commercial: 'wallet' };

const OPERATIONS_KIND_LABEL: Record<string, string> = {
  created: 'Item created', assigned: 'Item assigned', acknowledged: 'Item acknowledged',
  started: 'Work started', fulfilled: 'Item fulfilled', verified: 'Item verified',
  closed: 'Item closed', reopened: 'Item reopened', commented: 'Comment added',
};

function labelFor(e: ExecutiveTimelineEvent): string {
  if (e.source === 'reality') {
    const ev = e.event || {};
    return ev.text_input || (ev.kind === 'photo' ? 'Photo capture' : ev.kind === 'voice' ? 'Voice note' : 'Update');
  }
  if (e.source === 'operations') {
    const oe = e.operational_event || {};
    const itemTitle = e.operational_item?.title;
    const label = OPERATIONS_KIND_LABEL[oe.kind] || oe.kind || 'Item update';
    return itemTitle ? `${label} — ${itemTitle}` : label;
  }
  const labels: Record<string, string> = {
    contract_created: 'Contract created', contract_revised: 'Contract revised',
    variation_submitted: 'Variation submitted', variation_approved: 'Variation approved',
    variation_rejected: 'Variation rejected', payment_requested: 'Payment requested',
    payment_received: 'Payment received', milestone_achieved: 'Milestone completed',
    budget_updated: 'Budget updated', budget_created: 'Budget created',
  };
  return labels[e.kind] || e.kind || 'Commercial event';
}

function dateFor(e: ExecutiveTimelineEvent): string {
  const iso = e.created_at || e.event?.server_created_at || e.operational_event?.created_at || '';
  return iso.slice(0, 10);
}

export default function ExecutiveTimelineScreen() {
  const router = useRouter();
  const [data, setData] = useState<ExecutiveTimeline | null>(null);
  const [filter, setFilter] = useState<'all' | 'reality' | 'operations' | 'commercial'>('all');
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async (category?: string) => {
    setError(null);
    try {
      setData(await apiExecutiveTimeline(category ? { category } : undefined));
    } catch {
      setError('Could not load the Executive Timeline.');
    }
  }, []);

  useEffect(() => { (async () => { setLoading(true); await load(); setLoading(false); })(); }, [load]);
  const onRefresh = async () => { setRefreshing(true); await load(filter === 'all' ? undefined : filter); setRefreshing(false); };

  const onFilterChange = async (f: 'all' | 'reality' | 'operations' | 'commercial') => {
    setFilter(f);
    setLoading(true);
    await load(f === 'all' ? undefined : f);
    setLoading(false);
  };

  return (
    <SafeAreaView style={styles.container} edges={['top']}>
      <View style={styles.header}>
        <Pressable onPress={() => router.back()} hitSlop={12} testID="exec-timeline-back">
          <Ionicons name="chevron-back" size={26} color={theme.color.text} />
        </Pressable>
        <Text style={styles.headerTitle}>Executive Timeline</Text>
        <View style={{ width: 26 }} />
      </View>

      <View style={styles.filterRow}>
        {(['all', 'reality', 'operations', 'commercial'] as const).map((f) => (
          <Pressable key={f} testID={`exec-timeline-filter-${f}`} onPress={() => onFilterChange(f)}
            style={[styles.filterChip, filter === f && styles.filterChipActive]}>
            <Text style={[styles.filterChipText, filter === f && styles.filterChipTextActive]}>
              {f === 'all' ? 'All' : f === 'reality' ? 'Reality' : f === 'operations' ? 'Operations' : 'Commercial'}
            </Text>
          </Pressable>
        ))}
      </View>

      {error ? (
        <Pressable testID="exec-timeline-error" onPress={() => { setLoading(true); load(filter === 'all' ? undefined : filter).finally(() => setLoading(false)); }} style={styles.errorBanner}>
          <Ionicons name="warning" size={16} color={theme.color.error} />
          <Text style={styles.errorBannerText}>{error} Tap to retry.</Text>
        </Pressable>
      ) : null}

      {loading ? (
        <ActivityIndicator color={theme.color.brand} style={{ marginTop: 40 }} />
      ) : (
        <ScrollView
          contentContainerStyle={styles.content}
          refreshControl={<RefreshControl refreshing={refreshing} onRefresh={onRefresh} tintColor={theme.color.brand} />}
        >
          {!data || data.events.length === 0 ? (
            <Text style={styles.mutedText}>No events to show.</Text>
          ) : (
            data.events.map((e, i) => (
              <View key={i} style={styles.row} testID={`exec-timeline-event-${i}`}>
                <Ionicons name={SOURCE_ICON[e.source] || 'ellipse'} size={16} color={theme.color.brand} />
                <View style={{ flex: 1, marginLeft: 8 }}>
                  <Text style={styles.rowTitle} numberOfLines={1}>{labelFor(e)}</Text>
                  <Text style={styles.rowMeta}>{e.project_name} · {dateFor(e)}</Text>
                </View>
              </View>
            ))
          )}
        </ScrollView>
      )}
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1, backgroundColor: theme.color.surface },
  header: {
    flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between',
    paddingHorizontal: theme.spacing.lg, paddingVertical: theme.spacing.md,
  },
  headerTitle: { color: theme.color.text, fontSize: 18, fontWeight: '800' },
  filterRow: { flexDirection: 'row', gap: 8, paddingHorizontal: theme.spacing.lg, marginBottom: theme.spacing.sm },
  filterChip: {
    paddingHorizontal: 12, paddingVertical: 6, borderRadius: theme.radius.pill,
    borderWidth: 1, borderColor: theme.color.border,
  },
  filterChipActive: { backgroundColor: theme.color.brand, borderColor: theme.color.brand },
  filterChipText: { color: theme.color.textDim, fontSize: 12, fontWeight: '700' },
  filterChipTextActive: { color: theme.color.onBrand },
  content: { padding: theme.spacing.lg, paddingBottom: 60, gap: 4 },
  errorBanner: {
    flexDirection: 'row', alignItems: 'center', gap: 8, marginHorizontal: theme.spacing.lg,
    padding: 10, borderRadius: theme.radius.sm, backgroundColor: theme.color.surface2,
  },
  errorBannerText: { color: theme.color.error, fontSize: 13, flex: 1 },
  mutedText: { color: theme.color.textDim, fontSize: 13 },
  row: { flexDirection: 'row', alignItems: 'center', paddingVertical: 8 },
  rowTitle: { color: theme.color.text, fontSize: 14, fontWeight: '700' },
  rowMeta: { color: theme.color.textDim, fontSize: 12, marginTop: 2 },
});
