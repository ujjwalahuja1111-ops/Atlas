// Atlas Intelligent Shell — Phase A of the field-first intelligent UI
// redesign. This is the new primary control surface: a prominent
// input the user leads with, not a small box tucked below existing
// content. Reuses the existing, unmodified Phase 1 intent API
// (src/intent_api.ts) — no new backend, no second intent system.
import { useState, useEffect } from 'react';
import { View, Text, TextInput, Pressable, ActivityIndicator, StyleSheet } from 'react-native';
import { Ionicons } from '@expo/vector-icons';
import { useRouter } from 'expo-router';
import { theme } from '@/src/theme';
import { apiGetMe } from '@/src/api';
import { apiPostIntent, apiPostIntentWithConfirmedProject, type IntentResponse, type IntentCandidate } from '@/src/intent_api';
import { AtlasResponseCard } from '@/src/AtlasResponseCard';

type Role = 'admin' | 'pm' | 'supervisor' | 'client';

const SUGGESTED_PROMPTS: Record<Role, string[]> = {
  admin: ['Which projects need attention today?', 'Why is this project at risk?', "What's happening across my portfolio today?"],
  pm: ['Why is this project at risk?', 'Does this affect handover?', 'What needs my attention today?'],
  supervisor: ['What needs my attention today?'],
  client: ['What needs my attention today?'],
};

function greeting(): string {
  const h = new Date().getHours();
  return h < 12 ? 'Good morning' : h < 17 ? 'Good afternoon' : 'Good evening';
}

export function AtlasShell({
  role, activeProjectId, activeProjectName, fieldMode,
}: {
  role: Role; activeProjectId?: string | null; activeProjectName?: string | null;
  // Phase C — when true, shows the field quick-actions row and the
  // voice/photo shortcuts on the input row. Defaults to true for
  // Supervisor (the primary field role) and false otherwise, but any
  // caller can opt in explicitly — any role can be standing on site.
  fieldMode?: boolean;
}) {
  const router = useRouter();
  const [text, setText] = useState('');
  const [loading, setLoading] = useState(false);
  const [response, setResponse] = useState<IntentResponse | null>(null);
  const [lastQuery, setLastQuery] = useState('');
  const [userName, setUserName] = useState<string>('');
  const showField = fieldMode ?? role === 'supervisor';

  useEffect(() => {
    apiGetMe().then((u) => setUserName(u.name?.split(' ')[0] || '')).catch(() => {});
  }, []);

  const runQuery = async (q: string) => {
    if (!q.trim() || loading) return;
    setText('');
    setLastQuery(q);
    setLoading(true);
    try {
      setResponse(await apiPostIntent(q, activeProjectId));
    } finally {
      setLoading(false);
    }
  };

  const handleCandidatePick = async (candidate: IntentCandidate) => {
    setLoading(true);
    try {
      setResponse(await apiPostIntentWithConfirmedProject(lastQuery, candidate.id));
    } finally {
      setLoading(false);
    }
  };

  return (
    <View style={styles.container} testID="atlas-shell">
      <Text style={styles.greeting}>{greeting()}{userName ? `, ${userName}` : ''}.</Text>
      <Text style={styles.subGreeting}>{showField ? 'Tell Atlas what is happening.' : 'What would you like to know or do?'}</Text>

      {activeProjectName ? (
        <Pressable style={styles.contextPill} onPress={() => router.push('/(tabs)/projects')} testID="atlas-context-pill">
          <Ionicons name="briefcase-outline" size={13} color={theme.color.brand} />
          <Text style={styles.contextPillText}>Working on: {activeProjectName}</Text>
          <Ionicons name="chevron-down" size={13} color={theme.color.textDim} />
        </Pressable>
      ) : null}

      {showField && (
        <View style={styles.fieldActionsRow} testID="atlas-field-actions">
          <FieldActionButton icon="alert-circle-outline" label="Report Issue" color={theme.color.error}
            onPress={() => router.push('/(tabs)/capture?mode=issue')} />
          <FieldActionButton icon="help-buoy-outline" label="What's Blocking Me?"
            onPress={() => runQuery("What's blocking me?")} />
          <FieldActionButton icon="today-outline" label="Today's Work"
            onPress={() => runQuery('What do I need to know today?')} />
          <FieldActionButton icon="camera-outline" label="Capture Progress"
            onPress={() => router.push('/(tabs)/capture?mode=observation')} />
        </View>
      )}

      <View style={styles.inputRow}>
        <Ionicons name="sparkles-outline" size={20} color={theme.color.brand} />
        <TextInput
          testID="atlas-shell-input"
          style={styles.input}
          placeholder={showField ? 'Ask Atlas, or tell it what happened…' : 'Ask Atlas anything about your projects…'}
          placeholderTextColor={theme.color.textDim}
          value={text}
          onChangeText={setText}
          onSubmitEditing={() => runQuery(text)}
          returnKeyType="send"
        />
        {showField && (
          // Honest shortcuts, not a fake voice-to-intent integration —
          // the intent API is text-only (Phase 1's own explicit
          // scope); these route to Capture, the real pipeline that
          // actually handles voice and photos.
          <>
            <Pressable testID="atlas-shell-mic" onPress={() => router.push('/(tabs)/capture')} hitSlop={10}>
              <Ionicons name="mic-outline" size={22} color={theme.color.textDim} />
            </Pressable>
            <Pressable testID="atlas-shell-camera" onPress={() => router.push('/(tabs)/capture')} hitSlop={10}>
              <Ionicons name="camera-outline" size={22} color={theme.color.textDim} />
            </Pressable>
          </>
        )}
        {loading ? (
          <ActivityIndicator size="small" color={theme.color.brand} />
        ) : (
          <Pressable testID="atlas-shell-submit" onPress={() => runQuery(text)} hitSlop={10}>
            <Ionicons name="arrow-forward-circle" size={30} color={theme.color.brand} />
          </Pressable>
        )}
      </View>

      {!response && !loading && (
        <View style={styles.suggestions} testID="atlas-suggested-prompts">
          {SUGGESTED_PROMPTS[role].map((p) => (
            <Pressable key={p} style={styles.suggestionChip} onPress={() => runQuery(p)}>
              <Text style={styles.suggestionText}>{p}</Text>
            </Pressable>
          ))}
        </View>
      )}

      {response?.type === 'clarification_needed' && (
        <View style={styles.clarifyCard}>
          <Text style={styles.clarifyQuestion}>{response.question}</Text>
          <View style={styles.suggestions}>
            {response.candidates.map((c) => (
              <Pressable key={c.id} testID={`atlas-candidate-${c.id}`} style={styles.suggestionChip} onPress={() => handleCandidatePick(c)}>
                <Text style={styles.suggestionText}>{c.name}</Text>
              </Pressable>
            ))}
          </View>
        </View>
      )}

      {response && response.type !== 'clarification_needed' && (
        <AtlasResponseCard response={response} />
      )}
    </View>
  );
}

