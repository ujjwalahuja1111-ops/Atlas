// Atlas Intelligent Shell — Phase A. The response surface for the
// Intent box: renders the REAL data each existing engine returns
// (explain_health, project_lookahead_view, compare_projects, the
// digest functions) as a structured, scannable card. Every field
// referenced here was traced against the actual backend, including
// live end-to-end checks against real seeded data — not assumed from
// reading code alone. Those live checks caught two real bugs before
// they shipped: (1) data.stage is an object ({current, current_label,
// reason, ...}), not a plain string — rendering it directly would
// have shown "[object Object]"; (2) compare_projects' own row shape
// nests health under health.status/health.score and has no top-level
// progress_percent at all — an earlier static trace of a
// similarly-named function was simply the wrong one. See
// docs/ATLAS_INTENT_ORCHESTRATION_SPEC.md Item 12.
import { View, Text, Pressable, StyleSheet } from 'react-native';
import { Ionicons } from '@expo/vector-icons';
import { useRouter } from 'expo-router';
import { theme } from '@/src/theme';
import type { IntentResponse } from '@/src/intent_api';

const SEVERITY_DOT: Record<string, string> = {
  critical: '🔴', high: '🔴', medium: '🟠', low: '🟢',
};

function Section({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <View style={{ marginTop: 12 }}>
      <Text style={styles.sectionLabel}>{label}</Text>
      {children}
    </View>
  );
}

function ActionButton({ label, onPress }: { label: string; onPress: () => void }) {
  return (
    <Pressable style={styles.actionBtn} onPress={onPress}>
      <Text style={styles.actionBtnText}>{label}</Text>
      <Ionicons name="chevron-forward" size={14} color={theme.color.brand} />
    </Pressable>
  );
}

function HealthResponse({ data, projectId }: { data: any; projectId?: string }) {
  const router = useRouter();
  const statusColor = data.status === 'green' ? theme.color.success
    : data.status === 'amber' ? theme.color.warning : theme.color.error;
  return (
    <View>
      <View style={styles.scoreRow}>
        <View style={[styles.scoreBadge, { backgroundColor: statusColor }]}>
          <Text style={styles.scoreBadgeText}>{data.score}</Text>
        </View>
        <View style={{ flex: 1 }}>
          <Text style={styles.headline}>
            {data.status === 'green' ? 'Healthy' : data.status === 'amber' ? 'Needs attention' : 'At risk'}
          </Text>
          {typeof data.progress?.percent_complete === 'number' && (
            <Text style={styles.subtext}>{data.progress.percent_complete}% complete</Text>
          )}
        </View>
      </View>

      {Array.isArray(data.drivers) && data.drivers.length > 0 && (
        <Section label="WHAT'S CONTRIBUTING">
          {data.drivers.slice(0, 5).map((d: string, i: number) => (
            <Text key={i} style={styles.bulletLine}>• {d}</Text>
          ))}
        </Section>
      )}

      {Array.isArray(data.recommended_actions) && data.recommended_actions.length > 0 && (
        <Section label="RECOMMENDED NEXT STEPS">
          {data.recommended_actions.slice(0, 4).map((a: any, i: number) => (
            <View key={i} style={styles.actionRow}>
              <Text style={styles.actionDot}>{SEVERITY_DOT[a.severity] || '•'}</Text>
              <View style={{ flex: 1 }}>
                <Text style={styles.actionText}>{a.suggested_action || a.observation}</Text>
                {a.suggested_action && a.observation && (
                  <Text style={styles.actionSubtext}>{a.observation}</Text>
                )}
              </View>
            </View>
          ))}
        </Section>
      )}

      {projectId && (
        <ActionButton label="View full health breakdown" onPress={() => router.push(`/explain-health/${projectId}`)} />
      )}
    </View>
  );
}

