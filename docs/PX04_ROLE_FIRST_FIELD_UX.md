# PX04_ROLE_FIRST_FIELD_UX.md

## 1. Management / Admin Executive Hub Navigation

Root cause found by inspecting the actual navigation model first, not assumed. executive-hub.tsx lived as a route entirely outside the (tabs) group. Management already has the full 5-tab set (Home, Projects, Capture, Inbox, More) - confirmed by reading roles.ts directly - so the tab bar itself was never the problem. The problem was that navigating to an out-of-group route hides the entire tab navigator, and the only affordance on that screen was a router.back() that didn't reliably return anywhere useful, because Home's own redirect used router.replace(), which destroys the history entry it would need to go back to.

Fix: moved the screen to (tabs)/executive-hub.tsx, registered as a hidden tab-group member (href: null), matching the exact precedent already established for ops. This makes "Executive Hub is Home for Management" literally true - same tab slot, not a redirect to a separate destination - so the tab bar (and every other destination) stays reachable the entire time Management is on this screen. The now-nonsensical back-chevron (a tab root, not a pushed screen) was removed, matching how every other tab root in this app already behaves.

All three call sites updated ((tabs)/index.tsx's own redirect, portfolio/index.tsx, (tabs)/profile.tsx). No other references remained (confirmed via full-repo grep after the change).

Not touched: the stay=1 escape hatch projects/[id].tsx already uses to return to the tab navigator without triggering Management's own redirect. This is a separate, already-working mechanism for a different purpose (escaping a deep project view), not the dead-end this task describes.

## 2. Site Supervisor Capture - Audio Investigation

Traced the full path per this task's own explicit instruction, not assumed to be a UI problem. Confirmed correct and unchanged: microphone permission declarations in app.json (NSMicrophoneUsageDescription for iOS, RECORD_AUDIO for Android), the Expo SDK/expo-audio version pairing (SDK 54, expo-audio ~1.1.1), and the prepareToRecordAsync/setAudioModeAsync API call signatures against the actual installed type definitions.

The real defect: requestRecordingPermissionsAsync()'s own return value - which carries granted - was being awaited and then discarded entirely. Confirmed against expo-audio's own documented usage example (read directly from the installed package's .d.ts file), which explicitly destructures and checks this exact field. A denied permission silently proceeded as if it had been granted, failed deeper inside prepareToRecordAsync()/record(), and every error along that entire path was caught and thrown away with no reason ever reaching the screen - matching the observed symptom exactly: tap record, nothing happens, no explanation.

This is not role-specific code - useVoiceRecorder is the single shared implementation for both the Capture screen and operational-item Voice Updates (confirmed by reading the hook's own comment header, which already documents this consolidation). The bug would affect any role using voice capture; it was surfaced during Supervisor pilot testing because Capture is their primary workflow, per this task's own framing.

Fix: the hook now tracks and returns the real outcome - 'started' | 'permission_denied' | 'failed' - instead of a bare boolean. Both callers (capture.tsx, op/[id].tsx) updated to show a specific, field-friendly message for the permission case ("Microphone access is off. Turn it on in your phone Settings to record.") rather than a generic failure. Permission is also re-checked immediately before each recording attempt (not just once on mount), since a user may grant it via the device's own Settings app mid-session and this hook has no way to observe that change on its own.

Upload-failure retry path: if recording succeeds but the subsequent upload fails, the already-recorded local file's own URI (a real file expo-audio already wrote to the device, not fabricated data) is preserved in component state and a "Try Again" button appears, retrying the same recording rather than discarding it and forcing the user to speak it all again - per this task's own explicit Section 2 and Section 10 instructions.

Verification status: CODE VERIFIED (traced against the actual installed library's own types and documented usage; tsc/lint clean). DEVICE VERIFIED: BLOCKED - no Expo/device environment is available in this sandbox, the same constraint stated throughout this entire engagement's prior phases. This fix cannot be claimed working on a real device until someone runs it there.

## 3-8. Site Supervisor UX Simplification

What was rebuilt: the Supervisor's own Home header content. Previously this role shared the same underlying structure as PM/Management (MyDaySection + SupervisorCreCards, the latter showing CRE-engine-derived cards titled "Activities Ready" / "Pending Inspections" / "Overdue Activities"). Replaced with a dedicated SupervisorHomeHeader component: a greeting, the current site/project name, four large primary action cards (Site Update, Report Issue, My Tasks, Messages - matching this task's own Section 4/5 naming), and a "needs attention" banner only when there's something to show. Reuses the existing apiMyDay() call (no new backend endpoint) and translates its own field names into field language per this task's own Section 6 glossary (open_operational_items-style counts become "My Tasks"; blocked/waiting-for-material items become "needs attention").

SupervisorCreCards was removed from this role's own Home entirely, per this task's explicit "avoid a wall of KPIs... unless specifically required" instruction - it remains defined and available (unused by this change, not deleted) in case a future task finds a genuine need for it elsewhere.

What was NOT done, named directly rather than implied complete:
- A full terminology audit across every Supervisor-reachable screen (Section 6's own full glossary: "Operational Items" -> "My Tasks" everywhere, "Reality Capture" -> "Site Update" everywhere, "Timeline" -> "Site History" everywhere, "Escalations" -> "Needs Attention" everywhere, "Waiting For You" -> "Your Action Needed" everywhere). Only the new Home header uses field language; the Ops list screen, notification titles, and other Supervisor-reachable screens still use their original terminology. This is a real, substantial remaining scope item, not a minor polish task.
- Section 7 (Project Selection) - the existing siteId auto-select-first-site behavior on Capture was confirmed already reasonably close to this task's own "don't make them choose every time" requirement for a single-site Supervisor, but the explicit "Which site are you at today?" large-card chooser for a multi-site Supervisor was not built.
- Section 9 (Notification wording) - Inbox notification titles for Supervisor were not rewritten into the field language this task's own Section 9 examples show ("Electrical work assigned to you" instead of "Operational Item 84 changed status").
- Section 10 (offline/weak-network UX beyond Capture's own upload-retry) was not extended to other Supervisor-reachable write actions.

Given the size of PX-04's own full scope and the two concrete, pilot-blocking defects (navigation dead-end, audio recording) that needed root-cause investigation and correct fixes rather than surface patches, this phase prioritized those two plus the single highest-leverage piece of the Supervisor UX work (the Home screen a Supervisor sees first, every time they open the app) over a mechanical find-and-replace across the rest of the app. The remaining terminology/notification/multi-site work is real and substantial, not cosmetic, and is named here as the clear next step.

## 9-10. Notification Experience / Offline UX

Not attempted this phase beyond the Capture upload-retry path described in Section 2 above. Named directly, not implied complete.

## 11. Role-Specific Information Architecture

No new backend systems were created - every change this phase reuses existing engines and existing API calls (apiMyDay(), apiGetMe()). The change is presentation-only, matching this task's own explicit constraint.

## 12. Testing

Backend: no backend files were touched this phase. Full regression suite re-confirmed passing (213/213, matching the state already established before this phase began).

Frontend: npx tsc --noEmit clean. npm run lint: 23 problems, matching the established baseline (two real issues this phase's own edits introduced - a duplicate import and two unused declarations - were found and fixed before finalizing, not left in place).

No frontend test infrastructure exists in this repository - confirmed by searching for Jest/Detox configuration and .test.tsx files before attempting to add anything; none exist. This task's own Section 12 asks to "add regression tests... where testable" and separately to distinguish CODE VERIFIED / DEVICE VERIFIED / BLOCKED for audio specifically - both instructions anticipate exactly this situation. No test file was fabricated to create the appearance of automated coverage where none of the surrounding infrastructure supports it.

## 13. Live Device Verification

BLOCKED in its entirety. No Expo/device/simulator environment is available in this sandbox - the identical constraint stated in every UI-verification document across this entire engagement (LIVE-01 through PX-03 Phase 4). Nothing in this document claims a device screen was actually tapped through. The audio fix is CODE VERIFIED (traced against the real, installed library and its own documented usage) but explicitly not DEVICE VERIFIED.

## 14. Remaining Limitations

Stated directly:
- Audio fix is code-verified only; real-device confirmation is required before this can be called resolved for the pilot.
- Terminology audit is incomplete - only the new Supervisor Home header uses field language; the rest of the app (Ops list, notifications, other screens) does not yet.
- Multi-site Supervisor project-selection UX (Section 7's "which site are you at today?") was not built.
- Notification wording (Section 9) was not rewritten for Supervisor.
- No frontend automated test coverage exists for any of this phase's own changes, since no test infrastructure exists in this repository at all.
