// Personal Work Queue (Execution Experience Sprint 01, items 1 & 2).
// "The first section should always be" — rendered as the ListHeaderComponent
// ahead of the existing CRE cards on the Home tab, for every internal role.
import { useEffect, useState } from 'react';
import { View, Text, StyleSheet, Pressable, ActivityIndicator } from 'react-native';
import { Ionicons } from '@expo/vector-icons';
import { useRouter } from 'expo-router';
import { theme } from './theme';
import { apiWorkQueue, type WorkQueueResponse, type WorkQueueItem } from './ops_api';
import { URGENCY_COLOR, operationalItemUrgency, workflowActivityUrgency } from './urgency';

export function WorkQueueSection({ viewRole }: { viewRole: 'admin' | 'pm' | 'supervisor' }) {
  const router = useRouter();
  const [data, setData] = useState<WorkQueueResponse | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let cancelled = false;
    apiWorkQueue().then((d) => { if (!cancelled) { setData(d); setLoading(false); } })
      .catch(() => { if (!cancelled) setLoading(false); });
    return () => { cancelled = true; };
  }, []);

  if (loading) {
    return <View style={styles.loader}><ActivityIndicator color={theme.color.brand} /></View>;
  }
  if (!data) return null;

  if (viewRole === 'supervisor' && data.ready_to_start) {
    const { operational_items, workflow_activities } = data.ready_to_start;
    const total = operational_items.length + workflow_activities.length;
    return (
      <View style={styles.section} testID="work-queue-supervisor">
        <View style={styles.headerRow}>
          <Ionicons name="flash" size={18} color={theme.color.brand} />
          <Text style={styles.headerText}>READY TO START</Text>
          {total > 0 && <View style={styles.countBadge}><Text style={styles.countBadgeText}>{total}</Text></View>}
        </View>
        {total === 0 ? (
          <Text style={styles.empty}>Nothing ready to start right now.</Text>
        ) : (
          <>
            {operational_items.map((item) => (
              <WorkQueueCard key={item.id} item={item} onPress={() => router.push(`/op/${item.id}`)} />
            ))}
            {workflow_activities.map((a) => (
              <WorkflowQueueCard key={a.id} activity={a} onPress={() => router.push(`/workflow/${a.project_id}`)} />
            ))}
          </>
        )}
        {data.in_progress_assigned_to_me && data.in_progress_assigned_to_me.length > 0 && (
          <>
            <Text style={styles.subheader}>IN PROGRESS — ASSIGNED TO YOU</Text>
            {data.in_progress_assigned_to_me.map((item) => (
              <WorkQueueCard key={item.id} item={item} onPress={() => router.push(`/op/${item.id}`)} />
            ))}
          </>
        )}
      </View>
    );
  }

  if (data.assigned_to_me) {
    const { items, counts } = data.assigned_to_me;
    return (
      <View style={styles.section} testID="work-queue-pm">
        <View style={styles.headerRow}>
          <Ionicons name="person-circle" size={18} color={theme.color.brand} />
          <Text style={styles.headerText}>ASSIGNED TO ME</Text>
          {items.length > 0 && <View style={styles.countBadge}><Text style={styles.countBadgeText}>{items.length}</Text></View>}
        </View>
        <View style={styles.countsRow}>
          <CountPill label="Approvals" value={counts.pending_approvals} />
          <CountPill label="Overdue" value={counts.overdue} color={URGENCY_COLOR.overdue} />
          <CountPill label="Critical" value={counts.critical} color={URGENCY_COLOR.overdue} />
        </View>
        {items.length === 0 ? (
          <Text style={styles.empty}>Nothing needs your attention right now.</Text>
        ) : (
          items.slice(0, 8).map((item) => (
            <WorkQueueCard key={item.id} item={item} onPress={() => router.push(`/op/${item.id}`)} />
          ))
        )}
      </View>
    );
  }

  return null;
}

function CountPill({ label, value, color }: { label: string; value: number; color?: string }) {
  return (
    <View style={styles.pill}>
      <Text style={[styles.pillValue, color ? { color } : null]}>{value}</Text>
      <Text style={styles.pillLabel}>{label}</Text>
    </View>
  );
}

