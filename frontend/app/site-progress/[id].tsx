import { useCallback, useEffect, useState } from 'react';
import { View, Text, StyleSheet, ScrollView, Pressable, ActivityIndicator, RefreshControl } from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import { Ionicons } from '@expo/vector-icons';
import { useLocalSearchParams, useRouter } from 'expo-router';
import { theme } from '@/src/theme';
import { apiSiteProgress, type SiteProgress } from '@/src/ops_api';

export default function SiteProgressScreen() {
  const router = useRouter();
  const { id } = useLocalSearchParams<{ id: string }>();
  const [data, setData] = useState<SiteProgress | null>(null);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    if (!id) return;
    setError(null);
    try {
      setData(await apiSiteProgress(id));
    } catch {
      setError('Could not load Site Progress.');
    }
  }, [id]);

  useEffect(() => { (async () => { setLoading(true); await load(); setLoading(false); })(); }, [load]);
  const onRefresh = async () => { setRefreshing(true); await load(); setRefreshing(false); };

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
        <Pressable onPress={() => router.back()} hitSlop={12} testID="site-progress-back">
          <Ionicons name="chevron-back" size={26} color={theme.color.text} />
        </Pressable>
        <Text style={styles.headerTitle} numberOfLines={1}>{data?.project_name || 'Site Progress'}</Text>
        <View style={{ width: 26 }} />
      </View>

      {error ? (
        <Pressable testID="site-progress-error" onPress={() => { setLoading(true); load().finally(() => setLoading(false)); }} style={styles.errorBanner}>
          <Ionicons name="warning" size={16} color={theme.color.error} />
          <Text style={styles.errorBannerText}>{error} Tap to retry.</Text>
        </Pressable>
      ) : null}

      {data && (
        <ScrollView
          contentContainerStyle={styles.content}
          refreshControl={<RefreshControl refreshing={refreshing} onRefresh={onRefresh} tintColor={theme.color.brand} />}
        >
          <Section title="TODAY'S WORK" icon="hammer" testID="section-todays-work">
            {data.todays_work.length === 0 ? (
              <Text style={styles.mutedText}>Nothing ready or in progress right now.</Text>
            ) : data.todays_work.map((a) => (
              <Row key={a.id} icon={a.status === 'in_progress' ? 'play-circle' : 'flash'} title={a.name}
                subtitle={a.status === 'in_progress' ? 'In progress' : 'Ready to start'}
                onPress={() => router.push(`/workflow/${a.project_id}`)} testID={`todays-work-${a.id}`} />
            ))}
          </Section>

          <Section title="COMPLETED RECENTLY" icon="checkmark-circle" testID="section-completed">
            {data.completed_recently.length === 0 ? (
              <Text style={styles.mutedText}>Nothing completed yet today.</Text>
            ) : data.completed_recently.slice(0, 10).map((a) => (
              <Row key={a.id} icon="checkmark-circle" title={a.name} subtitle="Completed"
                onPress={() => router.push(`/workflow/${a.project_id}`)} testID={`completed-${a.id}`} />
            ))}
            {data.completed_recently.length > 10 && (
              <Text style={styles.mutedText}>+{data.completed_recently.length - 10} more</Text>
            )}
          </Section>

          <Section title="CURRENT ISSUES" icon="warning" testID="section-issues">
            {data.current_issues.length === 0 ? (
              <Text style={styles.mutedText}>No high-priority issues open.</Text>
            ) : data.current_issues.slice(0, 10).map((i) => (
              <Row key={i.id} icon="warning" title={i.title} subtitle={`${i.category} · ${i.priority}`}
                onPress={() => router.push(`/op/${i.id}`)} testID={`issue-${i.id}`} tone="error" />
            ))}
          </Section>

          <Section title="INSPECTIONS PENDING" icon="search" testID="section-inspections">
            {data.inspections_pending.length === 0 ? (
              <Text style={styles.mutedText}>No inspections outstanding.</Text>
            ) : data.inspections_pending.map((a) => (
              <Row key={a.id} icon="search" title={a.name} subtitle="Requires inspection"
                onPress={() => router.push(`/workflow/${a.project_id}`)} testID={`inspection-${a.id}`} />
            ))}
          </Section>

          <Section title="LATEST UPDATES" icon="time" testID="section-updates">
            {data.latest_updates.length === 0 ? (
              <Text style={styles.mutedText}>No recent captures.</Text>
            ) : data.latest_updates.map((u) => (
              <Pressable key={u.event?.id} testID={`update-${u.event?.id}`}
                onPress={() => u.event?.id && router.push(`/event/${u.event.id}`)} style={styles.row}>
                <Ionicons
                  name={u.event?.kind === 'photo' ? 'camera' : u.event?.kind === 'voice' ? 'mic' : 'document-text'}
                  size={16} color={theme.color.textDim} />
                <View style={{ flex: 1, marginLeft: 8 }}>
                  <Text style={styles.rowTitle} numberOfLines={1}>
                    {u.event?.text_input || (u.event?.kind === 'photo' ? 'Photo capture' : u.event?.kind === 'voice' ? 'Voice note' : 'Update')}
                  </Text>
                  <Text style={styles.rowSubtitle}>{u.event?.user_name} · {u.created_at?.slice(0, 10)}</Text>
                </View>
              </Pressable>
            ))}
          </Section>

          <View style={styles.statLine}>
            <Text style={styles.mutedText}>Total open operational items</Text>
            <Text style={styles.statValue}>{data.open_items_count}</Text>
          </View>
        </ScrollView>
      )}
    </SafeAreaView>
  );
}

