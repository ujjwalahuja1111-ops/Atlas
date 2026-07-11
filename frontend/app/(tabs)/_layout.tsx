import { useEffect, useState } from 'react';
import { Tabs } from 'expo-router';
import { Ionicons } from '@expo/vector-icons';
import { View, StyleSheet, ActivityIndicator } from 'react-native';
import { theme } from '@/src/theme';
import { TABS_FOR, getViewRole, completeLoginRouting, type TabDef, type ViewRole } from '@/src/roles';
import { loadAuth, saveAuth, apiGetMe } from '@/src/api';

/** Sprint-3: role-based tab bar.
 * A single Tabs.Screen list is declared for every possible screen, but each
 * screen's visibility is toggled via `href: null` when it's not part of the
 * current role's tab spec. No screens are duplicated. */
export default function TabLayout() {
  const [role, setRole] = useState<ViewRole | null>(null);

  useEffect(() => {
    getViewRole().then(setRole);
    // Sprint 6.2 Founder Verification fix — self-heal the locally cached
    // workspace/role from the server's current truth every time the tab
    // bar mounts (app open, returning from a detail screen to the tab
    // root, etc). getViewRole()/loadAuth() only ever read a value cached
    // ONCE at login (roles.ts completeLoginRouting) — an admin changing a
    // user's workspace or role mid-session was completely invisible on
    // that device until it explicitly logged out and back in. This was
    // the root cause behind two separate founder-reported symptoms at
    // once: a client account still showing supervisor/coordinator
    // action buttons (stale cache said "supervisor"), and the Capture
    // tab (and its Text option) appearing to not exist for an account
    // that should have it (stale cache said "client", which hides
    // Capture entirely). Best-effort and silent: if it fails (offline,
    // token expired, etc.) the value getViewRole() already returned
    // above keeps the tab bar working exactly as before this fix.
    (async () => {
      try {
        const auth = await loadAuth();
        if (!auth.token || !auth.user) return;
        const fresh = await apiGetMe();
        await saveAuth(auth.token, fresh);
        const freshRole = await completeLoginRouting(fresh.phone, fresh);
        setRole(freshRole);
      } catch {
        // offline / expired token / etc — fall through silently, the
        // cached role above already rendered a working tab bar.
      }
    })();
  }, []);

  if (!role) {
    return (
      <View style={styles.loading}>
        <ActivityIndicator size="large" color={theme.color.brand} />
      </View>
    );
  }

  const tabs = TABS_FOR[role];
  const byName: Record<string, TabDef | undefined> = Object.fromEntries(
    tabs.map((t) => [t.name, t])
  );

  const hidden = { href: null as any };

  return (
    <Tabs
      screenOptions={{
        headerShown: false,
        tabBarActiveTintColor: theme.color.brand,
        tabBarInactiveTintColor: theme.color.textDim,
        tabBarStyle: {
          backgroundColor: theme.color.surface2,
          borderTopColor: theme.color.border,
          borderTopWidth: 1,
          height: 80, paddingBottom: 16, paddingTop: 8,
        },
        tabBarLabelStyle: { fontSize: 11, fontWeight: '700', letterSpacing: 0.5 },
      }}
    >
      <Tabs.Screen name="index" options={
        byName.index ? {
          title: byName.index.label,
          tabBarIcon: ({ color, focused }) => (
            <Ionicons name={renderIcon(byName.index!.icon, focused)} size={26} color={color} />
          ),
        } : hidden
      } />
      <Tabs.Screen name="ops" options={
        byName.ops ? {
          title: byName.ops.label,
          tabBarIcon: ({ color, focused }) => (
            <Ionicons name={renderIcon(byName.ops!.icon, focused)} size={26} color={color} />
          ),
        } : hidden
      } />
      <Tabs.Screen name="capture" options={
        byName.capture ? {
          title: byName.capture.label,
          tabBarIcon: ({ focused }) => (
            <View style={[styles.capWrap, focused && styles.capWrapActive]}>
              <Ionicons name="mic" size={30} color={focused ? theme.color.onBrand : theme.color.text} />
            </View>
          ),
        } : hidden
      } />
      <Tabs.Screen name="profile" options={
        byName.profile ? {
          title: byName.profile.label,
          tabBarIcon: ({ color, focused }) => (
            <Ionicons name={renderIcon(byName.profile!.icon, focused)} size={26} color={color} />
          ),
        } : hidden
      } />
    </Tabs>
  );
}

function renderIcon(base: string, focused: boolean): any {
  return focused ? base : `${base}-outline`;
}

const styles = StyleSheet.create({
  loading: { flex: 1, alignItems: 'center', justifyContent: 'center',
             backgroundColor: theme.color.surface },
  capWrap: {
    width: 56, height: 56, borderRadius: 28, backgroundColor: theme.color.surface3,
    alignItems: 'center', justifyContent: 'center', marginTop: -16,
    borderWidth: 2, borderColor: theme.color.border,
  },
  capWrapActive: { backgroundColor: theme.color.brand, borderColor: theme.color.brand },
});
