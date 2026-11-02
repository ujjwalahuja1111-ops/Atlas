// Launch-readiness patch 2 — tests for the per-role "no project/site yet"
// wording and for the screen wiring. Run: npm run check-empty-states
// (node --experimental-strip-types --test). No device/browser: this proves the
// decision logic and that every screen is wired to it, not pixel rendering.
import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { noSiteState } from '../src/noSiteState.ts';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const read = (p) => fs.readFileSync(path.join(root, p), 'utf8');
const strip = (s) => s.split('\n').map((l) => l.replace(/\/\/.*$/, '')).join('\n');

// Mirrors VIEW_PERMS.canManageProjects (roles.ts); asserted against the file below.
const CAN_MANAGE = { admin: true, pm: true, supervisor: false, client: false };

test('VIEW_PERMS.canManageProjects matches what the empty states assume', () => {
  const roles = read('src/roles.ts');
  for (const [role, want] of Object.entries(CAN_MANAGE)) {
    const block = roles.slice(roles.indexOf(`  ${role}: {`)).split('\n  },')[0];
    assert.match(block, new RegExp(`canManageProjects: ${want}`), `${role} canManageProjects`);
  }
});

test('management: explains the business needs its first project and offers the existing create action', () => {
  const s = noSiteState('admin', true);
  assert.match(s.title, /first project/i);
  assert.deepEqual(s.action, { label: 'CREATE A PROJECT', route: '/projects/new' });
});

test('project manager: says nothing is assigned and management must assign/create; create offered only because the role may create', () => {
  const s = noSiteState('pm', true);
  assert.match(s.title, /No project or site is assigned/i);
  assert.match(s.body, /management/i);
  assert.equal(s.action?.route, '/projects/new');
  assert.equal(noSiteState('pm', false).action, null); // never offered without the permission
});

test('supervisor: told no site is available/assigned; no creation action', () => {
  const s = noSiteState('supervisor', false);
  assert.match(s.title, /No site is available/i);
  assert.match(s.body, /assign/i);
  assert.equal(s.action, null);
});

test('client: told access/assignment is pending; no creation action', () => {
  const s = noSiteState('client', false);
  assert.match(s.title, /access is being set up/i);
  assert.match(s.body, /assigned/i);
  assert.equal(s.action, null);
});

test('an unauthorized role is never offered create, even if the flag were wrongly true', () => {
  // The component derives the flag from VIEW_PERMS, so this documents that a
  // supervisor/client text path has no action at all.
  assert.equal(noSiteState('supervisor', true).action, null);
  assert.equal(noSiteState('client', true).action, null);
});

test('wording is business-neutral (no construction vocabulary)', () => {
  for (const role of ['admin', 'pm', 'supervisor', 'client']) {
    const s = noSiteState(role, true);
    assert.doesNotMatch(`${s.title} ${s.body}`, /construction|contractor|building|concrete|civil/i);
  }
});

test('Home, Client dashboard and Capture render NoSiteState when there are no sites', () => {
  const home = strip(read('app/(tabs)/index.tsx'));
  assert.match(home, /sites\.length === 0 && !loadError && viewRole \? \(\s*<NoSiteState role=\{viewRole\} \/>/);
  assert.match(home, /sites\.length === 0 && !loadError\) \{\s*return \(\s*<SafeAreaView[^>]*>\s*<NoSiteState role="client"/);
  const cap = strip(read('app/(tabs)/capture.tsx'));
  assert.match(cap, /sitesLoaded && sites\.length === 0 && viewRole/);
  assert.match(cap, /<NoSiteState role=\{viewRole\} \/>/);
});

test('Capture is not unlocked for roles that may not capture (role lock stays before the empty state)', () => {
  const cap = strip(read('app/(tabs)/capture.tsx'));
  assert.ok(cap.indexOf('showCapture') < cap.indexOf('sitesLoaded && sites.length === 0'));
});

test('populated workspace is unchanged: the original timeline empty state is still the fallback', () => {
  const home = strip(read('app/(tabs)/index.tsx'));
  assert.match(home, /\) : items\.length === 0 \? \(\s*<View style=\{styles\.empty\} testID="timeline-empty">/);
  assert.match(home, /START CAPTURE/);
});

test('Profile exposes Business Configuration and Team Setup to the admin section only', () => {
  const prof = strip(read('app/(tabs)/profile.tsx'));
  const adminStart = prof.indexOf("viewRole === 'admin' && (");
  const cfg = prof.indexOf('open-business-config');
  const team = prof.indexOf('open-team-setup');
  const logout = prof.indexOf('logout-button');
  assert.ok(adminStart > 0 && cfg > adminStart && team > adminStart && cfg < logout && team < logout);
  assert.match(prof, /router\.push\('\/business-setup'\)/);
  assert.match(prof, /router\.push\('\/provision-team'\)/);
});

test('business-setup no longer bounces an approved configuration and has no edit path for it', () => {
  const bs = strip(read('app/business-setup.tsx'));
  assert.doesNotMatch(bs, /status === 'approved'\) \{\s*router\.replace/);
  assert.match(bs, /business-config-approved/);
  const approvedView = bs.slice(bs.indexOf("config.status === 'approved') {\n    const caps"), bs.indexOf('Tell Atlas about your business'));
  assert.doesNotMatch(approvedView, /apiAnalyzeBusiness|apiApproveBusinessConfiguration|onPress=\{approve\}/);
});
