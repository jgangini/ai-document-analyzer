import type { ChangeEvent, RefObject } from 'react';

import type { SettingsFormData, UpdateSettingsField } from './Settings.model';
import { SettingsFieldHint } from './SettingsFieldHint';

const TIMEZONE_GROUPS = [
  {
    label: 'Americas',
    options: [
      ['America/New_York', 'America/New_York (EST/EDT)'],
      ['America/Chicago', 'America/Chicago (CST/CDT)'],
      ['America/Denver', 'America/Denver (MST/MDT)'],
      ['America/Los_Angeles', 'America/Los_Angeles (PST/PDT)'],
      ['America/Mexico_City', 'America/Mexico_City'],
      ['America/Bogota', 'America/Bogota'],
      ['America/Lima', 'America/Lima'],
      ['America/Santiago', 'America/Santiago'],
      ['America/Buenos_Aires', 'America/Buenos_Aires'],
      ['America/Sao_Paulo', 'America/Sao_Paulo'],
      ['America/Caracas', 'America/Caracas'],
      ['America/Toronto', 'America/Toronto'],
      ['America/Vancouver', 'America/Vancouver'],
    ],
  },
  {
    label: 'Europe',
    options: [
      ['Europe/London', 'Europe/London (GMT/BST)'],
      ['Europe/Paris', 'Europe/Paris (CET/CEST)'],
      ['Europe/Berlin', 'Europe/Berlin (CET/CEST)'],
      ['Europe/Madrid', 'Europe/Madrid (CET/CEST)'],
      ['Europe/Rome', 'Europe/Rome (CET/CEST)'],
      ['Europe/Amsterdam', 'Europe/Amsterdam (CET/CEST)'],
      ['Europe/Moscow', 'Europe/Moscow (MSK)'],
    ],
  },
  {
    label: 'Asia',
    options: [
      ['Asia/Tokyo', 'Asia/Tokyo (JST)'],
      ['Asia/Shanghai', 'Asia/Shanghai (CST)'],
      ['Asia/Hong_Kong', 'Asia/Hong_Kong (HKT)'],
      ['Asia/Singapore', 'Asia/Singapore (SGT)'],
      ['Asia/Seoul', 'Asia/Seoul (KST)'],
      ['Asia/Dubai', 'Asia/Dubai (GST)'],
      ['Asia/Kolkata', 'Asia/Kolkata (IST)'],
      ['Asia/Jakarta', 'Asia/Jakarta (WIB)'],
      ['Asia/Manila', 'Asia/Manila (PHT)'],
      ['Asia/Bangkok', 'Asia/Bangkok (ICT)'],
    ],
  },
  {
    label: 'Pacific',
    options: [
      ['Pacific/Auckland', 'Pacific/Auckland (NZST/NZDT)'],
      ['Pacific/Sydney', 'Australia/Sydney (AEST/AEDT)'],
      ['Pacific/Honolulu', 'Pacific/Honolulu (HST)'],
    ],
  },
  {
    label: 'Other',
    options: [
      ['UTC', 'UTC'],
      ['Africa/Johannesburg', 'Africa/Johannesburg (SAST)'],
      ['Africa/Cairo', 'Africa/Cairo (EET)'],
    ],
  },
];

type SettingsAppTabProps = {
  formData: SettingsFormData;
  applicationDisplayName: string;
  agentDisplayName: string;
  agentAvatarUrl: string;
  agentAvatarLetter: string;
  avatarDropActive: boolean;
  uploadPending: boolean;
  deletePending: boolean;
  agentAvatarInputRef: RefObject<HTMLInputElement>;
  onUpdateField: UpdateSettingsField;
  onAvatarDropActiveChange: (active: boolean) => void;
  onAvatarDropFiles: (files: FileList | null | undefined) => void;
  onAgentAvatarUpload: (event: ChangeEvent<HTMLInputElement>) => void;
  onDeleteAvatar: () => void;
};