function FieldActionButton({ icon, label, color, onPress }: { icon: any; label: string; color?: string; onPress: () => void }) {
  return (
    <Pressable style={styles.fieldActionBtn} onPress={onPress} testID={`atlas-field-action-${label.toLowerCase().replace(/[^a-z]+/g, '-')}`}>
      <Ionicons name={icon} size={24} color={color || theme.color.brand} />
      <Text style={styles.fieldActionLabel}>{label}</Text>
    </Pressable>
  );
}

const styles = StyleSheet.create({
  container: { paddingHorizontal: theme.spacing.md, paddingTop: theme.spacing.sm, marginBottom: theme.spacing.lg },
  greeting: { color: theme.color.text, fontSize: 26, fontWeight: '900' },
  subGreeting: { color: theme.color.textMuted, fontSize: 15, marginTop: 2, marginBottom: 14 },
  contextPill: {
    flexDirection: 'row', alignItems: 'center', gap: 6, alignSelf: 'flex-start',
    backgroundColor: theme.color.surface2, borderRadius: theme.radius.pill,
    borderWidth: 1, borderColor: theme.color.border, paddingVertical: 6, paddingHorizontal: 12, marginBottom: 14,
  },
  contextPillText: { color: theme.color.text, fontSize: 12, fontWeight: '700' },
  fieldActionsRow: { flexDirection: 'row', flexWrap: 'wrap', gap: 10, marginBottom: 14 },
  fieldActionBtn: {
    width: '47%', backgroundColor: theme.color.surface2, borderRadius: theme.radius.md, paddingVertical: 16,
    alignItems: 'center', gap: 6, borderWidth: 1, borderColor: theme.color.border, minHeight: 64,
  },
  fieldActionLabel: { color: theme.color.text, fontSize: 13, fontWeight: '700', textAlign: 'center' },
  inputRow: {
    flexDirection: 'row', alignItems: 'center', gap: 12, backgroundColor: theme.color.surface2,
    borderRadius: theme.radius.lg, borderWidth: 1, borderColor: theme.color.border,
    paddingHorizontal: 16, paddingVertical: 14,
  },
  input: { flex: 1, color: theme.color.text, fontSize: 16 },
  suggestions: { flexDirection: 'row', flexWrap: 'wrap', gap: 8, marginTop: 12 },
  suggestionChip: {
    backgroundColor: theme.color.surface3, borderRadius: theme.radius.pill,
    paddingVertical: 9, paddingHorizontal: 14, borderWidth: 1, borderColor: theme.color.border,
  },
  suggestionText: { color: theme.color.textMuted, fontSize: 13, fontWeight: '600' },
  clarifyCard: {
    marginTop: 10, backgroundColor: theme.color.surface2, borderRadius: theme.radius.md,
    borderWidth: 1, borderColor: theme.color.border, padding: 16,
  },
  clarifyQuestion: { color: theme.color.text, fontSize: 14, fontWeight: '800' },
});
