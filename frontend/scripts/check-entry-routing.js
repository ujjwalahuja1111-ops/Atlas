#!/usr/bin/env node
/**
 * Step 4 entry-point fix — focused regression guard, zero new
 * dependencies (no jest/testing-library toolchain exists in this
 * project; standing one up just for this one check would be a
 * disproportionate addition for a "smallest wiring fix" task).
 *
 * Statically confirms app/login.tsx and app/pending.tsx never regress
 * into hardcoding a post-auth destination ('/pending' or '/(tabs)')
 * instead of delegating to index.tsx's own single, centralized routing
 * decision via router.replace('/') — the exact bug this fix corrected:
 * a freshly-registered founding admin was being sent to '/pending'
 * unconditionally, and an approved management user straight to
 * '/(tabs)', both bypassing the /business-setup check entirely.
 *
 * Also guards the related Step 4 seed-isolation fix: neither screen may
 * call apiSeedDemo() at all anymore (see that section below).
 *
 * This is a style/pattern check, not a behavioural simulation — it
 * cannot replace a real component test, but it directly guards against
 * literally reintroducing the line changes either fix made.
 *
 * Run: node scripts/check-entry-routing.js
 */
const fs = require('fs');
const path = require('path');

const ROOT = path.join(__dirname, '..');
let failures = [];

function read(relPath) {
  return fs.readFileSync(path.join(ROOT, relPath), 'utf8');
}

// --- app/login.tsx -----------------------------------------------------
const login = read('app/login.tsx');

// Signup branch must delegate to '/', not hardcode '/pending'.
const signupBlock = login.slice(login.indexOf("if (mode === 'signup')"), login.indexOf('// Authentication Identity Validation'));
if (!/router\.replace\('\/'\)/.test(signupBlock)) {
  failures.push("login.tsx: the signup branch must call router.replace('/') so a freshly-" +
    "registered founding admin reaches /business-setup, not a hardcoded '/pending'.");
}
if (/router\.replace\('\/pending'\);\s*\n\s*return;\s*\n\s*}\s*\n\s*\n\s*\/\/ Authentication/.test(login) === false &&
    signupBlock.includes("router.replace('/pending')")) {
  failures.push("login.tsx: the signup branch still unconditionally hardcodes '/pending'.");
}

// The *login* branch's own pending-check (inside `if (!isApprovedAndActive(...))`)
// correctly keeps '/pending' - only the branch AFTER that check (the success
// path) must delegate to '/' instead of hardcoding '/(tabs)'.
const postApprovalLoginBlock = login.slice(
  login.indexOf('await completeLoginRouting'), login.indexOf('} catch (e: any) {'));
if (!/router\.replace\('\/'\)/.test(postApprovalLoginBlock)) {
  failures.push("login.tsx: the approved-login success path must call router.replace('/') " +
    "instead of hardcoding '/(tabs)', so a management user without an approved business " +
    "configuration yet still reaches /business-setup.");
}

// --- app/pending.tsx -----------------------------------------------------
const pending = read('app/pending.tsx');
const approvedBlock = pending.slice(pending.indexOf('if (isApprovedAndActive(fresh))'), pending.indexOf('} catch (e) { console.warn(e); }'));
if (!/router\.replace\('\/'\)/.test(approvedBlock)) {
  failures.push("pending.tsx: checkAgain()'s approved branch must call router.replace('/') " +
    "instead of hardcoding '/(tabs)', for the same reason as login.tsx above.");
}

// --- Step 4 seed-isolation guard ---------------------------------------
// Neither screen may call apiSeedDemo() at all anymore - it used to fire
// automatically on every login and on every home-screen focus with zero
// sites, silently injecting a hardcoded, construction-specific demo
// project into ANY business's workspace before they ever reached
// business setup (or regardless of their approved business type
// afterward). Demo data is explicit-developer-only now (scripts.dev's
// own `seed`/`reset-seed`); this guards against that call being
// reintroduced into either screen.
function stripLineComments(src) {
  // Strips '//'-to-end-of-line comments so explanatory prose (which
  // legitimately names apiSeedDemo while describing its removal) is not
  // itself mistaken for a live reference. Good enough for this file set
  // (no apiSeedDemo usage would ever legitimately appear inside a string
  // literal or block comment here either).
  return src.split('\n').map(line => line.replace(/\/\/.*$/, '')).join('\n');
}

const tabsIndex = read('app/(tabs)/index.tsx');
if (/apiSeedDemo/.test(stripLineComments(login))) {
  failures.push("login.tsx must not reference apiSeedDemo() at all - demo seeding is explicit-developer-only.");
}
if (/apiSeedDemo/.test(stripLineComments(tabsIndex))) {
  failures.push("app/(tabs)/index.tsx must not reference apiSeedDemo() at all - demo seeding is explicit-developer-only.");
}

if (failures.length) {
  console.error('FAILED — entry-routing regression guard:\n');
  for (const f of failures) console.error('  - ' + f);
  process.exit(1);
}
console.log('OK — login.tsx and pending.tsx both delegate post-auth routing to index.tsx via router.replace(\'/\').');
