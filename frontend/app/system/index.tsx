import { useCallback, useEffect, useState } from 'react';
import { View, Text, StyleSheet, ScrollView, Pressable, ActivityIndicator } from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import { Ionicons } from '@expo/vector-icons';
import { useRouter } from 'expo-router';
import { theme } from '@/src/theme';
import { getViewRole, type ViewRole } from '@/src/roles';
import { apiGetSystemInfo, type SystemInfo } from '@/src/admin_system_api';

function formatUptime(seconds: number): string {
  const d = Math.floor(seconds / 86400);
  const h = Math.floor((seconds % 86400) / 3600);
  const m = Math.floor((seconds % 3600) / 60);
  const parts = [];
  if (d) parts.push(`${d}d`);
  if (h) parts.push(`${h}h`);
  parts.push(`${m}m`);
  return parts.join(' ');
}

export default function SystemInfoScreen() {
  const router = useRouter();
  const [viewRole, setViewRole] = useState<ViewRole | null>(null);
  const [info, setInfo] = useState<SystemInfo | null>(null);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState<string | null>(null);

  useEffect(() => { getViewRole().then(setViewRole); }, []);

  const load = useCallback(async () => {
    setLoading(true);
    setLoadError(null);
    try {
      const data = await apiGetSystemInfo();
      setInfo(data);
    } catch (e: any) {
      console.warn(e);
      setLoadError(e?.message || 'Could not load system information. Tap to retry.');
    }
    finally { setLoading(false); }
  }, []);

  useEffect(() => { if (viewRole === 'admin') load(); }, [viewRole, load]);

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
          <Text style={styles.emptyBody}>System Information is an Admin-only workspace.</Text>
        </View>
      </SafeAreaView>
    );
  }

  const dbOk = info?.database_status === 'connected';

  return (
    <SafeAreaView style={styles.safe} edges={['top']}>
      <View style={styles.header}>
        <Pressable testID="system-back" onPress={() => router.back()} style={styles.iconBtn}>
          <Ionicons name="arrow-back" size={24} color={theme.color.text} />
        </Pressable>
        <View style={{ flex: 1 }}>
          <Text style={styles.h1}>SYSTEM INFORMATION</Text>
          <Text style={styles.h2}>Admin workspace · build &amp; health</Text>
        </View>
        <Pressable testID="system-refresh" onPress={load} style={styles.iconBtn}>
          <Ionicons name="refresh" size={22} color={theme.color.brand} />
        </Pressable>
      </View>

      {loadError && (
        <Pressable testID="system-load-error" onPress={load} style={styles.errorBanner}>
          <Ionicons name="warning" size={16} color={theme.color.error} />
          <Text style={styles.errorBannerText} numberOfLines={2}>{loadError} Tap to retry.</Text>
        </Pressable>
      )}

      {loading ? (
        <View style={styles.center}><ActivityIndicator size="large" color={theme.color.brand} /></View>
      ) : !info ? null : (
        <ScrollView contentContainerStyle={{ padding: theme.spacing.md, paddingBottom: 80 }}>
          <View style={styles.statusRow}>
            <StatusPill testID="system-backend-status" label="BACKEND"
              ok={info.backend_status === 'healthy'} value={info.backend_status.toUpperCase()} />
            <StatusPill testID="system-database-status" label="DATABASE"
              ok={dbOk} value={dbOk ? 'CONNECTED' : 'ERROR'} />
          </View>

          <Section title="Build">
            <Row icon="pricetag" label="Atlas Version" value={info.version} testID="system-version" />
            <Row icon="git-branch" label="Git Commit" value={info.git_commit} testID="system-git-commit" />
            <Row icon="calendar" label="Build Date" value={new Date(info.build_date).toLocaleString()} testID="system-build-date" />
            <Row icon="time" label="Server Uptime" value={formatUptime(info.uptime_seconds)} testID="system-uptime" />
          </Section>

          <Section title="Data">
            <Row icon="people" label="Total Users" value={String(info.total_users)} testID="system-total-users" />
            <Row icon="business" label="Total Projects" value={String(info.total_projects)} testID="system-total-projects" />
            <Row icon="location" label="Total Sites" value={String(info.total_sites)} testID="system-total-sites" />
            <Row icon="hourglass" label="Pending Approvals" value={String(info.pending_approvals)}
              testID="system-pending-approvals" highlight={info.pending_approvals > 0} />
          </Section>

          {info.database_status !== 'connected' && (
            <View style={styles.dbErrorBox}>
              <Text style={styles.dbErrorText}>{info.database_status}</Text>
            </View>
          )}
        </ScrollView>
      )}
    </SafeAreaView>
  );
}

