// UI Integration Sprint (UI-01) — Portfolio Summary widget, added to
// the existing Admin Dashboard (Home tab), not a new screen. Renders
// exactly what GET /api/portfolio/control-center's own summary
// already computes — no client-side calculation of any total.
import { useEffect, useState } from 'react';
import { View, Text, StyleSheet, ActivityIndicator } from 'react-native';
import { Ionicons } from '@expo/vector-icons';
import { theme } from './theme';
import { apiPortfolioControlCenter, type PortfolioSummary } from './cre_api';
import { URGENCY_COLOR } from './urgency';

function formatInr(n: number | null): string {
  if (n == null) return 'Not Available Yet';
  if (n >= 10000000) return `₹${(n / 10000000).toFixed(2)} Cr`;
  if (n >= 100000) return `₹${(n / 100000).toFixed(1)}L`;
  return `₹${n.toLocaleString('en-IN')}`;
}

export function PortfolioSummaryWidget() {
  const [summary, setSummary] = useState<PortfolioSummary | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    apiPortfolioControlCenter().then((r) => { setSummary(r.summary); setLoading(false); })
      .catch(() => setLoading(false));
  }, []);

  if (loading) return <View style={styles.loader}><ActivityIndicator color={theme.color.brand} /></View>;
  if (!summary) return null;

  return (
    <View style={styles.card} testID="portfolio-summary-widget">
      <View style={styles.headerRow}>
        <Ionicons name="business" size={16} color={theme.color.brand} />
        <Text style={styles.headerText}>PORTFOLIO SUMMARY</Text>
      </View>

      <View style={styles.healthRow}>
        <HealthPill label="Healthy" value={summary.healthy} color={URGENCY_COLOR.on_track} />
        <HealthPill label="Attention" value={summary.attention} color={URGENCY_COLOR.due_soon} />
        <HealthPill label="Critical" value={summary.critical} color={URGENCY_COLOR.overdue} />
        <HealthPill label="Active" value={summary.active_projects} />
      </View>

      <View style={styles.financialRow}>
        <FinancialLine label="Total Contract Value" value={formatInr(summary.total_contract_value)} />
        <FinancialLine label="Total Forecast" value={formatInr(summary.total_forecast_cost)} />
        <FinancialLine label="Total Outstanding Receivables" value={formatInr(summary.total_outstanding_receivables)} unavailable={summary.total_outstanding_receivables == null} />
      </View>
    </View>
  );
}

function HealthPill({ label, value, color }: { label: string; value: number; color?: string }) {
  return (
    <View style={styles.pill}>
      <Text style={[styles.pillValue, color ? { color } : null]}>{value}</Text>
      <Text style={styles.pillLabel}>{label}</Text>
    </View>
  );
}

function FinancialLine({ label, value, unavailable }: { label: string; value: string; unavailable?: boolean }) {
  return (
    <View style={styles.financialLine}>
      <Text style={styles.financialLabel}>{label}</Text>
      <Text style={[styles.financialValue, unavailable && styles.financialValueUnavailable]}>{value}</Text>
    </View>
  );
}

const styles = StyleSheet.create({
  loader: { paddingVertical: theme.spacing.md, alignItems: 'center' },
  card: {
    backgroundColor: theme.color.surface2, borderRadius: theme.radius.lg, padding: theme.spacing.sm,
    borderWidth: 1, borderColor: theme.color.border, marginBottom: theme.spacing.md,
  },
  headerRow: { flexDirection: 'row', alignItems: 'center', gap: 8, marginBottom: theme.spacing.sm },
  headerText: { color: theme.color.text, fontSize: 12, fontWeight: '900', letterSpacing: 1 },
  healthRow: { flexDirection: 'row', justifyContent: 'space-around', marginBottom: theme.spacing.sm, paddingBottom: theme.spacing.sm, borderBottomWidth: 1, borderBottomColor: theme.color.border },
  pill: { alignItems: 'center' },
  pillValue: { color: theme.color.text, fontSize: 20, fontWeight: '900' },
  pillLabel: { color: theme.color.textDim, fontSize: 10, fontWeight: '700' },
  financialRow: { gap: 4 },
  financialLine: { flexDirection: 'row', justifyContent: 'space-between', alignItems: 'center' },
  financialLabel: { color: theme.color.textDim, fontSize: 12 },
  financialValue: { color: theme.color.text, fontSize: 13, fontWeight: '800' },
  financialValueUnavailable: { color: theme.color.textDim, fontWeight: '400', fontStyle: 'italic', fontSize: 11 },
});
