import { useEffect, useState } from 'react';
import { View, Text, StyleSheet, Pressable, ActivityIndicator } from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import { Ionicons } from '@expo/vector-icons';
import { useRouter } from 'expo-router';
import { theme } from '@/src/theme';
import { loadAuth, clearAuth, isApprovedAndActive, type User } from '@/src/api';
import { clearViewRole, completeLoginRouting } from '@/src/roles';
import { apiFetch, authHeaders } from '@/src/http';

/**
 * Sprint 4.1 — blocking screen shown to any account that isn't approved and
 * active (a brand-new Sign Up, or an existing account an Administrator has
 * rejected/deactivated). No project or workspace data is fetched or shown
 * here — that's the actual enforcement of "new users must not receive
 * access to any project automatically."
 *
 * The person can manually refresh to check whether an Administrator has
 * approved them yet (there's no push mechanism in this pilot), or log out.
 */
export default function PendingApprovalScreen() {
  const router = useRouter();
  const [user, setUser] = useState<User | null>(null);
  const [checking, setChecking] = useState(false);

  useEffect(() => { loadAuth().then(({ user }) => setUser(user)); }, []);

  const checkAgain = async () => {
    setChecking(true);
    try {
      const BACKEND = process.env.EXPO_PUBLIC_BACKEND_URL;
      const r = await apiFetch(`${BACKEND}/api/me`, { headers: await authHeaders() });
      if (r.ok) {
        const fresh: User = await r.json();
        setUser(fresh);
        if (isApprovedAndActive(fresh)) {
          await completeLoginRouting(fresh.phone, fresh);
          router.replace('/(tabs)');
          return;
        }
      }
    } catch (e) { console.warn(e); }
    finally { setChecking(false); }
  };

  const logout = async () => {
    await clearAuth();
    await clearViewRole();
    router.replace('/login');
  };

  const status = user?.approval_status;

  return (
    <SafeAreaView style={styles.safe}>
      <View style={styles.center}>
        <View style={styles.badge}>
          <Ionicons name={status === 'rejected' ? 'close-circle' : 'time'} size={48}
            color={status === 'rejected' ? theme.color.error : theme.color.brand} />
        </View>
        <Text style={styles.title}>
          {status === 'rejected' ? 'Access Denied'
            : user && user.is_active === false ? 'Account Deactivated'
            : 'Awaiting Approval'}
        </Text>
        <Text style={styles.body}>
          {status === 'rejected'
            ? 'An Administrator has declined this account. Contact your Atlas Administrator if you believe this is a mistake.'
            : user && user.is_active === false
            ? 'This account has been deactivated by an Administrator.'
            : `Hi ${user?.name || ''}. Your account has been created but needs to be approved by an Administrator before you can access Atlas. You'll be assigned a role and project once approved.`}
        </Text>

        {status !== 'rejected' && user?.is_active !== false && (
          <Pressable testID="pending-check-again" onPress={checkAgain} disabled={checking} style={styles.checkBtn}>
            {checking ? <ActivityIndicator color={theme.color.onBrand} /> : (
              <>
                <Ionicons name="refresh" size={20} color={theme.color.onBrand} />
                <Text style={styles.checkBtnText}>CHECK AGAIN</Text>
              </>
            )}
          </Pressable>
        )}

        <Pressable testID="pending-logout" onPress={logout} style={styles.logoutBtn}>
          <Ionicons name="log-out-outline" size={20} color={theme.color.error} />
          <Text style={styles.logoutText}>LOG OUT</Text>
        </Pressable>
      </View>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  safe: { flex: 1, backgroundColor: theme.color.surface },
  center: { flex: 1, alignItems: 'center', justifyContent: 'center', padding: theme.spacing.xl, gap: theme.spacing.md },
  badge: {
    width: 96, height: 96, borderRadius: 48, backgroundColor: theme.color.surface2,
    alignItems: 'center', justifyContent: 'center', borderWidth: 1, borderColor: theme.color.border,
  },
  title: { color: theme.color.text, fontSize: 24, fontWeight: '900', letterSpacing: 1, textAlign: 'center' },
  body: { color: theme.color.textMuted, fontSize: 15, textAlign: 'center', lineHeight: 22 },
  checkBtn: {
    flexDirection: 'row', alignItems: 'center', gap: 8, height: 56, paddingHorizontal: theme.spacing.lg,
    borderRadius: theme.radius.md, backgroundColor: theme.color.brand, marginTop: theme.spacing.md,
  },
  checkBtnText: { color: theme.color.onBrand, fontSize: 15, fontWeight: '900', letterSpacing: 1 },
  logoutBtn: {
    flexDirection: 'row', alignItems: 'center', gap: 8, height: 56, paddingHorizontal: theme.spacing.lg,
    borderRadius: theme.radius.md, borderWidth: 2, borderColor: theme.color.error, marginTop: theme.spacing.sm,
  },
  logoutText: { color: theme.color.error, fontSize: 15, fontWeight: '900', letterSpacing: 1 },
});