function Section({ title, children }: { title: string; children: any }) {
  return (
    <View style={styles.section}>
      <Text style={styles.sectionTitle}>{title.toUpperCase()}</Text>
      {children}
    </View>
  );
}

function Row({ icon, label, value, testID, highlight }: {
  icon: any; label: string; value: string; testID: string; highlight?: boolean;
}) {
  return (
    <View style={styles.row} testID={testID}>
      <Ionicons name={icon} size={20} color={highlight ? theme.color.warning : theme.color.brand} />
      <Text style={styles.rowLabel}>{label}</Text>
      <Text style={[styles.rowValue, highlight && { color: theme.color.warning }]} numberOfLines={1}>{value}</Text>
    </View>
  );
}

function StatusPill({ testID, label, ok, value }: { testID: string; label: string; ok: boolean; value: string }) {
  return (
    <View testID={testID} style={[styles.statusPill, { borderColor: ok ? theme.color.success : theme.color.error }]}>
      <Ionicons name={ok ? 'checkmark-circle' : 'close-circle'} size={18} color={ok ? theme.color.success : theme.color.error} />
      <View>
        <Text style={styles.statusPillLabel}>{label}</Text>
        <Text style={[styles.statusPillValue, { color: ok ? theme.color.success : theme.color.error }]}>{value}</Text>
      </View>
    </View>
  );
}

const styles = StyleSheet.create({
  safe: { flex: 1, backgroundColor: theme.color.surface },
  header: { flexDirection: 'row', alignItems: 'center', padding: theme.spacing.md, gap: theme.spacing.sm },
  h1: { color: theme.color.text, fontSize: 20, fontWeight: '900', letterSpacing: 1 },
  h2: { color: theme.color.brand, fontSize: 11, fontWeight: '700', marginTop: 2 },
  iconBtn: { width: 44, height: 44, borderRadius: 22, backgroundColor: theme.color.surface2,
            alignItems: 'center', justifyContent: 'center' },
  center: { flex: 1, alignItems: 'center', justifyContent: 'center', gap: 8, padding: theme.spacing.lg },
  emptyTitle: { color: theme.color.text, fontSize: 18, fontWeight: '900', letterSpacing: 1, marginTop: 8 },
  emptyBody: { color: theme.color.textMuted, textAlign: 'center' },
  errorBanner: {
    flexDirection: 'row', alignItems: 'center', gap: 8, marginHorizontal: theme.spacing.md,
    marginBottom: theme.spacing.sm, padding: 10, borderRadius: theme.radius.sm,
    backgroundColor: theme.color.surface2, borderWidth: 1, borderColor: theme.color.error,
  },
  errorBannerText: { flex: 1, color: theme.color.error, fontSize: 12, fontWeight: '700' },
  statusRow: { flexDirection: 'row', gap: 10, marginBottom: theme.spacing.md },
  statusPill: { flex: 1, flexDirection: 'row', alignItems: 'center', gap: 10, padding: theme.spacing.md,
               borderRadius: theme.radius.md, borderWidth: 1, backgroundColor: theme.color.surface2 },
  statusPillLabel: { color: theme.color.textDim, fontSize: 10, fontWeight: '900', letterSpacing: 1 },
  statusPillValue: { fontSize: 14, fontWeight: '900', marginTop: 2 },
  section: { backgroundColor: theme.color.surface2, borderRadius: theme.radius.md, borderWidth: 1,
            borderColor: theme.color.border, padding: theme.spacing.md, marginBottom: theme.spacing.md },
  sectionTitle: { color: theme.color.brand, fontSize: 11, fontWeight: '900', letterSpacing: 1, marginBottom: 8 },
  row: { flexDirection: 'row', alignItems: 'center', gap: 10, paddingVertical: 10,
        borderBottomWidth: 1, borderBottomColor: theme.color.border },
  rowLabel: { flex: 1, color: theme.color.textMuted, fontSize: 13, fontWeight: '600' },
  rowValue: { color: theme.color.text, fontSize: 14, fontWeight: '800', maxWidth: '45%' },
  dbErrorBox: { backgroundColor: theme.color.surface2, borderWidth: 1, borderColor: theme.color.error,
               borderRadius: theme.radius.sm, padding: theme.spacing.md },
  dbErrorText: { color: theme.color.error, fontSize: 12, fontFamily: 'monospace' },
});
