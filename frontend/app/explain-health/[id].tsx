import { useCallback, useEffect, useState } from 'react';
import { View, Text, StyleSheet, ScrollView, Pressable, ActivityIndicator, RefreshControl } from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import { Ionicons } from '@expo/vector-icons';
import { useLocalSearchParams, useRouter } from 'expo-router';
import { theme } from '@/src/theme';
import { apiExplainHealth, type ExplainedHealth } from '@/src/cre_api';

const STATUS_COLOR: Record<string, string> = {
  green: theme.color.success, amber: theme.color.warning, red: theme.color.error,
};

const SEVERITY_COLOR: Record<string, string> = {
  critical: theme.color.error, warning: theme.color.warning,
  advisory: theme.color.info, info: theme.color.textDim,
};

export default function ExplainHealthScreen() {
  const router = useRouter();
  const { id } = useLocalSearchParams<{ id: string }>();
  const [data, setData] = useState<ExplainedHealth | null>(null);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    if (!id) return;
    setError(null);
    try {
      setData(await apiExplainHealth(id));
    } catch {
      setError('Could not load Health explanation.');
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
        <Pressable onPress={() => router.back()} hitSlop={12} testID="explain-health-back">
          <Ionicons name="chevron-back" size={26} color={theme.color.text} />
        </Pressable>
        <Text style={styles.headerTitle}>Project Health</Text>
        <View style={{ width: 26 }} />
      </View>

      {error ? (
        <Pressable testID="explain-health-error" onPress={() => { setLoading(true); load().finally(() => setLoading(false)); }} style={styles.errorBanner}>
          <Ionicons name="warning" size={16} color={theme.color.error} />
          <Text style={styles.errorBannerText}>{error} Tap to retry.</Text>
        </Pressable>
      ) : null}

      {data && (
        <ScrollView
          contentContainerStyle={styles.content}
          refreshControl={<RefreshControl refreshing={refreshing} onRefresh={onRefresh} tintColor={theme.color.brand} />}
        >
          {/* Score */}
          <View style={styles.scoreCard} testID="health-score">
            <View style={[styles.scoreBadge, { backgroundColor: STATUS_COLOR[data.status] }]}>
              <Text style={styles.scoreBadgeText}>{data.score}</Text>
            </View>
            <View style={{ flex: 1, marginLeft: 12 }}>
              <Text style={styles.scoreStatus}>{data.status.toUpperCase()}</Text>
              <Text style={styles.scoreMeta}>
                {data.progress.activities_completed}/{data.progress.activities_total} activities complete
                {data.progress.percent_complete !== null ? ` (${data.progress.percent_complete}%)` : ''}
              </Text>
            </View>
          </View>

          {/* Dimensions */}
          <Section title="DIMENSIONS" icon="grid" testID="section-dimensions">
            {Object.entries(data.dimensions).map(([dim, d]) => (
              <View key={dim} style={styles.dimensionRow}>
                <View style={styles.dimensionHeader}>
                  <Text style={styles.dimensionName}>{dim.toUpperCase()}</Text>
                  <Text style={[styles.dimensionScore, d.score < 55 && { color: theme.color.error }]}>{d.score}</Text>
                </View>
                <Text style={styles.dimensionExplanation}>{d.explanation}</Text>
              </View>
            ))}
          </Section>

          {/* Drivers */}
          <Section title="DRIVERS" icon="pulse" testID="section-drivers">
            {data.drivers.length === 0 ? (
              <Text style={styles.mutedText}>No reasoned concerns currently driving this score.</Text>
            ) : data.drivers.map((driver, i) => (
              <View key={i} style={styles.driverRow}>
                <Ionicons name="ellipse" size={6} color={theme.color.textDim} style={{ marginTop: 6 }} />
                <Text style={styles.driverText}>{driver}</Text>
              </View>
            ))}
          </Section>

          {/* Recommended Actions */}
          <Section title="RECOMMENDED ACTIONS" icon="checkmark-done-circle" testID="section-actions">
            {data.recommended_actions.length === 0 ? (
              <Text style={styles.mutedText}>{data.action_currency.note}</Text>
            ) : (
              <>
                {data.recommended_actions.slice(0, 15).map((a) => (
                  <View key={a.insight_id} style={styles.actionCard} testID={`action-${a.insight_id}`}>
                    <View style={styles.actionHeader}>
                      <View style={[styles.severityDot, { backgroundColor: SEVERITY_COLOR[a.severity] }]} />
                      <Text style={styles.actionTitle} numberOfLines={2}>{a.suggested_action?.title}</Text>
                    </View>
                    <Text style={styles.actionDescription}>{a.suggested_action?.description}</Text>
                  </View>
                ))}
                {data.recommended_actions.length > 15 && (
                  <Text style={styles.mutedText}>+{data.recommended_actions.length - 15} more</Text>
                )}
                <Text style={styles.currencyNote}>{data.action_currency.note}</Text>
              </>
            )}
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
  scoreCard: {
    flexDirection: 'row', alignItems: 'center', backgroundColor: theme.color.surface2,
    borderRadius: theme.radius.md, padding: theme.spacing.md,
  },
  scoreBadge: { width: 56, height: 56, borderRadius: 28, alignItems: 'center', justifyContent: 'center' },
  scoreBadgeText: { color: '#fff', fontSize: 22, fontWeight: '900' },
  scoreStatus: { color: theme.color.text, fontSize: 16, fontWeight: '800' },
  scoreMeta: { color: theme.color.textDim, fontSize: 12, marginTop: 2 },
  section: { backgroundColor: theme.color.surface2, borderRadius: theme.radius.md, overflow: 'hidden' },
  sectionHeader: { flexDirection: 'row', alignItems: 'center', gap: 8, padding: theme.spacing.md },
  sectionTitle: { color: theme.color.text, fontSize: 13, fontWeight: '800', letterSpacing: 0.5 },
  sectionBody: { paddingHorizontal: theme.spacing.md, paddingBottom: theme.spacing.md, gap: 10 },
  mutedText: { color: theme.color.textDim, fontSize: 13 },
  dimensionRow: { gap: 4 },
  dimensionHeader: { flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between' },
  dimensionName: { color: theme.color.text, fontSize: 12, fontWeight: '800', letterSpacing: 0.3 },
  dimensionScore: { color: theme.color.text, fontSize: 15, fontWeight: '800' },
  dimensionExplanation: { color: theme.color.textDim, fontSize: 12, lineHeight: 17 },
  driverRow: { flexDirection: 'row', gap: 8 },
  driverText: { color: theme.color.text, fontSize: 13, flex: 1, lineHeight: 18 },
  actionCard: { backgroundColor: theme.color.surface3, borderRadius: theme.radius.sm, padding: 10, gap: 4 },
  actionHeader: { flexDirection: 'row', alignItems: 'flex-start', gap: 8 },
  severityDot: { width: 8, height: 8, borderRadius: 4, marginTop: 4 },
  actionTitle: { color: theme.color.text, fontSize: 13, fontWeight: '700', flex: 1 },
  actionDescription: { color: theme.color.textDim, fontSize: 12, lineHeight: 16 },
  currencyNote: { color: theme.color.textDim, fontSize: 11, fontStyle: 'italic', marginTop: 4 },
});
