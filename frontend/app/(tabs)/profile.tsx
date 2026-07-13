import { useEffect, useState } from 'react';
import { View, Text, StyleSheet, Pressable, ActivityIndicator, Modal, TextInput, Alert, ScrollView, KeyboardAvoidingView, Platform } from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import { Ionicons } from '@expo/vector-icons';
import { useRouter } from 'expo-router';
import { theme } from '@/src/theme';
import { clearAuth, loadAuth, saveAuth, apiUpdateMe, type User } from '@/src/api';
import { clearViewRole, getViewRole, VIEW_ROLE_LABEL, type ViewRole } from '@/src/roles';

const ROLE_LABEL: Record<string, string> = {
  management: 'Management',
  project_manager: 'Project Manager',
  site_supervisor: 'Site Supervisor',
  client: 'Client',
};

export default function ProfileScreen() {
  const router = useRouter();
  const [user, setUser] = useState<User | null>(null);
  const [viewRole, setVR] = useState<ViewRole>('supervisor');
  const [editingName, setEditingName] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    (async () => {
      const { user } = await loadAuth();
      setUser(user);
      setVR(await getViewRole());
    })();
  }, []);

  const logout = async () => {
    await clearAuth();
    await clearViewRole();
    router.replace('/login');
  };

  // Sprint 4.1 fix (audit M4): Profile used to be entirely read-only, and
  // the only way to fix a typo'd name was re-logging in — which also
  // silently re-applies whatever role got passed to /auth/login. This uses
  // the new narrow, self-only PATCH /api/me instead.
  const saveName = async () => {
    if (!editingName?.trim() || !user) return;
    setBusy(true);
    try {
      const updated = await apiUpdateMe(editingName.trim());
      setUser(updated);
      const { token } = await loadAuth();
      if (token) await saveAuth(token, updated);
      setEditingName(null);
    } catch (e: any) {
      Alert.alert('Save failed', String(e?.message || e));
    } finally { setBusy(false); }
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

      {/* Sprint 6.1 — mobile scrolling fix: the admin workspace's extra nav
          buttons (Knowledge/Users/System Info) can push total content taller
          than the viewport on real devices, and this screen previously had
          no ScrollView at all — Logout (and anything below the fold) was
          simply unreachable. Wrapping the body guarantees every control
          stays reachable regardless of content height or screen size. */}
      <ScrollView contentContainerStyle={styles.scrollContent} showsVerticalScrollIndicator={false}>
        <View style={styles.card}>
          <View style={styles.avatar}>
            <Ionicons name="person" size={56} color={theme.color.onBrand} />
          </View>
          <View style={styles.nameRow}>
            <Text style={styles.name}>{user.name}</Text>
            <Pressable testID="edit-name-button" onPress={() => setEditingName(user.name)} style={styles.editNameBtn}>
              <Ionicons name="pencil" size={16} color={theme.color.brand} />
            </Pressable>
          </View>
          <Text style={styles.phone}>{user.phone}</Text>
          <View style={styles.roleTag}>
            <Ionicons name="shield-checkmark" size={16} color={theme.color.onBrand} />
            <Text style={styles.roleText}>{VIEW_ROLE_LABEL[viewRole]}</Text>
          </View>
        </View>

        <View style={styles.info}>
          <Row icon="business" label="Workspace" value={VIEW_ROLE_LABEL[viewRole]} />
          <Row icon="key" label="Backend role" value={ROLE_LABEL[user.role] || user.role} />
          <Row icon="globe" label="Voice languages" value="HI · PA · EN" />
          <Row icon="time" label="Member since" value={new Date(user.created_at).toLocaleDateString()} />
        </View>

        {viewRole === 'admin' && (
          <>
            <Pressable testID="open-knowledge" onPress={() => router.push('/knowledge')} style={styles.knowledgeBtn}>
              <Ionicons name="library-outline" size={22} color={theme.color.brand} />
              <Text style={styles.knowledgeText}>CONSTRUCTION KNOWLEDGE</Text>
              <Ionicons name="chevron-forward" size={18} color={theme.color.textDim} />
            </Pressable>
            <Pressable testID="open-user-management" onPress={() => router.push('/users')} style={styles.knowledgeBtn}>
              <Ionicons name="people-outline" size={22} color={theme.color.brand} />
              <Text style={styles.knowledgeText}>USER MANAGEMENT</Text>
              <Ionicons name="chevron-forward" size={18} color={theme.color.textDim} />
            </Pressable>
            <Pressable testID="open-system-info" onPress={() => router.push('/system')} style={styles.knowledgeBtn}>
              <Ionicons name="hardware-chip-outline" size={22} color={theme.color.brand} />
              <Text style={styles.knowledgeText}>SYSTEM INFORMATION</Text>
              <Ionicons name="chevron-forward" size={18} color={theme.color.textDim} />
            </Pressable>
          </>
        )}

        <Pressable testID="logout-button" onPress={logout} style={styles.logoutBtn}>
          <Ionicons name="log-out-outline" size={28} color={theme.color.error} />
          <Text style={styles.logoutText}>LOG OUT</Text>
        </Pressable>
      </ScrollView>

      <Modal visible={editingName !== null} animationType="slide" transparent onRequestClose={() => setEditingName(null)}>
        <KeyboardAvoidingView style={{ flex: 1 }} behavior={Platform.OS === 'ios' ? 'padding' : undefined}>
        <View style={styles.modalBack}>
          <View style={styles.modal}>
            <View style={styles.modalHead}>
              <Text style={styles.modalTitle}>EDIT NAME</Text>
              <Pressable onPress={() => setEditingName(null)}>
                <Ionicons name="close" size={26} color={theme.color.textDim} />
              </Pressable>
            </View>
            <TextInput
              testID="edit-name-input"
              value={editingName || ''} onChangeText={setEditingName}
              placeholderTextColor={theme.color.textDim}
              style={styles.input} autoCapitalize="words"
            />
            <Pressable testID="edit-name-save" onPress={saveName} disabled={busy || !editingName?.trim()}
              style={[styles.saveBtn, (busy || !editingName?.trim()) && { opacity: 0.5 }]}>
              <Ionicons name="checkmark" size={22} color={theme.color.onBrand} />
              <Text style={styles.saveBtnText}>SAVE</Text>
            </Pressable>
          </View>
        </View>
        </KeyboardAvoidingView>
      </Modal>
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
  nameRow: { flexDirection: 'row', alignItems: 'center', gap: 8 },
  name: { color: theme.color.text, fontSize: 24, fontWeight: '900', letterSpacing: 1 },
  editNameBtn: { width: 32, height: 32, borderRadius: 16, backgroundColor: theme.color.surface3,
                alignItems: 'center', justifyContent: 'center' },
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
  knowledgeBtn: {
    flexDirection: 'row', alignItems: 'center', gap: theme.spacing.sm,
    marginHorizontal: theme.spacing.md, marginTop: theme.spacing.md,
    minHeight: 56, paddingHorizontal: theme.spacing.md, backgroundColor: theme.color.surface2,
    borderRadius: theme.radius.md, borderWidth: 1, borderColor: theme.color.border,
  },
  knowledgeText: { flex: 1, color: theme.color.text, fontSize: 13, fontWeight: '800', letterSpacing: 0.5 },
  logoutBtn: {
    marginTop: theme.spacing.lg, marginHorizontal: theme.spacing.md, marginBottom: theme.spacing.lg,
    height: 72, borderRadius: theme.radius.md, borderWidth: 2, borderColor: theme.color.error,
    backgroundColor: theme.color.surface2, alignItems: 'center', justifyContent: 'center',
    flexDirection: 'row', gap: theme.spacing.sm,
  },
  scrollContent: { flexGrow: 1, paddingBottom: theme.spacing.lg },
  logoutText: { color: theme.color.error, fontSize: 18, fontWeight: '900', letterSpacing: 2 },
  modalBack: { flex: 1, backgroundColor: 'rgba(0,0,0,0.6)', justifyContent: 'flex-end' },
  modal: { backgroundColor: theme.color.surface, borderTopLeftRadius: 18, borderTopRightRadius: 18,
          padding: theme.spacing.lg, gap: 10 },
  modalHead: { flexDirection: 'row', alignItems: 'center', marginBottom: theme.spacing.sm },
  modalTitle: { flex: 1, color: theme.color.brand, fontSize: 14, fontWeight: '900', letterSpacing: 2 },
  input: { color: theme.color.text, backgroundColor: theme.color.surface2,
          borderRadius: theme.radius.sm, borderWidth: 1, borderColor: theme.color.border,
          paddingHorizontal: 12, paddingVertical: 10, fontSize: 15 },
  saveBtn: { marginTop: theme.spacing.sm, flexDirection: 'row', alignItems: 'center', justifyContent: 'center',
            gap: 8, height: 52, borderRadius: theme.radius.md, backgroundColor: theme.color.brand },
  saveBtnText: { color: theme.color.onBrand, fontSize: 16, fontWeight: '900', letterSpacing: 1 },
});
