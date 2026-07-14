/**
 * Sprint 3 — Role-based workspaces.
 * Sprint 4 cleanup — removed the manual workspace selector on login.
 * FAC-04 — Final Authorization Model Freeze: backend roles are now
 * `management | project_manager | site_supervisor | client` — four
 * first-class roles, each with its own dedicated workspace. The
 * previous generic `coordinator` role (which covered both Project
 * Manager and Client, distinguished only by a separately-assigned
 * `workspace` field) is gone entirely.
 *
 * Frontend-only. We introduce a *view role* stored in AsyncStorage that
 * governs which navigation, screens and data filters the current user
 * sees. The mapping to backend roles is deliberately one-way: view
 * roles derive backend permissions but never contradict them.
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

/** Backend role each view role authenticates as. FAC-04: now a clean 1:1
 * mapping — each view role has exactly one, dedicated backend role, with
 * zero sharing. Kept for reference/symmetry with DEFAULT_VIEW_ROLE_FOR
 * below; login no longer reads this directly (see
 * resolveLoginRole/completeLoginRouting) since the workspace picker this
 * drove was removed in the Sprint 4 cleanup. */
export const BACKEND_ROLE_FOR: Record<ViewRole, Role> = {
  client: 'client',
  supervisor: 'site_supervisor',
  pm: 'project_manager',
  admin: 'management',
};

/** FAC-OPS-06 — human-readable label for a raw backend Role. The single
 * canonical source: previously duplicated (and prone to drifting out of
 * sync with each other or with the Role type itself) in app/users/
 * index.tsx and app/(tabs)/profile.tsx, and not used at all by the
 * assignee pickers (app/(tabs)/ops.tsx, app/op/[id].tsx), which rendered
 * the raw snake_case role string directly. "Display the current backend
 * role everywhere" means both fresh AND readable — this is the readable
 * half; the freshness half is fixed at each picker's own data-loading
 * call site. */
export const ROLE_LABEL: Record<Role, string> = {
  management: 'Management',
  project_manager: 'Project Manager',
  site_supervisor: 'Site Supervisor',
  client: 'Client',
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
   * a real gap FAC-04 found and closed at the backend layer too: Client
   * and Project Manager used to share the generic `coordinator` backend
   * role, so that check would have let a Client through. Backend now
   * enforces this independently (routes/projects.py), and Client is its
   * own first-class role — but this remains the single frontend source
   * of truth for what to render. */
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
    // FOUNDER SPRINT — Operational Workflow Completion: showProposals is
    // now false. It used to be true and drove the client's "Approvals"
    // tab into ops.tsx's AI-proposal review flow (Accept/Reject a
    // *proposal*, an internal PM decision about an AI guess) - the wrong
    // concept entirely for a client, and one the backend now correctly
    // 403s for a client role anyway (FAC-04). The client's Home tab
    // (ClientDashboardScreen in index.tsx) now has its own dedicated
    // "Pending Approvals" section built directly on operational_items
    // (category=client_approval), routing into the existing, correctly-
    // gated op/[id].tsx approve/reject/comment screen - never ops.tsx.
    showProposals: false, showAssignments: false, showDashboards: false, showOpsBuckets: false,
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

/** Canonical backend role -> default workspace. FAC-04: this is now a
 * clean, total 1:1 mapping — every role has exactly one correct
 * workspace, always. Before this sprint, the generic `coordinator` role
 * covered both Project Manager and Client with no backend signal to
 * distinguish them, so `client` could never be auto-derived and instead
 * required a separate, manually-assigned `workspace` field. That
 * ambiguity is gone: Client is now its own role, so its workspace is
 * just as automatically derivable as any other. */
export const DEFAULT_VIEW_ROLE_FOR: Record<Role, ViewRole> = {
  site_supervisor: 'supervisor',
  project_manager: 'pm',
  management: 'admin',
  client: 'client',
};

const KNOWN_ROLE_PREFIX = 'atlas.known_role.';

/** Last backend role this device saw for a given phone number, so a
 * returning user is routed straight back into their workspace without
 * re-selecting anything. Scoped per-phone (not global) since a device may
 * be shared across people with different phone numbers/roles. */
async function getKnownRole(phone: string): Promise<Role | null> {
  const v = await AsyncStorage.getItem(KNOWN_ROLE_PREFIX + phone);
  return v === 'management' || v === 'project_manager' || v === 'site_supervisor' || v === 'client' ? v : null;
}

async function setKnownRole(phone: string, role: Role): Promise<void> {
  await AsyncStorage.setItem(KNOWN_ROLE_PREFIX + phone, role);
}

/**
 * Which backend role to authenticate as for this phone number, on this
 * device. Call BEFORE apiLogin(). The login API always requires a role
 * (backend contract unchanged — see routes/auth.py `Role = "site_supervisor"`
 * default), so a role must be supplied either way; we supply the
 * previously-seen one for a returning phone number, or the same safe
 * default the backend itself uses for a brand-new one. FAC-03/FAC-04:
 * this guess is never applied to an EXISTING account's stored role — the
 * backend (memory_engine.upsert_user) makes zero writes to an existing
 * account on login, full stop — it only ever supplies a starting role for
 * a genuinely brand-new account created through /auth/register's
 * approval flow, or a value the backend simply ignores for an existing one.
 */
export async function resolveLoginRole(phone: string): Promise<Role> {
  const known = await getKnownRole(phone.trim());
  return known || 'site_supervisor';
}

/**
 * Call AFTER a successful login with the AUTHORITATIVE user object from the
 * login response (`res.user`) — not the guess passed into resolveLoginRole.
 * Remembers the role for next time and resolves + persists the workspace
 * the user should land in.
 *
 * FAC-04: `user.workspace` is now ALWAYS correctly derived and stored by
 * the backend from `user.role` (see memory_engine.WORKSPACE_FOR_ROLE) —
 * there is no longer an independent "assign workspace" action that could
 * ever leave the two fields inconsistent. The `|| DEFAULT_VIEW_ROLE_FOR[...]`
 * fallback below is kept purely as a defensive backstop (e.g. a
 * theoretical pre-migration document this session hasn't touched yet),
 * not because it's expected to ever actually be needed.
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
