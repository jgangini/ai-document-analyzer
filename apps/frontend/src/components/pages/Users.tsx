import { useState, useEffect, useMemo } from 'react';
import { useNavigate } from 'react-router-dom';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { Layout } from '../common/Layout';
import { LoadingState } from '../common/LoadingState';
import { ConfirmDeleteModal } from '../common/ConfirmDeleteModal';
import { useAuth } from '../../context/AuthContext';
import { handleUnauthorizedApiResponse } from '../../lib/apiAuthFailure';
import { queryKeys } from '../../lib/queryClient';

async function requestUserJson<T>(
  path: string,
  options: { method?: string; body?: unknown } = {}
): Promise<T> {
  const token = localStorage.getItem('token');
  const response = await fetch(`/api${path}`, {
    method: options.method || 'GET',
    headers: {
      'Content-Type': 'application/json',
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
    },
    body: options.body === undefined ? undefined : JSON.stringify(options.body),
  });

  handleUnauthorizedApiResponse(response, path);
  if (!response.ok) {
    let detail = `HTTP ${response.status}`;
    try {
      const payload = await response.json();
      detail = String(payload?.detail || detail);
    } catch {
      // Keep the HTTP status fallback.
    }
    const error = new Error(detail) as Error & { response?: { data: { detail: string } } };
    error.response = { data: { detail } };
    throw error;
  }

  if (response.status === 204) {
    return null as T;
  }

  const text = await response.text();
  return (text ? JSON.parse(text) : null) as T;
}

