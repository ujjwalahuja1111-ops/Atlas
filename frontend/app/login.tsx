import { useState } from 'react';
import {
  View, Text, TextInput, Pressable, StyleSheet, KeyboardAvoidingView,
  Platform, ActivityIndicator, ImageBackground,
} from 'react-native';
import { LinearGradient } from 'expo-linear-gradient';
import { useRouter } from 'expo-router';
import { Ionicons } from '@expo/vector-icons';
import { theme } from '@/src/theme';
import { apiLogin, apiRegister, saveAuth, apiSeedDemo, isApprovedAndActive } from '@/src/api';
import { resolveLoginRole, completeLoginRouting, VIEW_ROLE_LABEL, type ViewRole } from '@/src/roles';

type Mode = 'login' | 'signup';

// Sprint 4.3 — "User Type" collected at Sign Up. Every value here is a
// ViewRole so it lines up 1:1 with the admin-assignable Workspace options
// (Client / Supervisor / Project Manager / Admin) — this is purely a
// REQUEST though; see the hint text below and apiRegister's docstring.
const USER_TYPES: ViewRole[] = ['client', 'supervisor', 'pm', 'admin'];

export default function LoginScreen() {
  const router = useRouter();
  const [mode, setMode] = useState<Mode>('login');
  const [phone, setPhone] = useState('');
  const [name, setName] = useState('');
  const [userType, setUserType] = useState<ViewRole>('supervisor');
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');

  const onContinue = async () => {
    if (phone.trim().length < 6 || !name.trim()) {
      setError('Enter your name and phone');
      return;
    }
    setLoading(true); setError('');
    try {
      if (mode === 'signup') {
        // Sprint 4.1: Sign Up creates a brand-new, pending account with no
        // role or project access — an Administrator must approve it via
        // User Management before it can do anything. We still save the
        // session (so /api/me works) but route to the Pending Approval
        // screen instead of the normal workspace. Sprint 4.3: `userType`
        // is sent as `requested_workspace` — purely a hint for the admin,
        // never auto-applied (see apiRegister's docstring).
        const res = await apiRegister(phone.trim(), name.trim(), userType);
        await saveAuth(res.token, res.user);
        router.replace('/pending');
        return;
      }

      // Sprint 4 cleanup: no manual workspace picker. We resolve which
      // backend role to authenticate as (returning phone number on this
      // device -> its last-known role; brand-new phone -> the same safe
      // default the backend itself uses), then auto-route into the
      // matching workspace using the AUTHORITATIVE role the backend hands
      // back — see src/roles.ts for the single, centralized mapping.
      const guessedRole = await resolveLoginRole(phone.trim());
      const res = await apiLogin(phone.trim(), name.trim(), guessedRole);
      await saveAuth(res.token, res.user);

      // Sprint 4.1: an account can be pending/rejected/deactivated even via
      // the plain login path (e.g. they registered earlier and haven't been
      // approved yet, or were deactivated after being approved). Route them
      // to the Pending screen instead of a workspace either way.
      if (!isApprovedAndActive(res.user)) {
        router.replace('/pending');
        return;
      }

      await completeLoginRouting(phone.trim(), res.user);
      apiSeedDemo().catch(() => {});
      router.replace('/(tabs)');
    } catch (e: any) {
      setError(e?.message || (mode === 'signup' ? 'Sign up failed' : 'Login failed'));
    } finally { setLoading(false); }
  };

  return (
    <KeyboardAvoidingView style={{ flex: 1 }} behavior={Platform.OS === 'ios' ? 'padding' : undefined}>
      <ImageBackground
        source={{ uri: 'https://images.pexels.com/photos/17770160/pexels-photo-17770160.jpeg' }}
        style={styles.bg} resizeMode="cover"
      >
        <LinearGradient
          colors={['rgba(18,18,18,0.4)', 'rgba(18,18,18,0.95)', '#121212']}
          style={StyleSheet.absoluteFill}
        />
        <View style={styles.container}>
          <View style={styles.header}>
            <View style={styles.logoBadge}>
              <Ionicons name="construct" size={36} color={theme.color.onBrand} />
            </View>
            <Text style={styles.brand}>ATLAS</Text>
            <Text style={styles.tagline}>Construction Intelligence</Text>
          </View>

          <View style={styles.form}>
            <View style={styles.modeRow}>
              <Pressable testID="mode-login" onPress={() => { setMode('login'); setError(''); }}
                style={[styles.modeChip, mode === 'login' && styles.modeChipActive]}>
                <Text style={[styles.modeChipText, mode === 'login' && styles.modeChipTextActive]}>LOG IN</Text>
              </Pressable>
              <Pressable testID="mode-signup" onPress={() => { setMode('signup'); setError(''); }}
                style={[styles.modeChip, mode === 'signup' && styles.modeChipActive]}>
                <Text style={[styles.modeChipText, mode === 'signup' && styles.modeChipTextActive]}>SIGN UP</Text>
              </Pressable>
            </View>

            <Text style={styles.label}>Your Name</Text>
            <TextInput
              testID="login-name-input"
              value={name} onChangeText={setName}
              placeholder="Rajesh Kumar" placeholderTextColor={theme.color.textDim}
              style={styles.input} autoCapitalize="words"
            />
            {mode === 'login' && (
              // Sprint 6.2 Identity Security fix: logging in never changes an
              // existing account's stored name (or role) — this field is
              // only ever used if this phone turns out to be brand new.
              // Backend enforcement lives in memory_engine.upsert_user();
              // this is just making the same behaviour clear here too.
              <Text style={styles.hint}>
                Only used if this is your first time signing in. To change your
                name later, use Profile.
              </Text>
            )}
            <Text style={styles.label}>Phone Number</Text>
            <TextInput
              testID="login-phone-input"
              value={phone} onChangeText={setPhone}
              placeholder="98765 43210" placeholderTextColor={theme.color.textDim}
              keyboardType="phone-pad" style={styles.input}
            />
            {mode === 'signup' && (
              <>
                <Text style={styles.label}>User Type</Text>
                <View style={styles.typeRow}>
                  {USER_TYPES.map((t) => (
                    <Pressable key={t} testID={`signup-type-${t}`} onPress={() => setUserType(t)}
                      style={[styles.typeChip, userType === t && styles.typeChipActive]}>
                      <Text style={[styles.typeChipText, userType === t && styles.typeChipTextActive]}>
                        {VIEW_ROLE_LABEL[t]}
                      </Text>
                    </Pressable>
                  ))}
                </View>
                <Text style={styles.hint}>
                  Your account will be created with no access yet. An Administrator
                  needs to approve it and assign your workspace, role, and project
                  before you can use Atlas. User Type is just a request — the
                  Administrator makes the final decision.
                </Text>
              </>
            )}
            {error ? <Text style={styles.error} testID="login-error">{error}</Text> : null}
          </View>

          <Pressable
            testID="login-continue-button"
            onPress={onContinue} disabled={loading}
            style={({ pressed }) => [
              styles.cta, pressed && { opacity: 0.85 }, loading && { opacity: 0.6 },
            ]}
          >
            {loading ? <ActivityIndicator color={theme.color.onBrand} /> : (
              <>
                <Text style={styles.ctaText}>{mode === 'signup' ? 'SIGN UP' : 'CONTINUE'}</Text>
                <Ionicons name="arrow-forward" size={28} color={theme.color.onBrand} />
              </>
            )}
          </Pressable>
        </View>
      </ImageBackground>
    </KeyboardAvoidingView>
  );
}

