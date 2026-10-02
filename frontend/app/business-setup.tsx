import { useEffect, useState } from 'react';
import { View, Text, StyleSheet, Pressable, ActivityIndicator, ScrollView, TextInput } from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import { useRouter } from 'expo-router';
import { theme } from '@/src/theme';
import {
  apiAnalyzeBusiness, apiGetBusinessConfiguration, apiApproveBusinessConfiguration,
  type BusinessConfiguration, type Capability, type CapabilityLevel, type Role,
} from '@/src/api';

/**
 * AI Business Setup — Step 2 of the locked market-ready sequence.
 *
 * BUSINESS DESCRIPTION -> AI RECOMMENDS -> HUMAN REVIEWS/EDITS -> APPROVE.
 * Step 3 (provisioning users/engines/workflows from the approved
 * configuration) is explicitly out of scope here — this screen only gets
 * a configuration into the "approved" state and hands off to the existing
 * app shell. No construction terminology appears before the business type
 * is known (Section 18's own explicit requirement) — this screen asks
 * nothing more specific than "describe your business."
 */

const CAPABILITY_LABELS: Record<Capability, string> = {
  capture: 'Field capture (voice/photo/text)',
  memory: 'Core memory (projects, sites, users)',
  intelligence: 'AI structuring of captures',
  operational_tracking: 'Operational tracking (requirements, commitments, follow-ups)',
  timeline: 'Timeline / evidence history',
  context: 'Context retrieval for questions',
  notifications: 'Notifications',
  history: 'Change-history queries',
  commercial: 'Commercial tracking (contracts, payments)',
  construction_reasoning: 'Construction-specific reasoning',
  workflow: 'Activity/milestone workflow',
  verification: 'Independent verification',
  relationship_linking: 'Relationship linking (corrections, fulfillment)',
};

const LEVEL_LABEL: Record<CapabilityLevel, string> = {
  required: 'Required', optional: 'Optional', not_required: 'Not needed',
};
const LEVEL_ORDER: CapabilityLevel[] = ['required', 'optional', 'not_required'];

const ROLE_LABELS: Record<Role, string> = {
  management: 'Admin / Owner', project_manager: 'Project Manager',
  site_supervisor: 'Site Supervisor / Operations Lead', client: 'Client access',
};
const ALL_ROLES: Role[] = ['management', 'project_manager', 'site_supervisor', 'client'];