// Assigned Activity Highlighting (item 2) — a colored left border (the
// item's derived urgency) plus an explicit "ASSIGNED TO YOU" badge, so
// a user never has to search for their own work.
function WorkQueueCard({ item, onPress }: { item: WorkQueueItem; onPress: () => void }) {
  const urgency = operationalItemUrgency(item);
  const color = URGENCY_COLOR[urgency];
  return (
    <Pressable testID={`work-queue-item-${item.id}`} onPress={onPress} style={[styles.card, { borderLeftColor: color }]}>
      <View style={{ flex: 1 }}>
        <View style={styles.cardTitleRow}>
          <Text style={styles.cardTitle} numberOfLines={1}>{item.title}</Text>
          <View style={styles.assignedBadge}>
            <Text style={styles.assignedBadgeText}>ASSIGNED TO YOU</Text>
          </View>
        </View>
        <Text style={styles.cardMeta}>
          {item.category.replace(/_/g, ' ')} · {(item as any).site_name || ''}
        </Text>
      </View>
      <View style={[styles.urgencyDot, { backgroundColor: color }]} />
    </Pressable>
  );
}

function WorkflowQueueCard({ activity, onPress }: { activity: any; onPress: () => void }) {
  const urgency = workflowActivityUrgency(activity);
  const color = URGENCY_COLOR[urgency];
  return (
    <Pressable testID={`work-queue-activity-${activity.id}`} onPress={onPress} style={[styles.card, { borderLeftColor: color }]}>
      <View style={{ flex: 1 }}>
        <Text style={styles.cardTitle} numberOfLines={1}>{activity.name}</Text>
        <Text style={styles.cardMeta}>{activity.trade || 'Activity'} · Ready — prerequisites complete</Text>
      </View>
      <View style={[styles.urgencyDot, { backgroundColor: color }]} />
    </Pressable>
  );
}

const styles = StyleSheet.create({
  loader: { paddingVertical: theme.spacing.lg, alignItems: 'center' },
  section: { marginBottom: theme.spacing.md },
  headerRow: { flexDirection: 'row', alignItems: 'center', gap: 8, marginBottom: theme.spacing.sm },
  headerText: { color: theme.color.text, fontSize: 13, fontWeight: '900', letterSpacing: 1 },
  subheader: { color: theme.color.textDim, fontSize: 11, fontWeight: '800', letterSpacing: 0.5, marginTop: theme.spacing.sm, marginBottom: 6 },
  countBadge: { backgroundColor: theme.color.brand, borderRadius: 10, paddingHorizontal: 8, paddingVertical: 2 },
  countBadgeText: { color: theme.color.onBrand, fontSize: 11, fontWeight: '800' },
  countsRow: { flexDirection: 'row', gap: theme.spacing.md, marginBottom: theme.spacing.sm },
  pill: { alignItems: 'center' },
  pillValue: { color: theme.color.text, fontSize: 18, fontWeight: '900' },
  pillLabel: { color: theme.color.textDim, fontSize: 10, fontWeight: '700' },
  empty: { color: theme.color.textDim, fontSize: 13, fontStyle: 'italic', paddingVertical: theme.spacing.sm },
  card: {
    flexDirection: 'row', alignItems: 'center', backgroundColor: theme.color.surface2,
    borderRadius: theme.radius.md, borderLeftWidth: 4, padding: theme.spacing.sm, marginBottom: 8, gap: 8,
  },
  cardTitleRow: { flexDirection: 'row', alignItems: 'center', gap: 6 },
  cardTitle: { color: theme.color.text, fontSize: 14, fontWeight: '700', flexShrink: 1 },
  cardMeta: { color: theme.color.textDim, fontSize: 12, marginTop: 2 },
  assignedBadge: { backgroundColor: theme.color.brand, borderRadius: 6, paddingHorizontal: 6, paddingVertical: 2 },
  assignedBadgeText: { color: theme.color.onBrand, fontSize: 9, fontWeight: '800' },
  urgencyDot: { width: 10, height: 10, borderRadius: 5 },
});
