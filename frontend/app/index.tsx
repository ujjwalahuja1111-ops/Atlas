import { useEffect, useState } from 'react';
import { Redirect } from 'expo-router';
import { View, ActivityIndicator, StyleSheet } from 'react-native';
import { loadAuth, isApprovedAndActive } from '@/src/api';
import { theme } from '@/src/theme';

export default function Index() {
  const [ready, setReady] = useState(false);
  const [dest, setDest] = useState<'/login' | '/pending' | '/(tabs)'>('/login');

  useEffect(() => {
    (async () => {
      const { token, user } = await loadAuth();
      if (!token) {
        setDest('/login');
      } else if (!isApprovedAndActive(user)) {
        // Sprint 4.1: a locally-stored token from a pending/rejected/
        // deactivated account should land on the Pending screen, not the
        // app shell — this is the actual enforcement of "no automatic
        // project access" for anyone who isn't approved yet.
        setDest('/pending');
      } else {
        setDest('/(tabs)');
      }
      setReady(true);
    })();
  }, []);

  if (!ready) {
    return (
      <View style={styles.c} testID="boot-loader">
        <ActivityIndicator size="large" color={theme.color.brand} />
      </View>
    );
  }
  return <Redirect href={dest} />;
}

const styles = StyleSheet.create({
  c: { flex: 1, backgroundColor: theme.color.surface, alignItems: 'center', justifyContent: 'center' },
});
