import { useCallback, useEffect, useRef, useState, type ReactNode } from 'react';
import {
  View, Text, StyleSheet, FlatList, Pressable, ScrollView,
  ActivityIndicator, RefreshControl,
} from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import { Image as ExpoImage } from 'expo-image';
import { Ionicons } from '@expo/vector-icons';
import { useRouter, useFocusEffect } from 'expo-router';
import { theme } from '@/src/theme';
import { getViewRole, VIEW_PERMS, type ViewRole } from '@/src/roles';
import { ManagementCreCards, PmCreCards, SupervisorCreCards } from '@/src/CreDashboard';
import {
  apiListSites, apiListProjects, apiTimeline, apiSeedDemo, apiProjectSummary,
  getActiveSite, setActiveSite,
  type Site, type Project, type TimelineItem, type ProjectSummary,
} from '@/src/api';
import { apiGetWorkflow, type WorkflowActivity } from '@/src/workflow_api';
import { apiClientDashboard, type ClientDashboard } from '@/src/cre_api';
import { apiListItems, type OperationalItem } from '@/src/ops_api';

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

// FOUNDER SPRINT — Client Workspace: the Operations feed (and the raw
// event timeline, which for a client was just "PROJECT UPDATES" over
// the same low-level event feed) are replaced entirely with a
// purpose-built dashboard for the client role. Every other role's Home
// tab is completely unchanged below (TimelineScreen, untouched).
export default function HomeScreen() {
  const [viewRole, setViewRole] = useState<ViewRole | null>(null);
  useEffect(() => { getViewRole().then(setViewRole); }, []);
  if (viewRole === null) {
    return (
      <SafeAreaView style={styles.safe}>
        <View style={styles.loader}><ActivityIndicator size="large" color={theme.color.brand} /></View>
      </SafeAreaView>
    );
  }
  if (viewRole === 'client') return <ClientDashboardScreen />;
  return <TimelineScreen />;
}

