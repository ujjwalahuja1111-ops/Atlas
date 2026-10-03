import { useEffect, useState } from 'react';
import { View, Text, StyleSheet, Pressable, ActivityIndicator, ScrollView, TextInput } from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import { useRouter } from 'expo-router';
import { theme } from '@/src/theme';
import { apiGetWorkspaceStatus, apiProvisionUser, type RoleSlot, type Role, type WorkspaceStatus } from '@/src/api';

/**
 * AI Engine / Role Configuration — Step 3's own "minimum user setup" UX
 * (Section 6). Shows ONLY the role slots the approved configuration
 * actually requires (no "Client" slot unless client access was approved,
 * enforced again on the backend regardless of what this screen renders -
 * Section 19's own "do not treat hiding a navigation item as
 * authorization"). Each real person is added one at a time, explicitly -
 * nothing is auto-generated.
 */
export default function ProvisionTeamScreen() {
  const router = useRouter();
  const [loading, setLoading] = useState(true);
  const [status, setStatus] = useState<WorkspaceStatus | null>(null);
  const [adding, setAdding] = useState<Role | null>(null);
  const [phone, setPhone] = useState('');
  const [name, setName] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  const load = async () => {
    try {
      const s = await apiGetWorkspaceStatus();
      setStatus(s);
      if (!s.configured) {
        router.replace('/business-setup');
      }
    } catch {
      // best-effort — stay on this screen with whatever we already have
    } finally {
      setLoading(false);
    }
  };

  // Run once on mount only, matching business-setup.tsx's own identical pattern.
  // eslint-disable-next-line react-hooks/exhaustive-deps
  useEffect(() => { load(); }, []);

  const startAdding = (role: Role) => {
    setAdding(role); setPhone(''); setName(''); setError(null);
  };

  const submit = async () => {
    if (!adding || !phone.trim() || !name.trim()) return;
    setSubmitting(true); setError(null);
    try {
      await apiProvisionUser(phone.trim(), name.trim(), adding);
      setAdding(null);
      await load();
    } catch (e: any) {
      setError(e?.message || 'Could not add this person.');
    } finally { setSubmitting(false); }
  };

  if (loading || !status?.configured) {
    return (
      <SafeAreaView style={styles.center}>
        <ActivityIndicator color={theme.color.brand} />
      </SafeAreaView>
    );
  }

  const slots: RoleSlot[] = status.role_slots || [];

  return (
    <SafeAreaView style={styles.container}>
      <ScrollView contentContainerStyle={styles.scroll}>
        <Text style={styles.title}>Your required team</Text>
        <Text style={styles.subtitle}>
          Add the actual people who need access. You can add more later from User Management.
        </Text>

        {slots.map(slot => (
          <View key={slot.role} style={styles.card}>
            <View style={styles.slotHeader}>
              <Text style={styles.slotLabel}>{slot.label}</Text>
              <Text style={styles.slotCount}>
                {slot.filled_count > 0 ? `${slot.filled_count} added` : 'Not yet added'}
              </Text>
            </View>

            {adding === slot.role ? (
              <View>
                <TextInput
                  style={styles.input}
                  placeholder="Phone number"
                  placeholderTextColor={theme.color.textDim}
                  keyboardType="phone-pad"
                  value={phone}
                  onChangeText={setPhone}
                />
                <TextInput
                  style={styles.input}
                  placeholder="Name"
                  placeholderTextColor={theme.color.textDim}
                  value={name}
                  onChangeText={setName}
                />
                {error && <Text style={styles.error}>{error}</Text>}
                <View style={styles.row}>
                  <Pressable style={styles.secondaryButton} onPress={() => setAdding(null)}>
                    <Text style={styles.secondaryButtonText}>Cancel</Text>
                  </Pressable>
                  <Pressable
                    style={[styles.smallButton, (!phone.trim() || !name.trim() || submitting) && styles.buttonDisabled]}
                    disabled={!phone.trim() || !name.trim() || submitting}
                    onPress={submit}
                  >
                    {submitting
                      ? <ActivityIndicator color={theme.color.onBrand} />
                      : <Text style={styles.buttonText}>Add</Text>}
                  </Pressable>
                </View>
              </View>
            ) : (
              <Pressable style={styles.addButton} onPress={() => startAdding(slot.role)}>
                <Text style={styles.addButtonText}>+ Add person</Text>
              </Pressable>
            )}
          </View>
        ))}

        <Pressable style={styles.button} onPress={() => router.replace('/(tabs)')}>
          <Text style={styles.buttonText}>
            {status.all_roles_filled ? 'Continue to Atlas' : 'Continue (add the rest later)'}
          </Text>
        </Pressable>
      </ScrollView>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1, backgroundColor: theme.color.surface },
  center: { flex: 1, backgroundColor: theme.color.surface, alignItems: 'center', justifyContent: 'center' },
  scroll: { padding: theme.spacing.xs * 2, paddingBottom: 48 },
  title: { color: theme.color.text, fontSize: 22, fontWeight: '700', marginBottom: 4 },
  subtitle: { color: theme.color.textMuted, fontSize: 14, marginBottom: 16 },
  card: {
    backgroundColor: theme.color.surface2, borderRadius: 12, padding: 16, marginBottom: 12,
    borderWidth: 1, borderColor: theme.color.border,
  },
  slotHeader: { flexDirection: 'row', justifyContent: 'space-between', alignItems: 'center', marginBottom: 8 },
  slotLabel: { color: theme.color.text, fontSize: 16, fontWeight: '600' },
  slotCount: { color: theme.color.textDim, fontSize: 12 },
  input: {
    color: theme.color.text, fontSize: 15, borderWidth: 1, borderColor: theme.color.border,
    borderRadius: 8, padding: 10, marginBottom: 8,
  },
  error: { color: theme.color.error, fontSize: 13, marginBottom: 8 },
  row: { flexDirection: 'row', justifyContent: 'flex-end', gap: 8 },
  addButton: {
    borderWidth: 1, borderColor: theme.color.brand, borderRadius: 8, paddingVertical: 10, alignItems: 'center',
  },
  addButtonText: { color: theme.color.brand, fontSize: 14, fontWeight: '600' },
  smallButton: { backgroundColor: theme.color.brand, borderRadius: 8, paddingVertical: 10, paddingHorizontal: 16 },
  secondaryButton: { paddingVertical: 10, paddingHorizontal: 16 },
  secondaryButtonText: { color: theme.color.textMuted, fontSize: 14 },
  button: { backgroundColor: theme.color.brand, borderRadius: 10, paddingVertical: 14, alignItems: 'center', marginTop: 8 },
  buttonDisabled: { opacity: 0.5 },
  buttonText: { color: theme.color.onBrand, fontSize: 15, fontWeight: '700' },
});
