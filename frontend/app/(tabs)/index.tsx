import { useCallback, useEffect, useRef, useState } from 'react';
import {
  View, Text, StyleSheet, FlatList, Pressable, ScrollView,
  ActivityIndicator, RefreshControl,
} from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import { Image as ExpoImage } from 'expo-image';
import { Ionicons } from '@expo/vector-icons';
import { useRouter, useFocusEffect } from 'expo-router';
import { theme } from '@/src/theme';
import {
  apiListSites, apiListProjects, apiTimeline, apiSeedDemo,
  getActiveSite, setActiveSite,
  type Site, type Project, type TimelineItem,
} from '@/src/api';

const TYPE_ICON: Record<string, any> = {
  voice_note: 'mic', photo: 'camera', material_request: 'cube',
  issue: 'warning', work_completed: 'checkmark-done', general: 'document-text',
};
const TYPE_COLOR: Record<string, string> = {
  voice_note: theme.color.brand, photo: theme.color.info,
  material_request: '#9C27B0', issue: theme.color.error,
  work_completed: theme.color.success, general: theme.color.textMuted,
};
const TYPE_LABEL: Record<string, string> = {
  voice_note: 'VOICE', photo: 'PHOTO', material_request: 'MATERIAL',
  issue: 'ISSUE', work_completed: 'DONE', general: 'NOTE',
};

function timeAgo(iso: string) {
  const diff = Math.floor((Date.now() - new Date(iso).getTime()) / 1000);
  if (diff < 60) return `${diff}s ago`;
  if (diff < 3600) return `${Math.floor(diff / 60)}m ago`;
  if (diff < 86400) return `${Math.floor(diff / 3600)}h ago`;
  return `${Math.floor(diff / 86400)}d ago`;
}

