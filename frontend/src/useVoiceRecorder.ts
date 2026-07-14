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
 */
export function useVoiceRecorder() {
  const recorder = useAudioRecorder(RecordingPresets.HIGH_QUALITY);
  const [recording, setRecording] = useState(false);
  const [elapsed, setElapsed] = useState(0);
  const timerRef = useRef<any>(null);

  useEffect(() => {
    (async () => {
      try {
        await AudioModule.requestRecordingPermissionsAsync();
        await setAudioModeAsync({ allowsRecording: true, playsInSilentMode: true });
      } catch {}
    })();
    return () => { if (timerRef.current) clearInterval(timerRef.current); };
  }, []);

  const start = async (): Promise<boolean> => {
    try {
      await recorder.prepareToRecordAsync();
      recorder.record();
      setRecording(true);
      setElapsed(0);
      timerRef.current = setInterval(() => setElapsed((s) => s + 1), 1000);
      return true;
    } catch {
      return false;
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

  return { recording, elapsed, start, stop, cancel };
}
