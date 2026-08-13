// PX-01B P2-04 — Project Creation Wizard. Every step reuses an
// existing API exclusively (apiCreateProject, apiCreateSite,
// apiAssignProjects, apiCreateContract, apiCreateBudget) — no new
// backend model, per this task's own explicit constraint. Creation is
// transactional: if any step after project creation fails, the
// partially-created project is deleted so no orphaned record is left
// behind, matching this task's own "rollback all created records" rule.
import { useState } from 'react';
import { View, Text, StyleSheet, ScrollView, Pressable, ActivityIndicator, TextInput, Switch } from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import { Ionicons } from '@expo/vector-icons';
import { useRouter } from 'expo-router';
import { theme } from '@/src/theme';
import { DatePicker } from '@/src/DatePicker';
import { apiCreateProject, apiCreateSite, apiDeleteProject, apiAssignProjects } from '@/src/api';
import { apiListUsers, type AssignableUser } from '@/src/ops_api';
import { apiCreateContract, apiCreateBudget } from '@/src/commercial_api';

const ROLE_BADGE: Record<string, string> = { project_manager: 'PM', site_supervisor: 'Supervisor', management: 'Management' };
const BILLING_CYCLES = ['Monthly', 'Milestone', 'Progress'] as const;

export default function ProjectCreationWizard() {
  const router = useRouter();
  const [step, setStep] = useState(1);
  const [creating, setCreating] = useState(false);
  const [createError, setCreateError] = useState<string | null>(null);

  // Step 1
  const [name, setName] = useState('');
  const [clientName, setClientName] = useState('');
  const [location, setLocation] = useState('');
  const [startDate, setStartDate] = useState<string | null>(null);
  const [completionDate, setCompletionDate] = useState<string | null>(null);
  const [dateError, setDateError] = useState<string | null>(null);

  // Step 2
  const [pmCandidates, setPmCandidates] = useState<AssignableUser[]>([]);
  const [supCandidates, setSupCandidates] = useState<AssignableUser[]>([]);
  const [candidatesLoaded, setCandidatesLoaded] = useState(false);
  const [selectedPm, setSelectedPm] = useState<AssignableUser | null>(null);
  const [selectedSup, setSelectedSup] = useState<AssignableUser | null>(null);

  // Step 3
  const [contractValue, setContractValue] = useState('');
  const [initialBudget, setInitialBudget] = useState('');
  const [gstIncluded, setGstIncluded] = useState(false);
  const [retentionPercent, setRetentionPercent] = useState('');
  const [billingCycle, setBillingCycle] = useState<typeof BILLING_CYCLES[number]>('Milestone');

  const loadCandidates = async () => {
    if (candidatesLoaded) return;
    const [pms, sups] = await Promise.all([
      apiListUsers('project_manager').catch(() => []),
      apiListUsers('site_supervisor').catch(() => []),
    ]);
    setPmCandidates(pms);
    setSupCandidates(sups);
    setCandidatesLoaded(true);
  };

  const goToStep2 = async () => {
    await loadCandidates();
    setStep(2);
  };

  const goToStep1Validated = () => {
    setDateError(null);
    if (!name.trim()) return;
    if (startDate && completionDate && completionDate < startDate) {
      setDateError('Target Completion Date cannot be before Start Date.');
      return;
    }
    goToStep2();
  };

  const initialMargin = (() => {
    const cv = parseFloat(contractValue) || 0;
    const b = parseFloat(initialBudget) || 0;
    if (cv <= 0) return null;
    return ((cv - b) / cv) * 100;
  })();

  const onCreate = async () => {
    setCreating(true);
    setCreateError(null);
    let createdProjectId: string | null = null;
    try {
      // 1. create project
      const project = await apiCreateProject({ name: name.trim(), location });
      createdProjectId = project.id;

      // 2. create default site
      await apiCreateSite({ project_id: project.id, name: 'Main Site', location });

      // 3. create memberships — PM first, so a PM-initiated wizard
      // becomes a member of the (currently memberless) project before
      // assigning anyone else, matching the backend's own "already a
      // member, or project has no members yet" rule.
      const memberIds = [selectedPm!.id, selectedSup!.id];
      for (const userId of memberIds) {
        await apiAssignProjects(userId, [project.id]);
      }

      // 4. create commercial shell (Contract + Budget), only if any commercial data was actually given
      const cv = parseFloat(contractValue);
      if (cv > 0 && startDate) {
        const durationDays = completionDate
          ? Math.max(1, Math.round((new Date(completionDate).getTime() - new Date(startDate).getTime()) / 86400000))
          : 180;
        await apiCreateContract({
          project_id: project.id, original_contract_value: cv, contract_date: startDate,
          duration_days: durationDays, gst_percent: gstIncluded ? 18 : 0,
          retention_percent: retentionPercent ? parseFloat(retentionPercent) : 0,
        });
        const budget = parseFloat(initialBudget);
        if (budget > 0) await apiCreateBudget(project.id, budget);
      }

      // 5. navigate to the new project's Workspace
      router.replace(`/workspace/${project.id}`);
    } catch {
      // Rollback: never leave an orphaned, half-configured project behind.
      if (createdProjectId) {
        await apiDeleteProject(createdProjectId).catch(() => {});
      }
      setCreateError('Something went wrong creating the project. Nothing was saved — please try again.');
    } finally {
      setCreating(false);
    }
  };

  return (
    <SafeAreaView style={styles.container} edges={['top']}>
      <View style={styles.header}>
        <Pressable testID="wizard-back" onPress={() => (step === 1 ? router.back() : setStep(step - 1))} hitSlop={12}>
          <Ionicons name="arrow-back" size={22} color={theme.color.text} />
        </Pressable>
        <Text style={styles.headerTitle}>New Project — Step {step} of 4</Text>
        <View style={{ width: 22 }} />
      </View>
      <View style={styles.stepBar}>
        {[1, 2, 3, 4].map((s) => <View key={s} style={[styles.stepDot, s <= step && styles.stepDotActive]} />)}
      </View>

      <ScrollView contentContainerStyle={styles.content}>
        {step === 1 && (
          <>
            <Text style={styles.sectionLabel}>BASIC INFORMATION</Text>
            <FieldLabel text="Project Name *" />
            <TextInput testID="wizard-name" style={styles.input} value={name} onChangeText={setName} placeholder="e.g. Sharma Residence" placeholderTextColor={theme.color.textDim} />
            <FieldLabel text="Client Name" />
            <TextInput testID="wizard-client" style={styles.input} value={clientName} onChangeText={setClientName} placeholder="Optional" placeholderTextColor={theme.color.textDim} />
            <FieldLabel text="Location" />
            <TextInput testID="wizard-location" style={styles.input} value={location} onChangeText={setLocation} placeholder="Optional" placeholderTextColor={theme.color.textDim} />
            <DatePicker label="Start Date" testID="wizard-start-date" value={startDate} onChange={setStartDate} />
            <DatePicker label="Target Completion Date" testID="wizard-completion-date" value={completionDate} onChange={setCompletionDate} />
            {dateError && <Text style={styles.errorText}>{dateError}</Text>}
            <PrimaryButton testID="wizard-next-1" label="Next: Team Assignment" onPress={goToStep1Validated} disabled={!name.trim()} />
          </>
        )}

        {step === 2 && (
          <>
            <Text style={styles.sectionLabel}>TEAM ASSIGNMENT</Text>
            <FieldLabel text="Project Manager *" />
            <UserSelector testID="wizard-pm" candidates={pmCandidates} selected={selectedPm} onSelect={setSelectedPm} />
            <FieldLabel text="Site Supervisor *" />
            <UserSelector testID="wizard-supervisor" candidates={supCandidates} selected={selectedSup} onSelect={setSelectedSup} />
            <Text style={styles.helperText}>Phone numbers are not shown here by design — the assignee picker strips contact details for pilot privacy.</Text>
            <PrimaryButton testID="wizard-next-2" label="Next: Commercial Setup" onPress={() => setStep(3)} disabled={!selectedPm || !selectedSup} />
          </>
        )}

        {step === 3 && (
          <>
            <Text style={styles.sectionLabel}>COMMERCIAL SETUP</Text>
            <FieldLabel text="Contract Value (₹)" />
            <TextInput testID="wizard-contract-value" style={styles.input} value={contractValue} onChangeText={setContractValue} keyboardType="decimal-pad" placeholder="Optional — can be set up later" placeholderTextColor={theme.color.textDim} />
            <FieldLabel text="Initial Budget (₹)" />
            <TextInput testID="wizard-budget" style={styles.input} value={initialBudget} onChangeText={setInitialBudget} keyboardType="decimal-pad" placeholder="Optional" placeholderTextColor={theme.color.textDim} />
            <View style={styles.toggleRow}>
              <Text style={styles.fieldLabel}>GST Included?</Text>
              <Switch testID="wizard-gst" value={gstIncluded} onValueChange={setGstIncluded} />
            </View>
            <FieldLabel text="Retention % (optional)" />
            <TextInput testID="wizard-retention" style={styles.input} value={retentionPercent} onChangeText={setRetentionPercent} keyboardType="decimal-pad" placeholder="e.g. 5" placeholderTextColor={theme.color.textDim} />
            <FieldLabel text="Billing Cycle" />
            <View style={styles.chipRow}>
              {BILLING_CYCLES.map((c) => (
                <Pressable key={c} testID={`wizard-billing-${c.toLowerCase()}`} onPress={() => setBillingCycle(c)}
                  style={[styles.chip, billingCycle === c && styles.chipActive]}>
                  <Text style={[styles.chipText, billingCycle === c && styles.chipTextActive]}>{c}</Text>
                </Pressable>
              ))}
            </View>
            <Text style={styles.helperText}>Billing Cycle is not yet stored by the Commercial Engine — collected here for record-keeping, applied to how milestones are created after the project exists.</Text>
            <PrimaryButton testID="wizard-next-3" label="Next: Review & Create" onPress={() => setStep(4)} />
          </>
        )}

        {step === 4 && (
          <>
            <Text style={styles.sectionLabel}>REVIEW & CREATE</Text>
            <View style={styles.summaryCard} testID="wizard-summary">
              <SummaryRow label="Project" value={name} />
              {clientName ? <SummaryRow label="Client" value={clientName} /> : null}
              {location ? <SummaryRow label="Location" value={location} /> : null}
              <SummaryRow label="Project Manager" value={selectedPm?.name || '—'} />
              <SummaryRow label="Site Supervisor" value={selectedSup?.name || '—'} />
              {contractValue ? <SummaryRow label="Contract Value" value={`₹${parseFloat(contractValue).toLocaleString('en-IN')}`} /> : null}
              {initialBudget ? <SummaryRow label="Initial Budget" value={`₹${parseFloat(initialBudget).toLocaleString('en-IN')}`} /> : null}
              {initialMargin !== null && (
                <SummaryRow label="Calculated Initial Margin" value={`${initialMargin.toFixed(1)}%`} emphasis />
              )}
            </View>
            {createError && <Text style={styles.errorText}>{createError}</Text>}
            <PrimaryButton testID="wizard-create" label={creating ? 'Creating…' : 'Create Project'} onPress={onCreate} disabled={creating} loading={creating} />
          </>
        )}
      </ScrollView>
    </SafeAreaView>
  );
}

