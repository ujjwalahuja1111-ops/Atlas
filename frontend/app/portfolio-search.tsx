import { useState } from 'react';
import { View, Text, StyleSheet, ScrollView, Pressable, ActivityIndicator, TextInput } from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import { Ionicons } from '@expo/vector-icons';
import { useRouter } from 'expo-router';
import { theme } from '@/src/theme';
import { apiPortfolioSearch, type PortfolioSearchResult } from '@/src/cre_api';

export default function PortfolioSearchScreen() {
  const router = useRouter();
  const [query, setQuery] = useState('');
  const [result, setResult] = useState<PortfolioSearchResult | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const onSearch = async (q: string) => {
    setQuery(q);
    if (q.trim().length < 2) { setResult(null); return; }
    setLoading(true);
    setError(null);
    try {
      setResult(await apiPortfolioSearch(q.trim()));
    } catch {
      setError('Search failed. Try again.');
    } finally {
      setLoading(false);
    }
  };

  return (
    <SafeAreaView style={styles.container} edges={['top']}>
      <View style={styles.header}>
        <Pressable onPress={() => router.back()} hitSlop={12} testID="portfolio-search-back">
          <Ionicons name="chevron-back" size={26} color={theme.color.text} />
        </Pressable>
        <Text style={styles.headerTitle}>Search</Text>
        <View style={{ width: 26 }} />
      </View>

      <View style={styles.searchBox}>
        <Ionicons name="search" size={18} color={theme.color.textDim} />
        <TextInput
          testID="portfolio-search-input"
          style={styles.searchInput}
          placeholder="Projects, sites, activities, items, variations, payments…"
          placeholderTextColor={theme.color.textDim}
          value={query}
          onChangeText={onSearch}
          autoFocus
        />
        {loading && <ActivityIndicator size="small" color={theme.color.brand} />}
      </View>

      {error ? <Text style={styles.errorText}>{error}</Text> : null}

      <ScrollView contentContainerStyle={styles.content}>
        {!result ? (
          <Text style={styles.mutedText}>Type at least 2 characters to search.</Text>
        ) : result.total_results === 0 ? (
          <Text style={styles.mutedText}>No results for "{result.query}".</Text>
        ) : (
          <>
            <ResultSection title="PROJECTS" items={result.projects}
              labelFor={(x) => x.name} onPress={(x) => router.push(`/projects/${x.id}/workspace`)} />
            <ResultSection title="SITES" items={result.sites}
              labelFor={(x) => x.name} onPress={(x) => router.push(`/projects/${x.project_id}/workspace`)} />
            <ResultSection title="WORKFLOW ACTIVITIES" items={result.activities}
              labelFor={(x) => x.name} onPress={(x) => router.push(`/workflow/${x.project_id}`)} />
            <ResultSection title="OPERATIONAL ITEMS" items={result.operational_items}
              labelFor={(x) => x.title} onPress={(x) => router.push(`/op/${x.id}`)} />
            <ResultSection title="VARIATIONS" items={result.variations}
              labelFor={(x) => x.title} onPress={(x) => router.push(`/commercial/${x.project_id}`)} />
            <ResultSection title="PAYMENTS" items={result.payments}
              labelFor={(x) => x.reference || x.id} onPress={(x) => router.push(`/commercial/${x.project_id}`)} />
          </>
        )}
      </ScrollView>
    </SafeAreaView>
  );
}

function ResultSection<T extends { id: string }>({ title, items, labelFor, onPress }: {
  title: string; items: T[]; labelFor: (x: T) => string; onPress: (x: T) => void;
}) {
  if (items.length === 0) return null;
  return (
    <View style={styles.section}>
      <Text style={styles.sectionTitle}>{title} ({items.length})</Text>
      {items.map((x) => (
        <Pressable key={x.id} testID={`search-result-${x.id}`} onPress={() => onPress(x)} style={styles.row}>
          <Text style={styles.rowText} numberOfLines={1}>{labelFor(x)}</Text>
          <Ionicons name="chevron-forward" size={16} color={theme.color.textDim} />
        </Pressable>
      ))}
    </View>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1, backgroundColor: theme.color.surface },
  header: {
    flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between',
    paddingHorizontal: theme.spacing.lg, paddingVertical: theme.spacing.md,
  },
  headerTitle: { color: theme.color.text, fontSize: 18, fontWeight: '800' },
  searchBox: {
    flexDirection: 'row', alignItems: 'center', gap: 8, marginHorizontal: theme.spacing.lg,
    paddingHorizontal: 12, paddingVertical: 10, borderRadius: theme.radius.sm,
    backgroundColor: theme.color.surface2, marginBottom: theme.spacing.sm,
  },
  searchInput: { flex: 1, color: theme.color.text, fontSize: 15 },
  errorText: { color: theme.color.error, fontSize: 13, marginHorizontal: theme.spacing.lg, marginBottom: 8 },
  content: { padding: theme.spacing.lg, paddingTop: 0, paddingBottom: 60, gap: theme.spacing.md },
  mutedText: { color: theme.color.textDim, fontSize: 13 },
  section: { gap: 2 },
  sectionTitle: { color: theme.color.brand, fontSize: 11, fontWeight: '800', letterSpacing: 0.5, marginBottom: 4 },
  row: { flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between', paddingVertical: 8 },
  rowText: { color: theme.color.text, fontSize: 14, flex: 1 },
});
