import { useEffect, useState } from 'react';
import { View, Text, StyleSheet, Pressable, ActivityIndicator } from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import { Ionicons } from '@expo/vector-icons';
import { useRouter } from 'expo-router';
import { theme } from '@/src/theme';
import { clearAuth, loadAuth, type User } from '@/src/api';

const ROLE_LABEL: Record<string, string> = {
  supervisor: 'Site Supervisor',
  coordinator: 'Project Coordinator',
  management: 'Management',
};

export default function ProfileScreen() {
  const router = useRouter();
  const [user, setUser] = useState<User | null>(null);

  useEffect(() => {
    (async () => {
      const { user } = await loadAuth();
      setUser(user);
    })();
  }, []);

  const logout = async () => {
    await clearAuth();
    router.replace('/login');
  };

  if (!user) {
    return (
      <SafeAreaView style={styles.safe}>
        <ActivityIndicator color={theme.color.brand} />
      </SafeAreaView>
    );
  }

  return (
    <SafeAreaView style={styles.safe} edges={['top']}>
      <View style={styles.header}>
        <Text style={styles.title}>PROFILE</Text>
      </View>

      <View style={styles.card}>
        <View style={styles.avatar}>
          <Ionicons name="person" size={56} color={theme.color.onBrand} />
        </View>
        <Text style={styles.name}>{user.name}</Text>
        <Text style={styles.phone}>{user.phone}</Text>
        <View style={styles.roleTag}>
          <Ionicons name="shield-checkmark" size={16} color={theme.color.onBrand} />
          <Text style={styles.roleText}>{ROLE_LABEL[user.role] || user.role}</Text>
        </View>
      </View>

      <View style={styles.info}>
        <Row icon="business" label="Platform" value="Project Atlas v2" />
        <Row icon="globe" label="Voice languages" value="HI · PA · EN" />
        <Row icon="time" label="Member since" value={new Date(user.created_at).toLocaleDateString()} />
      </View>

      <Pressable testID="logout-button" onPress={logout} style={styles.logoutBtn}>
        <Ionicons name="log-out-outline" size={28} color={theme.color.error} />
        <Text style={styles.logoutText}>LOG OUT</Text>
      </Pressable>
    </SafeAreaView>
  );
}

function Row({ icon, label, value }: { icon: any; label: string; value: string }) {
  return (
    <View style={styles.row}>
      <Ionicons name={icon} size={22} color={theme.color.brand} />
      <View style={{ flex: 1 }}>
        <Text style={styles.rowLabel}>{label}</Text>
        <Text style={styles.rowValue}>{value}</Text>
      </View>
    </View>
  );
}

const styles = StyleSheet.create({
  safe: { flex: 1, backgroundColor: theme.color.surface },
  header: { paddingHorizontal: theme.spacing.lg, paddingTop: theme.spacing.md, paddingBottom: theme.spacing.md },
  title: { color: theme.color.text, fontSize: 32, fontWeight: '900', letterSpacing: 2 },
  card: {
    margin: theme.spacing.md, padding: theme.spacing.lg, backgroundColor: theme.color.surface2,
    borderRadius: theme.radius.lg, alignItems: 'center', gap: theme.spacing.sm, borderWidth: 1, borderColor: theme.color.border,
  },
  avatar: {
    width: 96, height: 96, borderRadius: 48, backgroundColor: theme.color.brand,
    alignItems: 'center', justifyContent: 'center',
  },
  name: { color: theme.color.text, fontSize: 24, fontWeight: '900', letterSpacing: 1 },
  phone: { color: theme.color.textMuted, fontSize: 16, fontWeight: '600' },
  roleTag: {
    flexDirection: 'row', alignItems: 'center', gap: 6, backgroundColor: theme.color.brand,
    paddingHorizontal: theme.spacing.md, paddingVertical: 8, borderRadius: theme.radius.pill, marginTop: 6,
  },
  roleText: { color: theme.color.onBrand, fontSize: 13, fontWeight: '900', letterSpacing: 1 },
  info: { marginHorizontal: theme.spacing.md, gap: theme.spacing.sm },
  row: {
    flexDirection: 'row', alignItems: 'center', gap: theme.spacing.md,
    minHeight: 64, paddingHorizontal: theme.spacing.md, backgroundColor: theme.color.surface2,
    borderRadius: theme.radius.md, borderWidth: 1, borderColor: theme.color.border,
  },
  rowLabel: { color: theme.color.textDim, fontSize: 12, fontWeight: '700', letterSpacing: 1 },
  rowValue: { color: theme.color.text, fontSize: 16, fontWeight: '700', marginTop: 2 },
  logoutBtn: {
    marginTop: 'auto', marginHorizontal: theme.spacing.md, marginBottom: theme.spacing.lg,
    height: 72, borderRadius: theme.radius.md, borderWidth: 2, borderColor: theme.color.error,
    backgroundColor: theme.color.surface2, alignItems: 'center', justifyContent: 'center',
    flexDirection: 'row', gap: theme.spacing.sm,
  },
  logoutText: { color: theme.color.error, fontSize: 18, fontWeight: '900', letterSpacing: 2 },
});
