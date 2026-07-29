import { useEffect, useState } from 'react';
import {
  View, Text, StyleSheet, ScrollView, Pressable, ActivityIndicator,
  TextInput, Platform, KeyboardAvoidingView, Alert,
} from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import { Ionicons } from '@expo/vector-icons';
import { useRouter } from 'expo-router';
import { theme } from '@/src/theme';
import { DatePicker } from '@/src/DatePicker';
import { apiListSites, getActiveSite, type Site } from '@/src/api';
import { apiCreateItem } from '@/src/ops_api';

const CATEGORIES: { value: string; label: string; icon: any }[] = [
  { value: 'material_requirement', label: 'Material Requirement', icon: 'cube' },
  { value: 'labour_requirement', label: 'Labour Requirement', icon: 'people' },
  { value: 'equipment_requirement', label: 'Equipment Requirement', icon: 'construct' },
  { value: 'site_issue', label: 'Site Issue', icon: 'warning' },
  { value: 'safety_observation', label: 'Safety Observation', icon: 'shield-checkmark' },
  { value: 'quality_observation', label: 'Quality Observation', icon: 'checkmark-circle' },
  { value: 'drawing_request', label: 'Drawing Request', icon: 'document-text' },
  { value: 'client_approval', label: 'Client Approval Needed', icon: 'person-circle' },
  { value: 'inspection', label: 'Inspection', icon: 'search' },
  { value: 'commitment', label: 'Commitment', icon: 'ribbon' },
  { value: 'follow_up', label: 'Follow-up', icon: 'time' },
  { value: 'general', label: 'General', icon: 'ellipsis-horizontal-circle' },
];

const PRIORITIES: { value: 'low' | 'normal' | 'high' | 'critical'; label: string; color: string }[] = [
  { value: 'low', label: 'Low', color: theme.color.textDim },
  { value: 'normal', label: 'Normal', color: theme.color.info },
  { value: 'high', label: 'High', color: theme.color.warning },
  { value: 'critical', label: 'Critical', color: theme.color.error },
];

