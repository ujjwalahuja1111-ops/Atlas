// Portfolio Control Center (Phase 1 — schedule-based monitoring only).
// Presentation only: every number rendered here comes from the backend's
// portfolio_control_center() composition of existing CRE outputs (see
// engines/reasoning_engine.py). This screen adds no computation of its
// own — it formats and lays out what the endpoint already returned.
import { useCallback, useEffect, useState } from 'react';
import { View, Text, StyleSheet, ScrollView, Pressable, ActivityIndicator, RefreshControl } from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import { Ionicons } from '@expo/vector-icons';
import { useRouter } from 'expo-router';
import { theme } from '@/src/theme';
import { getViewRole, type ViewRole } from '@/src/roles';
import { apiPortfolioControlCenter, type PortfolioControlCenter, type PortfolioProjectRow } from '@/src/cre_api';

const HEALTH_COLOR: Record<string, string> = {
  Healthy: theme.color.success, Attention: theme.color.warning, Critical: theme.color.error,
};
const HEALTH_ICON: Record<string, any> = {
  Healthy: 'checkmark-circle', Attention: 'alert-circle', Critical: 'warning',
};

function formatDate(iso: string | null): string {
  if (!iso) return '—';
  try { return new Date(iso).toLocaleDateString(undefined, { year: 'numeric', month: 'short', day: 'numeric' }); }
  catch { return '—'; }
}

function formatVariance(days: number | null): string {
  if (days === null) return '—';
  if (days === 0) return 'On schedule';
  const rounded = Math.round(Math.abs(days));
  return days > 0 ? `${rounded}d behind` : `${rounded}d ahead`;
}

export default function PortfolioControlCenterScreen() {
  const router = useRouter();
  const [viewRole, setViewRole] = useState<ViewRole | null>(null);
  const [data, setData] = useState<PortfolioControlCenter | null>(null);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [loadError, setLoadError] = useState<string | null>(null);

  useEffect(() => { getViewRole().then(setViewRole); }, []);

  const load = useCallback(async () => {
    setLoadError(null);
    try {
      const result = await apiPortfolioControlCenter();
      setData(result);
    } catch (e: any) {
      console.warn(e);
      setLoadError(e?.message || 'Could not load the Portfolio Control Center. Tap to retry.');
    } finally {
      setLoading(false); setRefreshing(false);
    }
  }, []);

  useEffect(() => { if (viewRole === 'admin') load(); else if (viewRole !== null) setLoading(false); }, [viewRole, load]);

  if (viewRole === null) {
    return (
      <SafeAreaView style={styles.safe}><View style={styles.center}>
        <ActivityIndicator color={theme.color.brand} />
      </View></SafeAreaView>
    );
  }

  if (viewRole !== 'admin') {
    return (
      <SafeAreaView style={styles.safe} edges={['top']}>
        <View style={styles.center}>
          <Ionicons name="lock-closed-outline" size={48} color={theme.color.textDim} />
          <Text style={styles.emptyTitle}>Admin access required</Text>
          <Text style={styles.emptyBody}>The Portfolio Control Center is a Management-only workspace.</Text>
        </View>
      </SafeAreaView>
    );
  }

  return (
    <SafeAreaView style={styles.safe} edges={['top']}>
      <View style={styles.header}>
        <Pressable testID="portfolio-back" onPress={() => router.back()} style={styles.iconBtn}>
          <Ionicons name="arrow-back" size={24} color={theme.color.text} />
        </Pressable>
        <View style={{ flex: 1 }}>
          <Text style={styles.h1}>PORTFOLIO CONTROL CENTER</Text>
          <Text style={styles.h2}>Schedule-based portfolio health · Management</Text>
        </View>
        <Pressable testID="portfolio-refresh" onPress={load} style={styles.iconBtn}>
          <Ionicons name="refresh" size={22} color={theme.color.brand} />
        </Pressable>
      </View>

      {loadError && (
        <Pressable testID="portfolio-load-error" onPress={load} style={styles.errorBanner}>
          <Ionicons name="warning" size={16} color={theme.color.error} />
          <Text style={styles.errorBannerText} numberOfLines={2}>{loadError} Tap to retry.</Text>
        </Pressable>
      )}

      {loading ? (
        <View style={styles.center}><ActivityIndicator size="large" color={theme.color.brand} /></View>
      ) : (
        <ScrollView
          contentContainerStyle={styles.body}
          refreshControl={<RefreshControl refreshing={refreshing} onRefresh={() => { setRefreshing(true); load(); }} tintColor={theme.color.brand} />}
        >
          {data && <SummaryRow summary={data.summary} />}

          <Text style={styles.sectionLabel}>ACTIVE PROJECTS</Text>
          {!data || data.projects.length === 0 ? (
            <View style={styles.empty} testID="portfolio-empty">
              <Ionicons name="business-outline" size={64} color={theme.color.brand} />
              <Text style={styles.emptyTitle}>No active projects yet</Text>
              <Text style={styles.emptyBody}>Projects will appear here once created.</Text>
            </View>
          ) : (
            data.projects.map((row) => (
              <ProjectRow key={row.project_id} row={row} onPress={() => router.push(`/projects/${row.project_id}`)} />
            ))
          )}
        </ScrollView>
      )}
    </SafeAreaView>
  );
}

