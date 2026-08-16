import { useEffect, useRef, useState } from 'react';
import {
  useAudioRecorder, AudioModule, RecordingPresets, setAudioModeAsync,
} from 'expo-audio';

/**
 * FAC-OPS-06 — the single recording implementation shared by the Capture
 * screen (new site events) and operational item Voice Updates. Previously
 * app/op/[id].tsx maintained its own, entirely separate useAudioRecorder
 * instance and start/stop/cancel functions, duplicating everything
 * app/(tabs)/capture.tsx already did. This hook is that logic, extracted
 * once, with zero behavioural change to either caller — each screen still
 * owns its own submit action (capture creates an event; an item update
 * calls apiVoiceUpdate) and any screen-specific side effects (e.g.
 * Capture's GPS tagging on start), which are NOT part of this hook.
 *
 * PX-04 Section 2 — the actual root cause of "audio recording does not
 * work" on the real device, found by tracing the full path rather than
 * assumed: requestRecordingPermissionsAsync()'s own return value (which
 * carries `granted`) was being awaited and then thrown away entirely -
 * expo-audio's own documented usage example explicitly destructures and
 * checks this field. A denied permission silently proceeded as if it had
 * been granted, then failed deeper inside prepareToRecordAsync()/record(),
 * with every error along the way caught and discarded - no reason ever
 * reached the caller, so a real user just saw nothing happen when they
 * tapped record. permissionState now tracks the real, current status so
 * a caller can distinguish "you need to grant microphone access" from a
 * generic recording failure, and start() itself returns which of those
 * two happened, instead of a bare boolean.
 */
export type StartRecordingResult = 'started' | 'permission_denied' | 'failed';

export function useVoiceRecorder() {
  const recorder = useAudioRecorder(RecordingPresets.HIGH_QUALITY);
  const [recording, setRecording] = useState(false);
  const [elapsed, setElapsed] = useState(0);
  const [permissionState, setPermissionState] = useState<'unknown' | 'granted' | 'denied'>('unknown');
  const timerRef = useRef<any>(null);

  useEffect(() => {
    (async () => {
      try {
        const { granted } = await AudioModule.requestRecordingPermissionsAsync();
        setPermissionState(granted ? 'granted' : 'denied');
        if (granted) {
          await setAudioModeAsync({ allowsRecording: true, playsInSilentMode: true });
        }
      } catch {
        setPermissionState('denied');
      }
    })();
    return () => { if (timerRef.current) clearInterval(timerRef.current); };
  }, []);

  const start = async (): Promise<StartRecordingResult> => {
    // A permission denied on mount may have since been granted via the
    // device's own Settings app — re-check right before recording rather
    // than trusting a stale mount-time result, since this hook has no
    // way to observe an OS-level settings change on its own.
    try {
      const { granted } = await AudioModule.getRecordingPermissionsAsync();
      if (!granted) {
        setPermissionState('denied');
        return 'permission_denied';
      }
      setPermissionState('granted');
    } catch {
      return 'permission_denied';
    }
    try {
      await recorder.prepareToRecordAsync();
      recorder.record();
      setRecording(true);
      setElapsed(0);
      timerRef.current = setInterval(() => setElapsed((s) => s + 1), 1000);
      return 'started';
    } catch {
      return 'failed';
    }
  };

  /** Stops recording and returns the local file URI (or null if nothing
   * was captured), for the caller to submit however it needs to. */
  const stop = async (): Promise<string | null> => {
    if (timerRef.current) { clearInterval(timerRef.current); timerRef.current = null; }
    setRecording(false);
    try {
      await recorder.stop();
      return recorder.uri || null;
    } catch {
      return null;
    }
  };

  const cancel = async () => {
    try { await recorder.stop(); } catch {}
    setRecording(false);
    setElapsed(0);
    if (timerRef.current) { clearInterval(timerRef.current); timerRef.current = null; }
  };

  return { recording, elapsed, permissionState, start, stop, cancel };
}