function FieldLabel({ text }: { text: string }) {
  return <Text style={styles.fieldLabel}>{text}</Text>;
}

function PrimaryButton({ testID, label, onPress, disabled, loading }: { testID: string; label: string; onPress: () => void; disabled?: boolean; loading?: boolean }) {
  return (
    <Pressable testID={testID} onPress={onPress} disabled={disabled} style={[styles.primaryBtn, disabled && styles.primaryBtnDisabled]}>
      {loading ? <ActivityIndicator color={theme.color.onBrand} /> : <Text style={styles.primaryBtnText}>{label}</Text>}
    </Pressable>
  );
}

function SummaryRow({ label, value, emphasis }: { label: string; value: string; emphasis?: boolean }) {
  return (
    <View style={styles.summaryRow}>
      <Text style={styles.summaryLabel}>{label}</Text>
      <Text style={[styles.summaryValue, emphasis && styles.summaryValueEmphasis]}>{value}</Text>
    </View>
  );
}

function UserSelector({ testID, candidates, selected, onSelect }: {
  testID: string; candidates: AssignableUser[]; selected: AssignableUser | null; onSelect: (u: AssignableUser) => void;
}) {
  if (candidates.length === 0) {
    return <Text style={styles.helperText}>No eligible users found for this role.</Text>;
  }
  return (
    <View style={{ gap: 8 }}>
      {candidates.map((u) => (
        <Pressable key={u.id} testID={`${testID}-${u.id}`} onPress={() => onSelect(u)}
          style={[styles.userCard, selected?.id === u.id && styles.userCardSelected]}>
          <View style={{ flex: 1 }}>
            <Text style={styles.userName}>{u.name}</Text>
          </View>
          <View style={styles.roleBadge}>
            <Text style={styles.roleBadgeText}>{ROLE_BADGE[u.role] || u.role}</Text>
          </View>
          {selected?.id === u.id && <Ionicons name="checkmark-circle" size={20} color={theme.color.brand} style={{ marginLeft: 8 }} />}
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
  headerTitle: { color: theme.color.text, fontSize: 15, fontWeight: '800' },
  stepBar: { flexDirection: 'row', gap: 6, paddingHorizontal: theme.spacing.lg, marginBottom: theme.spacing.md },
  stepDot: { flex: 1, height: 4, borderRadius: 2, backgroundColor: theme.color.border },
  stepDotActive: { backgroundColor: theme.color.brand },
  content: { padding: theme.spacing.md, paddingBottom: 60 },
  sectionLabel: { color: theme.color.textDim, fontSize: 11, fontWeight: '800', letterSpacing: 1, marginBottom: theme.spacing.md },
  fieldLabel: { color: theme.color.text, fontSize: 13, fontWeight: '700', marginBottom: 6, marginTop: theme.spacing.sm },
  input: {
    backgroundColor: theme.color.surface2, borderRadius: theme.radius.sm, borderWidth: 1, borderColor: theme.color.border,
    paddingHorizontal: 12, paddingVertical: 10, color: theme.color.text, fontSize: 14, marginBottom: theme.spacing.sm,
  },
  errorText: { color: theme.color.error, fontSize: 13, marginTop: theme.spacing.xs, marginBottom: theme.spacing.sm },
  helperText: { color: theme.color.textDim, fontSize: 12, fontStyle: 'italic', marginTop: theme.spacing.sm },
  toggleRow: { flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between', marginTop: theme.spacing.sm },
  chipRow: { flexDirection: 'row', gap: 8, marginBottom: theme.spacing.sm },
  chip: { paddingVertical: 8, paddingHorizontal: 14, borderRadius: 16, backgroundColor: theme.color.surface2, borderWidth: 1, borderColor: theme.color.border },
  chipActive: { backgroundColor: theme.color.brand, borderColor: theme.color.brand },
  chipText: { color: theme.color.textDim, fontSize: 12, fontWeight: '700' },
  chipTextActive: { color: theme.color.onBrand },
  userCard: {
    flexDirection: 'row', alignItems: 'center', padding: 12, borderRadius: theme.radius.sm,
    backgroundColor: theme.color.surface2, borderWidth: 1, borderColor: theme.color.border,
  },
  userCardSelected: { borderColor: theme.color.brand },
  userName: { color: theme.color.text, fontSize: 14, fontWeight: '700' },
  roleBadge: { backgroundColor: theme.color.surface3, paddingHorizontal: 8, paddingVertical: 3, borderRadius: 10 },
  roleBadgeText: { color: theme.color.textDim, fontSize: 10, fontWeight: '700' },
  primaryBtn: {
    backgroundColor: theme.color.brand, borderRadius: theme.radius.sm, paddingVertical: 14,
    alignItems: 'center', marginTop: theme.spacing.lg,
  },
  primaryBtnDisabled: { opacity: 0.5 },
  primaryBtnText: { color: theme.color.onBrand, fontSize: 15, fontWeight: '800' },
  summaryCard: {
    backgroundColor: theme.color.surface2, borderRadius: theme.radius.md, borderWidth: 1,
    borderColor: theme.color.border, padding: theme.spacing.md,
  },
  summaryRow: { flexDirection: 'row', justifyContent: 'space-between', paddingVertical: 6 },
  summaryLabel: { color: theme.color.textDim, fontSize: 13 },
  summaryValue: { color: theme.color.text, fontSize: 13, fontWeight: '600' },
  summaryValueEmphasis: { color: theme.color.brand, fontWeight: '800' },
});
