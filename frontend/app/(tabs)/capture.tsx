import { useEffect, useRef, useState } from 'react';
import {
  View, Text, Pressable, StyleSheet, ActivityIndicator, ScrollView, TextInput,
  KeyboardAvoidingView, Platform,
} from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import { Ionicons } from '@expo/vector-icons';
import * as Haptics from 'expo-haptics';
import * as ImagePicker from 'expo-image-picker';
import * as Location from 'expo-location';
import { Image as ExpoImage } from 'expo-image';
import { useRouter } from 'expo-router';
import { theme } from '@/src/theme';
import { getViewRole, VIEW_PERMS, type ViewRole } from '@/src/roles';
import { useVoiceRecorder } from '@/src/useVoiceRecorder';
import {
  apiCreateEvent, apiListSites, apiListProjects,
  getActiveSite, setActiveSite,
  type Site, type Project,
} from '@/src/api';

export default function CaptureScreen() {
  const router = useRouter();
  // FAC-OPS-06 — shared with app/op/[id].tsx's voice update, instead of
  // each screen maintaining its own separate useAudioRecorder instance.
  const { recording, elapsed, start: startRecordingRaw, stop: stopRecordingRaw, cancel: cancelRecordingRaw } = useVoiceRecorder();
  const [photoUris, setPhotoUris] = useState<string[]>([]);
  const [sites, setSites] = useState<Site[]>([]);
  const [projectMap, setProjectMap] = useState<Record<string, Project>>({});
  const [siteId, setSiteId] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [status, setStatus] = useState<string>('');
  const [gps, setGps] = useState<{ lat: number; lng: number; accuracy?: number } | null>(null);
  const [gpsAsked, setGpsAsked] = useState(false);
  const [viewRole, setViewRole] = useState<ViewRole | null>(null);
  // Sprint 6.1 — manual "Add as Text" option, alongside the existing
  // voice/photo capture. Creates the exact same event structure (see
  // apiCreateEvent's `text` field, already supported by POST /api/events
  // independent of audio/photos — no backend change needed here).
  const [showTextInput, setShowTextInput] = useState(false);
  const [textNote, setTextNote] = useState('');
  useEffect(() => { getViewRole().then(setViewRole); }, []);

  useEffect(() => {
    (async () => {
      try {
        const list = await apiListSites();
        setSites(list);
        const projects = await apiListProjects();
        const pmap: Record<string, Project> = {};
        for (const p of projects) pmap[p.id] = p;
        setProjectMap(pmap);
        const stored = await getActiveSite();
        const active = stored && list.find((s) => s.id === stored) ? stored : list[0]?.id || null;
        setSiteId(active);
      } catch (e: any) {
        // Sprint 4.1 fix (audit H4): surface load failures instead of
        // silently swallowing them.
        console.warn(e);
        setStatus(e?.message || 'Could not load sites. Pull down on Home to retry.');
      }
    })();
  }, []);

  const tryCaptureGps = async () => {
    if (gpsAsked) return;
    setGpsAsked(true);
    try {
      const perm = await Location.requestForegroundPermissionsAsync();
      if (!perm.granted) return;
      const loc = await Location.getCurrentPositionAsync({ accuracy: Location.Accuracy.Balanced });
      setGps({ lat: loc.coords.latitude, lng: loc.coords.longitude, accuracy: loc.coords.accuracy ?? undefined });
    } catch {}
  };

  const startRecording = async () => {
    tryCaptureGps();
    Haptics.impactAsync(Haptics.ImpactFeedbackStyle.Heavy).catch(() => {});
    const ok = await startRecordingRaw();
    if (ok) setStatus('Recording…');
    else setStatus('Could not start recording');
  };

  const stopAndSubmit = async () => {
    if (!siteId) { setStatus('Pick a site first'); return; }
    try {
      Haptics.notificationAsync(Haptics.NotificationFeedbackType.Success).catch(() => {});
      const uri = await stopRecordingRaw();
      if (!uri && photoUris.length === 0) { setStatus('Nothing to send'); return; }
      setSubmitting(true);
      setStatus('Saving…');
      await apiCreateEvent({ siteId, audioUri: uri, photoUris, gps });
      setStatus('Saved! AI analyzing in background…');
      setPhotoUris([]);
      setTimeout(() => {
        setStatus('');
        router.push('/(tabs)');
      }, 500);
    } catch (e: any) {
      setStatus(e?.message || 'Save failed');
    } finally { setSubmitting(false); }
  };

  const cancelRecording = async () => {
    await cancelRecordingRaw();
    setStatus('');
  };

  const pickPhoto = async () => {
    Haptics.impactAsync(Haptics.ImpactFeedbackStyle.Medium).catch(() => {});
    tryCaptureGps();
    const perm = await ImagePicker.requestCameraPermissionsAsync();
    if (!perm.granted) { setStatus('Camera permission denied'); return; }
    const res = await ImagePicker.launchCameraAsync({
      mediaTypes: ['images'], quality: 0.6, allowsEditing: false,
    });
    if (!res.canceled && res.assets[0]?.uri) {
      setPhotoUris((p) => [...p, res.assets[0].uri]);
    }
  };

  const pickFromGallery = async () => {
    const perm = await ImagePicker.requestMediaLibraryPermissionsAsync();
    if (!perm.granted) { setStatus('Gallery permission denied'); return; }
    const res = await ImagePicker.launchImageLibraryAsync({
      mediaTypes: ['images'], quality: 0.6, allowsMultipleSelection: false,
    });
    if (!res.canceled && res.assets[0]?.uri) {
      setPhotoUris((p) => [...p, res.assets[0].uri]);
    }
  };

  const photoOnlySubmit = async () => {
    if (!siteId || photoUris.length === 0) return;
    setSubmitting(true);
    setStatus('Saving…');
    try {
      await apiCreateEvent({ siteId, photoUris, gps });
      setStatus('Saved!');
      setPhotoUris([]);
      setTimeout(() => { setStatus(''); router.push('/(tabs)'); }, 500);
    } catch (e: any) {
      setStatus(e?.message || 'Save failed');
    } finally { setSubmitting(false); }
  };

  // Sprint 6.1 — manual text capture. Mirrors photoOnlySubmit exactly:
  // same apiCreateEvent call (just a different field populated), same
  // success handling, same navigation. Creates the identical event
  // structure a voice note does wherever text applies (kind, site_id,
  // ai_status lifecycle) — nothing about the backend pipeline changes.
  const textOnlySubmit = async () => {
    if (!siteId || !textNote.trim()) return;
    setSubmitting(true);
    setStatus('Saving…');
    try {
      await apiCreateEvent({ siteId, text: textNote.trim(), gps });
      setStatus('Saved!');
      setTextNote('');
      setShowTextInput(false);
      setTimeout(() => { setStatus(''); router.push('/(tabs)'); }, 500);
    } catch (e: any) {
      setStatus(e?.message || 'Save failed');
    } finally { setSubmitting(false); }
  };

  const mins = String(Math.floor(elapsed / 60)).padStart(2, '0');
  const secs = String(elapsed % 60).padStart(2, '0');
  const activeSite = sites.find((s) => s.id === siteId);
  const activeProject = activeSite ? projectMap[activeSite.project_id] : null;

  // Sprint 4.1 fix (audit H3): this screen previously had zero role
  // awareness at all — VIEW_PERMS.client.showCapture=false was only ever
  // enforced by hiding the tab bar icon, not by the screen itself. Any
  // direct navigation here (e.g. the Home empty-state CTA, before its own
  // H2 fix) bypassed that entirely. Matches the guard pattern already used
  // in knowledge/index.tsx and knowledge/[id].tsx.
  if (viewRole !== null && !VIEW_PERMS[viewRole].showCapture) {
    return (
      <SafeAreaView style={styles.safe} edges={['top']}>
        <View style={[styles.center, { flex: 1 }]}>
          <Ionicons name="lock-closed-outline" size={48} color={theme.color.textDim} />
          <Text style={{ color: theme.color.text, fontSize: 18, fontWeight: '900', marginTop: 8 }}>
            Capture not available
          </Text>
          <Text style={{ color: theme.color.textMuted, marginTop: 4, textAlign: 'center', paddingHorizontal: 24 }}>
            This workspace doesn't include capturing new site updates.
          </Text>
        </View>
      </SafeAreaView>
    );
  }

  return (
    <SafeAreaView style={styles.safe} edges={['top']}>
      <KeyboardAvoidingView style={{ flex: 1 }} behavior={Platform.OS === 'ios' ? 'padding' : undefined}
        keyboardVerticalOffset={Platform.OS === 'ios' ? 90 : 0}>
        <View style={styles.headerRow}>
          <Text style={styles.title}>CAPTURE</Text>
          <Text style={styles.subtitle} numberOfLines={1}>
            {activeProject ? `${activeProject.name} · ` : ''}{activeSite?.name || 'No site selected'}
          </Text>
        </View>

        <ScrollView horizontal showsHorizontalScrollIndicator={false}
          style={styles.chipsRow} contentContainerStyle={styles.chipsContent}>
          {sites.length === 0 ? (
            <Text style={styles.noSitesText}>No sites available yet</Text>
          ) : sites.map((s) => {
            const active = s.id === siteId;
            return (
              <Pressable key={s.id} testID={`capture-site-${s.id}`}
                onPress={async () => { setSiteId(s.id); await setActiveSite(s.id); }}
                style={[styles.chip, active && styles.chipActive]}>
                <Ionicons name="business" size={16}
                  color={active ? theme.color.onBrand : theme.color.textMuted} />
                <Text style={[styles.chipText, active && styles.chipTextActive]} numberOfLines={1}>
                  {s.name}
                </Text>
              </Pressable>
            );
          })}
        </ScrollView>

        {/* Sprint 6.2 — the whole capture body is now scrollable, so it
            never clips content or leaves controls unreachable on smaller
            screens or when the keyboard is open. */}
        <ScrollView
          style={{ flex: 1 }}
          contentContainerStyle={styles.scrollBody}
          keyboardShouldPersistTaps="handled"
          showsVerticalScrollIndicator={false}
        >
          {photoUris.length > 0 ? (
            <View style={styles.photoStrip}>
              {photoUris.map((uri, i) => (
                <View key={i} style={styles.photoPreviewWrap}>
                  <ExpoImage source={{ uri }} style={styles.photoPreview} contentFit="cover" />
                  <Pressable testID={`clear-photo-${i}`}
                    onPress={() => setPhotoUris((p) => p.filter((_, j) => j !== i))}
                    style={styles.photoX}>
                    <Ionicons name="close" size={18} color="#fff" />
                  </Pressable>
                </View>
              ))}
              <Pressable testID="photo-only-send" onPress={photoOnlySubmit} disabled={submitting}
                style={styles.photoSendBtn}>
                {submitting ? <ActivityIndicator color={theme.color.onBrand} size="small" /> : (
                  <>
                    <Ionicons name="send" size={16} color={theme.color.onBrand} />
                    <Text style={styles.photoSendBtnText}>SEND PHOTOS</Text>
                  </>
                )}
              </Pressable>
            </View>
          ) : null}

          <Text style={styles.statusText} numberOfLines={2} testID="capture-status">
            {status || (recording ? `Recording · ${mins}:${secs}` : sites.length === 0 ? 'No sites available — check back soon' : 'Choose how you want to capture')}
          </Text>

          {/* Sprint 6.2 — Voice / Photo / Text as one consistent,
              responsive control group: equal size, equal weight, same
              row. Recording state is shown by the Voice button itself
              transforming (icon + label + timer), mirroring the same
              record/stop pattern already used for Voice Update on
              operational items. */}
          <View style={styles.captureGroup}>
            <Pressable
              testID="record-button"
              onPress={recording ? stopAndSubmit : startRecording}
              disabled={submitting || !siteId}
              style={[styles.captureBtn, recording && styles.captureBtnRecording, (submitting || !siteId) && { opacity: 0.4 }]}
            >
              {submitting && recording === false ? (
                <ActivityIndicator color={theme.color.onBrand} />
              ) : (
                <Ionicons name={recording ? 'stop' : 'mic'} size={30} color={theme.color.onBrand} />
              )}
              <Text style={styles.captureBtnLabel}>{recording ? `${mins}:${secs}` : 'VOICE'}</Text>
            </Pressable>

            <Pressable
              testID="camera-button" onPress={pickPhoto}
              disabled={submitting || recording}
              style={[styles.captureBtn, styles.captureBtnSecondary, (submitting || recording) && { opacity: 0.4 }]}
            >
              <Ionicons name="camera" size={30} color={theme.color.text} />
              <Text style={[styles.captureBtnLabel, { color: theme.color.text }]}>PHOTO</Text>
            </Pressable>

            <Pressable
              testID="text-capture-button" onPress={() => setShowTextInput((v) => !v)}
              disabled={submitting || recording}
              style={[styles.captureBtn, styles.captureBtnSecondary, showTextInput && styles.captureBtnActive, (submitting || recording) && { opacity: 0.4 }]}
            >
              <Ionicons name="create-outline" size={30} color={showTextInput ? theme.color.onBrand : theme.color.text} />
              <Text style={[styles.captureBtnLabel, { color: showTextInput ? theme.color.onBrand : theme.color.text }]}>TEXT</Text>
            </Pressable>
          </View>

          {recording && (
            <Pressable testID="voice-cancel-capture" onPress={cancelRecording} style={styles.cancelRecordingLink}>
              <Text style={styles.cancelRecordingLinkText}>Cancel recording</Text>
            </Pressable>
          )}

          <Pressable testID="gallery-button" onPress={pickFromGallery}
            disabled={submitting || recording} style={styles.galleryLink}>
            <Ionicons name="images-outline" size={16} color={theme.color.textDim} />
            <Text style={styles.galleryLinkText}>or choose photo from gallery</Text>
          </Pressable>

          {!recording && (
            <Text style={styles.helperText}>Hindi · Punjabi · Hinglish · English</Text>
          )}

          {showTextInput && (
            <View style={styles.textCaptureBox}>
              <TextInput
                testID="text-capture-input"
                value={textNote}
                onChangeText={setTextNote}
                placeholder="Add a site note as text…"
                placeholderTextColor={theme.color.textDim}
                style={styles.textCaptureInput}
                multiline
                autoFocus
              />
              <Pressable testID="text-capture-send" onPress={textOnlySubmit}
                disabled={submitting || !textNote.trim()}
                style={[styles.textCaptureSend, (submitting || !textNote.trim()) && { opacity: 0.4 }]}>
                {submitting ? <ActivityIndicator color={theme.color.onBrand} size="small" /> : (
                  <>
                    <Ionicons name="send" size={18} color={theme.color.onBrand} />
                    <Text style={styles.textCaptureSendLabel}>ADD AS TEXT</Text>
                  </>
                )}
              </Pressable>
            </View>
          )}

          {gps ? (
            <View style={styles.gpsTag}>
              <Ionicons name="location" size={12} color={theme.color.brand} />
              <Text style={styles.gpsText}>GPS LOCKED</Text>
            </View>
          ) : null}
        </ScrollView>
      </KeyboardAvoidingView>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  safe: { flex: 1, backgroundColor: theme.color.surface },
  headerRow: { paddingHorizontal: theme.spacing.lg, paddingTop: theme.spacing.md, paddingBottom: 4 },
  title: { color: theme.color.text, fontSize: 32, fontWeight: '900', letterSpacing: 2 },
  subtitle: { color: theme.color.brand, fontSize: 15, fontWeight: '700', marginTop: 2 },
  chipsRow: { maxHeight: 60, flexGrow: 0 },
  chipsContent: { paddingHorizontal: theme.spacing.md, gap: theme.spacing.sm, alignItems: 'center', height: 60 },
  chip: {
    height: 44, paddingHorizontal: theme.spacing.md, borderRadius: theme.radius.pill,
    backgroundColor: theme.color.surface2, borderWidth: 1, borderColor: theme.color.border,
    flexDirection: 'row', alignItems: 'center', gap: 6, flexShrink: 0, maxWidth: 220,
  },
  chipActive: { backgroundColor: theme.color.brand, borderColor: theme.color.brand },
  chipText: { color: theme.color.textMuted, fontSize: 13, fontWeight: '700' },
  chipTextActive: { color: theme.color.onBrand },
  // Sprint 6.2 — the body is now a ScrollView (was a fixed-height flex
  // container), so nothing ever clips or overlaps regardless of screen
  // size, content length, or keyboard state.
  scrollBody: {
    flexGrow: 1, alignItems: 'center', justifyContent: 'center',
    paddingHorizontal: theme.spacing.lg, paddingVertical: theme.spacing.lg, gap: theme.spacing.md,
  },
  noSitesText: { color: theme.color.textDim, fontSize: 13, fontWeight: '600', paddingHorizontal: theme.spacing.md },
  statusText: { color: theme.color.text, fontSize: 18, fontWeight: '700', letterSpacing: 0.5, textAlign: 'center' },
  // Sprint 6.2 — Voice / Photo / Text as one consistent, responsive group:
  // equal flex, equal height, same row, wraps on very narrow screens
  // instead of clipping or overlapping text.
  captureGroup: {
    flexDirection: 'row', flexWrap: 'wrap', gap: theme.spacing.sm,
    width: '100%', justifyContent: 'center',
  },
  captureBtn: {
    flex: 1, minWidth: 92, height: 92, borderRadius: theme.radius.md,
    backgroundColor: theme.color.brand, alignItems: 'center', justifyContent: 'center', gap: 6,
    boxShadow: '0 4px 12px rgba(255,90,0,0.35)',
  },
  captureBtnSecondary: {
    backgroundColor: theme.color.surface2, borderWidth: 1, borderColor: theme.color.border,
    boxShadow: 'none',
  },
  captureBtnActive: { backgroundColor: theme.color.brand, borderColor: theme.color.brand },
  captureBtnRecording: { backgroundColor: theme.color.error },
  captureBtnLabel: { color: theme.color.onBrand, fontSize: 12, fontWeight: '900', letterSpacing: 1 },
  cancelRecordingLink: { paddingVertical: 4 },
  cancelRecordingLinkText: { color: theme.color.error, fontSize: 13, fontWeight: '700' },
  galleryLink: { flexDirection: 'row', alignItems: 'center', gap: 6, paddingVertical: 6 },
  galleryLinkText: { color: theme.color.textDim, fontSize: 13, fontWeight: '600' },
  helperText: { color: theme.color.textDim, fontSize: 13, fontWeight: '600', letterSpacing: 0.5, textAlign: 'center' },
  textCaptureBox: {
    width: '100%', backgroundColor: theme.color.surface2, borderRadius: theme.radius.md,
    borderWidth: 1, borderColor: theme.color.border, padding: theme.spacing.md, gap: theme.spacing.sm,
  },
  textCaptureInput: {
    minHeight: 80, color: theme.color.text, fontSize: 15, textAlignVertical: 'top',
  },
  textCaptureSend: {
    flexDirection: 'row', alignItems: 'center', justifyContent: 'center', gap: 8,
    height: 48, borderRadius: theme.radius.sm, backgroundColor: theme.color.brand,
  },
  textCaptureSendLabel: { color: theme.color.onBrand, fontSize: 13, fontWeight: '900', letterSpacing: 1 },
  photoStrip: { flexDirection: 'row', gap: 8, flexWrap: 'wrap', justifyContent: 'center', width: '100%' },
  photoPreviewWrap: { width: 100, height: 80, borderRadius: theme.radius.sm, overflow: 'hidden', position: 'relative' },
  photoPreview: { width: '100%', height: '100%' },
  photoX: {
    position: 'absolute', top: 4, right: 4, width: 24, height: 24, borderRadius: 12,
    backgroundColor: 'rgba(0,0,0,0.6)', alignItems: 'center', justifyContent: 'center',
  },
  photoSendBtn: {
    flexDirection: 'row', alignItems: 'center', justifyContent: 'center', gap: 6,
    height: 40, paddingHorizontal: theme.spacing.md, borderRadius: theme.radius.sm,
    backgroundColor: theme.color.success, width: '100%',
  },
  photoSendBtnText: { color: theme.color.onBrand, fontSize: 12, fontWeight: '900', letterSpacing: 1 },
  gpsTag: {
    flexDirection: 'row', alignItems: 'center', gap: 4, paddingHorizontal: 10, paddingVertical: 4,
    backgroundColor: theme.color.surface3, borderRadius: theme.radius.sm,
  },
  gpsText: { color: theme.color.brand, fontSize: 11, fontWeight: '900', letterSpacing: 1 },
});