function ScheduleImpactResponse({ data, projectId }: { data: any; projectId?: string }) {
  const router = useRouter();
  const upcoming = Array.isArray(data.upcoming) ? data.upcoming : [];
  // data.stage is an object ({current, current_label, reason, ...}),
  // confirmed live against the real endpoint — never render it
  // directly, always its own current_label field.
  const stageLabel: string | null = data.stage?.current_label || null;
  return (
    <View>
      {stageLabel && <Text style={styles.subtext}>Current stage: {stageLabel}</Text>}
      {upcoming.length === 0 ? (
        <Text style={styles.bulletLine}>No upcoming activity data available for this project yet.</Text>
      ) : (
        <Section label="WHAT'S NEXT">
          {upcoming.slice(0, 4).map((a: any, i: number) => (
            <View key={i} style={styles.actionRow}>
              <Text style={styles.actionDot}>{a.ready ? '🟢' : '🔴'}</Text>
              <View style={{ flex: 1 }}>
                <Text style={styles.actionText}>{a.name}{a.trade ? ` (${a.trade})` : ''}</Text>
                {!a.ready && Array.isArray(a.possible_blockers) && a.possible_blockers[0] && a.possible_blockers[0] !== 'none identified in Atlas' && (
                  <Text style={styles.actionSubtext}>Blocked: {a.possible_blockers[0]}</Text>
                )}
              </View>
            </View>
          ))}
        </Section>
      )}
      {projectId && (
        <ActionButton label="View full schedule" onPress={() => router.push(`/workflow/${projectId}`)} />
      )}
    </View>
  );
}

function ComparisonResponse({ data }: { data: any }) {
  const router = useRouter();
  const rows = Array.isArray(data.projects) ? data.projects : [];
  return (
    <View>
      {rows.map((r: any, i: number) => (
        <Pressable key={i} style={styles.compareRow} onPress={() => router.push(`/projects/${r.project_id}`)}>
          <View style={{ flex: 1 }}>
            <Text style={styles.actionText}>{r.project_name}</Text>
            <Text style={styles.actionSubtext}>
              {r.health?.status || '—'}{typeof r.health?.score === 'number' ? ` (${r.health.score})` : ''}
              {typeof r.schedule_variance_days === 'number' && r.schedule_variance_days !== 0
                ? ` · ${r.schedule_variance_days > 0 ? `${r.schedule_variance_days}d behind` : `${-r.schedule_variance_days}d ahead`}` : ''}
              {typeof r.workflow?.total_activities === 'number' && r.workflow.total_activities > 0
                ? ` · ${r.workflow.total_activities} activities` : ''}
            </Text>
          </View>
          <Ionicons name="chevron-forward" size={16} color={theme.color.textDim} />
        </Pressable>
      ))}
    </View>
  );
}

function DigestResponse({ data }: { data: any }) {
  const router = useRouter();
  return (
    <View>
      {data.coordination?.summary_lines?.length > 0 && (
        <Section label="COORDINATION">
          {data.coordination.summary_lines.map((l: string, i: number) => (
            <Text key={i} style={styles.bulletLine}>• {l}</Text>
          ))}
          {data.coordination.top_priority && (
            <Text style={styles.actionText}>Top priority: {data.coordination.top_priority}</Text>
          )}
        </Section>
      )}
      {data.my_day && (
        <Section label="TODAY">
          {['ready_to_start', 'in_progress', 'due_today', 'blocked'].map((key) =>
            Array.isArray(data.my_day[key]) && data.my_day[key].length > 0 ? (
              <Text key={key} style={styles.bulletLine}>
                • {data.my_day[key].length} item{data.my_day[key].length !== 1 ? 's' : ''} {key.replace(/_/g, ' ')}
              </Text>
            ) : null
          )}
        </Section>
      )}
      {data.management_attention?.summary_lines?.length > 0 && (
        <Section label="MANAGEMENT ATTENTION">
          {data.management_attention.summary_lines.map((l: string, i: number) => (
            <Text key={i} style={styles.bulletLine}>• {l}</Text>
          ))}
        </Section>
      )}
      <ActionButton label="Open Inbox" onPress={() => router.push('/(tabs)/notifications')} />
    </View>
  );
}

