// Project Atlas — shared HTTP client helpers (Sprint 4.1 stabilization)
//
// Consolidates the header-building logic that was previously duplicated
// identically across api.ts, ops_api.ts, and knowledge_api.ts (audit
// finding L7), and adds the one thing none of them had: global session-
// expiry handling (audit finding H5). apiFetch() is a drop-in replacement
// for the global `fetch` — callers keep their existing `if (!r.ok) throw`
// logic completely unchanged; this only adds a 401 side-effect.
import AsyncStorage from '@react-native-async-storage/async-storage';
import { router } from 'expo-router';

const TOKEN_KEY = 'atlas_token';
const USER_KEY = 'atlas_user';

export async function authHeaders(): Promise<Record<string, string>> {
  const token = await AsyncStorage.getItem(TOKEN_KEY);
  return token ? { Authorization: `Bearer ${token}` } : {};
}

export async function jsonHeaders(): Promise<Record<string, string>> {
  return { 'Content-Type': 'application/json', ...(await authHeaders()) };
}

// Guards against every in-flight request that gets a 401 at the same
// moment (e.g. a screen firing several parallel calls) all trying to
// redirect at once — only the first one acts. Reset on every successful
// login/registration so a *future* expiry can trigger the redirect again.
let sessionExpiredHandled = false;
export function resetSessionExpiredGuard() {
  sessionExpiredHandled = false;
}

/**
 * Drop-in replacement for `fetch`. On a 401 from any authenticated
 * endpoint (never for the auth endpoints themselves, which legitimately
 * return other statuses for bad credentials/input, not "your session
 * expired"), clears the stored session and routes back to Login exactly
 * once. Every existing `if (!r.ok) throw new Error(...)` call site keeps
 * working completely unchanged — this only adds the side effect before
 * returning the same Response object.
 */
export async function apiFetch(input: string, init?: RequestInit): Promise<Response> {
  const r = await fetch(input, init);
  if (r.status === 401 && !input.includes('/api/auth/')) {
    if (!sessionExpiredHandled) {
      sessionExpiredHandled = true;
      await AsyncStorage.multiRemove([TOKEN_KEY, USER_KEY]);
      router.replace('/login');
    }
  }
  return r;
}
