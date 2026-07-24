// Calendar Date Picker — a lightweight, dependency-free calendar picker
// built on React Native primitives + date-fns (already a project
// dependency; no new native module/library added, avoiding the native-
// linking risk a package like @react-native-community/datetimepicker
// would introduce in this environment).
//
// Contract: value/onChange are always ISO 8601 date strings
// ("YYYY-MM-DD" for date-only fields), matching how every planning
// field already stores dates. The UI presents a human-friendly label;
// storage is untouched — this is a pure input-method replacement, not
// a data model or schema change.
import { useState } from 'react';
import { View, Text, StyleSheet, Pressable, Modal, ScrollView } from 'react-native';
import { Ionicons } from '@expo/vector-icons';
import {
  format, startOfMonth, endOfMonth, startOfWeek, endOfWeek,
  eachDayOfInterval, addMonths, subMonths, isSameMonth, isSameDay, parseISO, isValid,
} from 'date-fns';
import { theme } from './theme';

export type DatePickerProps = {
  label?: string;
  /** ISO date string ("YYYY-MM-DD") or null/undefined for unset. */
  value: string | null | undefined;
  /** Called with an ISO date string, or null when cleared. */
  onChange: (isoDate: string | null) => void;
  testID?: string;
  placeholder?: string;
  /** Allow clearing a previously-set date. Defaults to true. */
  clearable?: boolean;
};

function toIsoDate(d: Date): string {
  return format(d, 'yyyy-MM-dd');
}

function parseValue(value: string | null | undefined): Date | null {
  if (!value) return null;
  // Planning fields today store either a bare date ("2026-09-01") or a
  // full ISO datetime ("2026-09-01T00:00:00+00:00") - both parse fine.
  const d = parseISO(value);
  return isValid(d) ? d : null;
}

export function DatePicker({ label, value, onChange, testID, placeholder, clearable = true }: DatePickerProps) {
  const [open, setOpen] = useState(false);
  const selected = parseValue(value);
  const [viewMonth, setViewMonth] = useState<Date>(selected || new Date());

  const openPicker = () => {
    setViewMonth(selected || new Date());
    setOpen(true);
  };

  const gridStart = startOfWeek(startOfMonth(viewMonth));
  const gridEnd = endOfWeek(endOfMonth(viewMonth));
  const days = eachDayOfInterval({ start: gridStart, end: gridEnd });

  return (
    <View>
      {!!label && <Text style={styles.label}>{label}</Text>}
      <Pressable testID={testID} onPress={openPicker} style={styles.field}>
        <Ionicons name="calendar-outline" size={16} color={theme.color.textDim} />
        <Text style={[styles.fieldText, !selected && styles.fieldPlaceholder]}>
          {selected ? format(selected, 'd MMM yyyy') : (placeholder || 'Select a date')}
        </Text>
        {clearable && selected && (
          <Pressable testID={testID ? `${testID}-clear` : undefined} onPress={() => onChange(null)} hitSlop={8}>
            <Ionicons name="close-circle" size={16} color={theme.color.textDim} />
          </Pressable>
        )}
      </Pressable>

      <Modal visible={open} animationType="fade" transparent>
        <Pressable style={styles.backdrop} onPress={() => setOpen(false)}>
          <View style={styles.sheet} onStartShouldSetResponder={() => true}>
            <View style={styles.monthRow}>
              <Pressable testID={testID ? `${testID}-prev-month` : undefined} onPress={() => setViewMonth((m) => subMonths(m, 1))} hitSlop={8}>
                <Ionicons name="chevron-back" size={20} color={theme.color.brand} />
              </Pressable>
              <Text style={styles.monthLabel}>{format(viewMonth, 'MMMM yyyy')}</Text>
              <Pressable testID={testID ? `${testID}-next-month` : undefined} onPress={() => setViewMonth((m) => addMonths(m, 1))} hitSlop={8}>
                <Ionicons name="chevron-forward" size={20} color={theme.color.brand} />
              </Pressable>
            </View>

            <View style={styles.weekdayRow}>
              {['S', 'M', 'T', 'W', 'T', 'F', 'S'].map((d, i) => (
                <Text key={i} style={styles.weekdayText}>{d}</Text>
              ))}
            </View>

            <View style={styles.grid}>
              {days.map((day) => {
                const inMonth = isSameMonth(day, viewMonth);
                const isSelected = selected && isSameDay(day, selected);
                return (
                  <Pressable
                    key={day.toISOString()}
                    testID={testID ? `${testID}-day-${toIsoDate(day)}` : undefined}
                    onPress={() => { onChange(toIsoDate(day)); setOpen(false); }}
                    style={[styles.dayCell, isSelected && styles.dayCellSelected]}
                  >
                    <Text style={[
                      styles.dayText,
                      !inMonth && styles.dayTextMuted,
                      isSelected && styles.dayTextSelected,
                    ]}>
                      {format(day, 'd')}
                    </Text>
                  </Pressable>
                );
              })}
            </View>

            <View style={styles.footerRow}>
              <Pressable testID={testID ? `${testID}-today` : undefined} onPress={() => { onChange(toIsoDate(new Date())); setOpen(false); }}>
                <Text style={styles.footerLink}>Today</Text>
              </Pressable>
              {clearable && (
                <Pressable testID={testID ? `${testID}-clear-modal` : undefined} onPress={() => { onChange(null); setOpen(false); }}>
                  <Text style={styles.footerLink}>Clear</Text>
                </Pressable>
              )}
              <Pressable testID={testID ? `${testID}-close` : undefined} onPress={() => setOpen(false)}>
                <Text style={[styles.footerLink, { color: theme.color.text }]}>Close</Text>
              </Pressable>
            </View>
          </View>
        </Pressable>
      </Modal>
    </View>
  );
}

