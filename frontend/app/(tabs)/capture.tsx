import { useEffect, useRef, useState } from 'react';
import {
  View, Text, Pressable, StyleSheet, ActivityIndicator, ScrollView,
} from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import { Ionicons } from '@expo/vector-icons';
import * as Haptics from 'expo-haptics';
import * as ImagePicker from 'expo-image-picker';
import * as Location from 'expo-location';
import { Image as ExpoImage } from 'expo-image';
import {
  useAudioRecorder, AudioModule, RecordingPresets, setAudioModeAsync,
} from 'expo-audio';
import { useRouter } from 'expo-router';
import { theme } from '@/src/theme';
import { getViewRole, VIEW_PERMS, type ViewRole } from '@/src/roles';
import {
  apiCreateEvent, apiListSites, apiListProjects,
  getActiveSite, setActiveSite,
  type Site, type Project,
} from '@/src/api';

export default function CaptureScreen() {
  const router = useRouter();
  const recorder = useAudioRecorder(RecordingPresets.HIGH_QUALITY);
  const [recording, setRecording] = useState(false);
  const [elapsed, setElapsed] = useState(0);
  const [photoUris, setPhotoUris] = useState<string[]>([]);
  const [sites, setSites] = useState<Site[]>([]);
  const [projectMap, setProjectMap] = useState<Record<string, Project>>({});
  const [siteId, setSiteId] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [status, setStatus] = useState<string>('');
  const [gps, setGps] = useState<{ lat: number; lng: number; accuracy?: number } | null>(null);
  const [gpsAsked, setGpsAsked] = useState(false);
  const [viewRole, setViewRole] = useState<ViewRole | null>(null);
  const timerRef = useRef<any>(null);

  useEffect(() => { getViewRole().then(setViewRole); }, []);

  useEffect(() => {
    (async () => {
      try {
        await AudioModule.requestRecordingPermissionsAsync();
        await setAudioModeAsync({ allowsRecording: true, playsInSilentMode: true });
      } catch {}
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
    return () => { if (timerRef.current) clearInterval(timerRef.current); };
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
    try {
      Haptics.impactAsync(Haptics.ImpactFeedbackStyle.Heavy).catch(() => {});
      await recorder.prepareToRecordAsync();
      recorder.record();
      setRecording(true);
      setElapsed(0);
      setStatus('Recording…');
      timerRef.current = setInterval(() => setElapsed((s) => s + 1), 1000);
    } catch {
      setStatus('Could not start recording');
    }
  };

  const stopAndSubmit = async () => {
    if (!siteId) { setStatus('Pick a site first'); return; }
    try {
      Haptics.notificationAsync(Haptics.NotificationFeedbackType.Success).catch(() => {});
      if (timerRef.current) clearInterval(timerRef.current);
      setRecording(false);
      await recorder.stop();
      const uri = recorder.uri;
      if (!uri && photoUris.length === 0) { setStatus('Nothing to send'); return; }
      setSubmitting(true);
      setStatus('Saving…');
      await apiCreateEvent({ siteId, audioUri: uri, photoUris, gps });
      setStatus('Saved! AI analyzing in background…');
      setPhotoUris([]);
      setElapsed(0);
      setTimeout(() => {
        setStatus('');
        router.push('/(tabs)');
      }, 500);
    } catch (e: any) {
      setStatus(e?.message || 'Save failed');
    } finally { setSubmitting(false); }
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

      <View style={styles.center}>
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
          </View>
        ) : null}

        <Text style={styles.statusText} testID="capture-status">
          {status || (recording ? `${mins}:${secs}` : sites.length === 0 ? 'No sites available — check back soon' : 'Tap mic to record')}
        </Text>

        <Pressable
          testID="record-button"
          onPress={recording ? stopAndSubmit : startRecording}
          disabled={submitting || !siteId}
          style={({ pressed }) => [
            styles.micButton, recording && styles.micRecording,
            (submitting || !siteId) && { opacity: 0.5 },
            pressed && { transform: [{ scale: 0.97 }] },
          ]}
        >
          {submitting ? (
            <ActivityIndicator color={theme.color.onBrand} size="large" />
          ) : (
            <Ionicons name={recording ? 'stop' : 'mic'} size={80} color={theme.color.onBrand} />
          )}
        </Pressable>

        <Text style={styles.helperText}>
          {recording ? 'Tap again to stop & send' : 'Hindi · Punjabi · Hinglish · English'}
        </Text>

        <View style={styles.secondaryRow}>
          <Pressable testID="camera-button" onPress={pickPhoto}
            disabled={submitting || recording}
            style={[styles.secondaryBtn, (submitting || recording) && { opacity: 0.4 }]}>
            <Ionicons name="camera" size={32} color={theme.color.text} />
            <Text style={styles.secondaryLabel}>PHOTO</Text>
          </Pressable>
          <Pressable testID="gallery-button" onPress={pickFromGallery}
            disabled={submitting || recording}
            style={[styles.secondaryBtn, (submitting || recording) && { opacity: 0.4 }]}>
            <Ionicons name="images" size={32} color={theme.color.text} />
            <Text style={styles.secondaryLabel}>GALLERY</Text>
          </Pressable>
          {photoUris.length > 0 && !recording ? (
            <Pressable testID="photo-only-send" onPress={photoOnlySubmit}
              disabled={submitting}
              style={[styles.secondaryBtn, styles.secondarySend]}>
              <Ionicons name="send" size={28} color={theme.color.onBrand} />
              <Text style={[styles.secondaryLabel, { color: theme.color.onBrand }]}>SEND</Text>
            </Pressable>
          ) : null}
        </View>

        {gps ? (
          <View style={styles.gpsTag}>
            <Ionicons name="location" size={12} color={theme.color.brand} />
            <Text style={styles.gpsText}>GPS LOCKED</Text>
          </View>
        ) : null}
      </View>
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
  center: { flex: 1, alignItems: 'center', justifyContent: 'center', paddingHorizontal: theme.spacing.lg, gap: theme.spacing.md },
  noSitesText: { color: theme.color.textDim, fontSize: 13, fontWeight: '600', paddingHorizontal: theme.spacing.md },
  statusText: { color: theme.color.text, fontSize: 20, fontWeight: '700', letterSpacing: 1, textAlign: 'center' },
  micButton: {
    width: 200, height: 200, borderRadius: 100, backgroundColor: theme.color.brand,
    alignItems: 'center', justifyContent: 'center',
    boxShadow: '0 8px 20px rgba(255,90,0,0.5)',
    elevation: 12,
  },
  micRecording: { backgroundColor: theme.color.error },
  helperText: { color: theme.color.textDim, fontSize: 13, fontWeight: '600', letterSpacing: 0.5 },
  secondaryRow: { flexDirection: 'row', gap: theme.spacing.md, marginTop: theme.spacing.lg, flexWrap: 'wrap', justifyContent: 'center' },
  secondaryBtn: {
    width: 100, height: 100, borderRadius: theme.radius.md, backgroundColor: theme.color.surface2,
    alignItems: 'center', justifyContent: 'center', gap: 6, borderWidth: 1, borderColor: theme.color.border,
  },
  secondarySend: { backgroundColor: theme.color.success, borderColor: theme.color.success },
  secondaryLabel: { color: theme.color.textMuted, fontSize: 12, fontWeight: '800', letterSpacing: 1 },
  photoStrip: { flexDirection: 'row', gap: 8, flexWrap: 'wrap', justifyContent: 'center' },
  photoPreviewWrap: { width: 100, height: 80, borderRadius: theme.radius.sm, overflow: 'hidden', position: 'relative' },
  photoPreview: { width: '100%', height: '100%' },
  photoX: {
    position: 'absolute', top: 4, right: 4, width: 24, height: 24, borderRadius: 12,
    backgroundColor: 'rgba(0,0,0,0.6)', alignItems: 'center', justifyContent: 'center',
  },
  gpsTag: {
    flexDirection: 'row', alignItems: 'center', gap: 4, paddingHorizontal: 10, paddingVertical: 4,
    backgroundColor: theme.color.surface3, borderRadius: theme.radius.sm,
  },
  gpsText: { color: theme.color.brand, fontSize: 11, fontWeight: '900', letterSpacing: 1 },
});
