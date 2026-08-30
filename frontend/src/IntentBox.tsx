// Atlas Intent & Orchestration — Phase 1. "How can Atlas help?" — a
// single text entry point, native to Atlas's own visual language
// (theme.ts, existing card/pill conventions), deliberately NOT a chat
// window: no message history, no persona, no bubbles. One input, one
// answer, rendered as a normal Atlas card — per the spec's own Item 1
// ("this is not a chat interface layered beside the app").
import { useState } from 'react';
import { View, Text, TextInput, Pressable, ActivityIndicator, StyleSheet } from 'react-native';
import { Ionicons } from '@expo/vector-icons';
import { theme } from '@/src/theme';
import { apiPostIntent, apiPostIntentWithConfirmedProject, type IntentResponse, type IntentCandidate } from '@/src/intent_api';

const INTENT_LABELS: Record<string, string> = {
  query_health: 'Project Health',
  query_schedule_impact: 'Schedule Impact',
  query_comparison: 'Comparison',
  query_digest: "Today's Summary",
};

function summarizeResult(resp: IntentResponse): { title: string; lines: string[] } {
  if (resp.type !== 'result') return { title: '', lines: [] };
  const label = INTENT_LABELS[resp.intent] || resp.intent;
  if (!resp.result.ok) {
    return { title: label, lines: [resp.result.error || 'Could not retrieve this right now.'] };
  }
  const data = resp.result.data;
  const lines: string[] = [];
  if (resp.intent === 'query_health' && data) {
    if (data.status) lines.push(`Status: ${data.status}`);
    if (typeof data.score === 'number') lines.push(`Score: ${data.score}`);
    if (Array.isArray(data.recommended_actions) && data.recommended_actions.length) {
      lines.push(`${data.recommended_actions.length} recommended action(s)`);
    }
  } else if (resp.intent === 'query_schedule_impact' && data) {
    if (Array.isArray(data.upcoming)) lines.push(`${data.upcoming.length} upcoming activit${data.upcoming.length === 1 ? 'y' : 'ies'}`);
  } else if (resp.intent === 'query_comparison' && data) {
    if (Array.isArray(data.projects)) lines.push(`Comparing ${data.projects.length} projects`);
  } else if (resp.intent === 'query_digest' && data) {
    if (data.coordination) lines.push('Coordination summary ready');
    if (data.my_day) lines.push("Today's tasks ready");
    if (data.management_attention) lines.push('Management digest ready');
  }
  if (resp.result.partial_errors?.length) {
    lines.push(`(${resp.result.partial_errors.join(', ')})`);
  }
  if (!lines.length) lines.push('No further detail available.');
  return { title: resp.project ? `${label} — ${resp.project.name}` : label, lines };
}

export function IntentBox({ activeProjectId }: { activeProjectId?: string | null }) {
  const [text, setText] = useState('');
  const [loading, setLoading] = useState(false);
  const [response, setResponse] = useState<IntentResponse | null>(null);
  const [lastQuery, setLastQuery] = useState('');

  const handleSubmit = async () => {
    const q = text.trim();
    if (!q || loading) return;
    setText('');
    setLastQuery(q);
    setLoading(true);
    try {
      const r = await apiPostIntent(q, activeProjectId);
      setResponse(r);
    } finally {
      setLoading(false);
    }
  };

  const handleCandidatePick = async (candidate: IntentCandidate) => {
    setLoading(true);
    try {
      const r = await apiPostIntentWithConfirmedProject(lastQuery, candidate.id);
      setResponse(r);
    } finally {
      setLoading(false);
    }
  };

  return (
    <View style={styles.container} testID="atlas-intent-box">
      <View style={styles.inputRow}>
        <Ionicons name="sparkles-outline" size={18} color={theme.color.brand} />
        <TextInput
          testID="atlas-intent-input"
          style={styles.input}
          placeholder="How can Atlas help?"
          placeholderTextColor={theme.color.textDim}
          value={text}
          onChangeText={setText}
          onSubmitEditing={handleSubmit}
          returnKeyType="send"
        />
        {loading ? (
          <ActivityIndicator size="small" color={theme.color.brand} />
        ) : (
          <Pressable testID="atlas-intent-submit" onPress={handleSubmit} hitSlop={10}>
            <Ionicons name="arrow-forward-circle" size={26} color={theme.color.brand} />
          </Pressable>
        )}
      </View>

      {response?.type === 'clarification_needed' && (
        <View style={styles.resultCard}>
          <Text style={styles.resultTitle}>{response.question}</Text>
          <View style={styles.chipRow}>
            {response.candidates.map((c) => (
              <Pressable key={c.id} testID={`atlas-intent-candidate-${c.id}`} style={styles.chip} onPress={() => handleCandidatePick(c)}>
                <Text style={styles.chipText}>{c.name}</Text>
              </Pressable>
            ))}
          </View>
        </View>
      )}

      {response?.type === 'unresolved' && (
        <View style={styles.resultCard}>
          <Text style={styles.resultLine}>{response.message}</Text>
        </View>
      )}

      {response?.type === 'result' && (() => {
        const { title, lines } = summarizeResult(response);
        return (
          <View style={styles.resultCard} testID="atlas-intent-result">
            {!!title && <Text style={styles.resultTitle}>{title}</Text>}
            {lines.map((l, i) => (
              <Text key={i} style={styles.resultLine}>{l}</Text>
            ))}
          </View>
        );
      })()}
    </View>
  );
}

const styles = StyleSheet.create({
  container: { paddingHorizontal: theme.spacing.md, marginBottom: theme.spacing.md },
  inputRow: {
    flexDirection: 'row', alignItems: 'center', gap: 10, backgroundColor: theme.color.surface2,
    borderRadius: theme.radius.pill, borderWidth: 1, borderColor: theme.color.border,
    paddingHorizontal: 14, paddingVertical: 10,
  },
  input: { flex: 1, color: theme.color.text, fontSize: 15 },
  resultCard: {
    marginTop: 10, backgroundColor: theme.color.surface2, borderRadius: theme.radius.md,
    borderWidth: 1, borderColor: theme.color.border, padding: 14,
  },
  resultTitle: { color: theme.color.text, fontSize: 14, fontWeight: '800', marginBottom: 6 },
  resultLine: { color: theme.color.textMuted, fontSize: 13, marginTop: 2 },
  chipRow: { flexDirection: 'row', flexWrap: 'wrap', gap: 8, marginTop: 6 },
  chip: {
    backgroundColor: theme.color.surface3, borderRadius: theme.radius.pill,
    paddingVertical: 8, paddingHorizontal: 14, borderWidth: 1, borderColor: theme.color.border,
  },
  chipText: { color: theme.color.text, fontSize: 13, fontWeight: '700' },
});