export default function TimelineScreen() {
  const router = useRouter();
  const [sites, setSites] = useState<Site[]>([]);
  const [projectMap, setProjectMap] = useState<Record<string, Project>>({});
  const [activeSiteId, setActiveSiteIdState] = useState<string | null>(null);
  const [items, setItems] = useState<TimelineItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const pollRef = useRef<any>(null);

  const stopPolling = () => { if (pollRef.current) { clearInterval(pollRef.current); pollRef.current = null; } };

  const fetchTimeline = useCallback(async (siteId: string) => {
    try {
      const t = await apiTimeline(siteId);
      setItems(t);
      const hasPending = t.some((i) => i.event.ai_status === 'pending');
      if (hasPending && !pollRef.current) {
        pollRef.current = setInterval(async () => {
          try {
            const tt = await apiTimeline(siteId);
            setItems(tt);
            if (!tt.some((x) => x.event.ai_status === 'pending')) stopPolling();
          } catch {}
        }, 4000);
      } else if (!hasPending) {
        stopPolling();
      }
    } catch (e) {
      console.warn(e);
    }
  }, []);

  const loadAll = useCallback(async () => {
    try {
      let s = await apiListSites();
      if (s.length === 0) {
        await apiSeedDemo();
        s = await apiListSites();
      }
      setSites(s);
      const projects = await apiListProjects();
      const pmap: Record<string, Project> = {};
      for (const p of projects) pmap[p.id] = p;
      setProjectMap(pmap);

      const stored = await getActiveSite();
      const active = stored && s.find((x) => x.id === stored) ? stored : s[0]?.id || null;
      setActiveSiteIdState(active);
      if (active) {
        await setActiveSite(active);
        await fetchTimeline(active);
      } else {
        setItems([]);
      }
    } catch (e) {
      console.warn(e);
    } finally {
      setLoading(false); setRefreshing(false);
    }
  }, [fetchTimeline]);

  useFocusEffect(useCallback(() => {
    loadAll();
    return () => stopPolling();
  }, [loadAll]));

  useEffect(() => () => stopPolling(), []);

  const onSelectSite = async (id: string) => {
    stopPolling();
    setActiveSiteIdState(id);
    await setActiveSite(id);
    setLoading(true);
    await fetchTimeline(id);
    setLoading(false);
  };

  const activeSite = sites.find((s) => s.id === activeSiteId);
  const activeProject = activeSite ? projectMap[activeSite.project_id] : null;

  return (
    <SafeAreaView style={styles.safe} edges={['top']}>
      <View style={styles.header}>
        <View style={{ flex: 1 }}>
          <Text style={styles.h1}>TIMELINE</Text>
          <Text style={styles.h2} numberOfLines={1}>
            {activeProject ? `${activeProject.name} · ` : ''}{activeSite?.name || 'No site'}
          </Text>
        </View>
        <Pressable testID="open-projects" onPress={() => router.push('/projects')} style={styles.projBtn}>
          <Ionicons name="folder-open" size={20} color={theme.color.brand} />
          <Text style={styles.projBtnText}>PROJECTS</Text>
        </Pressable>
      </View>

      <View style={styles.chipsContainer}>
        <ScrollView horizontal showsHorizontalScrollIndicator={false}
          contentContainerStyle={styles.chipsContent}>
          {sites.map((s) => {
            const active = s.id === activeSiteId;
            const proj = projectMap[s.project_id];
            return (
              <Pressable
                key={s.id} testID={`site-chip-${s.id}`}
                onPress={() => onSelectSite(s.id)}
                style={[styles.chip, active && styles.chipActive]}
              >
                <Ionicons name="business" size={18}
                  color={active ? theme.color.onBrand : theme.color.textMuted} />
                <View style={{ flexShrink: 1 }}>
                  <Text style={[styles.chipText, active && styles.chipTextActive]} numberOfLines={1}>
                    {s.name}
                  </Text>
                  {proj ? (
                    <Text style={[styles.chipSub, active && { color: theme.color.onBrand, opacity: 0.85 }]} numberOfLines={1}>
                      {proj.name}
                    </Text>
                  ) : null}
                </View>
              </Pressable>
            );
          })}
        </ScrollView>
      </View>

      {loading ? (
        <View style={styles.loader} testID="timeline-loader">
          <ActivityIndicator size="large" color={theme.color.brand} />
        </View>
      ) : items.length === 0 ? (
        <View style={styles.empty} testID="timeline-empty">
          <Ionicons name="mic-circle-outline" size={80} color={theme.color.brand} />
          <Text style={styles.emptyTitle}>No events yet</Text>
          <Text style={styles.emptyBody}>Tap CAPTURE to record reality.</Text>
          <Pressable testID="timeline-empty-capture"
            onPress={() => router.push('/(tabs)/capture')} style={styles.emptyCta}>
            <Ionicons name="mic" size={28} color={theme.color.onBrand} />
            <Text style={styles.emptyCtaText}>START CAPTURE</Text>
          </Pressable>
        </View>
      ) : (
        <FlatList
          testID="timeline-list"
          data={items}
          keyExtractor={(i) => i.event.id}
          renderItem={({ item, index }) => (
            <TimelineRow item={item} isLast={index === items.length - 1} onPress={() => router.push(`/event/${item.event.id}`)} />
          )}
          contentContainerStyle={{ padding: theme.spacing.md, paddingBottom: 120 }}
          refreshControl={
            <RefreshControl refreshing={refreshing}
              onRefresh={() => { setRefreshing(true); loadAll(); }}
              tintColor={theme.color.brand} />
          }
        />
      )}
    </SafeAreaView>
  );
}