const styles = StyleSheet.create({
  label: { color: theme.color.textDim, fontSize: 10, fontWeight: '800', letterSpacing: 0.5, marginBottom: 4 },
  field: {
    flexDirection: 'row', alignItems: 'center', gap: 8, backgroundColor: theme.color.surface2,
    borderRadius: theme.radius.sm, borderWidth: 1, borderColor: theme.color.border,
    paddingHorizontal: 10, paddingVertical: 10,
  },
  fieldText: { color: theme.color.text, fontSize: 14, fontWeight: '600', flex: 1 },
  fieldPlaceholder: { color: theme.color.textDim, fontWeight: '400' },
  backdrop: { flex: 1, backgroundColor: 'rgba(0,0,0,0.6)', alignItems: 'center', justifyContent: 'center' },
  sheet: {
    backgroundColor: theme.color.surface2, borderRadius: theme.radius.lg, padding: theme.spacing.md,
    width: '88%', maxWidth: 360, borderWidth: 1, borderColor: theme.color.border,
  },
  monthRow: { flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between', marginBottom: theme.spacing.sm },
  monthLabel: { color: theme.color.text, fontSize: 15, fontWeight: '800' },
  weekdayRow: { flexDirection: 'row', marginBottom: 4 },
  weekdayText: { flex: 1, textAlign: 'center', color: theme.color.textDim, fontSize: 11, fontWeight: '700' },
  grid: { flexDirection: 'row', flexWrap: 'wrap' },
  dayCell: { width: `${100 / 7}%`, aspectRatio: 1, alignItems: 'center', justifyContent: 'center', borderRadius: theme.radius.sm },
  dayCellSelected: { backgroundColor: theme.color.brand },
  dayText: { color: theme.color.text, fontSize: 13, fontWeight: '600' },
  dayTextMuted: { color: theme.color.textDim, fontWeight: '400' },
  dayTextSelected: { color: theme.color.onBrand, fontWeight: '800' },
  footerRow: {
    flexDirection: 'row', justifyContent: 'space-between', marginTop: theme.spacing.sm,
    paddingTop: theme.spacing.sm, borderTopWidth: 1, borderTopColor: theme.color.border,
  },
  footerLink: { color: theme.color.brand, fontSize: 13, fontWeight: '700' },
});
