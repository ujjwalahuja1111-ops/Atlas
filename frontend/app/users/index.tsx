import { useCallback, useEffect, useMemo, useState } from 'react';
import {
  View, Text, StyleSheet, ScrollView, Pressable, ActivityIndicator, Modal, Alert, TextInput,
} from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import { Ionicons } from '@expo/vector-icons';
import { useRouter } from 'expo-router';
import { theme } from '@/src/theme';
import { getViewRole, DEFAULT_VIEW_ROLE_FOR, VIEW_ROLE_LABEL, WORKSPACE_OPTIONS_FOR_ROLE, type ViewRole } from '@/src/roles';
import { apiListProjects, type Project, type User, type Role } from '@/src/api';
import {
  apiListAdminUsers, apiApproveUser, apiRejectUser, apiAssignUserRole,
  apiAssignUserWorkspace, apiAssignUserProjects, apiSetUserActive, type ApprovalStatus,
} from '@/src/admin_users_api';
import { toCsv, exportCsv } from '@/src/csv';

const FILTERS: { key: ApprovalStatus | 'all'; label: string }[] = [
  { key: 'pending', label: 'PENDING' },
  { key: 'approved', label: 'APPROVED' },
  { key: 'rejected', label: 'REJECTED' },
  { key: 'all', label: 'ALL' },
];

const ROLE_OPTIONS: Role[] = ['supervisor', 'coordinator', 'management'];

