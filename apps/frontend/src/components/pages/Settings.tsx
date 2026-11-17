import { useEffect, useMemo, useRef, useState, type ChangeEvent } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';

import { DEFAULT_APP_DISPLAY_NAME } from '../../config/branding';
import { useToast } from '../../context/ToastContext';
import { appBrandingQueryKey } from '../../hooks/useAppBranding';
import { settingsApi } from '../../services/settingsApi';
import { ConfirmModal } from '../common/ConfirmModal';
import { Layout } from '../common/Layout';
import { LoadingState } from '../common/LoadingState';
import { SettingsAppTab } from './settings/SettingsAppTab';
import { SettingsEmbeddingTab } from './settings/SettingsEmbeddingTab';
import {
  DEFAULT_AGENT_NAME,
  normalizeSettingsPayload,
  type SettingsFormData,
  type SettingsTabId,
} from './settings/Settings.model';
import { SettingsRagTab } from './settings/SettingsRagTab';
import { SettingsTabs } from './settings/SettingsTabs';

export function Settings() {
  const [formData, setFormData] = useState<SettingsFormData | null>(null);
  const [activeTab, setActiveTab] = useState<SettingsTabId>('app');
  const [showSaveModal, setShowSaveModal] = useState(false);
  const [avatarDropActive, setAvatarDropActive] = useState(false);
  const agentAvatarInputRef = useRef<HTMLInputElement>(null);
  const { showToast } = useToast();
  const queryClient = useQueryClient();

  const { data, isLoading } = useQuery({
    queryKey: ['settings'],
    queryFn: () => settingsApi.get(),
  });

  useEffect(() => {
    if (data?.data) {
      setFormData(normalizeSettingsPayload(data.data));
    }
  }, [data]);

  const updateMutation = useMutation({
    mutationFn: (updates: SettingsFormData) => settingsApi.update(updates),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['settings'] });
      queryClient.invalidateQueries({ queryKey: appBrandingQueryKey });
      showToast('Settings saved successfully', 'success');
    },
    onError: () => showToast('Failed to save settings', 'error'),
  });

  const uploadAvatarMutation = useMutation({
    mutationFn: (file: File) => settingsApi.uploadAgentAvatar(file),
    onSuccess: (response) => {
      const avatarUrl = String(response?.data?.avatar_url || '').trim();
      setFormData((prev) => ({
        ...(prev || {}),
        app: {
          ...(prev?.app || {}),
          avatar_url: avatarUrl,
        },
      }));
      queryClient.invalidateQueries({ queryKey: ['settings'] });
      showToast('Agent image updated', 'success');
    },
    onError: (error: any) => {
      const detail = String(error?.response?.data?.detail || error?.message || 'Failed to upload image');
      showToast(detail, 'error');
    },
  });

  const deleteAvatarMutation = useMutation({
    mutationFn: () => settingsApi.deleteAgentAvatar(),
    onSuccess: () => {
      setFormData((prev) => ({
        ...(prev || {}),
        app: {
          ...(prev?.app || {}),
          avatar_url: '',
        },
      }));
      queryClient.invalidateQueries({ queryKey: ['settings'] });
      showToast('Agent image removed', 'success');
    },
    onError: (error: any) => {
      const detail = String(error?.response?.data?.detail || error?.message || 'Failed to remove image');
      showToast(detail, 'error');
    },
  });

  const updateField = (category: string, field: string, value: any) => {
    setFormData((prev) => ({
      ...(prev || {}),
      [category]: {
        ...(prev?.[category] || {}),
        [field]: value,
      },
    }));
  };

  const applicationDisplayName = useMemo(() => {
    const resolved = String(formData?.app?.name || '').trim();
    return resolved || DEFAULT_APP_DISPLAY_NAME;
  }, [formData?.app?.name]);

  const agentDisplayName = useMemo(() => {
    const resolved = String(formData?.app?.agent_name || '').trim();
    return resolved || DEFAULT_AGENT_NAME;
  }, [formData?.app?.agent_name]);

  const agentAvatarLetter = useMemo(() => {
    return (agentDisplayName[0] || 'N').toUpperCase();
  }, [agentDisplayName]);

  const agentAvatarUrl = useMemo(() => {
    const resolved = String(formData?.app?.avatar_url || '').trim();
    return resolved || '';
  }, [formData?.app?.avatar_url]);

  const processAgentAvatarFile = (file: File | null | undefined) => {
    if (!file) return;
    const allowed = ['image/png', 'image/jpeg', 'image/gif'];
    if (!allowed.includes(file.type)) {
      showToast('Unsupported format. Use PNG, JPG, or GIF.', 'error');
      return;
    }
    if (file.size > 2 * 1024 * 1024) {
      showToast('Image size exceeds 2 MB.', 'error');
      return;
    }
    uploadAvatarMutation.mutate(file);
  };

  const handleAgentAvatarDropFiles = (files: FileList | null | undefined) => {
    if (!files || files.length === 0) return;
    if (files.length > 1) {
      showToast('Only one image file is allowed.', 'error');
    }
    processAgentAvatarFile(files[0]);
  };

  const handleAgentAvatarUpload = (event: ChangeEvent<HTMLInputElement>) => {
    processAgentAvatarFile(event.target.files?.[0]);
    event.currentTarget.value = '';
  };

  const confirmSave = () => {
    if (formData) {
      updateMutation.mutate(formData);
    }
    setShowSaveModal(false);
  };

  if (isLoading || !formData) {
    return (
      <Layout>
        <LoadingState className="py-8" label="Loading settings..." textClassName="text-oracle-light-gray" />
      </Layout>
    );
  }

  return (
    <Layout>
      <div>
        <div className="flex items-start justify-between gap-4 mb-4">
          <div>
            <h1 className="text-3xl font-bold text-gray-900 mb-2">Settings</h1>
            <p className="text-oracle-light-gray">Configure application parameters</p>
          </div>
          <div className="flex gap-2">
            <button
              onClick={() => setShowSaveModal(true)}
              className="btn-primary"
              disabled={updateMutation.isPending}
            >
              {updateMutation.isPending ? 'Saving...' : 'Save'}
            </button>
          </div>
        </div>

        <div className="app-light-surface bg-white rounded-lg shadow p-8 space-y-6">
          <SettingsTabs activeTab={activeTab} onTabChange={setActiveTab} />

          <div>
            {activeTab === 'app' && (
              <SettingsAppTab
                formData={formData}
                applicationDisplayName={applicationDisplayName}
                agentDisplayName={agentDisplayName}
                agentAvatarUrl={agentAvatarUrl}
                agentAvatarLetter={agentAvatarLetter}
                avatarDropActive={avatarDropActive}
                uploadPending={uploadAvatarMutation.isPending}
                deletePending={deleteAvatarMutation.isPending}
                agentAvatarInputRef={agentAvatarInputRef}
                onUpdateField={updateField}
                onAvatarDropActiveChange={setAvatarDropActive}
                onAvatarDropFiles={handleAgentAvatarDropFiles}
                onAgentAvatarUpload={handleAgentAvatarUpload}
                onDeleteAvatar={() => deleteAvatarMutation.mutate()}
              />
            )}
            {activeTab === 'rag' && <SettingsRagTab formData={formData} onUpdateField={updateField} />}
            {activeTab === 'embedding' && (
              <SettingsEmbeddingTab formData={formData} onUpdateField={updateField} />
            )}
          </div>
        </div>
      </div>

      {showSaveModal && (
        <ConfirmModal
          icon={
            <svg className="w-10 h-10 text-red-600" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.75} d="M8.228 9c.549-1.165 2.03-2 3.772-2 2.21 0 4 1.343 4 3 0 1.4-1.278 2.575-3.006 2.907-.542.104-.994.54-.994 1.093m0 3h.01M12 21a9 9 0 100-18 9 9 0 000 18z" />
            </svg>
          }
          iconBg="bg-red-100"
          iconRing="ring-red-50"
          title="Save settings"
          message="Are you sure you want to save these changes?"
          detail="Applies modified settings immediately for all users."
          confirmText="Save changes"
          confirmClass="text-red-600 hover:bg-red-50"
          onConfirm={confirmSave}
          onCancel={() => setShowSaveModal(false)}
          loading={updateMutation.isPending}
          loadingText="Saving..."
        />
      )}
    </Layout>
  );
}
