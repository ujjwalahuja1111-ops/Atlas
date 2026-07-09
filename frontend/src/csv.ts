// Project Atlas — CSV export utility (Sprint 4.2)
//
// Deliberately dependency-free: no expo-file-system / expo-sharing, since
// adding a new native module would need a rebuild this environment can't
// verify. Uses only what's already available:
//   - Web (Platform.OS === 'web'): a Blob + temporary <a download> link,
//     the standard browser download pattern.
//   - Native (iOS/Android): React Native's built-in Share API, which opens
//     the OS share sheet (Save to Files, Mail, etc.) — already part of
//     'react-native' core, not a new dependency.
import { Platform, Share } from 'react-native';

/** Escapes a single CSV field per RFC 4180: wrap in quotes if it contains a
 * comma, quote, or newline; double any internal quotes. */
function escapeCsvField(value: unknown): string {
  const s = value === null || value === undefined ? '' : String(value);
  if (/[",\n]/.test(s)) {
    return `"${s.replace(/"/g, '""')}"`;
  }
  return s;
}

/** Builds a CSV string from an array of objects, using `columns` (in
 * order) as both the header row and the field-extraction keys. */
export function toCsv<T extends Record<string, any>>(
  rows: T[],
  columns: { key: keyof T; label: string }[],
): string {
  const header = columns.map((c) => escapeCsvField(c.label)).join(',');
  const body = rows.map((row) =>
    columns.map((c) => escapeCsvField(row[c.key])).join(',')
  );
  return [header, ...body].join('\r\n');
}

/** Exports a CSV string as a downloadable/shareable file. `filename` should
 * include the .csv extension. */
export async function exportCsv(csv: string, filename: string): Promise<void> {
  if (Platform.OS === 'web') {
    // Accessed via `globalThis` with an explicit `any` cast rather than the
    // bare DOM globals (`document`/`Blob`/`URL`) so this file type-checks
    // regardless of whether the project's tsconfig `lib` includes "dom" —
    // this branch only ever runs in an actual browser (Platform.OS ===
    // 'web'), where these are always present at runtime.
    const g = globalThis as any;
    const blob = new g.Blob([csv], { type: 'text/csv;charset=utf-8;' });
    const url = g.URL.createObjectURL(blob);
    const link = g.document.createElement('a');
    link.href = url;
    link.download = filename;
    g.document.body.appendChild(link);
    link.click();
    g.document.body.removeChild(link);
    g.URL.revokeObjectURL(url);
    return;
  }
  // Native: no filesystem write, just hand the CSV text to the OS share
  // sheet so the person can save it to Files, email it, etc.
  await Share.share({
    title: filename,
    message: csv,
  });
}