export default function UserManagementScreen() {
  const router = useRouter();
  const [viewRole, setViewRole] = useState<ViewRole | null>(null);
  const [filter, setFilter] = useState<ApprovalStatus | 'all'>('pending');
  const [query, setQuery] = useState('');
  const [users, setUsers] = useState<User[]>([]);
  const [projects, setProjects] = useState<Project[]>([]);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [assigningUser, setAssigningUser] = useState<User | null>(null);
  const [detailUser, setDetailUser] = useState<User | null>(null);
  const [exporting, setExporting] = useState(false);

  useEffect(() => { getViewRole().then(setViewRole); }, []);

  const load = useCallback(async () => {
    setLoading(true);
    setLoadError(null);
    try {
      const [u, p] = await Promise.all([
        apiListAdminUsers(filter === 'all' ? undefined : filter),
        apiListProjects(),
      ]);
      setUsers(u);
      setProjects(p);
    } catch (e: any) {
      console.warn(e);
      setLoadError(e?.message || 'Could not load users. Tap to retry.');
    }
    finally { setLoading(false); }
  }, [filter]);

  useEffect(() => { if (viewRole === 'admin') load(); }, [viewRole, load]);

  // Sprint 4.2: Search. Client-side over the already-loaded (and already
  // status-filtered) list — reuses the existing GET /api/admin/users
  // response with zero backend change, matching "reuse existing APIs
  // wherever possible." List sizes here are capped at 1000 server-side,
  // consistent with every other list endpoint in Atlas.
  const filteredUsers = useMemo(() => {
    const q = query.trim().toLowerCase();
    if (!q) return users;
    return users.filter((u) =>
      u.name.toLowerCase().includes(q) || u.phone.toLowerCase().includes(q)
    );
  }, [users, query]);

  const onApprove = async (u: User) => {
    setBusy(true);
    try { await apiApproveUser(u.id); await load(); }
    catch (e: any) { Alert.alert('Approve failed', String(e?.message || e)); }
    finally { setBusy(false); }
  };

  const onReject = async (u: User) => {
    setBusy(true);
    try { await apiRejectUser(u.id); await load(); }
    catch (e: any) { Alert.alert('Reject failed', String(e?.message || e)); }
    finally { setBusy(false); }
  };

  const onAssignRole = async (u: User, role: Role) => {
    setBusy(true);
    try {
      const updated = await apiAssignUserRole(u.id, role);
      setAssigningUser(updated);
      await load();
    } catch (e: any) { Alert.alert('Assign role failed', String(e?.message || e)); }
    finally { setBusy(false); }
  };

  const onAssignWorkspace = async (u: User, workspace: ViewRole) => {
    setBusy(true);
    try {
      const updated = await apiAssignUserWorkspace(u.id, workspace);
      setAssigningUser(updated);
      await load();
    } catch (e: any) { Alert.alert('Assign workspace failed', String(e?.message || e)); }
    finally { setBusy(false); }
  };

  const onToggleProject = async (u: User, projectId: string) => {
    const current = u.assigned_project_ids || [];
    const next = current.includes(projectId)
      ? current.filter((id) => id !== projectId)
      : [...current, projectId];
    setBusy(true);
    try {
      const updated = await apiAssignUserProjects(u.id, next);
      setAssigningUser(updated);
      await load();
    } catch (e: any) { Alert.alert('Assign projects failed', String(e?.message || e)); }
    finally { setBusy(false); }
  };

  const onSetActive = async (u: User, isActive: boolean) => {
    setBusy(true);
    try { await apiSetUserActive(u.id, isActive); await load(); }
    catch (e: any) { Alert.alert(isActive ? 'Activate failed' : 'Deactivate failed', String(e?.message || e)); }
    finally { setBusy(false); }
  };

  const projectName = (id: string) => projects.find((p) => p.id === id)?.name || id;

  // Sprint 4.2: CSV export. Exports whatever is currently visible (respects
  // the active filter + search), so "export" always matches what the admin
  // is looking at.
  const onExportCsv = async () => {
    setExporting(true);
    try {
      // Rebuild rows with human-readable project names and normalized
      // values rather than raw ids/booleans, since this is meant to be
      // opened directly by a person, not re-imported programmatically.
      const rows = filteredUsers.map((u) => ({
        name: u.name,
        phone: u.phone,
        role: u.role,
        approval_status: u.approval_status || 'approved',
        is_active: u.is_active === false ? 'No' : 'Yes',
        assigned_projects: (u.assigned_project_ids || []).map(projectName).join('; '),
        created_at: u.created_at,
      }));
      const csv = toCsv(rows, [
        { key: 'name', label: 'Name' },
        { key: 'phone', label: 'Mobile Number' },
        { key: 'role', label: 'Role' },
        { key: 'approval_status', label: 'Approval Status' },
        { key: 'is_active', label: 'Active' },
        { key: 'assigned_projects', label: 'Assigned Projects' },
        { key: 'created_at', label: 'Created At' },
      ]);
      const stamp = new Date().toISOString().slice(0, 10);
      await exportCsv(csv, `atlas-users-${stamp}.csv`);
    } catch (e: any) {
      Alert.alert('Export failed', String(e?.message || e));
    } finally { setExporting(false); }
  };

  if (viewRole === null) {
    return (
      <SafeAreaView style={styles.safe}><View style={styles.center}>
        <ActivityIndicator color={theme.color.brand} />
      </View></SafeAreaView>
    );
  }

  if (viewRole !== 'admin') {
    return (
      <SafeAreaView style={styles.safe} edges={['top']}>
        <View style={styles.center}>
          <Ionicons name="lock-closed-outline" size={48} color={theme.color.textDim} />
          <Text style={styles.emptyTitle}>Admin access required</Text>
          <Text style={styles.emptyBody}>User Management is an Admin-only workspace.</Text>
        </View>
      </SafeAreaView>
    );
  }

  return (
    <SafeAreaView style={styles.safe} edges={['top']}>
      <View style={styles.header}>
        <Pressable testID="users-back" onPress={() => router.back()} style={styles.iconBtn}>
          <Ionicons name="arrow-back" size={24} color={theme.color.text} />
        </Pressable>
        <View style={{ flex: 1 }}>
          <Text style={styles.h1}>USER MANAGEMENT</Text>
          <Text style={styles.h2}>Admin workspace · approvals &amp; access</Text>
        </View>
        <Pressable testID="users-export-csv" onPress={onExportCsv} disabled={exporting || filteredUsers.length === 0}
          style={[styles.iconBtn, (exporting || filteredUsers.length === 0) && { opacity: 0.5 }]}>
          {exporting ? <ActivityIndicator size="small" color={theme.color.brand} /> : (
            <Ionicons name="download-outline" size={22} color={theme.color.brand} />
          )}
        </Pressable>
      </View>

      <View style={styles.searchBox}>
        <Ionicons name="search" size={16} color={theme.color.textDim} />
        <TextInput
          testID="users-search"
          value={query} onChangeText={setQuery}
          placeholder="Search name or phone…"
          placeholderTextColor={theme.color.textDim}
          style={styles.searchInput}
        />
        {query.length > 0 && (
          <Pressable testID="users-search-clear" onPress={() => setQuery('')}>
            <Ionicons name="close-circle" size={18} color={theme.color.textDim} />
          </Pressable>
        )}
      </View>

      <ScrollView horizontal showsHorizontalScrollIndicator={false} style={styles.tabsRow}
        contentContainerStyle={{ gap: 8, paddingHorizontal: theme.spacing.md }}>
        {FILTERS.map((f) => (
          <Pressable key={f.key} testID={`users-filter-${f.key}`} onPress={() => setFilter(f.key)}
            style={[styles.tab, filter === f.key && styles.tabActive]}>
            <Text style={[styles.tabText, filter === f.key && styles.tabTextActive]}>{f.label}</Text>
          </Pressable>
        ))}
      </ScrollView>

      {loadError && (
        <Pressable testID="users-load-error" onPress={load} style={styles.errorBanner}>
          <Ionicons name="warning" size={16} color={theme.color.error} />
          <Text style={styles.errorBannerText} numberOfLines={2}>{loadError} Tap to retry.</Text>
        </Pressable>
      )}

      {loading ? (
        <View style={styles.center}><ActivityIndicator size="large" color={theme.color.brand} /></View>
      ) : (
        <ScrollView contentContainerStyle={{ padding: theme.spacing.md, paddingBottom: 80 }}>
          {filteredUsers.length === 0 && (
            <View style={styles.empty}>
              <Ionicons name="people-outline" size={56} color={theme.color.brand} />
              <Text style={styles.emptyTitle}>No users here</Text>
              <Text style={styles.emptyBody}>
                {query ? 'No one matches your search.' : 'Nobody matches this filter right now.'}
              </Text>
            </View>
          )}
          {filteredUsers.map((u) => {
            const status = u.approval_status || 'approved';
            const active = u.is_active !== false;
            return (
              <Pressable key={u.id} testID={`user-row-${u.id}`} style={styles.row}
                onPress={() => setDetailUser(u)}>
                <View style={styles.rowHead}>
                  <View style={{ flex: 1 }}>
                    <Text style={styles.name} numberOfLines={1}>{u.name}</Text>
                    <Text style={styles.meta}>
                      {u.phone} · {u.role}
                      {u.workspace ? ` · ${VIEW_ROLE_LABEL[u.workspace]}` : ''}
                    </Text>
                    {status === 'pending' && u.requested_workspace && (
                      <Text style={styles.requestedLine}>
                        Requested: {VIEW_ROLE_LABEL[u.requested_workspace]}
                      </Text>
                    )}
                  </View>
                  <View style={[styles.statusBadge, {
                    borderColor: status === 'pending' ? theme.color.info
                      : status === 'rejected' ? theme.color.error : theme.color.success,
                  }]}>
                    <Text style={[styles.statusBadgeText, {
                      color: status === 'pending' ? theme.color.info
                        : status === 'rejected' ? theme.color.error : theme.color.success,
                    }]}>{status.toUpperCase()}</Text>
                  </View>
                  {!active && (
                    <View style={[styles.statusBadge, { borderColor: theme.color.textDim, marginLeft: 6 }]}>
                      <Text style={[styles.statusBadgeText, { color: theme.color.textDim }]}>INACTIVE</Text>
                    </View>
                  )}
                </View>

                {(u.assigned_project_ids || []).length > 0 && (
                  <Text style={styles.projectsLine} numberOfLines={2}>
                    Projects: {(u.assigned_project_ids || []).map(projectName).join(', ')}
                  </Text>
                )}

                <View style={styles.actionsRow}>
                  {status === 'pending' && (
                    <>
                      <ActionBtn testID={`user-approve-${u.id}`} icon="checkmark" label="APPROVE"
                        color={theme.color.success} onPress={() => onApprove(u)} disabled={busy} />
                      <ActionBtn testID={`user-reject-${u.id}`} icon="close" label="REJECT"
                        color={theme.color.error} onPress={() => onReject(u)} disabled={busy} />
                    </>
                  )}
                  <ActionBtn testID={`user-details-${u.id}`} icon="eye" label="VIEW"
                    color={theme.color.textMuted} onPress={() => setDetailUser(u)} disabled={busy} />
                  <ActionBtn testID={`user-assign-${u.id}`} icon="options" label="ROLE / ACCESS"
                    color={theme.color.brand} onPress={() => setAssigningUser(u)} disabled={busy} />
                  {active ? (
                    <ActionBtn testID={`user-deactivate-${u.id}`} icon="power" label="DEACTIVATE"
                      color={theme.color.warning}
                      onPress={() => Alert.alert('Deactivate user?', `${u.name} will lose access immediately.`,
                        [{ text: 'Cancel' }, { text: 'Deactivate', style: 'destructive', onPress: () => onSetActive(u, false) }])}
                      disabled={busy} />
                  ) : (
                    <ActionBtn testID={`user-activate-${u.id}`} icon="refresh" label="ACTIVATE"
                      color={theme.color.success} onPress={() => onSetActive(u, true)} disabled={busy} />
                  )}
                </View>
              </Pressable>
            );
          })}
        </ScrollView>
      )}

      {/* Role / Projects assignment modal */}
      <Modal visible={!!assigningUser} animationType="slide" transparent onRequestClose={() => setAssigningUser(null)}>
        <View style={styles.modalBack}>
          <View style={styles.modal}>
            <View style={styles.modalHead}>
              <Text style={styles.modalTitle}>{assigningUser?.name?.toUpperCase()}</Text>
              <Pressable onPress={() => setAssigningUser(null)}>
                <Ionicons name="close" size={26} color={theme.color.textDim} />
              </Pressable>
            </View>

            <Text style={styles.label}>Role (Permission Level)</Text>
            <View style={styles.roleRow}>
              {ROLE_OPTIONS.map((r) => {
                const isActive = assigningUser?.role === r;
                return (
                  <Pressable key={r} testID={`user-role-${r}`}
                    onPress={() => assigningUser && onAssignRole(assigningUser, r)}
                    style={[styles.roleChip, isActive && styles.roleChipActive]}>
                    <Text style={[styles.roleChipText, isActive && styles.roleChipTextActive]}>{r.toUpperCase()}</Text>
                  </Pressable>
                );
              })}
            </View>

            <Text style={[styles.label, { marginTop: 14 }]}>Workspace</Text>
            {assigningUser?.requested_workspace && !assigningUser.workspace && (
              <Text style={styles.requestedHint}>
                Requested at Sign Up: {VIEW_ROLE_LABEL[assigningUser.requested_workspace]}
              </Text>
            )}
            <View style={styles.roleRow}>
              {assigningUser && WORKSPACE_OPTIONS_FOR_ROLE[assigningUser.role].map((w) => {
                const isActive = assigningUser?.workspace === w;
                return (
                  <Pressable key={w} testID={`user-workspace-${w}`}
                    onPress={() => assigningUser && onAssignWorkspace(assigningUser, w)}
                    style={[styles.roleChip, isActive && styles.roleChipActive]}>
                    <Text style={[styles.roleChipText, isActive && styles.roleChipTextActive]}>
                      {VIEW_ROLE_LABEL[w].toUpperCase()}
                    </Text>
                  </Pressable>
                );
              })}
            </View>
            {assigningUser && WORKSPACE_OPTIONS_FOR_ROLE[assigningUser.role].length === 0 && (
              <Text style={styles.emptyBody}>No workspace options for this role.</Text>
            )}

            <Text style={[styles.label, { marginTop: 14 }]}>Projects</Text>
            <ScrollView style={{ maxHeight: 260 }}>
              {projects.length === 0 && <Text style={styles.emptyBody}>No projects exist yet.</Text>}
              {projects.map((p) => {
                const checked = !!assigningUser?.assigned_project_ids?.includes(p.id);
                return (
                  <Pressable key={p.id} testID={`user-project-${p.id}`}
                    onPress={() => assigningUser && onToggleProject(assigningUser, p.id)}
                    style={styles.projectRow}>
                    <Ionicons name={checked ? 'checkbox' : 'square-outline'} size={22}
                      color={checked ? theme.color.brand : theme.color.textDim} />
                    <Text style={styles.projectRowText}>{p.name}</Text>
                  </Pressable>
                );
              })}
            </ScrollView>
          </View>
        </View>
      </Modal>

      {/* View Details modal */}
      <Modal visible={!!detailUser} animationType="slide" transparent onRequestClose={() => setDetailUser(null)}>
        <View style={styles.modalBack}>
          <View style={styles.modal}>
            <View style={styles.modalHead}>
              <Text style={styles.modalTitle}>USER DETAILS</Text>
              <Pressable onPress={() => setDetailUser(null)}>
                <Ionicons name="close" size={26} color={theme.color.textDim} />
              </Pressable>
            </View>
            {detailUser && (
              <ScrollView style={{ maxHeight: 420 }}>
                <DetailRow label="Name" value={detailUser.name} />
                <DetailRow label="Mobile Number" value={detailUser.phone} />
                <DetailRow label="Backend Role" value={detailUser.role} />
                <DetailRow label="Workspace"
                  value={VIEW_ROLE_LABEL[detailUser.workspace || DEFAULT_VIEW_ROLE_FOR[detailUser.role]]
                    + (detailUser.workspace ? '' : ' (default)')} />
                <DetailRow label="Approval Status" value={(detailUser.approval_status || 'approved').toUpperCase()} />
                <DetailRow label="Active" value={detailUser.is_active === false ? 'No' : 'Yes'} />
                <DetailRow label="Assigned Projects"
                  value={(detailUser.assigned_project_ids || []).length
                    ? (detailUser.assigned_project_ids || []).map(projectName).join(', ')
                    : 'None'} />
                <DetailRow label="Created" value={new Date(detailUser.created_at).toLocaleString()} />
              </ScrollView>
            )}
            <Pressable testID="user-details-close" onPress={() => setDetailUser(null)} style={styles.closeDetailBtn}>
              <Text style={styles.closeDetailBtnText}>CLOSE</Text>
            </Pressable>
          </View>
        </View>
      </Modal>
    </SafeAreaView>
  );
}