function TimelineScreen() {
  const router = useRouter();
  const [sites, setSites] = useState<Site[]>([]);
  const [projectMap, setProjectMap] = useState<Record<string, Project>>({});
  const [activeSiteId, setActiveSiteIdState] = useState<string | null>(null);
  const [items, setItems] = useState<TimelineItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [canCapture, setCanCapture] = useState(true);
  const [viewRole, setViewRoleState] = useState<ViewRole | null>(null);
  const pollRef = useRef<any>(null);

  useEffect(() => { getViewRole().then((vr) => { setCanCapture(VIEW_PERMS[vr].showCapture); setViewRoleState(vr); }); }, []);
  // CRE Integration — the active site's project, if any. Cards for
  // internal roles are per-project, matching every other per-project
  // screen's existing "active site" convention (capture.tsx, etc.).
  const activeProjectId = sites.find((s) => s.id === activeSiteId)?.project_id || null;

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
    setLoadError(null);
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
    } catch (e: any) {
      // Sprint 4.1 fix (audit H4): surface load failures instead of
      // silently swallowing them.
      console.warn(e);
      setLoadError(e?.message || 'Could not load your timeline. Pull to retry.');
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

      {loadError && (
        <Pressable testID="timeline-load-error" onPress={() => { setLoading(true); loadAll(); }} style={styles.errorBanner}>
          <Ionicons name="warning" size={16} color={theme.color.error} />
          <Text style={styles.errorBannerText} numberOfLines={2}>{loadError} Tap to retry.</Text>
        </Pressable>
      )}

      {loading ? (
        <View style={styles.loader} testID="timeline-loader">
          <ActivityIndicator size="large" color={theme.color.brand} />
        </View>
      ) : items.length === 0 ? (
        <View style={styles.empty} testID="timeline-empty">
          <Ionicons name="mic-circle-outline" size={80} color={theme.color.brand} />
          <Text style={styles.emptyTitle}>No events yet</Text>
          {canCapture ? (
            <>
              <Text style={styles.emptyBody}>Tap CAPTURE to record reality.</Text>
              <Pressable testID="timeline-empty-capture"
                onPress={() => router.push('/(tabs)/capture')} style={styles.emptyCta}>
                <Ionicons name="mic" size={28} color={theme.color.onBrand} />
                <Text style={styles.emptyCtaText}>START CAPTURE</Text>
              </Pressable>
            </>
          ) : (
            <Text style={styles.emptyBody}>Updates from the site will appear here.</Text>
          )}
        </View>
      ) : (
        <FlatList
          testID="timeline-list"
          data={items}
          keyExtractor={(i) => i.event.id}
          ListHeaderComponent={
            viewRole === 'admin' ? <ManagementCreCards projectId={activeProjectId} /> :
            viewRole === 'pm' ? <PmCreCards projectId={activeProjectId} /> :
            viewRole === 'supervisor' ? <SupervisorCreCards projectId={activeProjectId} /> :
            null
          }
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

// ---------------------------------------------------------------------------
// FOUNDER SPRINT — Client Dashboard. Replaces the client's previous
// "PROJECT UPDATES" (raw event timeline) Home tab AND the separate
// "APPROVALS" tab (the Operations feed, filtered) entirely. Built
// entirely from existing endpoints already used elsewhere in the app —
// project summary (Sprint 2), workflow activities (Sprint 5, doubling as
// milestones), timeline photos (Sprint 1), and operational items scoped
// to client_approval (Sprint 3/6.2/FAC-04) — no new backend endpoints.
// AI daily/weekly summaries and Documents have no backend/data model yet
// (summaries are an explicitly future, dedicated capability per prior
// product direction; a documents store was never built) — both render
// as honest, clearly-labelled placeholders rather than being invented
// here, matching "this sprint is not about adding features."
// ---------------------------------------------------------------------------
function ClientDashboardScreen() {
  const router = useRouter();
  const [sites, setSites] = useState<Site[]>([]);
  const [projectMap, setProjectMap] = useState<Record<string, Project>>({});
  const [activeSiteId, setActiveSiteIdState] = useState<string | null>(null);
  const [summary, setSummary] = useState<ProjectSummary | null>(null);
  const [activities, setActivities] = useState<WorkflowActivity[]>([]);
  const [creDash, setCreDash] = useState<ClientDashboard | null>(null);
  const [photos, setPhotos] = useState<{ base64: string; eventId: string }[]>([]);
  const [approvals, setApprovals] = useState<OperationalItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [loadError, setLoadError] = useState<string | null>(null);

  const activeSite = sites.find((s) => s.id === activeSiteId);
  const activeProject = activeSite ? projectMap[activeSite.project_id] : null;

  const loadForSite = useCallback(async (siteId: string, projectId: string | undefined) => {
    const [tl, items] = await Promise.all([
      apiTimeline(siteId).catch(() => [] as TimelineItem[]),
      apiListItems({ site_id: siteId, category: 'client_approval' }).catch(() => [] as OperationalItem[]),
    ]);
    const photoList: { base64: string; eventId: string }[] = [];
    for (const t of tl) {
      for (const p of t.photo_thumbs || []) {
        photoList.push({ base64: p.base64, eventId: t.event.id });
        if (photoList.length >= 12) break;
      }
      if (photoList.length >= 12) break;
    }
    setPhotos(photoList);
    setApprovals(items.filter((i) => !['closed', 'archived', 'cancelled', 'duplicate'].includes(i.status)));

    if (projectId) {
      const [s, wf, cd] = await Promise.all([
        apiProjectSummary(projectId).catch(() => null),
        apiGetWorkflow(projectId).catch(() => [] as WorkflowActivity[]),
        apiClientDashboard(projectId).catch(() => null),
      ]);
      setSummary(s);
      setActivities(wf);
      setCreDash(cd);
    } else {
      setSummary(null);
      setActivities([]);
      setCreDash(null);
    }
  }, []);

  const loadAll = useCallback(async () => {
    setLoadError(null);
    try {
      const s = await apiListSites();
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
        const site = s.find((x) => x.id === active);
        await loadForSite(active, site?.project_id);
      }
    } catch (e: any) {
      console.warn(e);
      setLoadError(e?.message || 'Could not load your project updates. Pull to retry.');
    } finally {
      setLoading(false); setRefreshing(false);
    }
  }, [loadForSite]);

  useFocusEffect(useCallback(() => { loadAll(); }, [loadAll]));

  const onSelectSite = async (id: string) => {
    setActiveSiteIdState(id);
    await setActiveSite(id);
    setLoading(true);
    const site = sites.find((x) => x.id === id);
    await loadForSite(id, site?.project_id);
    setLoading(false);
  };

  const completedCount = activities.filter((a) => a.status === 'completed').length;
  const progressPct = activities.length > 0 ? Math.round((completedCount / activities.length) * 100) : null;

  if (loading) {
    return (
      <SafeAreaView style={styles.safe} edges={['top']}>
        <View style={styles.loader} testID="client-dashboard-loader">
          <ActivityIndicator size="large" color={theme.color.brand} />
        </View>
      </SafeAreaView>
    );
  }

  return (
    <SafeAreaView style={styles.safe} edges={['top']}>
      <View style={styles.header}>
        <View style={{ flex: 1 }}>
          <Text style={styles.h1}>PROJECT UPDATES</Text>
          <Text style={styles.h2} numberOfLines={1}>
            {activeProject ? `${activeProject.name} · ` : ''}{activeSite?.name || 'No site'}
          </Text>
        </View>
      </View>

      {sites.length > 1 && (
        <View style={styles.chipsContainer}>
          <ScrollView horizontal showsHorizontalScrollIndicator={false} contentContainerStyle={styles.chipsContent}>
            {sites.map((s) => {
              const active = s.id === activeSiteId;
              return (
                <Pressable key={s.id} testID={`client-site-chip-${s.id}`} onPress={() => onSelectSite(s.id)}
                  style={[styles.chip, active && styles.chipActive]}>
                  <Ionicons name="business" size={18} color={active ? theme.color.onBrand : theme.color.textMuted} />
                  <Text style={[styles.chipText, active && styles.chipTextActive]} numberOfLines={1}>{s.name}</Text>
                </Pressable>
              );
            })}
          </ScrollView>
        </View>
      )}

      {loadError && (
        <Pressable testID="client-dashboard-load-error" onPress={() => { setLoading(true); loadAll(); }} style={styles.errorBanner}>
          <Ionicons name="warning" size={16} color={theme.color.error} />
          <Text style={styles.errorBannerText} numberOfLines={2}>{loadError} Tap to retry.</Text>
        </Pressable>
      )}

      <ScrollView
        contentContainerStyle={dash.body}
        refreshControl={<RefreshControl refreshing={refreshing} onRefresh={() => { setRefreshing(true); loadAll(); }} tintColor={theme.color.brand} />}
      >
        {!activeSite ? (
          <View style={styles.empty} testID="client-dashboard-empty">
            <Ionicons name="business-outline" size={80} color={theme.color.brand} />
            <Text style={styles.emptyTitle}>No project yet</Text>
            <Text style={styles.emptyBody}>Your project updates will appear here once a site is set up.</Text>
          </View>
        ) : (
          <>
            {/* Project progress + CRE current stage / plain-English summary */}
            <DashCard title="PROJECT PROGRESS" icon="trending-up" testID="dash-progress">
              {creDash?.stage?.current_label && (
                <Text style={dash.stageLabel} testID="dash-current-stage">{creDash.stage.current_label}</Text>
              )}
              {progressPct === null ? (
                <Text style={dash.mutedText}>Progress tracking will appear once a workflow is set up for this project.</Text>
              ) : (
                <>
                  <View style={dash.progressRow}>
                    <View style={dash.progressBarBg}>
                      <View style={[dash.progressBarFill, { width: `${progressPct}%` }]} />
                    </View>
                    <Text style={dash.progressPct}>{progressPct}%</Text>
                  </View>
                  <Text style={dash.mutedText}>{completedCount} of {activities.length} activities complete</Text>
                </>
              )}
              {creDash?.summary_text && (
                <Text style={[dash.mutedText, { marginTop: 4 }]} testID="dash-summary-text">{creDash.summary_text}</Text>
              )}
              {summary && (
                <View style={dash.statRow}>
                  <DashStat label="OPEN ITEMS" value={summary.open_tasks} />
                  <DashStat label="SITES" value={summary.active_sites} />
                </View>
              )}
            </DashCard>

            {/* Milestones — prefers the CRE-reasoned "what's coming next"
                (dependency-aware, not just the raw activity list) when
                available; falls back to the plain workflow list if CRE
                has not run for this project yet. */}
            {(creDash?.upcoming_milestones?.length || activities.length > 0) && (
              <DashCard title="MILESTONES" icon="flag" testID="dash-milestones">
                {creDash?.upcoming_milestones?.length ? (
                  creDash.upcoming_milestones.map((m, i) => (
                    <View key={i} style={dash.milestoneRow}>
                      <Ionicons name="ellipse-outline" size={18} color={theme.color.brand} />
                      <Text style={dash.milestoneText} numberOfLines={1}>{m.name}</Text>
                    </View>
                  ))
                ) : (
                  activities.slice(0, 8).map((a) => (
                    <View key={a.id} style={dash.milestoneRow}>
                      <Ionicons
                        name={a.status === 'completed' ? 'checkmark-circle' : a.status === 'in_progress' ? 'time' : 'ellipse-outline'}
                        size={18}
                        color={a.status === 'completed' ? theme.color.success : a.status === 'in_progress' ? theme.color.brand : theme.color.textDim}
                      />
                      <Text style={[dash.milestoneText, a.status === 'completed' && dash.milestoneDone]} numberOfLines={1}>
                        {a.name}
                      </Text>
                    </View>
                  ))
                )}
              </DashCard>
            )}

            {/* Photos */}
            <DashCard title="PHOTOS" icon="images" testID="dash-photos">
              {photos.length === 0 ? (
                <Text style={dash.mutedText}>No photos shared yet.</Text>
              ) : (
                <ScrollView horizontal showsHorizontalScrollIndicator={false} contentContainerStyle={{ gap: 8 }}>
                  {photos.map((p, i) => (
                    <Pressable key={`${p.eventId}-${i}`} onPress={() => router.push(`/event/${p.eventId}`)}>
                      <ExpoImage source={{ uri: `data:image/jpeg;base64,${p.base64}` }} style={dash.photoThumb} contentFit="cover" />
                    </Pressable>
                  ))}
                </ScrollView>
              )}
            </DashCard>

            {/* AI-generated summaries — placeholder; no summary-generation
                engine exists yet (explicitly a future, dedicated capability) */}
            <DashCard title="WEEKLY SUMMARY" icon="sparkles" testID="dash-ai-summary">
              <View style={dash.placeholderBox}>
                <Ionicons name="hourglass-outline" size={22} color={theme.color.textDim} />
                <Text style={dash.mutedText}>
                  AI-generated summaries are not available yet. Your project team can share updates directly in the meantime.
                </Text>
              </View>
            </DashCard>

            {/* Pending approvals */}
            <DashCard title="PENDING APPROVALS" icon="checkmark-done" testID="dash-approvals">
              {approvals.length === 0 ? (
                <Text style={dash.mutedText}>Nothing needs your approval right now.</Text>
              ) : (
                approvals.map((item) => (
                  <Pressable key={item.id} testID={`dash-approval-${item.id}`}
                    onPress={() => router.push(`/op/${item.id}`)} style={dash.approvalRow}>
                    <View style={{ flex: 1 }}>
                      <Text style={dash.approvalTitle} numberOfLines={1}>{item.title}</Text>
                      {item.description ? <Text style={dash.mutedText} numberOfLines={1}>{item.description}</Text> : null}
                    </View>
                    <Ionicons name="chevron-forward" size={20} color={theme.color.textDim} />
                  </Pressable>
                ))
              )}
            </DashCard>

            {/* Documents — placeholder; no documents store exists yet */}
            <DashCard title="DOCUMENTS" icon="document-text" testID="dash-documents">
              <Text style={dash.mutedText}>No documents shared yet.</Text>
            </DashCard>
          </>
        )}
      </ScrollView>
    </SafeAreaView>
  );
}

function DashCard({ title, icon, testID, children }: { title: string; icon: any; testID: string; children: ReactNode }) {
  return (
    <View style={dash.card} testID={testID}>
      <View style={dash.cardHead}>
        <Ionicons name={icon} size={18} color={theme.color.brand} />
        <Text style={dash.cardTitle}>{title}</Text>
      </View>
      {children}
    </View>
  );
}

function DashStat({ label, value }: { label: string; value: number }) {
  return (
    <View style={dash.stat}>
      <Text style={dash.statValue}>{value}</Text>
      <Text style={dash.statLabel}>{label}</Text>
    </View>
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
  errorBanner: {
    flexDirection: 'row', alignItems: 'center', gap: 8, marginHorizontal: theme.spacing.md,
    marginBottom: theme.spacing.sm, padding: 10, borderRadius: theme.radius.sm,
    backgroundColor: theme.color.surface2, borderWidth: 1, borderColor: theme.color.error,
  },
  errorBannerText: { flex: 1, color: theme.color.error, fontSize: 12, fontWeight: '700' },
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

const dash = StyleSheet.create({
  body: { padding: theme.spacing.md, paddingBottom: 120, gap: theme.spacing.md },
  card: {
    backgroundColor: theme.color.surface2, borderRadius: theme.radius.md,
    borderWidth: 1, borderColor: theme.color.border, padding: theme.spacing.md, gap: theme.spacing.sm,
  },
  cardHead: { flexDirection: 'row', alignItems: 'center', gap: 8, marginBottom: 4 },
  cardTitle: { color: theme.color.text, fontSize: 13, fontWeight: '900', letterSpacing: 1 },
  stageLabel: { color: theme.color.brand, fontSize: 15, fontWeight: '800', marginBottom: 2 },
  mutedText: { color: theme.color.textMuted, fontSize: 14, lineHeight: 20 },
  progressRow: { flexDirection: 'row', alignItems: 'center', gap: 10 },
  progressBarBg: { flex: 1, height: 10, borderRadius: 5, backgroundColor: theme.color.surface3, overflow: 'hidden' },
  progressBarFill: { height: '100%', backgroundColor: theme.color.brand, borderRadius: 5 },
  progressPct: { color: theme.color.text, fontSize: 14, fontWeight: '900', minWidth: 40, textAlign: 'right' },
  statRow: { flexDirection: 'row', gap: theme.spacing.lg, marginTop: 8 },
  stat: { alignItems: 'center' },
  statValue: { color: theme.color.text, fontSize: 22, fontWeight: '900' },
  statLabel: { color: theme.color.textDim, fontSize: 10, fontWeight: '800', letterSpacing: 0.5, marginTop: 2 },
  milestoneRow: { flexDirection: 'row', alignItems: 'center', gap: 8, paddingVertical: 4 },
  milestoneText: { color: theme.color.text, fontSize: 14, flex: 1 },
  milestoneDone: { color: theme.color.textDim, textDecorationLine: 'line-through' },
  photoThumb: { width: 100, height: 100, borderRadius: theme.radius.sm },
  placeholderBox: { flexDirection: 'row', alignItems: 'flex-start', gap: 10 },
  approvalRow: {
    flexDirection: 'row', alignItems: 'center', gap: 8, paddingVertical: 10,
    borderTopWidth: 1, borderTopColor: theme.color.border,
  },
  approvalTitle: { color: theme.color.text, fontSize: 15, fontWeight: '700' },
});