const styles = StyleSheet.create({
  bg: { flex: 1 },
  container: { flex: 1, padding: theme.spacing.lg, justifyContent: 'space-between', paddingTop: 80, paddingBottom: 32 },
  header: { alignItems: 'flex-start' },
  logoBadge: {
    width: 72, height: 72, borderRadius: 18, backgroundColor: theme.color.brand,
    alignItems: 'center', justifyContent: 'center', marginBottom: theme.spacing.md,
  },
  brand: { color: theme.color.text, fontSize: 56, fontWeight: '900', letterSpacing: 4 },
  tagline: { color: theme.color.brand, fontSize: 16, fontWeight: '700', marginTop: 4, letterSpacing: 2 },
  form: { gap: theme.spacing.sm },
  modeRow: { flexDirection: 'row', gap: 8, marginBottom: theme.spacing.sm },
  modeChip: {
    flex: 1, height: 44, borderRadius: theme.radius.md, alignItems: 'center', justifyContent: 'center',
    backgroundColor: theme.color.surface2, borderWidth: 1, borderColor: theme.color.border,
  },
  modeChipActive: { backgroundColor: theme.color.brand, borderColor: theme.color.brand },
  modeChipText: { color: theme.color.textMuted, fontSize: 13, fontWeight: '900', letterSpacing: 1 },
  modeChipTextActive: { color: theme.color.onBrand },
  label: { color: theme.color.textMuted, fontSize: 14, fontWeight: '700', marginTop: theme.spacing.sm, letterSpacing: 1 },
  input: {
    height: theme.touch, backgroundColor: theme.color.surface2, borderRadius: theme.radius.md,
    paddingHorizontal: theme.spacing.md, color: theme.color.text, fontSize: 20, borderWidth: 1,
    borderColor: theme.color.border,
  },
  hint: { color: theme.color.textDim, fontSize: 12, marginTop: 8, lineHeight: 18 },
  typeRow: { flexDirection: 'row', gap: 8, flexWrap: 'wrap' },
  typeChip: {
    flexGrow: 1, minWidth: '47%', height: 44, borderRadius: theme.radius.md,
    alignItems: 'center', justifyContent: 'center',
    backgroundColor: theme.color.surface2, borderWidth: 1, borderColor: theme.color.border,
  },
  typeChipActive: { backgroundColor: theme.color.brand, borderColor: theme.color.brand },
  typeChipText: { color: theme.color.textMuted, fontSize: 13, fontWeight: '900', letterSpacing: 0.5 },
  typeChipTextActive: { color: theme.color.onBrand },
  cta: {
    height: 72, borderRadius: theme.radius.md, backgroundColor: theme.color.brand,
    flexDirection: 'row', alignItems: 'center', justifyContent: 'center', gap: theme.spacing.sm,
  },
  ctaText: { color: theme.color.onBrand, fontSize: 22, fontWeight: '900', letterSpacing: 2 },
  error: { color: theme.color.error, fontSize: 14, marginTop: 8, fontWeight: '600' },
});