function TimelineRow({ item, isLast, onPress }: { item: TimelineItem; isLast: boolean; onPress: () => void }) {
  const evt = item.event;
  const analysis = item.analysis;
  const aiType = analysis?.structured?.type || (evt.kind === 'voice' ? 'voice_note' : evt.kind === 'photo' ? 'photo' : 'general');
  const color = TYPE_COLOR[aiType] || theme.color.brand;
  const title = analysis?.structured?.title || (evt.text_input ? evt.text_input.slice(0, 60) : 'Captured event');
  const summary = analysis?.structured?.summary || evt.text_input || '';
  return (
    <Pressable testID={`event-card-${evt.id}`} onPress={onPress} style={rowStyles.row}>
      <View style={rowStyles.timeline}>
        <View style={[rowStyles.node, { backgroundColor: color }]}>
          <Ionicons name={TYPE_ICON[aiType] || 'document-text'} size={20} color="#fff" />
        </View>
        {!isLast && <View style={rowStyles.line} />}
      </View>
      <View style={rowStyles.card}>
        <View style={rowStyles.head}>
          <View style={[rowStyles.typeTag, { backgroundColor: color }]}>
            <Text style={rowStyles.typeText}>{TYPE_LABEL[aiType] || 'EVENT'}</Text>
          </View>
          <AiStatusBadge status={evt.ai_status} />
          <Text style={rowStyles.timeAgo}>{timeAgo(evt.server_created_at)}</Text>
        </View>
        <Text style={rowStyles.title} numberOfLines={2}>{title}</Text>
        {summary ? <Text style={rowStyles.body} numberOfLines={3}>{summary}</Text> : null}
        {item.photo_thumbs && item.photo_thumbs.length > 0 ? (
          <ExpoImage
            source={{ uri: `data:image/jpeg;base64,${item.photo_thumbs[0].base64}` }}
            style={rowStyles.thumb} contentFit="cover"
          />
        ) : null}
        <View style={rowStyles.foot}>
          <Ionicons name="person-circle-outline" size={18} color={theme.color.textDim} />
          <Text style={rowStyles.byline}>{evt.user_name || 'Unknown'}</Text>
          {analysis?.language_detected ? (
            <>
              <Text style={rowStyles.dot}>•</Text>
              <Text style={rowStyles.byline}>{analysis.language_detected}</Text>
            </>
          ) : null}
          {evt.gps ? (
            <>
              <Text style={rowStyles.dot}>•</Text>
              <Ionicons name="location" size={12} color={theme.color.textDim} />
              <Text style={rowStyles.byline}>GPS</Text>
            </>
          ) : null}
        </View>
      </View>
    </Pressable>
  );
}

function AiStatusBadge({ status }: { status: string }) {
  if (status === 'analyzed') return null; // implicit success
  const styles2 = {
    pending: { bg: theme.color.surface3, fg: theme.color.brand, icon: 'sync' as const, label: 'ANALYZING' },
    failed:  { bg: theme.color.surface3, fg: theme.color.error, icon: 'warning' as const, label: 'AI FAILED' },
    skipped: { bg: theme.color.surface3, fg: theme.color.textDim, icon: 'remove' as const, label: 'NO AI' },
  }[status as 'pending' | 'failed' | 'skipped'] || null;
  if (!styles2) return null;
  return (
    <View style={[badge.wrap, { backgroundColor: styles2.bg, borderColor: styles2.fg }]}>
      <Ionicons name={styles2.icon} size={12} color={styles2.fg} />
      <Text style={[badge.text, { color: styles2.fg }]}>{styles2.label}</Text>
    </View>
  );
}

const badge = StyleSheet.create({
  wrap: { flexDirection: 'row', alignItems: 'center', gap: 4, paddingHorizontal: 8, paddingVertical: 2, borderRadius: 6, borderWidth: 1 },
  text: { fontSize: 10, fontWeight: '900', letterSpacing: 1 },
});