export function AtlasResponseCard({ response }: { response: IntentResponse }) {
  if (response.type === 'unresolved') {
    return (
      <View style={styles.card} testID="atlas-response-unresolved">
        <Text style={styles.bulletLine}>{response.message}</Text>
      </View>
    );
  }
  if (response.type === 'clarification_needed') {
    // Rendered by the caller (needs interactive candidate picking with
    // its own state) — this component only handles the "result" shape.
    return null;
  }

  const { intent, result, project } = response;
  return (
    <View style={styles.card} testID="atlas-response-card">
      {project && (
        <View style={styles.projectPill}>
          <Ionicons name="briefcase-outline" size={12} color={theme.color.brand} />
          <Text style={styles.projectPillText}>{project.name}</Text>
        </View>
      )}
      {!result.ok ? (
        <Text style={styles.bulletLine}>{result.error || "I couldn't retrieve this right now."}</Text>
      ) : intent === 'query_health' ? (
        <HealthResponse data={result.data} projectId={project?.id} />
      ) : intent === 'query_schedule_impact' ? (
        <ScheduleImpactResponse data={result.data} projectId={project?.id} />
      ) : intent === 'query_comparison' ? (
        <ComparisonResponse data={result.data} />
      ) : intent === 'query_digest' ? (
        <DigestResponse data={result.data} />
      ) : (
        <Text style={styles.bulletLine}>No further detail available.</Text>
      )}
      {result.partial_errors?.length ? (
        <Text style={styles.partialNote}>({result.partial_errors.join(', ')})</Text>
      ) : null}
    </View>
  );
}

const styles = StyleSheet.create({
  card: {
    marginTop: 10, backgroundColor: theme.color.surface2, borderRadius: theme.radius.md,
    borderWidth: 1, borderColor: theme.color.border, padding: 16,
  },
  projectPill: {
    flexDirection: 'row', alignItems: 'center', gap: 4, alignSelf: 'flex-start',
    backgroundColor: theme.color.brandTint, borderRadius: theme.radius.pill,
    paddingVertical: 3, paddingHorizontal: 10, marginBottom: 10,
  },
  projectPillText: { color: theme.color.brand, fontSize: 11, fontWeight: '700' },
  scoreRow: { flexDirection: 'row', alignItems: 'center', gap: 12 },
  scoreBadge: { width: 44, height: 44, borderRadius: 22, alignItems: 'center', justifyContent: 'center' },
  scoreBadgeText: { color: '#fff', fontSize: 16, fontWeight: '900' },
  headline: { color: theme.color.text, fontSize: 16, fontWeight: '800' },
  subtext: { color: theme.color.textDim, fontSize: 12, marginTop: 2 },
  sectionLabel: { color: theme.color.textDim, fontSize: 11, fontWeight: '800', letterSpacing: 0.6, marginBottom: 6 },
  bulletLine: { color: theme.color.textMuted, fontSize: 13, marginTop: 3, lineHeight: 18 },
  actionRow: { flexDirection: 'row', alignItems: 'flex-start', gap: 8, marginTop: 6 },
  actionDot: { fontSize: 12, marginTop: 2 },
  actionText: { color: theme.color.text, fontSize: 13, fontWeight: '700' },
  actionSubtext: { color: theme.color.textDim, fontSize: 12, marginTop: 1 },
  actionBtn: {
    flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between', marginTop: 14,
    paddingVertical: 10, paddingHorizontal: 12, backgroundColor: theme.color.surface3, borderRadius: theme.radius.sm,
  },
  actionBtnText: { color: theme.color.brand, fontSize: 13, fontWeight: '700' },
  compareRow: {
    flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between',
    paddingVertical: 10, borderBottomWidth: 1, borderBottomColor: theme.color.border,
  },
  partialNote: { color: theme.color.textDim, fontSize: 11, marginTop: 10, fontStyle: 'italic' },
});
