// Launch-readiness patch 2 — what to tell a user who has no project/site yet.
//
// Pure (no React, no storage) so the per-role wording and the "who may be
// offered a create action" rule are unit-testable without a device.
// Authorization is NOT decided here: `canManageProjects` is passed in from the
// existing VIEW_PERMS table (roles.ts), and the backend still enforces
// management/project_manager on POST /projects and POST /sites. This only
// decides whether to *show* the existing action. Wording is deliberately
// business-neutral ("project"/"site"), with no industry assumptions.
import type { ViewRole } from './roles';

export type NoSiteAction = { label: string; route: '/projects/new' };
export type NoSiteState = { title: string; body: string; action: NoSiteAction | null };

const CREATE: NoSiteAction = { label: 'CREATE A PROJECT', route: '/projects/new' };

export function noSiteState(role: ViewRole, canManageProjects: boolean): NoSiteState {
  switch (role) {
    case 'admin':
      return {
        title: 'Your business needs its first project',
        body: 'Create a project and its first site to start capturing and tracking work.',
        action: canManageProjects ? CREATE : null,
      };
    case 'pm':
      return {
        title: 'No project or site is assigned to you yet',
        body: 'Ask management to assign you to a project or create one for you.'
          + (canManageProjects ? ' You can also create a project yourself.' : ''),
        action: canManageProjects ? CREATE : null,
      };
    case 'supervisor':
      return {
        title: 'No site is available to you yet',
        body: 'You have not been assigned to a site. Ask your project manager or management to assign you to one.',
        action: null,
      };
    case 'client':
      return {
        title: 'Your access is being set up',
        body: 'No project has been shared with you yet. Updates will appear here once a project is assigned to you.',
        action: null,
      };
  }
}
