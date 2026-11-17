import type { SettingsFormData, UpdateSettingsField } from './Settings.model';
import { SettingsNumberField } from './SettingsNumberField';

type RagNumberSetting = {
  key: string;
  label: string;
  defaultValue: number;
  hint: string;
  min?: number;
  max?: number;
};

const INGESTION_SETTINGS: RagNumberSetting[] = [
  {
    key: 'ingest.max_parallel_jobs',
    label: 'Parallel Jobs',
    defaultValue: 2,
    min: 1,
    max: 20,
    hint: 'Sets how many ingestion jobs can run in parallel across the queue.',
  },
  {
    key: 'ingest.max_parallel_documents',
    label: 'Parallel Documents',
    defaultValue: 3,
    min: 1,
    max: 20,
    hint: 'Limits how many files a single ingestion workflow can process at the same time.',
  },
];

const RETRIEVAL_SETTINGS: RagNumberSetting[] = [
  {
    key: 'retrieval.doc_shortlist_scoped',
    label: 'Scoped Document Shortlist',
    defaultValue: 12,
    hint: 'Controls how many files are kept when the question scope is already narrowed.',
  },
  {
    key: 'retrieval.doc_shortlist_global',
    label: 'Global Document Shortlist',
    defaultValue: 20,
    hint: 'Sets the initial file shortlist when the question searches across the full workspace.',
  },
  {
    key: 'retrieval.page_pool_scoped',
    label: 'Scoped Page Pool',
    defaultValue: 36,
    hint: 'Defines the maximum page pool gathered from scoped file candidates before reranking.',
  },
  {
    key: 'retrieval.page_pool_global',
    label: 'Global Page Pool',
    defaultValue: 60,
    hint: 'Defines the maximum page pool gathered for open-ended searches across all files.',
  },
  {
    key: 'retrieval.rerank_scoped',
    label: 'Scoped Rerank Pool',
    defaultValue: 24,
    hint: 'Caps reranking depth for metadata-first and already-scoped questions.',
  },
  {
    key: 'retrieval.rerank_global',
    label: 'Global Rerank Pool',
    defaultValue: 32,
    hint: 'Caps reranking depth for broad semantic searches across the whole corpus.',
  },
  {
    key: 'retrieval.max_candidates',
    label: 'Max Candidates',
    defaultValue: 2000,
    min: 40,
    hint: 'Caps the total retrieval candidates collected before fusion and diversity selection.',
  },
  {
    key: 'retrieval.max_mmr_pool',
    label: 'Max MMR Pool',
    defaultValue: 1200,
    hint: 'Limits the pool sent into MMR so diversity stays useful without adding excess latency.',
  },
];

type SettingsRagTabProps = {
  formData: SettingsFormData;
  onUpdateField: UpdateSettingsField;
};

function RagSettingGrid({
  settings,
  formData,
  onUpdateField,
}: {
  settings: RagNumberSetting[];
  formData: SettingsFormData;
  onUpdateField: UpdateSettingsField;
}) {
  return (
    <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
      {settings.map((setting) => (
        <SettingsNumberField
          key={setting.key}
          label={setting.label}
          value={formData.rag?.[setting.key] ?? setting.defaultValue}
          onChange={(value) => onUpdateField('rag', setting.key, value)}
          hint={setting.hint}
          min={setting.min ?? 1}
          max={setting.max}
          emptyValue={setting.defaultValue}
        />
      ))}
    </div>
  );
}

export function SettingsRagTab({ formData, onUpdateField }: SettingsRagTabProps) {
  return (
    <div className="space-y-4">
      <div className="settings-section-card--accent flex items-center gap-3 rounded-lg border border-red-200 bg-red-50 p-4">
        <svg className="w-10 h-10 text-oracle-red" fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z" />
        </svg>
        <div>
          <p className="font-medium text-gray-800">RAG Processing Settings</p>
          <p className="text-sm text-gray-600">Configure ingestion concurrency and retrieval budgets used by the runtime</p>
        </div>
      </div>

      <div className="rounded-lg border border-gray-200 bg-gray-50 p-4 space-y-4">
        <div>
          <p className="font-medium text-oracle-dark-gray">Ingestion</p>
          <p className="text-sm text-oracle-medium-gray">These values control how many ingestion workers can run at the same time.</p>
        </div>
        <RagSettingGrid settings={INGESTION_SETTINGS} formData={formData} onUpdateField={onUpdateField} />
      </div>

      <div className="rounded-lg border border-gray-200 bg-gray-50 p-4 space-y-4">
        <div>
          <p className="font-medium text-oracle-dark-gray">Retrieval</p>
          <p className="text-sm text-oracle-medium-gray">Tune shortlist and page pool sizes before fusion and reranking.</p>
        </div>
        <RagSettingGrid settings={RETRIEVAL_SETTINGS} formData={formData} onUpdateField={onUpdateField} />
      </div>
    </div>
  );
}
