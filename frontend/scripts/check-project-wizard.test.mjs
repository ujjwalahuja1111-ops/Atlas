// Launch-readiness patch 3 — the create-project wizard must not require a
// team that the business may not have. Run: npm run check-project-wizard
// Static guard (no device): the wizard blocked step 2 unless BOTH a project
// manager and a site supervisor were selected, so any business without both
// roles (restaurant, warehouse, software, one-person shop) could not create
// its first project, hence no site, hence no capture.
import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const src = fs.readFileSync(path.join(root, 'app/projects/new.tsx'), 'utf8')
  .split('\n').map((l) => l.replace(/^\s*\/\/.*$/, '').replace(/\s\/\/.*$/, '')).join('\n');

test('step 2 can proceed without selecting a project manager or supervisor', () => {
  assert.doesNotMatch(src, /wizard-next-2[^\n]*disabled=\{[^}]*selected(Pm|Sup)/);
});

test('project creation does not dereference an unselected team member', () => {
  assert.doesNotMatch(src, /selectedPm!|selectedSup!/);
  assert.match(src, /if \(selectedPm\) memberIds\.push/);
  assert.match(src, /if \(selectedSup\) memberIds\.push/);
});

test('team fields are labelled optional, not required', () => {
  assert.doesNotMatch(src, /Project Manager \*|Site Supervisor \*/);
  assert.match(src, /Project Manager \(optional\)/);
  assert.match(src, /Site Supervisor \(optional\)/);
});

test('a non-management creator is added so they can see their own project', () => {
  assert.match(src, /apiGetMe\(\)/);
  assert.match(src, /me\.role !== 'management'/);
});

test('the project and its first site are still created before any team assignment', () => {
  const create = src.indexOf('apiCreateProject({');
  const site = src.indexOf('apiCreateSite({');
  const assign = src.indexOf('apiAssignProjects(userId');
  assert.ok(create > 0 && site > create && assign > site);
});

test('the wizard assigns additively; User Management still sends the full list (replace) to un-assign', () => {
  const api = fs.readFileSync(path.join(root, 'src/api.ts'), 'utf8');
  const fn = api.slice(api.indexOf('export async function apiAssignProjects'));
  assert.match(fn.slice(0, fn.indexOf('\n}\n')), /mode: 'add'/);
  const admin = fs.readFileSync(path.join(root, 'src/admin_users_api.ts'), 'utf8');
  const afn = admin.slice(admin.indexOf('export async function apiAssignUserProjects'));
  assert.doesNotMatch(afn.slice(0, afn.indexOf('\n}\n')), /mode/);
  const users = fs.readFileSync(path.join(root, 'app/users/index.tsx'), 'utf8');
  assert.match(users, /current\.filter\(\(id\) => id !== projectId\)/); // removal path intact
});
