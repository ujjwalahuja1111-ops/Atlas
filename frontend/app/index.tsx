import { useEffect, useState } from 'react';
import { Redirect } from 'expo-router';
import { View, ActivityIndicator, StyleSheet } from 'react-native';
import { loadAuth } from '@/src/api';
import { theme } from '@/src/theme';

export default function Index() {
  const [ready, setReady] = useState(false);
  const [authed, setAuthed] = useState(false);

  useEffect(() => {
    (async () => {
      const { token } = await loadAuth();
      setAuthed(!!token);
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
  return authed ? <Redirect href="/(tabs)" /> : <Redirect href="/login" />;
}

const styles = StyleSheet.create({
  c: { flex: 1, backgroundColor: theme.color.surface, alignItems: 'center', justifyContent: 'center' },
});