function Section({ title, icon, children, testID }: { title: string; icon: any; children: React.ReactNode; testID: string }) {
  return (
    <View style={styles.section} testID={testID}>
      <View style={styles.sectionHeader}>
        <Ionicons name={icon} size={16} color={theme.color.brand} />
        <Text style={styles.sectionTitle}>{title}</Text>
      </View>
      <View style={styles.sectionBody}>{children}</View>
    </View>
  );
}

function Row({ icon, title, subtitle, onPress, testID, tone }: {
  icon: any; title: string; subtitle: string; onPress: () => void; testID: string; tone?: 'error';
}) {
  return (
    <Pressable testID={testID} onPress={onPress} style={styles.row}>
      <Ionicons name={icon} size={16} color={tone === 'error' ? theme.color.error : theme.color.textDim} />
      <View style={{ flex: 1, marginLeft: 8 }}>
        <Text style={styles.rowTitle} numberOfLines={1}>{title}</Text>
        <Text style={styles.rowSubtitle} numberOfLines={1}>{subtitle}</Text>
      </View>
      <Ionicons name="chevron-forward" size={16} color={theme.color.textDim} />
    </Pressable>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1, backgroundColor: theme.color.surface },
  center: { flex: 1, backgroundColor: theme.color.surface, alignItems: 'center', justifyContent: 'center' },
  header: {
    flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between',
    paddingHorizontal: theme.spacing.lg, paddingVertical: theme.spacing.md,
  },
  headerTitle: { color: theme.color.text, fontSize: 16, fontWeight: '800', flex: 1, textAlign: 'center' },
  content: { padding: theme.spacing.lg, paddingBottom: 60, gap: theme.spacing.md },
  errorBanner: {
    flexDirection: 'row', alignItems: 'center', gap: 8, marginHorizontal: theme.spacing.lg,
    padding: 10, borderRadius: theme.radius.sm, backgroundColor: theme.color.surface2,
  },
  errorBannerText: { color: theme.color.error, fontSize: 13, flex: 1 },
  section: { backgroundColor: theme.color.surface2, borderRadius: theme.radius.md, overflow: 'hidden' },
  sectionHeader: { flexDirection: 'row', alignItems: 'center', gap: 8, padding: theme.spacing.md },
  sectionTitle: { color: theme.color.text, fontSize: 13, fontWeight: '800', letterSpacing: 0.5 },
  sectionBody: { paddingHorizontal: theme.spacing.md, paddingBottom: theme.spacing.md, gap: 4 },
  mutedText: { color: theme.color.textDim, fontSize: 13 },
  row: { flexDirection: 'row', alignItems: 'center', paddingVertical: 8 },
  rowTitle: { color: theme.color.text, fontSize: 14, fontWeight: '700' },
  rowSubtitle: { color: theme.color.textDim, fontSize: 12, marginTop: 2 },
  statLine: {
    flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between',
    backgroundColor: theme.color.surface2, borderRadius: theme.radius.md, padding: theme.spacing.md,
  },
  statValue: { color: theme.color.text, fontSize: 18, fontWeight: '800' },
});