const styles = StyleSheet.create({
  safe: { flex: 1, backgroundColor: theme.color.surface },
  header: { flexDirection: 'row', alignItems: 'center', gap: 8, paddingHorizontal: theme.spacing.lg, paddingTop: theme.spacing.md, paddingBottom: theme.spacing.sm },
  h1: { color: theme.color.text, fontSize: 32, fontWeight: '900', letterSpacing: 2 },
  h2: { color: theme.color.brand, fontSize: 15, fontWeight: '700', marginTop: 2 },
  projBtn: { flexDirection: 'row', alignItems: 'center', gap: 6, paddingHorizontal: 12, height: 36,
             borderRadius: theme.radius.pill, borderWidth: 1, borderColor: theme.color.brand,
             backgroundColor: theme.color.surface2 },
  projBtnText: { color: theme.color.brand, fontSize: 11, fontWeight: '900', letterSpacing: 1 },
  chipsContainer: { height: 72, marginBottom: theme.spacing.sm },
  chipsContent: { paddingHorizontal: theme.spacing.md, gap: theme.spacing.sm, alignItems: 'center' },
  chip: {
    height: 56, paddingHorizontal: theme.spacing.md, borderRadius: theme.radius.md,
    backgroundColor: theme.color.surface2, borderWidth: 1, borderColor: theme.color.border,
    flexDirection: 'row', alignItems: 'center', gap: 8, flexShrink: 0, maxWidth: 260,
  },
  chipActive: { backgroundColor: theme.color.brand, borderColor: theme.color.brand },
  chipText: { color: theme.color.text, fontSize: 14, fontWeight: '800' },
  chipSub: { color: theme.color.textDim, fontSize: 11, fontWeight: '600', marginTop: 1 },
  chipTextActive: { color: theme.color.onBrand },
  loader: { flex: 1, alignItems: 'center', justifyContent: 'center' },
  empty: { flex: 1, alignItems: 'center', justifyContent: 'center', padding: theme.spacing.xl, gap: theme.spacing.md },
  emptyTitle: { color: theme.color.text, fontSize: 24, fontWeight: '900', letterSpacing: 1 },
  emptyBody: { color: theme.color.textMuted, fontSize: 16, textAlign: 'center' },
  emptyCta: {
    marginTop: theme.spacing.md, height: 64, paddingHorizontal: theme.spacing.lg,
    backgroundColor: theme.color.brand, borderRadius: theme.radius.md, flexDirection: 'row',
    alignItems: 'center', gap: theme.spacing.sm,
  },
  emptyCtaText: { color: theme.color.onBrand, fontSize: 18, fontWeight: '900', letterSpacing: 1 },
});

const rowStyles = StyleSheet.create({
  row: { flexDirection: 'row', marginBottom: theme.spacing.md },
  timeline: { width: 56, alignItems: 'center' },
  node: {
    width: 44, height: 44, borderRadius: 22, alignItems: 'center', justifyContent: 'center',
    borderWidth: 3, borderColor: theme.color.surface,
  },
  line: { width: 3, flex: 1, backgroundColor: theme.color.border, marginTop: 4 },
  card: {
    flex: 1, backgroundColor: theme.color.surface2, borderRadius: theme.radius.md,
    padding: theme.spacing.md, borderWidth: 1, borderColor: theme.color.border, gap: 8,
  },
  head: { flexDirection: 'row', alignItems: 'center', gap: 8, flexWrap: 'wrap' },
  typeTag: { paddingHorizontal: 10, paddingVertical: 4, borderRadius: theme.radius.sm },
  typeText: { color: '#fff', fontSize: 11, fontWeight: '900', letterSpacing: 1 },
  timeAgo: { color: theme.color.textDim, fontSize: 12, fontWeight: '600', marginLeft: 'auto' },
  title: { color: theme.color.text, fontSize: 18, fontWeight: '800' },
  body: { color: theme.color.textMuted, fontSize: 15, lineHeight: 22 },
  thumb: { width: '100%', height: 160, borderRadius: theme.radius.sm, marginTop: 4 },
  foot: { flexDirection: 'row', alignItems: 'center', gap: 4, marginTop: 4, flexWrap: 'wrap' },
  byline: { color: theme.color.textDim, fontSize: 13, fontWeight: '600' },
  dot: { color: theme.color.textDim, marginHorizontal: 4 },
});
