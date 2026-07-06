/**
 * Sprint 3 — Role-based workspaces.
 *
 * Frontend-only. Backend roles remain `supervisor | coordinator | management`.
 * We introduce a *view role* stored in AsyncStorage that governs which
 * navigation, screens and data filters the current user sees. The mapping
 * to backend roles is deliberately one-way: view roles derive backend
 * permissions but never contradict them.
 */
import AsyncStorage from '@react-native-async-storage/async-storage';
import type { Role } from './api';

export type ViewRole = 'client' | 'supervisor' | 'pm' | 'admin';
export const VIEW_ROLE_KEY = 'atlas.view_role';

export const VIEW_ROLE_LABEL: Record<ViewRole, string> = {
  client: 'Client',
  supervisor: 'Site Supervisor',
  pm: 'Project Manager',
  admin: 'Admin',
};

export const VIEW_ROLE_ICON: Record<ViewRole, any> = {
  client: 'briefcase-outline',
  supervisor: 'hardware-chip-outline',
  pm: 'clipboard-outline',
  admin: 'shield-checkmark-outline',
};

/** Backend role each view role authenticates as. */
export const BACKEND_ROLE_FOR: Record<ViewRole, Role> = {
  client: 'coordinator',   // read-mostly; the frontend hides everything operational
  supervisor: 'supervisor',
  pm: 'coordinator',
  admin: 'management',
};

/** Per-view-role visibility flags. Screens read these to decide what to render. */
export type ViewPerms = {
  showProposals: boolean;
  showAssignments: boolean;
  showDashboards: boolean;
  showOpsBuckets: boolean;
  showCapture: boolean;
  /** When set, proposals list is filtered to this category only. */
  proposalCategoryFilter?: string;
  /** When set, ops list filters to this category only. */
  itemCategoryFilter?: string;
  /** When true, ops screen shows only items assigned to me. */
  onlyMyItems?: boolean;
  /** Timeline header label. */
  homeLabel: string;
  /** Ops screen header label. */
  opsLabel: string;
};

export const VIEW_PERMS: Record<ViewRole, ViewPerms> = {
  client: {
    showProposals: true, showAssignments: false, showDashboards: false, showOpsBuckets: false,
    showCapture: false, proposalCategoryFilter: 'client_approval',
    homeLabel: 'PROJECT UPDATES', opsLabel: 'APPROVALS',
  },
  supervisor: {
    showProposals: false, showAssignments: true, showDashboards: false, showOpsBuckets: false,
    showCapture: true, onlyMyItems: true,
    homeLabel: 'TODAY', opsLabel: 'ISSUES',
  },
  pm: {
    showProposals: true, showAssignments: true, showDashboards: true, showOpsBuckets: true,
    showCapture: true,
    homeLabel: 'DASHBOARD', opsLabel: 'OPERATIONS',
  },
  admin: {
    showProposals: true, showAssignments: true, showDashboards: true, showOpsBuckets: true,
    showCapture: true,
    homeLabel: 'DASHBOARD', opsLabel: 'OPERATIONS',
  },
};

/** Tab bar definition per role. Tabs not listed here are hidden via href:null. */
export type TabDef = { name: 'index' | 'ops' | 'capture' | 'profile'; label: string; icon: string };
export const TABS_FOR: Record<ViewRole, TabDef[]> = {
  client:      [
    { name: 'index',   label: 'HOME',      icon: 'home' },
    { name: 'ops',     label: 'APPROVALS', icon: 'checkmark-done' },
    { name: 'profile', label: 'PROFILE',   icon: 'person' },
  ],
  supervisor:  [
    { name: 'index',   label: 'TODAY',   icon: 'today' },
    { name: 'capture', label: 'CAPTURE', icon: 'mic' },
    { name: 'ops',     label: 'ISSUES',  icon: 'warning' },
    { name: 'profile', label: 'PROFILE', icon: 'person' },
  ],
  pm:          [
    { name: 'index',   label: 'DASHBOARD',  icon: 'grid' },
    { name: 'capture', label: 'CAPTURE',    icon: 'mic' },
    { name: 'ops',     label: 'OPERATIONS', icon: 'list-circle' },
    { name: 'profile', label: 'PROFILE',    icon: 'person' },
  ],
  admin:       [
    { name: 'index',   label: 'DASHBOARD',  icon: 'grid' },
    { name: 'capture', label: 'CAPTURE',    icon: 'mic' },
    { name: 'ops',     label: 'OPERATIONS', icon: 'list-circle' },
    { name: 'profile', label: 'PROFILE',    icon: 'person' },
  ],
};

export async function setViewRole(r: ViewRole) {
  await AsyncStorage.setItem(VIEW_ROLE_KEY, r);
}

export async function getViewRole(): Promise<ViewRole> {
  const raw = await AsyncStorage.getItem(VIEW_ROLE_KEY);
  if (raw === 'client' || raw === 'supervisor' || raw === 'pm' || raw === 'admin') return raw;
  return 'supervisor';
}

export async function clearViewRole() {
  await AsyncStorage.removeItem(VIEW_ROLE_KEY);
}
