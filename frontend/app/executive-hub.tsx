import { useCallback, useEffect, useState } from 'react';
import { View, Text, StyleSheet, ScrollView, Pressable, ActivityIndicator, RefreshControl } from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import { Ionicons } from '@expo/vector-icons';
import { useRouter } from 'expo-router';
import { theme } from '@/src/theme';
import {
  apiPriorityEngine, apiCrossProjectIntelligence, apiCommercialIntelligence,
  type PriorityEngineResult, type CrossProjectIntelligence, type CommercialIntelligence,
} from '@/src/cre_api';
import { apiGetManagementDigest, type ManagementDigest } from '@/src/inbox_intelligence_api';

function formatInrShort(n: number | null | undefined): string {
  if (n === null || n === undefined) return '—';
  const sign = n < 0 ? '-' : '';
  const abs = Math.abs(n);
  if (abs >= 10000000) return `${sign}₹${(abs / 10000000).toFixed(2)}Cr`;
  if (abs >= 100000) return `${sign}₹${(abs / 100000).toFixed(1)}L`;
  return `${sign}₹${abs.toLocaleString('en-IN')}`;
}

export default function ExecutiveHubScreen() {
  const router = useRouter();
  const [priorities, setPriorities] = useState<PriorityEngineResult | null>(null);
  const [managementDigest, setManagementDigest] = useState<ManagementDigest | null>(null);
  const [crossProject, setCrossProject] = useState<CrossProjectIntelligence | null>(null);
  const [commercial, setCommercial] = useState<CommercialIntelligence | null>(null);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    setError(null);
    try {
      const [p, c, m, digest] = await Promise.all([
        apiPriorityEngine(), apiCrossProjectIntelligence(), apiCommercialIntelligence(), apiGetManagementDigest(),
      ]);
      setPriorities(p); setCrossProject(c); setCommercial(m); setManagementDigest(digest);
    } catch {
      setError('Could not load the Executive Hub.');
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
        <Pressable onPress={() => router.back()} hitSlop={12} testID="exec-hub-back">
          <Ionicons name="chevron-back" size={26} color={theme.color.text} />
        </Pressable>
        <Text style={styles.headerTitle}>Executive Hub</Text>
        <Pressable onPress={() => router.push('/portfolio-search')} hitSlop={12} testID="exec-hub-search">
          <Ionicons name="search" size={22} color={theme.color.brand} />
        </Pressable>
      </View>

      {error ? (
        <Pressable testID="exec-hub-error" onPress={() => { setLoading(true); load().finally(() => setLoading(false)); }} style={styles.errorBanner}>
          <Ionicons name="warning" size={16} color={theme.color.error} />
          <Text style={styles.errorBannerText}>{error} Tap to retry.</Text>
        </Pressable>
      ) : null}

      <ScrollView
        contentContainerStyle={styles.content}
        refreshControl={<RefreshControl refreshing={refreshing} onRefresh={onRefresh} tintColor={theme.color.brand} />}
      >
        {/* Priority Engine summary */}
        <Pressable style={styles.section} onPress={() => router.push('/priorities')} testID="exec-hub-priorities">
          <View style={styles.sectionHeader}>
            <Ionicons name="flag" size={16} color={theme.color.brand} />
            <Text style={styles.sectionTitle}>TODAY'S PRIORITIES</Text>
            <Ionicons name="chevron-forward" size={16} color={theme.color.textDim} />
          </View>
          <View style={styles.sectionBody}>
            {!priorities || priorities.priorities.length === 0 ? (
              <Text style={styles.mutedText}>Nothing needs escalation right now.</Text>
            ) : (
              priorities.priorities.slice(0, 3).map((p, i) => (
                <Text key={i} style={styles.rowText} numberOfLines={1}>• {p.title}</Text>
              ))
            )}
            {priorities && priorities.priorities.length > 3 && (
              <Text style={styles.mutedText}>+{priorities.priorities.length - 3} more</Text>
            )}
          </View>
        </Pressable>

        {/* PX-02 Phase 4 Section 8 — Management Attention Digest: a
            portfolio-level synthesis (declining-health project count,
            escalated blocker count, payment requests awaiting
            approval), not a raw notification list, per this task's
            own explicit distinction. */}
        <View style={styles.section} testID="exec-hub-management-digest">
          <View style={styles.sectionHeader}>
            <Ionicons name="alert-circle" size={16} color={theme.color.brand} />
            <Text style={styles.sectionTitle}>NEEDS ATTENTION TODAY</Text>
          </View>
          <View style={styles.sectionBody}>
            {!managementDigest ? (
              <Text style={styles.mutedText}>Loading…</Text>
            ) : (
              managementDigest.needs_attention_projects.length === 0
                && managementDigest.escalated_blockers_count === 0
                && managementDigest.payment_requests_awaiting_approval === 0 ? (
                <Text style={styles.mutedText}>Nothing needs attention right now.</Text>
              ) : (
                <>
                  {managementDigest.needs_attention_projects.map((p) => (
                    <Text key={p.project_id} style={styles.rowText} numberOfLines={1}>
                      • {p.project_name} — health {p.health_status}
                    </Text>
                  ))}
                  {managementDigest.escalated_blockers_count > 0 && (
                    <Text style={styles.rowText}>• {managementDigest.escalated_blockers_count} escalated blocker{managementDigest.escalated_blockers_count !== 1 ? 's' : ''}</Text>
                  )}
                  {managementDigest.payment_requests_awaiting_approval > 0 && (
                    <Text style={styles.rowText}>• {managementDigest.payment_requests_awaiting_approval} payment request{managementDigest.payment_requests_awaiting_approval !== 1 ? 's' : ''} awaiting approval</Text>
                  )}
                </>
              )
            )}
          </View>
        </View>

        {/* Portfolio Control Center link */}
        <Pressable style={styles.section} onPress={() => router.push('/portfolio')} testID="exec-hub-portfolio">
          <View style={styles.sectionHeader}>
            <Ionicons name="grid" size={16} color={theme.color.brand} />
            <Text style={styles.sectionTitle}>PORTFOLIO CONTROL CENTER</Text>
            <Ionicons name="chevron-forward" size={16} color={theme.color.textDim} />
          </View>
          <View style={styles.sectionBody}>
            <Text style={styles.mutedText}>Every project's own health, schedule, and financials — one row each.</Text>
          </View>
        </Pressable>

        {/* Cross-Project Intelligence */}
        <View style={styles.section} testID="exec-hub-cross-project">
          <View style={styles.sectionHeader}>
            <Ionicons name="repeat" size={16} color={theme.color.brand} />
            <Text style={styles.sectionTitle}>REPEATED PATTERNS</Text>
          </View>
          <View style={styles.sectionBody}>
            {!crossProject || crossProject.repeated_patterns.length === 0 ? (
              <Text style={styles.mutedText}>No concern repeats across 2+ projects right now.</Text>
            ) : (
              crossProject.repeated_patterns.slice(0, 5).map((p, i) => (
                <View key={i} style={styles.patternRow}>
                  <Text style={styles.rowText} numberOfLines={2}>{p.description}</Text>
                  <Text style={styles.patternMeta}>{p.project_count} projects: {p.project_names.join(', ')}</Text>
                </View>
              ))
            )}
          </View>
        </View>

        {/* Commercial Intelligence */}
        <View style={styles.section} testID="exec-hub-commercial">
          <View style={styles.sectionHeader}>
            <Ionicons name="wallet" size={16} color={theme.color.brand} />
            <Text style={styles.sectionTitle}>COMMERCIAL INTELLIGENCE</Text>
          </View>
          <View style={styles.sectionBody}>
            {commercial ? (
              <>
                <StatLine label="Over budget" value={commercial.projects_over_budget.length} />
                <StatLine label="Approaching budget" value={commercial.projects_approaching_budget.length} />
                <StatLine label="Awaiting payment" value={commercial.projects_awaiting_payment.length} />
                <StatLine label="Large pending variations" value={commercial.large_pending_variations.length} />
                <StatLine label="Cash-flow risk" value={commercial.cash_flow_risk.length} />
                <View style={styles.totalOutstandingBox}>
                  <Text style={styles.mutedText}>Total outstanding, portfolio-wide</Text>
                  <Text style={styles.totalOutstandingValue}>{formatInrShort(commercial.total_outstanding_portfolio_wide)}</Text>
                </View>
              </>
            ) : (
              <Text style={styles.mutedText}>No commercial data available yet.</Text>
            )}
          </View>
        </View>

        {/* Executive Timeline link */}
        <Pressable style={styles.section} onPress={() => router.push('/executive-timeline')} testID="exec-hub-timeline">
          <View style={styles.sectionHeader}>
            <Ionicons name="time" size={16} color={theme.color.brand} />
            <Text style={styles.sectionTitle}>EXECUTIVE TIMELINE</Text>
            <Ionicons name="chevron-forward" size={16} color={theme.color.textDim} />
          </View>
          <View style={styles.sectionBody}>
            <Text style={styles.mutedText}>One chronological history across Commercial, Operations, Workflow, and Reality.</Text>
          </View>
        </Pressable>
      </ScrollView>
    </SafeAreaView>
  );
}

function StatLine({ label, value }: { label: string; value: number }) {
  return (
    <View style={styles.statLine}>
      <Text style={styles.mutedText}>{label}</Text>
      <Text style={[styles.statValue, value > 0 && { color: theme.color.warning }]}>{value}</Text>
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
  sectionTitle: { color: theme.color.text, fontSize: 13, fontWeight: '800', letterSpacing: 0.5, flex: 1 },
  sectionBody: { paddingHorizontal: theme.spacing.md, paddingBottom: theme.spacing.md, gap: 6 },
  mutedText: { color: theme.color.textDim, fontSize: 13 },
  rowText: { color: theme.color.text, fontSize: 13 },
  patternRow: { marginBottom: 6 },
  patternMeta: { color: theme.color.textDim, fontSize: 11, marginTop: 2 },
  statLine: { flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between' },
  statValue: { color: theme.color.text, fontSize: 14, fontWeight: '800' },
  totalOutstandingBox: {
    flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between',
    marginTop: 8, paddingTop: 8, borderTopWidth: 1, borderTopColor: theme.color.border,
  },
  totalOutstandingValue: { color: theme.color.text, fontSize: 16, fontWeight: '800' },
});
