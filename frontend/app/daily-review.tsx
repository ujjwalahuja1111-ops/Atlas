import { useCallback, useEffect, useState } from 'react';
import { View, Text, StyleSheet, ScrollView, Pressable, ActivityIndicator, RefreshControl } from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import { Ionicons } from '@expo/vector-icons';
import { useRouter } from 'expo-router';
import { theme } from '@/src/theme';
import { apiDailyReview, type DailyReview } from '@/src/ops_api';

function formatInrShort(n: number | null | undefined): string {
  if (n === null || n === undefined) return '—';
  const abs = Math.abs(n);
  if (abs >= 10000000) return `₹${(abs / 10000000).toFixed(2)}Cr`;
  if (abs >= 100000) return `₹${(abs / 100000).toFixed(1)}L`;
  return `₹${abs.toLocaleString('en-IN')}`;
}

export default function DailyReviewScreen() {
  const router = useRouter();
  const [data, setData] = useState<DailyReview | null>(null);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    setError(null);
    try {
      setData(await apiDailyReview());
    } catch {
      setError('Could not load Daily Review.');
    }
  }, []);

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
        <Pressable onPress={() => router.back()} hitSlop={12} testID="daily-review-back">
          <Ionicons name="chevron-back" size={26} color={theme.color.text} />
        </Pressable>
        <Text style={styles.headerTitle}>Daily Review</Text>
        <View style={{ width: 26 }} />
      </View>

      {error ? (
        <Pressable testID="daily-review-error" onPress={() => { setLoading(true); load().finally(() => setLoading(false)); }} style={styles.errorBanner}>
          <Ionicons name="warning" size={16} color={theme.color.error} />
          <Text style={styles.errorBannerText}>{error} Tap to retry.</Text>
        </Pressable>
      ) : null}

      {data && (
        <ScrollView
          contentContainerStyle={styles.content}
          refreshControl={<RefreshControl refreshing={refreshing} onRefresh={onRefresh} tintColor={theme.color.brand} />}
        >
          <Section title="FINISHED TODAY" icon="checkmark-circle" testID="section-finished">
            {data.finished_today.activities.length === 0 && data.finished_today.operational_items.length === 0 ? (
              <Text style={styles.mutedText}>Nothing finished yet today.</Text>
            ) : (
              <>
                {data.finished_today.activities.map((a) => (
                  <Row key={a.id} icon="hammer" title={a.name} subtitle="Workflow activity"
                    onPress={() => router.push(`/workflow/${a.project_id}`)} testID={`finished-activity-${a.id}`} />
                ))}
                {data.finished_today.operational_items.map((i) => (
                  <Row key={i.id} icon="checkmark-done" title={i.title} subtitle={i.category}
                    onPress={() => router.push(`/op/${i.id}`)} testID={`finished-item-${i.id}`} />
                ))}
              </>
            )}
          </Section>

          <Section title="WHAT REMAINS OPEN" icon="ellipse-outline" testID="section-open">
            <StatLine label="Open operational items" value={data.remains_open_count} />
          </Section>

          <Section title="WHAT SLIPPED" icon="time" testID="section-slipped">
            {data.slipped_activities.length === 0 ? (
              <Text style={styles.mutedText}>Nothing slipped today.</Text>
            ) : data.slipped_activities.map((a) => (
              <Row key={a.id} icon="time" title={a.name}
                subtitle={`Planned finish ${a.planned_finish?.slice(0, 10) || '—'}`}
                onPress={() => router.push(`/workflow/${a.project_id}`)} testID={`slipped-${a.id}`} tone="error" />
            ))}
          </Section>

          <Section title="NEWLY BLOCKED TODAY" icon="alert-circle" testID="section-blocked">
            {data.newly_blocked_today.length === 0 ? (
              <Text style={styles.mutedText}>Nothing became blocked today.</Text>
            ) : data.newly_blocked_today.map((a) => (
              <Row key={a.id} icon="alert-circle" title={a.name} subtitle="Blocked"
                onPress={() => router.push(`/workflow/${a.project_id}`)} testID={`blocked-${a.id}`} tone="error" />
            ))}
          </Section>

          <Section title="INSPECTIONS REMAINING" icon="search" testID="section-inspections">
            {data.inspections_remaining.length === 0 ? (
              <Text style={styles.mutedText}>No inspections outstanding.</Text>
            ) : data.inspections_remaining.map((a) => (
              <Row key={a.id} icon="search" title={a.name} subtitle="Requires inspection"
                onPress={() => router.push(`/workflow/${a.project_id}`)} testID={`inspection-${a.id}`} />
            ))}
          </Section>

          <Section title="APPROVALS REMAINING" icon="checkmark-done" testID="section-approvals">
            {data.approvals_remaining.length === 0 ? (
              <Text style={styles.mutedText}>No approvals outstanding.</Text>
            ) : data.approvals_remaining.map((i) => (
              <Row key={i.id} icon="checkmark-done" title={i.title} subtitle={i.category}
                onPress={() => router.push(`/op/${i.id}`)} testID={`approval-${i.id}`} />
            ))}
          </Section>

          <Section title="COMMERCIAL ACTIONS REMAINING" icon="wallet" testID="section-commercial">
            {data.commercial_actions_remaining.pending_variations.length === 0 &&
             data.commercial_actions_remaining.pending_payment_requests.length === 0 ? (
              <Text style={styles.mutedText}>No commercial actions outstanding.</Text>
            ) : (
              <>
                {data.commercial_actions_remaining.pending_variations.map((v) => (
                  <Row key={v.id} icon="swap-horizontal" title={v.title} subtitle={formatInrShort(v.proposed_cost)}
                    onPress={() => router.push(`/commercial/${v.project_id}`)} testID={`commercial-variation-${v.id}`} />
                ))}
                {data.commercial_actions_remaining.pending_payment_requests.map((pr) => (
                  <Row key={pr.id} icon="receipt" title={pr.number} subtitle={formatInrShort(pr.amount)}
                    onPress={() => router.push(`/commercial/${pr.project_id}`)} testID={`commercial-pr-${pr.id}`} />
                ))}
              </>
            )}
          </Section>

          <Section title="TOMORROW" icon="arrow-forward-circle" testID="section-tomorrow">
            <StatLine label="Projects requiring attention" value={data.projects_requiring_attention_tomorrow}
              tone={data.projects_requiring_attention_tomorrow > 0 ? 'warning' : undefined} />
          </Section>
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

function StatLine({ label, value, tone }: { label: string; value: number; tone?: 'warning' }) {
  return (
    <View style={styles.statLine}>
      <Text style={styles.mutedText}>{label}</Text>
      <Text style={[styles.statValue, tone === 'warning' && { color: theme.color.warning }]}>{value}</Text>
    </View>
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
  statLine: { flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between' },
  statValue: { color: theme.color.text, fontSize: 18, fontWeight: '800' },
});
