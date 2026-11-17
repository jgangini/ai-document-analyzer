import { SETTINGS_TABS, type SettingsTabId } from './Settings.model';

type SettingsTabsProps = {
  activeTab: SettingsTabId;
  onTabChange: (tab: SettingsTabId) => void;
};

export function SettingsTabs({ activeTab, onTabChange }: SettingsTabsProps) {
  return (
    <div className="flex gap-2 border-b border-oracle-border">
      {SETTINGS_TABS.map((tab) => (
        <button
          key={tab.id}
          onClick={() => onTabChange(tab.id)}
          className={`px-4 py-2 text-sm font-medium transition-colors border-b-2 -mb-px ${
            activeTab === tab.id
              ? 'border-oracle-red text-oracle-red'
              : 'border-transparent text-oracle-medium-gray hover:text-oracle-dark-gray'
          }`}
        >
          {tab.name}
        </button>
      ))}
    </div>
  );
}