function SummaryRow({ summary }: { summary: PortfolioControlCenter['summary'] }) {
  return (
    <View style={styles.summaryGrid} testID="portfolio-summary">
      <SummaryTile icon="business" label="ACTIVE PROJECTS" value={summary.active_projects} />
      <SummaryTile icon="checkmark-circle" label="HEALTHY" value={summary.healthy} color={theme.color.success} />
      <SummaryTile icon="alert-circle" label="ATTENTION" value={summary.attention} color={theme.color.warning} />
      <SummaryTile icon="warning" label="CRITICAL" value={summary.critical} color={theme.color.error} />
      <SummaryTile icon="time" label="BEHIND SCHEDULE" value={summary.projects_behind_schedule} />
      <SummaryTile icon="checkmark-done" label="PENDING APPROVALS" value={summary.pending_client_approvals} />
      <SummaryTile icon="flag" label="CRITICAL ITEMS" value={summary.critical_operational_items} color={theme.color.error} />
    </View>
  );
}

function SummaryTile({ icon, label, value, color }: { icon: any; label: string; value: number; color?: string }) {
  return (
    <View style={styles.tile}>
      <Ionicons name={icon} size={18} color={color || theme.color.brand} />
      <Text style={[styles.tileValue, color ? { color } : null]}>{value}</Text>
      <Text style={styles.tileLabel}>{label}</Text>
    </View>
  );
}

function ProjectRow({ row, onPress }: { row: PortfolioProjectRow; onPress: () => void }) {
  return (
    <Pressable testID={`portfolio-row-${row.project_id}`} onPress={onPress} style={styles.card}>
      <View style={styles.cardHead}>
        <Text style={styles.cardTitle} numberOfLines={1}>{row.project_name}</Text>
        <View style={[styles.healthBadge, { borderColor: HEALTH_COLOR[row.health_status] }]}>
          <Ionicons name={HEALTH_ICON[row.health_status]} size={14} color={HEALTH_COLOR[row.health_status]} />
          <Text style={[styles.healthBadgeText, { color: HEALTH_COLOR[row.health_status] }]}>{row.health_status}</Text>
        </View>
      </View>

      <View style={styles.progressRow}>
        <View style={styles.progressBarBg}>
          <View style={[styles.progressBarFill, {
            width: `${row.progress_percent ?? 0}%`,
            backgroundColor: HEALTH_COLOR[row.health_status],
          }]} />
        </View>
        <Text style={styles.progressPct}>{row.progress_percent !== null ? `${row.progress_percent}%` : '—'}</Text>
      </View>

      <View style={styles.explanationBox} testID={`portfolio-explanation-${row.project_id}`}>
        {row.health_explanation.map((line, i) => (
          <View key={i} style={styles.explanationRow}>
            <Text style={[styles.explanationBullet, { color: HEALTH_COLOR[row.health_status] }]}>•</Text>
            <Text style={styles.explanationText} numberOfLines={1}>{line}</Text>
          </View>
        ))}
      </View>

      <View style={styles.metaGrid}>
        <Meta label="PLANNED" value={formatDate(row.planned_completion)} />
        <Meta label="FORECAST" value={formatDate(row.forecast_completion)} />
        <Meta label="VARIANCE" value={formatVariance(row.schedule_variance_days)}
          valueColor={row.schedule_variance_days && row.schedule_variance_days > 0 ? theme.color.error : undefined} />
      </View>

      <View style={styles.metaGrid}>
        <Meta label="CRITICAL ISSUES" value={String(row.critical_issues_count)} />
        <Meta label="OPEN ITEMS" value={String(row.open_operational_items)} />
        <Meta label="PENDING APPROVALS" value={String(row.pending_client_approvals)} />
      </View>

      {row.next_milestone && (
        <View style={styles.milestoneRow}>
          <Ionicons name="flag-outline" size={14} color={theme.color.textDim} />
          <Text style={styles.milestoneText} numberOfLines={1}>Next: {row.next_milestone}</Text>
        </View>
      )}

      {/* Future Ready — Phase 2 placeholders, visibly disabled, no data. */}
      {!row.financials.enabled && (
        <View style={styles.financialsPlaceholder} testID={`portfolio-financials-disabled-${row.project_id}`}>
          <Ionicons name="lock-closed-outline" size={12} color={theme.color.textDim} />
          <Text style={styles.financialsPlaceholderText}>Budget · Cost · Profitability — coming soon</Text>
        </View>
      )}
    </Pressable>
  );
}