function ActionBtn({ testID, icon, label, color, onPress, disabled }: {
  testID: string; icon: any; label: string; color: string; onPress: () => void; disabled?: boolean;
}) {
  return (
    <Pressable testID={testID} onPress={onPress} disabled={disabled}
      style={[styles.actionBtn, { borderColor: color }, disabled && { opacity: 0.5 }]}>
      <Ionicons name={icon} size={14} color={color} />
      <Text style={[styles.actionBtnText, { color }]}>{label}</Text>
    </Pressable>
  );
}

function DetailRow({ label, value }: { label: string; value: string }) {
  return (
    <View style={styles.detailRow}>
      <Text style={styles.detailLabel}>{label}</Text>
      <Text style={styles.detailValue}>{value}</Text>
    </View>
  );
}

const styles = StyleSheet.create({
  safe: { flex: 1, backgroundColor: theme.color.surface },
  header: { flexDirection: 'row', alignItems: 'center', padding: theme.spacing.md, gap: theme.spacing.sm },
  h1: { color: theme.color.text, fontSize: 20, fontWeight: '900', letterSpacing: 1 },
  h2: { color: theme.color.brand, fontSize: 11, fontWeight: '700', marginTop: 2 },
  iconBtn: { width: 44, height: 44, borderRadius: 22, backgroundColor: theme.color.surface2,
            alignItems: 'center', justifyContent: 'center' },
  searchBox: { flexDirection: 'row', alignItems: 'center', gap: 8, marginHorizontal: theme.spacing.md,
              marginBottom: theme.spacing.sm, paddingHorizontal: 12, height: 40,
              borderRadius: theme.radius.md, backgroundColor: theme.color.surface2,
              borderWidth: 1, borderColor: theme.color.border },
  searchInput: { flex: 1, color: theme.color.text, fontSize: 14 },
  tabsRow: { flexGrow: 0, marginBottom: theme.spacing.sm },
  tab: { paddingHorizontal: 14, paddingVertical: 8, borderRadius: theme.radius.pill,
        backgroundColor: theme.color.surface2, borderWidth: 1, borderColor: theme.color.border },
  tabActive: { backgroundColor: theme.color.brand, borderColor: theme.color.brand },
  tabText: { color: theme.color.brand, fontSize: 11, fontWeight: '900', letterSpacing: 0.5 },
  tabTextActive: { color: theme.color.onBrand },
  center: { flex: 1, alignItems: 'center', justifyContent: 'center', gap: 8, padding: theme.spacing.lg },
  empty: { alignItems: 'center', padding: theme.spacing.xl, gap: theme.spacing.sm },
  emptyTitle: { color: theme.color.text, fontSize: 18, fontWeight: '900', letterSpacing: 1, marginTop: 8 },
  emptyBody: { color: theme.color.textMuted, textAlign: 'center' },
  errorBanner: {
    flexDirection: 'row', alignItems: 'center', gap: 8, marginHorizontal: theme.spacing.md,
    marginBottom: theme.spacing.sm, padding: 10, borderRadius: theme.radius.sm,
    backgroundColor: theme.color.surface2, borderWidth: 1, borderColor: theme.color.error,
  },
  errorBannerText: { flex: 1, color: theme.color.error, fontSize: 12, fontWeight: '700' },
  row: { padding: theme.spacing.md, backgroundColor: theme.color.surface2, borderRadius: theme.radius.md,
        borderWidth: 1, borderColor: theme.color.border, marginBottom: theme.spacing.sm, gap: 8 },
  rowHead: { flexDirection: 'row', alignItems: 'center', gap: 8 },
  name: { color: theme.color.text, fontSize: 16, fontWeight: '800' },
  meta: { color: theme.color.textDim, fontSize: 12, marginTop: 2 },
  requestedLine: { color: theme.color.info, fontSize: 11, marginTop: 2, fontWeight: '600' },
  requestedHint: { color: theme.color.info, fontSize: 11, marginBottom: 6 },
  statusBadge: { paddingHorizontal: 8, paddingVertical: 3, borderRadius: 6, borderWidth: 1 },
  statusBadgeText: { fontSize: 10, fontWeight: '900', letterSpacing: 0.5 },
  projectsLine: { color: theme.color.textDim, fontSize: 12 },
  actionsRow: { flexDirection: 'row', flexWrap: 'wrap', gap: 6, marginTop: 4 },
  actionBtn: { flexDirection: 'row', alignItems: 'center', gap: 4, paddingHorizontal: 10, paddingVertical: 6,
              borderRadius: theme.radius.pill, borderWidth: 1 },
  actionBtnText: { fontSize: 10, fontWeight: '900', letterSpacing: 0.5 },
  modalBack: { flex: 1, backgroundColor: 'rgba(0,0,0,0.6)', justifyContent: 'flex-end' },
  modal: { backgroundColor: theme.color.surface, borderTopLeftRadius: 18, borderTopRightRadius: 18,
          padding: theme.spacing.lg, gap: 6, maxHeight: '85%' },
  modalHead: { flexDirection: 'row', alignItems: 'center', marginBottom: theme.spacing.sm },
  modalTitle: { flex: 1, color: theme.color.brand, fontSize: 14, fontWeight: '900', letterSpacing: 2 },
  label: { color: theme.color.textDim, fontSize: 11, fontWeight: '800', letterSpacing: 1, marginBottom: 4 },
  roleRow: { flexDirection: 'row', gap: 8 },
  roleChip: { flex: 1, paddingVertical: 10, borderRadius: theme.radius.sm, alignItems: 'center',
             backgroundColor: theme.color.surface2, borderWidth: 1, borderColor: theme.color.border },
  roleChipActive: { backgroundColor: theme.color.brand, borderColor: theme.color.brand },
  roleChipText: { color: theme.color.brand, fontSize: 11, fontWeight: '900', letterSpacing: 0.5 },
  roleChipTextActive: { color: theme.color.onBrand },
  projectRow: { flexDirection: 'row', alignItems: 'center', gap: 10, paddingVertical: 12,
               borderBottomWidth: 1, borderBottomColor: theme.color.border },
  projectRowText: { color: theme.color.text, fontSize: 15, fontWeight: '600' },
  detailRow: { paddingVertical: 10, borderBottomWidth: 1, borderBottomColor: theme.color.border },
  detailLabel: { color: theme.color.textDim, fontSize: 11, fontWeight: '800', letterSpacing: 0.5 },
  detailValue: { color: theme.color.text, fontSize: 15, fontWeight: '700', marginTop: 3 },
  closeDetailBtn: { marginTop: theme.spacing.md, height: 48, borderRadius: theme.radius.md,
                    backgroundColor: theme.color.surface2, borderWidth: 1, borderColor: theme.color.border,
                    alignItems: 'center', justifyContent: 'center' },
  closeDetailBtnText: { color: theme.color.text, fontSize: 14, fontWeight: '900', letterSpacing: 1 },
});
