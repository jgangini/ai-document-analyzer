import type { SettingsFormData, UpdateSettingsField } from './Settings.model';
import { SettingsNumberField } from './SettingsNumberField';

type SettingsEmbeddingTabProps = {
  formData: SettingsFormData;
  onUpdateField: UpdateSettingsField;
};

export function SettingsEmbeddingTab({ formData, onUpdateField }: SettingsEmbeddingTabProps) {
  return (
    <div className="space-y-4">
      <div className="flex items-center gap-3 p-4 bg-amber-50 border border-amber-200 rounded-lg">
        <svg className="w-10 h-10 text-amber-600" fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.75} d="M9.75 3v2.25M14.25 3v2.25M9.75 18.75V21M14.25 18.75V21M3 9.75h2.25M3 14.25h2.25M18.75 9.75H21M18.75 14.25H21M6.75 6.75h10.5v10.5H6.75V6.75z" />
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.75} d="M9.75 9.75h4.5v4.5h-4.5v-4.5z" />
        </svg>
        <div>
          <p className="font-medium text-amber-800">Embedding and Answer Strategy</p>
          <p className="text-sm text-amber-700">The embedding model is fixed; only answer and visual verification budgets are tunable.</p>
        </div>
      </div>
      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
        <SettingsNumberField
          label="Embedding Dimension"
          value={formData.embedding?.dimension ?? 768}
          hint="Derived from the active local multimodal model."
          min={1}
          disabled
        />
        <SettingsNumberField
          label="Answer Max Evidence"
          value={formData.embedding?.answer_max_evidence ?? 3}
          onChange={(value) => onUpdateField('embedding', 'answer_max_evidence', value)}
          hint="Limits how many top evidence pages are passed into final answer synthesis."
          min={1}
          max={20}
          emptyValue={3}
        />
        <SettingsNumberField
          label="Visual Analysis Top K"
          value={formData.embedding?.visual_analysis_top_k ?? 2}
          onChange={(value) => onUpdateField('embedding', 'visual_analysis_top_k', value)}
          hint="Controls how many pages go through explicit visual verification."
          min={1}
          max={20}
          emptyValue={2}
        />
      </div>
    </div>
  );
}