export function Users() {
  const navigate = useNavigate();
  const { user: authUser } = useAuth();
  const queryClient = useQueryClient();
  const [searchTerm, setSearchTerm] = useState('');
  const [currentPage, setCurrentPage] = useState(1);
  const [pageSize] = useState(10);
  const [showCreateModal, setShowCreateModal] = useState(false);
  const [deleteTarget, setDeleteTarget] = useState<any | null>(null);
  const [deletingUser, setDeletingUser] = useState(false);
  const [successMessage, setSuccessMessage] = useState('');
  const [errorMessage, setErrorMessage] = useState('');

  const [newUser, setNewUser] = useState({
    username: '',
    password: '',
    name: '',
    last_name: '',
    group_id: 1,
  });

  useEffect(() => {
    if (authUser && authUser.group_id !== 0) {
      navigate('/home');
    }
  }, [authUser, navigate]);

  const { data: usersList = [], isLoading: loading } = useQuery({
    queryKey: queryKeys.users.list,
    queryFn: async () => {
      const data = await requestUserJson<{ users?: any[] }>('/user/users');
      return data.users ?? [];
    },
    enabled: !!(authUser && authUser.group_id === 0),
  });

  const { data: userGroups = [] } = useQuery({
    queryKey: queryKeys.users.groups,
    queryFn: async () => {
      const data = await requestUserJson<{ groups?: { user_group_id: number; user_group_name: string }[] }>('/user/groups');
      return data.groups ?? [];
    },
    enabled: !!(authUser && authUser.group_id === 0),
  });

  const filteredUsers = useMemo(() => {
    let filtered = usersList;
    if (searchTerm.trim()) {
      const term = searchTerm.trim().toLowerCase();
      filtered = usersList.filter(
        (u) =>
          (u.username || '').toLowerCase().includes(term) ||
          (u.name || '').toLowerCase().includes(term) ||
          (u.last_name || '').toLowerCase().includes(term) ||
          (u.group_name || '').toLowerCase().includes(term)
      );
    }
    return [...filtered].sort((a, b) => {
      const dateA = (a.created || a.user_created) ? new Date(a.created || a.user_created).getTime() : 0;
      const dateB = (b.created || b.user_created) ? new Date(b.created || b.user_created).getTime() : 0;
      return dateB - dateA;
    });
  }, [usersList, searchTerm]);

  useEffect(() => {
    setCurrentPage(1);
  }, [searchTerm, usersList]);

  const totalPages = Math.max(1, Math.ceil(filteredUsers.length / pageSize));
  const startIndex = (currentPage - 1) * pageSize;
  const paginatedUsers = filteredUsers.slice(startIndex, startIndex + pageSize);

  const highlightMatch = (text: string, search: string) => {
    if (!search.trim() || !text) return text ?? '—';
    const s = search.trim().toLowerCase();
    const lower = (text ?? '').toLowerCase();
    const idx = lower.indexOf(s);
    if (idx === -1) return text ?? '—';
    return (
      <>
        {(text ?? '').slice(0, idx)}
        <mark className="bg-amber-200 rounded px-0.5">{text!.slice(idx, idx + s.length)}</mark>
        {(text ?? '').slice(idx + s.length)}
      </>
    );
  };

  /** Same format as Workflows/NdDuModels: DD-MM-YYYY HH:mm:ss.ms */
  const formatDate = (dateStr: string | null) => {
    if (!dateStr) return '—';
    const d = new Date(dateStr);
    if (Number.isNaN(d.getTime())) return '—';
    const dd = String(d.getDate()).padStart(2, '0');
    const mm = String(d.getMonth() + 1).padStart(2, '0');
    const yyyy = d.getFullYear();
    const hh = String(d.getHours()).padStart(2, '0');
    const min = String(d.getMinutes()).padStart(2, '0');
    const ss = String(d.getSeconds()).padStart(2, '0');
    const ms = String(d.getMilliseconds()).padStart(3, '0');
    return `${dd}-${mm}-${yyyy} ${hh}:${min}:${ss}.${ms}`;
  };

  const handleCreateUser = async () => {
    setSuccessMessage('');
    setErrorMessage('');
    
    try {
      await requestUserJson('/user/create', { method: 'POST', body: newUser });
      setSuccessMessage('User created successfully!');
      setShowCreateModal(false);
      setNewUser({
        username: '',
        password: '',
        name: '',
        last_name: '',
        group_id: userGroups[0]?.user_group_id ?? 1,
      });
      queryClient.invalidateQueries({ queryKey: queryKeys.users.list });
      setTimeout(() => setSuccessMessage(''), 5000);
    } catch (error: any) {
      setErrorMessage(error.response?.data?.detail || 'Failed to create user');
    }
  };

  const confirmDeleteUser = async () => {
    if (!deleteTarget || deletingUser) return;
    setDeletingUser(true);
    setSuccessMessage('');
    setErrorMessage('');
    try {
      await requestUserJson(`/user/${deleteTarget.user_id}`, { method: 'DELETE' });
      setSuccessMessage('User deleted successfully!');
      setDeleteTarget(null);
      queryClient.invalidateQueries({ queryKey: queryKeys.users.list });
      setTimeout(() => setSuccessMessage(''), 5000);
    } catch (error: any) {
      setErrorMessage(error.response?.data?.detail || 'Failed to delete user');
    } finally {
      setDeletingUser(false);
    }
  };

  return (
    <>
      <Layout contentContainerClassName="max-w-7xl mx-auto px-6 py-8" mainMarginBottom="50px">
            <div className="flex items-start justify-between gap-4 mb-4">
              <div>
                <h1 className="text-3xl font-bold text-gray-900 mb-2">Users</h1>
                <p className="text-oracle-light-gray">
                  Manage user accounts, access groups, and administrative permissions.
                </p>
              </div>
              <button
                type="button"
                onClick={() => setShowCreateModal(true)}
                className="flex-shrink-0 inline-flex items-center gap-2 px-4 py-2 rounded-lg text-sm font-medium text-white bg-oracle-red hover:bg-oracle-red/90 border border-transparent transition-colors"
              >
                <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 4v16m8-8H4" />
                </svg>
                User
              </button>
            </div>
            <div className="app-light-surface bg-white rounded-lg shadow p-8">
              {successMessage && (
                <div className="mb-4 p-3 bg-green-50 border border-green-200 text-green-800 rounded text-sm flex items-center gap-2">
                  <svg className="w-4 h-4 flex-shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 12l2 2 4-4m6 2a9 9 0 11-18 0 9 9 0 0118 0z" />
                  </svg>
                  <span>{successMessage}</span>
                </div>
              )}
              {errorMessage && (
                <div className="mb-4 p-3 bg-red-50 border border-red-200 text-red-800 rounded text-sm flex items-center justify-between">
                  <div className="flex items-center gap-2">
                    <svg className="w-4 h-4 flex-shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M10 14l2-2m0 0l2-2m-2 2l-2-2m2 2l2 2m7-2a9 9 0 11-18 0 9 9 0 0118 0z" />
                    </svg>
                    <span>{errorMessage}</span>
                  </div>
                  <button
                    type="button"
                    onClick={() => setErrorMessage('')}
                    className="text-red-600 hover:text-red-800"
                  >
                    <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
                    </svg>
                  </button>
                </div>
              )}
              <div className="mb-6 flex gap-4 flex-wrap">
                <div className="flex-1 min-w-[200px]">
                  <input
                    type="text"
                    value={searchTerm}
                    onChange={(e) => setSearchTerm(e.target.value)}
                    className="input-oracle focus:outline-none focus:ring-2 focus:ring-oracle-red/50 focus:border-oracle-red"
                    placeholder="Search by username, name or group..."
                    aria-label="Search users"
                  />
                </div>
                <button
                  type="button"
                  onClick={() => queryClient.refetchQueries({ queryKey: queryKeys.users.list })}
                  disabled={loading}
                  title="Refresh"
                  className="flex-shrink-0 w-10 h-10 flex items-center justify-center rounded border border-gray-300 bg-white text-gray-600 hover:bg-gray-50 hover:border-gray-400 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
                  aria-label="Refresh"
                >
                  <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15" />
                  </svg>
                </button>
              </div>
              {loading ? (
                <LoadingState className="py-12" />
              ) : usersList.length === 0 ? (
                <div className="p-8 border-2 border-dashed border-gray-300 rounded-lg text-center">
                  <svg className="w-16 h-16 text-gray-400 mx-auto mb-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 4.354a4 4 0 110 5.292M15 21H3v-1a6 6 0 0112 0v1zm0 0h6v-1a6 6 0 00-9-5.197M13 7a4 4 0 11-8 0 4 4 0 018 0z" />
                  </svg>
                  <p className="text-gray-500 mb-2">No users yet</p>
                  <p className="text-sm text-gray-400">
                    Create a user with + User
                  </p>
                </div>
              ) : filteredUsers.length === 0 ? (
                <div className="p-8 border-2 border-dashed border-gray-300 rounded-lg text-center">
                  <p className="text-gray-500">No users match your search</p>
                  <button
                    type="button"
                    onClick={() => setSearchTerm('')}
                    className="mt-2 text-oracle-blue-link hover:underline text-sm"
                  >
                    Clear search
                  </button>
                </div>
              ) : (
                <>
                  <div className="overflow-x-auto">
                    <table className="min-w-full divide-y divide-gray-200">
                      <thead className="bg-gray-50">
                        <tr>
                          <th className="px-4 py-3 text-center text-xs font-medium text-gray-500 uppercase tracking-wider w-16">#</th>
                          <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">Username</th>
                          <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider max-w-[180px]">Name</th>
                          <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">Group</th>
                          <th className="px-2 py-2 text-left text-xs font-medium text-gray-500 uppercase tracking-wider w-[190px] min-w-[190px] max-w-[190px]">Created</th>
                          <th className="w-24 min-w-0 px-3 py-3 text-center text-xs font-medium uppercase tracking-wider text-gray-500">Actions</th>
                        </tr>
                      </thead>
                      <tbody className="bg-white divide-y divide-gray-200">
                        {paginatedUsers.map((user, index) => (
                          <tr key={user.user_id} className="hover:bg-gray-50">
                            <td className="px-4 py-4 text-center text-sm font-semibold text-gray-700">{startIndex + index + 1}</td>
                            <td className="px-6 py-4 text-sm font-medium text-gray-900">{highlightMatch(user.username ?? '', searchTerm)}</td>
                            <td className="px-6 py-4 text-sm text-gray-600 max-w-[180px] truncate" title={[user.name, user.last_name].filter(Boolean).join(' ').trim() || undefined}>
                              {highlightMatch([user.name, user.last_name].filter(Boolean).join(' '), searchTerm)}
                            </td>
                            <td className="px-6 py-4 text-sm text-gray-600">{highlightMatch(user.group_name ?? '', searchTerm)}</td>
                            <td className="py-1.5 px-3 whitespace-nowrap w-[190px] min-w-[190px] max-w-[190px]">{formatDate(user.created ?? user.user_created)}</td>
                            <td className="w-24 min-w-0 whitespace-nowrap px-3 py-1.5 text-center text-sm">
                              {user.user_id !== 0 && (
                                <button
                                  type="button"
                                  onClick={() => setDeleteTarget(user)}
                                  className="inline-flex h-8 w-8 items-center justify-center rounded text-red-600 transition-colors hover:bg-gray-100"
                                  title="Delete user"
                                  aria-label={`Delete ${user.username || 'user'}`}
                                >
                                  <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16" />
                                  </svg>
                                </button>
                              )}
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                  {filteredUsers.length > 0 && (
                    <div className="mt-4 flex items-center justify-between border-t border-gray-200 pt-4">
                      <p className="text-sm text-gray-600">
                        Showing {startIndex + 1}–{Math.min(startIndex + pageSize, filteredUsers.length)} of {filteredUsers.length}
                      </p>
                      <div className="flex items-center gap-2">
                        <button
                          type="button"
                          onClick={() => setCurrentPage((p) => Math.max(1, p - 1))}
                          disabled={currentPage <= 1}
                          className="px-3 py-1.5 text-sm border border-gray-300 rounded bg-white text-gray-700 hover:bg-gray-50 disabled:opacity-50 disabled:cursor-not-allowed"
                        >
                          Previous
                        </button>
                        <span className="text-sm text-gray-600">
                          Page {currentPage} of {totalPages}
                        </span>
                        <button
                          type="button"
                          onClick={() => setCurrentPage((p) => Math.min(totalPages, p + 1))}
                          disabled={currentPage >= totalPages}
                          className="px-3 py-1.5 text-sm border border-gray-300 rounded bg-white text-gray-700 hover:bg-gray-50 disabled:opacity-50 disabled:cursor-not-allowed"
                        >
                          Next
                        </button>
                      </div>
                    </div>
                  )}
                </>
              )}
            </div>
      </Layout>

      {/* Create User Modal */}
      {showCreateModal && (
        <div className="fixed inset-0 m-0 bg-black/30 backdrop-blur-sm flex items-center justify-center z-[300] p-4">
          <div
            className="rounded-2xl shadow-2xl overflow-hidden max-w-md w-full border-0"
            style={{
              background: 'rgba(255,255,255,0.72)',
              backdropFilter: 'blur(20px) saturate(180%)',
              WebkitBackdropFilter: 'blur(20px) saturate(180%)',
            }}
          >
            <div className="px-5 py-4 flex items-center gap-3 bg-oracle-dark-gray">
              <h2 className="text-lg font-semibold text-white">Create New User</h2>
              <div className="ml-auto" />
              <button
                type="button"
                onClick={() => setShowCreateModal(false)}
                className="p-1.5 rounded-lg hover:bg-white/10 transition-colors text-gray-200"
                aria-label="Close create user modal"
              >
                <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
                </svg>
              </button>
            </div>

            <div className="bg-white p-8 space-y-6">
              <div className="space-y-4">
                <div>
                  <label className="block text-sm font-medium mb-1">Email *</label>
                  <input
                    type="email"
                    value={newUser.username}
                    onChange={(e) => setNewUser({ ...newUser, username: e.target.value })}
                    className="input-oracle"
                    placeholder="user@example.com"
                  />
                </div>

                <div>
                  <label className="block text-sm font-medium mb-1">Password *</label>
                  <input
                    type="password"
                    value={newUser.password}
                    onChange={(e) => setNewUser({ ...newUser, password: e.target.value })}
                    className="input-oracle"
                    placeholder="Password"
                  />
                </div>

                <div className="grid grid-cols-2 gap-4">
                  <div>
                    <label className="block text-sm font-medium mb-1">First Name *</label>
                    <input
                      type="text"
                      value={newUser.name}
                      onChange={(e) => setNewUser({ ...newUser, name: e.target.value })}
                      className="input-oracle"
                    />
                  </div>
                  <div>
                    <label className="block text-sm font-medium mb-1">Last Name *</label>
                    <input
                      type="text"
                      value={newUser.last_name}
                      onChange={(e) => setNewUser({ ...newUser, last_name: e.target.value })}
                      className="input-oracle"
                    />
                  </div>
                </div>

                <div>
                  <label className="block text-sm font-medium mb-1">User Group</label>
                  <select
                    value={newUser.group_id}
                    onChange={(e) => setNewUser({ ...newUser, group_id: parseInt(e.target.value, 10) })}
                    className="input-oracle"
                  >
                    {userGroups.map((g) => (
                      <option key={g.user_group_id} value={g.user_group_id}>
                        {g.user_group_name}
                      </option>
                    ))}
                  </select>
                </div>
              </div>

              <div className="flex gap-3">
                <button
                  onClick={handleCreateUser}
                  disabled={!newUser.username || !newUser.password || !newUser.name}
                  className="btn-primary flex-1"
                >
                  Create
                </button>
                <button
                  onClick={() => setShowCreateModal(false)}
                  className="btn-secondary flex-1"
                >
                  Cancel
                </button>
              </div>
            </div>
          </div>
        </div>
      )}

      {deleteTarget ? (
        <ConfirmDeleteModal
          title="Delete user"
          message={
            <span>
              Are you sure you want to delete{' '}
              <span className="font-medium text-oracle-dark-gray">
                {deleteTarget.username || 'this user'}
              </span>
              ?
            </span>
          }
          detail="This removes the user account from the application."
          loading={deletingUser}
          onConfirm={() => void confirmDeleteUser()}
          onCancel={() => {
            if (!deletingUser) setDeleteTarget(null);
          }}
        />
      ) : null}
    </>
  );
}
