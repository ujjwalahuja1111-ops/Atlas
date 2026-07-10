/**
 * Sprint 3 — Role-based workspaces.
 * Sprint 4 cleanup — removed the manual workspace selector on login.
 *
 * Frontend-only. Backend roles remain `supervisor | coordinator | management`.
 * We introduce a *view role* stored in AsyncStorage that governs which
 * navigation, screens and data filters the current user sees. The mapping
 * to backend roles is deliberately one-way: view roles derive backend
 * permissions but never contradict them.
 *
 * Login used to ask the person to manually pick one of four workspaces
 * (Client / Supervisor / PM / Admin) and derived the backend role from that
 * choice. That selector is gone. Login now goes the other direction:
 * `resolveLoginRole()` / `completeLoginRouting()` (bottom of this file) are
 * the SINGLE, CENTRALIZED place that maps a backend role to its default
 * workspace and vice versa — no screen computes this mapping itself.
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

/** Backend role each view role authenticates as. Kept for reference/symmetry
 * with DEFAULT_VIEW_ROLE_FOR below; login no longer reads this directly
 * (see resolveLoginRole/completeLoginRouting) since the workspace picker
 * this drove was removed in the Sprint 4 cleanup. */
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
  /** Sprint 4.1 fix (audit M3): whether this workspace can create/edit/
   * archive/delete projects & sites. Previously projects/index.tsx,
   * projects/[id].tsx, and ops.tsx each derived this from the raw backend
   * role (`user.role !== 'supervisor'`) instead of this abstraction —
   * harmless today since Client and PM share backend role `coordinator`,
   * but it meant a read-mostly Client workspace would get full management
   * rights the moment it became reachable again. This is the single source
   * of truth now. */
  canManageProjects: boolean;
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
    showCapture: false, canManageProjects: false, proposalCategoryFilter: 'client_approval',
    homeLabel: 'PROJECT UPDATES', opsLabel: 'APPROVALS',
  },
  supervisor: {
    showProposals: false, showAssignments: true, showDashboards: false, showOpsBuckets: false,
    showCapture: true, canManageProjects: false, onlyMyItems: true,
    homeLabel: 'TODAY', opsLabel: 'ISSUES',
  },
  pm: {
    showProposals: true, showAssignments: true, showDashboards: true, showOpsBuckets: true,
    showCapture: true, canManageProjects: true,
    homeLabel: 'DASHBOARD', opsLabel: 'OPERATIONS',
  },
  admin: {
    showProposals: true, showAssignments: true, showDashboards: true, showOpsBuckets: true,
    showCapture: true, canManageProjects: true,
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

// ---------------------------------------------------------------------------
// Sprint 4 cleanup: automatic workspace routing (replaces the Sprint 3
// manual login selector). This is the ONLY place in the app that maps a
// backend role to a workspace — screens must not duplicate this mapping.
// ---------------------------------------------------------------------------

/** Canonical backend role -> default workspace. `coordinator` collapses to
 * the fuller `pm` workspace: `client` was always a manually-chosen, more
 * restricted lens over the same backend role (there is no backend signal
 * that distinguishes a "client" coordinator from a "PM" coordinator), so it
 * is not something we can auto-detect. `client` remains fully supported in
 * VIEW_PERMS/TABS_FOR for any future flow that sets it explicitly (e.g. if a
 * dedicated backend distinction is ever added) — it is just no longer a
 * login auto-routing target. */
export const DEFAULT_VIEW_ROLE_FOR: Record<Role, ViewRole> = {
  supervisor: 'supervisor',
  coordinator: 'pm',
  management: 'admin',
};

/**
 * Sprint 4.3 — Identity & Access Foundation. Which workspace options are
 * valid to assign for a given backend role — mirrors
 * `backend/engines/memory_engine.py`'s `WORKSPACE_ROLE_MAP` exactly. Used
 * by the User Management "assign workspace" UI to only offer compatible
 * choices; the backend independently re-validates this on every request
 * (never trust client-side validation alone), so this is a UX convenience,
 * not the actual enforcement boundary.
 */
export const WORKSPACE_OPTIONS_FOR_ROLE: Record<Role, ViewRole[]> = {
  supervisor: ['supervisor'],
  coordinator: ['client', 'pm'],
  management: ['admin'],
};

const KNOWN_ROLE_PREFIX = 'atlas.known_role.';

/** Last backend role this device saw for a given phone number, so a
 * returning user is routed straight back into their workspace without
 * re-selecting anything. Scoped per-phone (not global) since a device may
 * be shared across people with different phone numbers/roles. */
async function getKnownRole(phone: string): Promise<Role | null> {
  const v = await AsyncStorage.getItem(KNOWN_ROLE_PREFIX + phone);
  return v === 'supervisor' || v === 'coordinator' || v === 'management' ? v : null;
}

async function setKnownRole(phone: string, role: Role): Promise<void> {
  await AsyncStorage.setItem(KNOWN_ROLE_PREFIX + phone, role);
}

/**
 * Which backend role to authenticate as for this phone number, on this
 * device. Call BEFORE apiLogin(). The login API always requires a role
 * (backend contract unchanged — see routes/auth.py `Role = "supervisor"`
 * default), so a role must be supplied either way; we supply the
 * previously-seen one for a returning phone number, or the same safe
 * default the backend itself uses for a brand-new one. This never
 * overrides an existing account's real role with a guess — it only ever
 * "guesses" for a phone+device combo we have never seen before, which is
 * exactly the situation the backend's own default already exists to
 * handle.
 */
export async function resolveLoginRole(phone: string): Promise<Role> {
  const known = await getKnownRole(phone.trim());
  return known || 'supervisor';
}

/**
 * Call AFTER a successful login with the AUTHORITATIVE user object from the
 * login response (`res.user`) — not the guess passed into resolveLoginRole.
 * Remembers the role for next time and resolves + persists the workspace
 * the user should land in.
 *
 * Sprint 4.3 — Identity & Access Foundation: an Administrator can now
 * explicitly assign a workspace (`user.workspace`) that's independent of
 * the automatic role->workspace derivation below. If present, it wins. If
 * absent — every account that predates this feature, and any new account
 * an admin hasn't explicitly assigned a workspace to yet — falls back to
 * the exact same DEFAULT_VIEW_ROLE_FOR derivation used since Sprint 4,
 * so this is fully backward compatible with zero behaviour change for
 * every existing account.
 */
export async function completeLoginRouting(
  phone: string,
  user: { role: Role; workspace?: ViewRole | null },
): Promise<ViewRole> {
  await setKnownRole(phone.trim(), user.role);
  const workspace = user.workspace || DEFAULT_VIEW_ROLE_FOR[user.role];
  await setViewRole(workspace);
  return workspace;
}
