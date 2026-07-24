// Visual Urgency — a single, shared urgency language for Atlas, so a
// color means the same thing everywhere it appears (Events, Activities,
// Operations, Dashboards, Portfolio). Pure presentation: derives a
// label/color from data that already exists on the item (status,
// priority, required_by) — no new field, no new state.
import { theme } from './theme';

export type UrgencyState = 'not_started' | 'assigned' | 'on_track' | 'due_soon' | 'overdue' | 'blocked';

export const URGENCY_COLOR: Record<UrgencyState, string> = {
  not_started: '#9E9E9E', // Grey
  assigned: '#2196F3',    // Blue
  on_track: theme.color.success,   // Green
  due_soon: theme.color.warning,   // Amber
  overdue: theme.color.error,      // Red
  blocked: '#9C27B0',     // Purple
};

export const URGENCY_LABEL: Record<UrgencyState, string> = {
  not_started: 'Not Started',
  assigned: 'Assigned',
  on_track: 'On Track',
  due_soon: 'Due Soon',
  overdue: 'Overdue',
  blocked: 'Blocked',
};

const DUE_SOON_WINDOW_MS = 2 * 24 * 60 * 60 * 1000; // 2 days

/** Derives an UrgencyState from an operational item's existing fields.
 * Reused everywhere an item's urgency needs to be shown - one
 * definition, not a color choice re-decided per screen. */
export function operationalItemUrgency(item: {
  status: string; priority?: string | null; required_by?: string | null;
}): UrgencyState {
  if (item.status === 'blocked') return 'blocked';
  if (['fulfilled', 'verified', 'closed', 'archived', 'cancelled', 'duplicate'].includes(item.status)) return 'on_track';
  if (item.required_by) {
    const due = new Date(item.required_by).getTime();
    const now = Date.now();
    if (!isNaN(due)) {
      if (due < now) return 'overdue';
      if (due - now <= DUE_SOON_WINDOW_MS) return 'due_soon';
    }
  }
  if (item.status === 'open') return 'not_started';
  if (item.status === 'assigned' || item.status === 'acknowledged') return 'assigned';
  return 'on_track';
}

/** Derives an UrgencyState from a workflow activity's existing status
 * field plus planned_finish, the same "one definition, reused
 * everywhere" principle as operationalItemUrgency above. */
export function workflowActivityUrgency(activity: {
  status: string; planned_finish?: string | null;
}): UrgencyState {
  if (activity.status === 'blocked') return 'blocked';
  if (activity.status === 'completed') return 'on_track';
  if (activity.planned_finish) {
    const due = new Date(activity.planned_finish).getTime();
    const now = Date.now();
    if (!isNaN(due)) {
      if (due < now) return 'overdue';
      if (due - now <= DUE_SOON_WINDOW_MS) return 'due_soon';
    }
  }
  if (activity.status === 'not_started') return 'not_started';
  if (activity.status === 'ready') return 'assigned';
  return 'on_track'; // in_progress, on schedule
}
