import { DEFAULT_APP_DISPLAY_NAME } from '../../../config/branding';

export const DEFAULT_AGENT_NAME = 'Nadia Assist';

export type SettingsTabId = 'app' | 'rag' | 'embedding';

export type SettingsFormData = Record<string, any>;

export type UpdateSettingsField = (category: string, field: string, value: any) => void;

export const SETTINGS_TABS: Array<{ id: SettingsTabId; name: string }> = [
  { id: 'app', name: 'Application' },
  { id: 'rag', name: 'RAG Processing' },
  { id: 'embedding', name: 'Embedding' },
];

export function normalizeSettingsPayload(payload: any) {
  const app = { ...(payload?.app || {}) };
  const configuredName = String(app.name || '').trim();
  const configuredAgentName = String(app.agent_name || '').trim();

  if (!configuredAgentName) {
    app.agent_name = DEFAULT_AGENT_NAME;
  }
  if (!configuredName) {
    app.name = DEFAULT_APP_DISPLAY_NAME;
  }

  return {
    ...payload,
    app,
  };
}
