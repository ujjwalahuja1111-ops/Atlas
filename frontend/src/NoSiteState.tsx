import { View, Text, Pressable, StyleSheet } from 'react-native';
import { Ionicons } from '@expo/vector-icons';
import { useRouter } from 'expo-router';
import { theme } from './theme';
import { VIEW_PERMS, type ViewRole } from './roles';
import { noSiteState } from './noSiteState';

// Shared empty state for "this user has no project/site yet" (Home, Client
// dashboard, Capture). The message and the optional create action come from
// the pure noSiteState(); the action reuses the existing /projects/new wizard.
export function NoSiteState({ role }: { role: ViewRole }) {
  const router = useRouter();
  const s = noSiteState(role, VIEW_PERMS[role].canManageProjects);
  return (
    <View style={styles.wrap} testID="no-site-state">
      <Ionicons name="folder-open-outline" size={64} color={theme.color.brand} />
      <Text style={styles.title} testID="no-site-title">{s.title}</Text>
      <Text style={styles.body}>{s.body}</Text>
      {s.action && (
        <Pressable testID="no-site-create" onPress={() => router.push(s.action!.route)} style={styles.cta}>
          <Text style={styles.ctaText}>{s.action.label}</Text>
        </Pressable>
      )}
    </View>
  );
}

const styles = StyleSheet.create({
  wrap: { alignItems: 'center', justifyContent: 'center', padding: 24, gap: 10, flex: 1 },
  title: { color: theme.color.text, fontSize: 20, fontWeight: '900', textAlign: 'center', marginTop: 8 },
  body: { color: theme.color.textMuted, textAlign: 'center', fontSize: 14, lineHeight: 20 },
  cta: { backgroundColor: theme.color.brand, borderRadius: 10, paddingVertical: 14, paddingHorizontal: 24, marginTop: 8 },
  ctaText: { color: theme.color.onBrand, fontSize: 16, fontWeight: '900', letterSpacing: 1 },
});
