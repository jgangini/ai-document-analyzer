import { useState, useEffect } from 'react';
import { Layout } from '../common/Layout';
import { LoadingState } from '../common/LoadingState';
import { handleUnauthorizedApiResponse } from '../../lib/apiAuthFailure';

async function requestProfileJson<T>(
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

  const text = await response.text();
  return (text ? JSON.parse(text) : null) as T;
}

export function Profile() {
  const [editing, setEditing] = useState(false);
  const [saving, setSaving] = useState(false);
  const [loading, setLoading] = useState(true);
  const [user, setUser] = useState<any>(null);
  const [successMessage, setSuccessMessage] = useState('');
  const [errorMessage, setErrorMessage] = useState('');
  
  const [formData, setFormData] = useState({
    name: '',
    last_name: '',
    current_password: '',
    new_password: '',
    confirm_password: '',
  });

  useEffect(() => {
    const fetchUserData = async () => {
      try {
        const userData = await requestProfileJson<any>('/user/me');
        setUser(userData);
        setFormData({
          name: userData.name || '',
          last_name: userData.last_name || '',
          current_password: '',
          new_password: '',
          confirm_password: '',
        });
      } catch (error) {
        console.error('Error loading user data:', error);
      } finally {
        setLoading(false);
      }
    };

    fetchUserData();
  }, []);

  const handleSaveProfile = async () => {
    setSaving(true);
    setSuccessMessage('');
    setErrorMessage('');
    
    try {
      await requestProfileJson('/user/profile', {
        method: 'PUT',
        body: {
          name: formData.name,
          last_name: formData.last_name,
        },
      });
      
      setUser({
        ...user,
        name: formData.name,
        last_name: formData.last_name
      });
      
      setSuccessMessage('Profile updated successfully!');
      setEditing(false);
      
      setTimeout(() => setSuccessMessage(''), 5000);
    } catch (error: any) {
      setErrorMessage(error.response?.data?.detail || 'Failed to update profile');
    } finally {
      setSaving(false);
    }
  };

  const handleChangePassword = async () => {
    setSuccessMessage('');
    setErrorMessage('');
    
    if (formData.new_password !== formData.confirm_password) {
      setErrorMessage('New passwords do not match');
      return;
    }

    setSaving(true);
    try {
      await requestProfileJson('/user/change-password', {
        method: 'POST',
        body: {
          current_password: formData.current_password,
          new_password: formData.new_password,
        },
      });
      
      setSuccessMessage('Password changed successfully!');
      setFormData({
        ...formData,
        current_password: '',
        new_password: '',
        confirm_password: ''
      });
      
      setTimeout(() => setSuccessMessage(''), 5000);
    } catch (error: any) {
      setErrorMessage(error.response?.data?.detail || 'Failed to change password');
    } finally {
      setSaving(false);
    }
  };

  if (loading) {
    return (
      <div className="app-shell-dark min-h-screen flex items-center justify-center">
        <LoadingState />
      </div>
    );
  }

  if (!user) {
    return (
      <div className="app-shell-dark min-h-screen flex items-center justify-center">
        <p className="text-gray-600">Failed to load user data</p>
      </div>
    );
  }

  return (
    <Layout contentContainerClassName="max-w-4xl mx-auto px-6 py-8" mainMarginBottom="50px">
            <h1 className="text-3xl font-bold text-gray-900 mb-6">Edit Profile</h1>
            
            {/* Profile Section */}
            <div className="bg-white rounded-lg shadow p-8 mb-6">
              <div className="flex items-center gap-4 mb-6">
                <div className="w-20 h-20 rounded-full bg-gray-200 flex items-center justify-center">
                  <svg className="w-12 h-12 text-gray-400" fill="currentColor" viewBox="0 0 20 20">
                    <path fillRule="evenodd" d="M10 9a3 3 0 100-6 3 3 0 000 6zm-7 9a7 7 0 1114 0H3z" clipRule="evenodd" />
                  </svg>
                </div>
                <div>
                  <h2 className="text-xl font-semibold text-gray-900">{user?.username}</h2>
                  <p className="text-sm text-gray-600">Administrator</p>
                </div>
              </div>

              <div className="grid grid-cols-2 gap-4 mb-6">
                <div>
                  <label className="block text-sm font-medium mb-1">First Name</label>
                  <input
                    type="text"
                    value={formData.name}
                    onChange={(e) => setFormData({ ...formData, name: e.target.value })}
                    disabled={!editing}
                    className="input-oracle"
                  />
                </div>
                <div>
                  <label className="block text-sm font-medium mb-1">Last Name</label>
                  <input
                    type="text"
                    value={formData.last_name}
                    onChange={(e) => setFormData({ ...formData, last_name: e.target.value })}
                    disabled={!editing}
                    className="input-oracle"
                  />
                </div>
              </div>

              <div className="mb-6">
                <label className="block text-sm font-medium mb-1">Email</label>
                <input
                  type="text"
                  value={user?.username || ''}
                  disabled
                  className="input-oracle bg-gray-100"
                />
                <p className="text-xs text-gray-500 mt-1">Email cannot be changed</p>
              </div>

              {/* Success/Error Messages - Profile */}
              {successMessage && successMessage.includes('Profile') && (
                <div className="mb-4 p-3 bg-green-50 border border-green-200 text-green-800 rounded text-sm flex items-center gap-2">
                  <svg className="w-4 h-4 flex-shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 12l2 2 4-4m6 2a9 9 0 11-18 0 9 9 0 0118 0z" />
                  </svg>
                  <span>{successMessage}</span>
                </div>
              )}

              <div className="flex gap-3">
                {!editing ? (
                  <button
                    onClick={() => setEditing(true)}
                    className="btn-secondary"
                  >
                    Edit Profile
                  </button>
                ) : (
                  <>
                    <button
                      onClick={handleSaveProfile}
                      disabled={saving}
                      className="btn-primary"
                    >
                      {saving ? 'Saving...' : 'Save Changes'}
                    </button>
                    <button
                      onClick={() => setEditing(false)}
                      className="btn-secondary"
                    >
                      Cancel
                    </button>
                  </>
                )}
              </div>
            </div>

            {/* Change Password Section */}
            <div className="bg-white rounded-lg shadow p-8">
              <h3 className="text-lg font-semibold mb-4">Change Password</h3>
              
              <div className="space-y-4">
                <div>
                  <label className="block text-sm font-medium mb-1">Current Password</label>
                  <input
                    type="password"
                    value={formData.current_password}
                    onChange={(e) => setFormData({ ...formData, current_password: e.target.value })}
                    className="input-oracle"
                    placeholder="Enter current password"
                  />
                </div>
                <div>
                  <label className="block text-sm font-medium mb-1">New Password</label>
                  <input
                    type="password"
                    value={formData.new_password}
                    onChange={(e) => setFormData({ ...formData, new_password: e.target.value })}
                    className="input-oracle"
                    placeholder="Enter new password"
                  />
                </div>
                <div>
                  <label className="block text-sm font-medium mb-1">Confirm New Password</label>
                  <input
                    type="password"
                    value={formData.confirm_password}
                    onChange={(e) => setFormData({ ...formData, confirm_password: e.target.value })}
                    className="input-oracle"
                    placeholder="Confirm new password"
                  />
                </div>
              </div>

              {/* Success/Error Messages - Password */}
              {successMessage && successMessage.includes('Password') && (
                <div className="mt-4 p-3 bg-green-50 border border-green-200 text-green-800 rounded text-sm flex items-center gap-2">
                  <svg className="w-4 h-4 flex-shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 12l2 2 4-4m6 2a9 9 0 11-18 0 9 9 0 0118 0z" />
                  </svg>
                  <span>{successMessage}</span>
                </div>
              )}
              
              {errorMessage && (
                <div className="mt-4 p-3 bg-red-50 border border-red-200 text-red-800 rounded text-sm flex items-center justify-between">
                  <div className="flex items-center gap-2">
                    <svg className="w-4 h-4 flex-shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M10 14l2-2m0 0l2-2m-2 2l-2-2m2 2l2 2m7-2a9 9 0 11-18 0 9 9 0 0118 0z" />
                    </svg>
                    <span>{errorMessage}</span>
                  </div>
                  <button
                    onClick={() => setErrorMessage('')}
                    className="text-red-600 hover:text-red-800"
                  >
                    <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
                    </svg>
                  </button>
                </div>
              )}

              <button
                onClick={handleChangePassword}
                disabled={saving || !formData.current_password || !formData.new_password}
                className="btn-primary mt-6"
              >
                {saving ? 'Changing...' : 'Change Password'}
              </button>
            </div>
    </Layout>
  );
}