export function SettingsAppTab({
  formData,
  applicationDisplayName,
  agentDisplayName,
  agentAvatarUrl,
  agentAvatarLetter,
  avatarDropActive,
  uploadPending,
  deletePending,
  agentAvatarInputRef,
  onUpdateField,
  onAvatarDropActiveChange,
  onAvatarDropFiles,
  onAgentAvatarUpload,
  onDeleteAvatar,
}: SettingsAppTabProps) {
  return (
    <div className="space-y-4">
      <div className="settings-section-card--neutral flex items-center gap-3 rounded-lg border border-gray-300 bg-gray-100 p-4">
        <svg className="w-10 h-10 text-gray-600" fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M10.325 4.317c.426-1.756 2.924-1.756 3.35 0a1.724 1.724 0 002.573 1.066c1.543-.94 3.31.826 2.37 2.37a1.724 1.724 0 001.065 2.572c1.756.426 1.756 2.924 0 3.35a1.724 1.724 0 00-1.066 2.573c.94 1.543-.826 3.31-2.37 2.37a1.724 1.724 0 00-2.572 1.065c-.426 1.756-2.924 1.756-3.35 0a1.724 1.724 0 00-2.573-1.066c-1.543.94-3.31-.826-2.37-2.37a1.724 1.724 0 00-1.065-2.572c-1.756-.426-1.756-2.924 0-3.35a1.724 1.724 0 001.066-2.573c-.94-1.543.826-3.31 2.37-2.37.996.608 2.296.07 2.572-1.065z" />
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15 12a3 3 0 11-6 0 3 3 0 016 0z" />
        </svg>
        <div>
          <p className="font-medium text-gray-800">Application Settings</p>
          <p className="text-sm text-gray-600">Configure general application parameters and behavior</p>
        </div>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
        <div>
          <label className="block text-sm font-medium mb-1">Application Name</label>
          <input
            type="text"
            value={applicationDisplayName}
            onChange={(event) => onUpdateField('app', 'name', event.target.value)}
            className="input-oracle"
          />
          <SettingsFieldHint>Controls the product name shown in the header, login and home pages.</SettingsFieldHint>
        </div>
        <div>
          <label className="block text-sm font-medium mb-1">Agent Name</label>
          <input
            type="text"
            value={agentDisplayName}
            onChange={(event) => onUpdateField('app', 'agent_name', event.target.value)}
            className="input-oracle"
          />
          <SettingsFieldHint>Controls the assistant name used inside chat responses and avatars.</SettingsFieldHint>
        </div>
        <div>
          <label className="block text-sm font-medium mb-1">Session Timeout (minutes)</label>
          <input
            type="number"
            value={formData.app?.session_timeout_minutes || 480}
            onChange={(event) => onUpdateField('app', 'session_timeout_minutes', parseInt(event.target.value))}
            className="input-oracle"
            min="30"
          />
        </div>
        <div>
          <label className="block text-sm font-medium mb-1">Timezone</label>
          <select
            value={formData.app?.timezone || 'America/Lima'}
            onChange={(event) => onUpdateField('app', 'timezone', event.target.value)}
            className="input-oracle"
          >
            {TIMEZONE_GROUPS.map((group) => (
              <optgroup key={group.label} label={group.label}>
                {group.options.map(([value, label]) => (
                  <option key={value} value={value}>
                    {label}
                  </option>
                ))}
              </optgroup>
            ))}
          </select>
        </div>
        <div>
          <label className="block text-sm font-medium mb-1">Default Agent Language</label>
          <select
            value={formData.app?.language || 'es'}
            onChange={(event) => onUpdateField('app', 'language', event.target.value)}
            className="input-oracle"
          >
            <option value="es">Spanish</option>
            <option value="en">English</option>
            <option value="pt">Portuguese</option>
          </select>
        </div>
      </div>

      <div className="md:max-w-[calc((100%-1rem)/2)]">
        <label className="block text-sm font-medium mb-1">Agent Image (optional)</label>
        <div
          className={`py-6 px-6 border-2 border-dashed rounded-lg text-center transition-all ${
            avatarDropActive ? 'border-oracle-red bg-red-50' : 'border-gray-300 bg-gray-50 hover:bg-gray-100'
          } ${uploadPending ? 'opacity-70' : ''}`}
          onDragOver={(event) => {
            event.preventDefault();
            if (uploadPending) return;
            onAvatarDropActiveChange(true);
          }}
          onDragLeave={(event) => {
            event.preventDefault();
            onAvatarDropActiveChange(false);
          }}
          onDrop={(event) => {
            event.preventDefault();
            onAvatarDropActiveChange(false);
            if (uploadPending) return;
            onAvatarDropFiles(event.dataTransfer?.files);
          }}
        >
          <div className="mx-auto w-12 h-12 rounded-xl bg-oracle-red text-white flex items-center justify-center text-lg font-bold overflow-hidden">
            {agentAvatarUrl ? (
              <img src={agentAvatarUrl} alt="Agent avatar" className="w-full h-full object-cover" />
            ) : (
              <span>{agentAvatarLetter}</span>
            )}
          </div>
          <p className="mt-3 text-sm font-semibold text-oracle-dark-gray">Drag and Drop</p>
          <p className="text-sm text-oracle-medium-gray mt-1">Select one image file, or drop it here</p>
          <p className="text-xs text-oracle-light-gray mt-1">Only PNG, JPG and GIF files are accepted</p>
          {uploadPending ? (
            <p className="mt-2 text-sm text-oracle-medium-gray">Uploading...</p>
          ) : (
            <label
              htmlFor="agent-avatar-input"
              className="mt-2 inline-block text-oracle-blue-link hover:underline text-sm cursor-pointer"
              onClick={(event) => event.stopPropagation()}
            >
              Select File
            </label>
          )}
          {agentAvatarUrl && (
            <button
              type="button"
              onClick={(event) => {
                event.stopPropagation();
                onDeleteAvatar();
              }}
              disabled={deletePending}
              className="ml-2 text-sm text-red-600 hover:underline disabled:opacity-60"
            >
              {deletePending ? 'Removing...' : 'Remove'}
            </button>
          )}
          <input
            id="agent-avatar-input"
            ref={agentAvatarInputRef}
            type="file"
            accept="image/png,image/jpeg,image/gif"
            onChange={onAgentAvatarUpload}
            disabled={uploadPending}
            className="hidden"
          />
          <p className="text-xs text-oracle-light-gray mt-2">Max file size: 2 MB</p>
        </div>
      </div>
    </div>
  );
}