function Meta({ label, value, valueColor }: { label: string; value: string; valueColor?: string }) {
  return (
    <View style={styles.metaItem}>
      <Text style={styles.metaLabel}>{label}</Text>
      <Text style={[styles.metaValue, valueColor ? { color: valueColor } : null]} numberOfLines={1}>{value}</Text>
    </View>
  );
}

const styles = StyleSheet.create({
  safe: { flex: 1, backgroundColor: theme.color.surface },
  center: { flex: 1, alignItems: 'center', justifyContent: 'center', gap: 8, padding: theme.spacing.lg },
  header: { flexDirection: 'row', alignItems: 'center', padding: theme.spacing.md, gap: theme.spacing.sm },
  iconBtn: {
    width: 44, height: 44, borderRadius: 22, backgroundColor: theme.color.surface2,
    alignItems: 'center', justifyContent: 'center',
  },
  h1: { color: theme.color.text, fontSize: 16, fontWeight: '900', letterSpacing: 1 },
  h2: { color: theme.color.textDim, fontSize: 12, marginTop: 2 },
  errorBanner: {
    flexDirection: 'row', alignItems: 'center', gap: 8, marginHorizontal: theme.spacing.md,
    marginBottom: theme.spacing.sm, padding: theme.spacing.sm, borderRadius: theme.radius.sm,
    backgroundColor: theme.color.surface2, borderWidth: 1, borderColor: theme.color.error,
  },
  errorBannerText: { color: theme.color.error, fontSize: 13, flex: 1 },
  body: { padding: theme.spacing.md, paddingBottom: 120, gap: theme.spacing.md },
  sectionLabel: { color: theme.color.textDim, fontSize: 12, fontWeight: '800', letterSpacing: 1, marginTop: 4 },
  empty: { alignItems: 'center', justifyContent: 'center', gap: 8, paddingVertical: theme.spacing.xl },
  emptyTitle: { color: theme.color.text, fontSize: 16, fontWeight: '800' },
  emptyBody: { color: theme.color.textDim, fontSize: 13, textAlign: 'center' },

  summaryGrid: { flexDirection: 'row', flexWrap: 'wrap', gap: theme.spacing.sm },
  tile: {
    flexBasis: '31%', flexGrow: 1, backgroundColor: theme.color.surface2, borderRadius: theme.radius.md,
    borderWidth: 1, borderColor: theme.color.border, padding: theme.spacing.sm, gap: 2, alignItems: 'flex-start',
  },
  tileValue: { color: theme.color.text, fontSize: 22, fontWeight: '900' },
  tileLabel: { color: theme.color.textDim, fontSize: 10, fontWeight: '700', letterSpacing: 0.5 },

  card: {
    backgroundColor: theme.color.surface2, borderRadius: theme.radius.md, borderWidth: 1,
    borderColor: theme.color.border, padding: theme.spacing.md, gap: theme.spacing.sm,
  },
  cardHead: { flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between', gap: 8 },
  cardTitle: { color: theme.color.text, fontSize: 15, fontWeight: '800', flex: 1 },
  healthBadge: {
    flexDirection: 'row', alignItems: 'center', gap: 4, borderWidth: 1, borderRadius: theme.radius.sm,
    paddingHorizontal: 8, paddingVertical: 3,
  },
  healthBadgeText: { fontSize: 11, fontWeight: '800' },

  progressRow: { flexDirection: 'row', alignItems: 'center', gap: 8 },
  progressBarBg: { flex: 1, height: 8, borderRadius: 4, backgroundColor: theme.color.surface3, overflow: 'hidden' },
  progressBarFill: { height: '100%', borderRadius: 4 },
  progressPct: { color: theme.color.text, fontSize: 12, fontWeight: '800', minWidth: 36, textAlign: 'right' },

  explanationBox: { gap: 2 },
  explanationRow: { flexDirection: 'row', alignItems: 'center', gap: 6 },
  explanationBullet: { fontSize: 13, fontWeight: '900' },
  explanationText: { color: theme.color.textMuted, fontSize: 12, flex: 1 },

  metaGrid: { flexDirection: 'row', gap: theme.spacing.md },
  metaItem: { flex: 1 },
  metaLabel: { color: theme.color.textDim, fontSize: 9, fontWeight: '800', letterSpacing: 0.5 },
  metaValue: { color: theme.color.text, fontSize: 13, fontWeight: '700', marginTop: 1 },

  milestoneRow: { flexDirection: 'row', alignItems: 'center', gap: 6 },
  milestoneText: { color: theme.color.textDim, fontSize: 12, flex: 1 },

  financialsPlaceholder: {
    flexDirection: 'row', alignItems: 'center', gap: 6, paddingTop: theme.spacing.sm,
    borderTopWidth: 1, borderTopColor: theme.color.border, opacity: 0.5,
  },
  financialsPlaceholderText: { color: theme.color.textDim, fontSize: 11, fontStyle: 'italic' },
});
