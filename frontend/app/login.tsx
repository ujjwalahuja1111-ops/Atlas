import { useState } from 'react';
import {
  View, Text, TextInput, Pressable, StyleSheet, KeyboardAvoidingView,
  Platform, ActivityIndicator, ImageBackground, ScrollView,
} from 'react-native';
import { LinearGradient } from 'expo-linear-gradient';
import { useRouter } from 'expo-router';
import { Ionicons } from '@expo/vector-icons';
import { theme } from '@/src/theme';
import { apiLogin, saveAuth, apiSeedDemo } from '@/src/api';
import {
  BACKEND_ROLE_FOR, VIEW_ROLE_ICON, VIEW_ROLE_LABEL, setViewRole,
  type ViewRole,
} from '@/src/roles';

const VIEW_ROLES: ViewRole[] = ['client', 'supervisor', 'pm', 'admin'];

export default function LoginScreen() {
  const router = useRouter();
  const [phone, setPhone] = useState('');
  const [name, setName] = useState('');
  const [viewRole, setViewRoleState] = useState<ViewRole>('supervisor');
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');

  const onContinue = async () => {
    if (phone.trim().length < 6 || !name.trim()) {
      setError('Enter your name and phone');
      return;
    }
    setLoading(true); setError('');
    try {
      const backendRole = BACKEND_ROLE_FOR[viewRole];
      const res = await apiLogin(phone.trim(), name.trim(), backendRole);
      await saveAuth(res.token, res.user);
      await setViewRole(viewRole);
      apiSeedDemo().catch(() => {});
      router.replace('/(tabs)');
    } catch (e: any) {
      setError(e?.message || 'Login failed');
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
            <Text style={styles.label}>Your Name</Text>
            <TextInput
              testID="login-name-input"
              value={name} onChangeText={setName}
              placeholder="Rajesh Kumar" placeholderTextColor={theme.color.textDim}
              style={styles.input} autoCapitalize="words"
            />
            <Text style={styles.label}>Phone Number</Text>
            <TextInput
              testID="login-phone-input"
              value={phone} onChangeText={setPhone}
              placeholder="98765 43210" placeholderTextColor={theme.color.textDim}
              keyboardType="phone-pad" style={styles.input}
            />
            <Text style={styles.label}>Role</Text>
            <View style={styles.roleRow}>
              {VIEW_ROLES.map((r) => {
                const active = viewRole === r;
                return (
                  <Pressable
                    key={r} testID={`role-${r}`}
                    onPress={() => setViewRoleState(r)}
                    style={[styles.roleChip, active && styles.roleChipActive]}
                  >
                    <Ionicons name={VIEW_ROLE_ICON[r]} size={20}
                      color={active ? theme.color.onBrand : theme.color.textMuted} />
                    <Text style={[styles.roleText, active && styles.roleTextActive]}>{VIEW_ROLE_LABEL[r]}</Text>
                  </Pressable>
                );
              })}
            </View>
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
                <Text style={styles.ctaText}>CONTINUE</Text>
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
  label: { color: theme.color.textMuted, fontSize: 14, fontWeight: '700', marginTop: theme.spacing.sm, letterSpacing: 1 },
  input: {
    height: theme.touch, backgroundColor: theme.color.surface2, borderRadius: theme.radius.md,
    paddingHorizontal: theme.spacing.md, color: theme.color.text, fontSize: 20, borderWidth: 1,
    borderColor: theme.color.border,
  },
  roleRow: { flexDirection: 'row', gap: theme.spacing.sm },
  roleChip: {
    flex: 1, height: theme.touch, borderRadius: theme.radius.md,
    borderWidth: 2, borderColor: theme.color.border, backgroundColor: theme.color.surface2,
    alignItems: 'center', justifyContent: 'center', gap: 4,
  },
  roleChipActive: { backgroundColor: theme.color.brand, borderColor: theme.color.brand },
  roleText: { color: theme.color.textMuted, fontSize: 12, fontWeight: '700' },
  roleTextActive: { color: theme.color.onBrand },
  cta: {
    height: 72, borderRadius: theme.radius.md, backgroundColor: theme.color.brand,
    flexDirection: 'row', alignItems: 'center', justifyContent: 'center', gap: theme.spacing.sm,
  },
  ctaText: { color: theme.color.onBrand, fontSize: 22, fontWeight: '900', letterSpacing: 2 },
  error: { color: theme.color.error, fontSize: 14, marginTop: 8, fontWeight: '600' },
});