export default function CreateOperationalItemScreen() {
  const router = useRouter();
  const [sites, setSites] = useState<Site[]>([]);
  const [siteId, setSiteId] = useState<string | null>(null);
  const [category, setCategory] = useState<string | null>(null);
  const [title, setTitle] = useState('');
  const [description, setDescription] = useState('');
  const [priority, setPriority] = useState<'low' | 'normal' | 'high' | 'critical'>('normal');
  const [requiredBy, setRequiredBy] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [loadingSites, setLoadingSites] = useState(true);

  useEffect(() => {
    (async () => {
      try {
        const list = await apiListSites();
        setSites(list);
        const stored = await getActiveSite();
        setSiteId(stored || (list[0]?.id ?? null));
      } finally {
        setLoadingSites(false);
      }
    })();
  }, []);

  const canSubmit = !!siteId && !!category && title.trim().length > 0 && !submitting;

  const onSubmit = async () => {
    if (!canSubmit || !siteId || !category) return;
    setSubmitting(true);
    try {
      const item = await apiCreateItem({
        site_id: siteId, category, title: title.trim(),
        description: description.trim() || undefined, priority,
        required_by: requiredBy || undefined,
      });
      router.replace(`/op/${item.id}`);
    } catch (e: any) {
      Alert.alert('Could not create item', e?.message || 'Please try again.');
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <SafeAreaView style={styles.container} edges={['top']}>
      <View style={styles.header}>
        <Pressable onPress={() => router.back()} hitSlop={12} testID="create-item-back">
          <Ionicons name="chevron-back" size={26} color={theme.color.text} />
        </Pressable>
        <Text style={styles.headerTitle}>New Item</Text>
        <View style={{ width: 26 }} />
      </View>

      <KeyboardAvoidingView behavior={Platform.OS === 'ios' ? 'padding' : undefined} style={{ flex: 1 }}>
        <ScrollView contentContainerStyle={styles.content} keyboardShouldPersistTaps="handled">
          {loadingSites ? (
            <ActivityIndicator color={theme.color.brand} style={{ marginTop: 40 }} />
          ) : (
            <>
              <Text style={styles.sectionLabel}>SITE</Text>
              <View style={styles.chipRow}>
                {sites.map((s) => (
                  <Pressable key={s.id} testID={`create-item-site-${s.id}`}
                    onPress={() => setSiteId(s.id)}
                    style={[styles.chip, siteId === s.id && styles.chipActive]}>
                    <Text style={[styles.chipText, siteId === s.id && styles.chipTextActive]}>{s.name}</Text>
                  </Pressable>
                ))}
              </View>

              <Text style={styles.sectionLabel}>CATEGORY</Text>
              <View style={styles.categoryGrid}>
                {CATEGORIES.map((c) => (
                  <Pressable key={c.value} testID={`create-item-category-${c.value}`}
                    onPress={() => setCategory(c.value)}
                    style={[styles.categoryCard, category === c.value && styles.categoryCardActive]}>
                    <Ionicons name={c.icon} size={20}
                      color={category === c.value ? theme.color.brand : theme.color.textDim} />
                    <Text style={[styles.categoryText, category === c.value && styles.categoryTextActive]}>
                      {c.label}
                    </Text>
                  </Pressable>
                ))}
              </View>

              <Text style={styles.sectionLabel}>TITLE</Text>
              <TextInput
                testID="create-item-title"
                style={styles.input}
                placeholder="Short, specific summary"
                placeholderTextColor={theme.color.textDim}
                value={title}
                onChangeText={setTitle}
                maxLength={140}
              />

              <Text style={styles.sectionLabel}>DESCRIPTION (OPTIONAL)</Text>
              <TextInput
                testID="create-item-description"
                style={[styles.input, styles.inputMultiline]}
                placeholder="Any further detail"
                placeholderTextColor={theme.color.textDim}
                value={description}
                onChangeText={setDescription}
                multiline
                numberOfLines={4}
              />

              <Text style={styles.sectionLabel}>PRIORITY</Text>
              <View style={styles.chipRow}>
                {PRIORITIES.map((p) => (
                  <Pressable key={p.value} testID={`create-item-priority-${p.value}`}
                    onPress={() => setPriority(p.value)}
                    style={[styles.chip, priority === p.value && { backgroundColor: p.color, borderColor: p.color }]}>
                    <Text style={[styles.chipText, priority === p.value && styles.chipTextActive]}>{p.label}</Text>
                  </Pressable>
                ))}
              </View>

              <Text style={styles.sectionLabel}>REQUIRED BY (OPTIONAL)</Text>
              <DatePicker value={requiredBy} onChange={setRequiredBy} testID="create-item-required-by" />
            </>
          )}
        </ScrollView>
      </KeyboardAvoidingView>

      <View style={styles.footer}>
        <Pressable
          testID="create-item-submit"
          disabled={!canSubmit}
          onPress={onSubmit}
          style={[styles.submitButton, !canSubmit && styles.submitButtonDisabled]}
        >
          {submitting ? <ActivityIndicator color={theme.color.onBrand} /> : (
            <Text style={styles.submitButtonText}>CREATE ITEM</Text>
          )}
        </Pressable>
      </View>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1, backgroundColor: theme.color.surface },
  header: {
    flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between',
    paddingHorizontal: theme.spacing.lg, paddingVertical: theme.spacing.md,
  },
  headerTitle: { color: theme.color.text, fontSize: 18, fontWeight: '800' },
  content: { padding: theme.spacing.lg, paddingBottom: 120, gap: theme.spacing.xs },
  sectionLabel: {
    color: theme.color.textDim, fontSize: 11, fontWeight: '800', letterSpacing: 0.5,
    marginTop: theme.spacing.lg, marginBottom: theme.spacing.sm,
  },
  chipRow: { flexDirection: 'row', flexWrap: 'wrap', gap: 8 },
  chip: {
    paddingHorizontal: 14, paddingVertical: 8, borderRadius: theme.radius.pill,
    borderWidth: 1, borderColor: theme.color.border, backgroundColor: theme.color.surface2,
  },
  chipActive: { backgroundColor: theme.color.brand, borderColor: theme.color.brand },
  chipText: { color: theme.color.text, fontSize: 13, fontWeight: '700' },
  chipTextActive: { color: theme.color.onBrand },
  categoryGrid: { flexDirection: 'row', flexWrap: 'wrap', gap: 8 },
  categoryCard: {
    width: '31%', alignItems: 'center', gap: 6, paddingVertical: 12, borderRadius: theme.radius.sm,
    borderWidth: 1, borderColor: theme.color.border, backgroundColor: theme.color.surface2,
  },
  categoryCardActive: { borderColor: theme.color.brand, backgroundColor: theme.color.brandTint },
  categoryText: { color: theme.color.textDim, fontSize: 11, fontWeight: '700', textAlign: 'center' },
  categoryTextActive: { color: theme.color.brand },
  input: {
    borderWidth: 1, borderColor: theme.color.border, borderRadius: theme.radius.sm,
    paddingHorizontal: 14, paddingVertical: 12, color: theme.color.text, fontSize: 15,
    backgroundColor: theme.color.surface2,
  },
  inputMultiline: { minHeight: 90, textAlignVertical: 'top' },
  footer: {
    padding: theme.spacing.lg, borderTopWidth: 1, borderTopColor: theme.color.border,
    backgroundColor: theme.color.surface,
  },
  submitButton: {
    backgroundColor: theme.color.brand, borderRadius: theme.radius.sm,
    paddingVertical: 14, alignItems: 'center',
  },
  submitButtonDisabled: { opacity: 0.4 },
  submitButtonText: { color: theme.color.onBrand, fontSize: 15, fontWeight: '800' },
});
