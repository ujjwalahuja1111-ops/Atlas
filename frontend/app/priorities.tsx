import { useCallback, useEffect, useState } from 'react';
import { View, Text, StyleSheet, ScrollView, Pressable, ActivityIndicator, RefreshControl } from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import { Ionicons } from '@expo/vector-icons';
import { useRouter } from 'expo-router';
import { theme } from '@/src/theme';
import { apiPriorityEngine, type PriorityEngineResult, type PriorityItem } from '@/src/cre_api';

const SEVERITY_COLOR: Record<string, string> = {
  critical: theme.color.error, warning: theme.color.warning,
  advisory: theme.color.info, info: theme.color.textDim,
};

const KIND_ICON: Record<string, any> = {
  project_health: 'pulse', schedule: 'time', approval: 'checkmark-done',
  commercial: 'wallet', recommended_action: 'bulb',
};

export default function PriorityEngineScreen() {
  const router = useRouter();
  const [data, setData] = useState<PriorityEngineResult | null>(null);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    setError(null);
    try {
      setData(await apiPriorityEngine());
    } catch {
      setError('Could not load Priority Engine.');
    }
  }, []);

  useEffect(() => { (async () => { setLoading(true); await load(); setLoading(false); })(); }, [load]);
  const onRefresh = async () => { setRefreshing(true); await load(); setRefreshing(false); };

  const openPriority = (p: PriorityItem) => {
    if (p.kind === 'commercial') router.push(`/commercial/${p.project_id}`);
    else router.push(`/explain-health/${p.project_id}`);
  };

  if (loading) {
    return (
      <SafeAreaView style={styles.center} edges={['top']}>
        <ActivityIndicator color={theme.color.brand} size="large" />
      </SafeAreaView>
    );
  }

  return (
    <SafeAreaView style={styles.container} edges={['top']}>
      <View style={styles.header}>
        <Pressable onPress={() => router.back()} hitSlop={12} testID="priority-engine-back">
          <Ionicons name="chevron-back" size={26} color={theme.color.text} />
        </Pressable>
        <Text style={styles.headerTitle}>Today's Priorities</Text>
        <View style={{ width: 26 }} />
      </View>

      {error ? (
        <Pressable testID="priority-engine-error" onPress={() => { setLoading(true); load().finally(() => setLoading(false)); }} style={styles.errorBanner}>
          <Ionicons name="warning" size={16} color={theme.color.error} />
          <Text style={styles.errorBannerText}>{error} Tap to retry.</Text>
        </Pressable>
      ) : null}

      {data && (
        <ScrollView
          contentContainerStyle={styles.content}
          refreshControl={<RefreshControl refreshing={refreshing} onRefresh={onRefresh} tintColor={theme.color.brand} />}
        >
          <Text style={styles.subheader}>{data.projects_covered} projects covered · {data.priorities.length} item{data.priorities.length === 1 ? '' : 's'} need attention</Text>

          {data.priorities.length === 0 ? (
            <View style={styles.emptyState} testID="priority-engine-empty">
              <Ionicons name="checkmark-circle" size={32} color={theme.color.success} />
              <Text style={styles.emptyStateText}>Nothing needs escalation right now — every project is on track.</Text>
            </View>
          ) : (
            data.priorities.map((p, i) => (
              <Pressable key={i} testID={`priority-item-${i}`} onPress={() => openPriority(p)} style={styles.card}>
                <View style={[styles.severityBar, { backgroundColor: SEVERITY_COLOR[p.severity] }]} />
                <View style={{ flex: 1, padding: theme.spacing.md }}>
                  <View style={styles.cardHeader}>
                    <Ionicons name={KIND_ICON[p.kind] || 'ellipse'} size={14} color={theme.color.textDim} />
                    <Text style={styles.cardProject} numberOfLines={1}>{p.project_name}</Text>
                  </View>
                  <Text style={styles.cardTitle} numberOfLines={2}>{p.title}</Text>
                  <Text style={styles.cardDetail} numberOfLines={2}>{p.detail}</Text>
                </View>
                <Ionicons name="chevron-forward" size={18} color={theme.color.textDim} style={{ marginRight: theme.spacing.md }} />
              </Pressable>
            ))
          )}
        </ScrollView>
      )}
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
  headerTitle: { color: theme.color.text, fontSize: 18, fontWeight: '800' },
  content: { padding: theme.spacing.lg, paddingBottom: 60, gap: theme.spacing.sm },
  subheader: { color: theme.color.textDim, fontSize: 12, marginBottom: theme.spacing.sm },
  errorBanner: {
    flexDirection: 'row', alignItems: 'center', gap: 8, marginHorizontal: theme.spacing.lg,
    padding: 10, borderRadius: theme.radius.sm, backgroundColor: theme.color.surface2,
  },
  errorBannerText: { color: theme.color.error, fontSize: 13, flex: 1 },
  emptyState: { alignItems: 'center', gap: 10, paddingVertical: 60 },
  emptyStateText: { color: theme.color.textDim, fontSize: 14, textAlign: 'center', paddingHorizontal: theme.spacing.lg },
  card: {
    flexDirection: 'row', alignItems: 'stretch', backgroundColor: theme.color.surface2,
    borderRadius: theme.radius.md, overflow: 'hidden',
  },
  severityBar: { width: 4 },
  cardHeader: { flexDirection: 'row', alignItems: 'center', gap: 6, marginBottom: 4 },
  cardProject: { color: theme.color.textDim, fontSize: 11, fontWeight: '700', flex: 1 },
  cardTitle: { color: theme.color.text, fontSize: 14, fontWeight: '700', marginBottom: 2 },
  cardDetail: { color: theme.color.textDim, fontSize: 12, lineHeight: 16 },
});