export default function BusinessSetupScreen() {
  const router = useRouter();
  const [loading, setLoading] = useState(true);
  const [description, setDescription] = useState('');
  const [analyzing, setAnalyzing] = useState(false);
  const [approving, setApproving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [config, setConfig] = useState<BusinessConfiguration | null>(null);

  // Editable state, seeded from the AI's own recommendation once it
  // arrives — the human can change any of it before approving.
  const [capabilities, setCapabilities] = useState<Record<Capability, CapabilityLevel> | null>(null);
  const [roles, setRoles] = useState<Role[] | null>(null);
  const [clientAccess, setClientAccess] = useState<boolean | null>(null);

  useEffect(() => {
    (async () => {
      try {
        const existing = await apiGetBusinessConfiguration();
        if ('status' in existing && existing.status !== 'none') {
          const cfg = existing as BusinessConfiguration;
          setConfig(cfg);
          if (cfg.status === 'approved') {
            router.replace('/(tabs)');
            return;
          }
          seedEditableState(cfg);
        }
      } catch {
        /* no existing config yet — start fresh */
      } finally { setLoading(false); }
    })();
    // Run once on mount only, matching pending.tsx's own identical pattern
    // for this exact kind of one-shot auth/routing check.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  function seedEditableState(cfg: BusinessConfiguration) {
    setCapabilities({ ...cfg.ai_recommendation.capability_recommendations });
    setRoles([...cfg.ai_recommendation.recommended_roles]);
    setClientAccess(cfg.ai_recommendation.client_access_required);
  }

  const analyze = async () => {
    if (!description.trim()) return;
    setAnalyzing(true); setError(null);
    try {
      const cfg = await apiAnalyzeBusiness(description.trim());
      setConfig(cfg);
      seedEditableState(cfg);
    } catch (e: any) {
      setError(e?.message || "Atlas couldn't analyze that description. Please try again.");
    } finally { setAnalyzing(false); }
  };

  const toggleCapability = (key: Capability) => {
    setCapabilities(prev => {
      if (!prev) return prev;
      const cur = prev[key];
      const next = LEVEL_ORDER[(LEVEL_ORDER.indexOf(cur) + 1) % LEVEL_ORDER.length];
      return { ...prev, [key]: next };
    });
  };

  const toggleRole = (role: Role) => {
    setRoles(prev => {
      if (!prev) return prev;
      return prev.includes(role) ? prev.filter(r => r !== role) : [...prev, role];
    });
  };

  const approve = async () => {
    if (!capabilities || !roles || clientAccess === null) return;
    setApproving(true); setError(null);
    try {
      await apiApproveBusinessConfiguration({
        capability_overrides: capabilities, role_overrides: roles, client_access_override: clientAccess,
      });
      router.replace('/(tabs)');
    } catch (e: any) {
      setError(e?.message || 'Could not save this configuration.');
    } finally { setApproving(false); }
  };

  const startOver = () => {
    setConfig(null); setCapabilities(null); setRoles(null); setClientAccess(null); setDescription('');
  };

  if (loading) {
    return (
      <SafeAreaView style={styles.center}>
        <ActivityIndicator color={theme.color.brand} />
      </SafeAreaView>
    );
  }

  return (
    <SafeAreaView style={styles.container}>
      <ScrollView contentContainerStyle={styles.scroll}>
        <Text style={styles.title}>Tell Atlas about your business</Text>
        <Text style={styles.subtitle}>
          Describe how your team actually works. Atlas will recommend a setup — you review and confirm it.
        </Text>

        {!config && (
          <View style={styles.card}>
            <TextInput
              style={styles.input}
              multiline
              placeholder="e.g. We run a restaurant with two outlets. Outlet managers handle suppliers, kitchen operations and staff..."
              placeholderTextColor={theme.color.textDim}
              value={description}
              onChangeText={setDescription}
            />
            {error && <Text style={styles.error}>{error}</Text>}
            <Pressable
              style={[styles.button, (!description.trim() || analyzing) && styles.buttonDisabled]}
              disabled={!description.trim() || analyzing}
              onPress={analyze}
            >
              {analyzing
                ? <ActivityIndicator color={theme.color.onBrand} />
                : <Text style={styles.buttonText}>Analyze my business</Text>}
            </Pressable>
          </View>
        )}

        {config && capabilities && roles && clientAccess !== null && (
          <View>
            <View style={styles.card}>
              <Text style={styles.sectionTitle}>What Atlas understood</Text>
              <Text style={styles.explanation}>{config.ai_recommendation.explanation}</Text>
              <Text style={styles.meta}>
                {config.ai_recommendation.business_profile.business_type}
                {config.ai_recommendation.business_profile.operating_model
                  ? ` · ${config.ai_recommendation.business_profile.operating_model}` : ''}
              </Text>
              {config.ai_recommendation.assumptions.length > 0 && (
                <View style={styles.assumptions}>
                  <Text style={styles.assumptionsLabel}>Assumptions Atlas made:</Text>
                  {config.ai_recommendation.assumptions.map((a, i) => (
                    <Text key={i} style={styles.assumptionLine}>• {a}</Text>
                  ))}
                </View>
              )}
            </View>

            {config.ai_recommendation.configuration_questions.length > 0 && (
              <View style={styles.card}>
                <Text style={styles.sectionTitle}>A couple of questions</Text>
                {config.ai_recommendation.configuration_questions.map((q, i) => (
                  <Text key={i} style={styles.question}>{q}</Text>
                ))}
                <Text style={styles.hint}>Adjust the options below to reflect your answers.</Text>
              </View>
            )}

            <View style={styles.card}>
              <Text style={styles.sectionTitle}>Roles</Text>
              <Text style={styles.hint}>These are recommendations only — no accounts are created yet.</Text>
              {ALL_ROLES.map(role => (
                <Pressable key={role} style={styles.row} onPress={() => toggleRole(role)}>
                  <View style={[styles.checkbox, roles.includes(role) && styles.checkboxOn]} />
                  <Text style={styles.rowText}>{ROLE_LABELS[role]}</Text>
                </Pressable>
              ))}
            </View>

            <View style={styles.card}>
              <Text style={styles.sectionTitle}>Client access</Text>
              <Pressable style={styles.row} onPress={() => setClientAccess(!clientAccess)}>
                <View style={[styles.checkbox, clientAccess && styles.checkboxOn]} />
                <Text style={styles.rowText}>Clients/customers need to log into Atlas directly</Text>
              </Pressable>
            </View>

            <View style={styles.card}>
              <Text style={styles.sectionTitle}>Capabilities</Text>
              <Text style={styles.hint}>Tap to cycle: Required → Optional → Not needed</Text>
              {(Object.keys(CAPABILITY_LABELS) as Capability[]).map(key => (
                <Pressable key={key} style={styles.row} onPress={() => toggleCapability(key)}>
                  <Text style={styles.rowText}>{CAPABILITY_LABELS[key]}</Text>
                  <Text style={[
                    styles.levelBadge,
                    capabilities[key] === 'required' && styles.levelRequired,
                    capabilities[key] === 'optional' && styles.levelOptional,
                    capabilities[key] === 'not_required' && styles.levelNotRequired,
                  ]}>
                    {LEVEL_LABEL[capabilities[key]]}
                  </Text>
                </Pressable>
              ))}
            </View>

            {error && <Text style={styles.error}>{error}</Text>}

            <Pressable style={[styles.button, approving && styles.buttonDisabled]} disabled={approving} onPress={approve}>
              {approving
                ? <ActivityIndicator color={theme.color.onBrand} />
                : <Text style={styles.buttonText}>Confirm and continue</Text>}
            </Pressable>
            <Pressable style={styles.secondaryButton} onPress={startOver}>
              <Text style={styles.secondaryButtonText}>Start over with a different description</Text>
            </Pressable>
          </View>
        )}
      </ScrollView>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1, backgroundColor: theme.color.surface },
  center: { flex: 1, backgroundColor: theme.color.surface, alignItems: 'center', justifyContent: 'center' },
  scroll: { padding: theme.spacing.xs * 2, paddingBottom: 48 },
  title: { color: theme.color.text, fontSize: 22, fontWeight: '700', marginBottom: 4 },
  subtitle: { color: theme.color.textMuted, fontSize: 14, marginBottom: 16 },
  card: {
    backgroundColor: theme.color.surface2, borderRadius: 12, padding: 16, marginBottom: 16,
    borderWidth: 1, borderColor: theme.color.border,
  },
  sectionTitle: { color: theme.color.text, fontSize: 16, fontWeight: '600', marginBottom: 8 },
  input: {
    color: theme.color.text, minHeight: 120, textAlignVertical: 'top', fontSize: 15,
    borderWidth: 1, borderColor: theme.color.border, borderRadius: 8, padding: 12, marginBottom: 12,
  },
  explanation: { color: theme.color.textMuted, fontSize: 14, marginBottom: 8, lineHeight: 20 },
  meta: { color: theme.color.textDim, fontSize: 12 },
  assumptions: { marginTop: 12 },
  assumptionsLabel: { color: theme.color.textDim, fontSize: 12, marginBottom: 4 },
  assumptionLine: { color: theme.color.textDim, fontSize: 12, lineHeight: 18 },
  question: { color: theme.color.text, fontSize: 14, marginBottom: 6 },
  hint: { color: theme.color.textDim, fontSize: 12, marginBottom: 8 },
  row: {
    flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between',
    paddingVertical: 10, borderBottomWidth: 1, borderBottomColor: theme.color.border,
  },
  rowText: { color: theme.color.text, fontSize: 14, flex: 1 },
  checkbox: {
    width: 20, height: 20, borderRadius: 4, borderWidth: 2, borderColor: theme.color.borderStrong, marginRight: 12,
  },
  checkboxOn: { backgroundColor: theme.color.brand, borderColor: theme.color.brand },
  levelBadge: { fontSize: 12, fontWeight: '600', paddingHorizontal: 8, paddingVertical: 4, borderRadius: 6, overflow: 'hidden' },
  levelRequired: { color: theme.color.onBrand, backgroundColor: theme.color.success },
  levelOptional: { color: theme.color.text, backgroundColor: theme.color.surface3 },
  levelNotRequired: { color: theme.color.textDim, backgroundColor: 'transparent' },
  error: { color: theme.color.error, fontSize: 13, marginBottom: 12 },
  button: {
    backgroundColor: theme.color.brand, borderRadius: 10, paddingVertical: 14,
    alignItems: 'center', marginTop: 4,
  },
  buttonDisabled: { opacity: 0.5 },
  buttonText: { color: theme.color.onBrand, fontSize: 15, fontWeight: '700' },
  secondaryButton: { alignItems: 'center', paddingVertical: 14 },
  secondaryButtonText: { color: theme.color.textMuted, fontSize: 13 },
});
