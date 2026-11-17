export type ImprovementTab = 'traces' | 'evals' | 'feedback' | 'checkpoints';

export const CHECKPOINTS_PAGE_SIZE = 10;
export const EVAL_CASES_PAGE_SIZE = 10;
export const DEFAULT_EVAL_CATEGORY = 'manual';

export const EVAL_CATEGORY_OPTIONS = [
  { value: 'manual', label: 'Manual' },
  { value: 'regression', label: 'Regression' },
  { value: 'smoke', label: 'Smoke' },
  { value: 'negative', label: 'Negative' },
  { value: 'document_quality', label: 'Document quality' },
];

export const IMPROVEMENT_TABS: Array<{ id: ImprovementTab; label: string }> = [
  { id: 'traces', label: 'Traces' },
  { id: 'evals', label: 'Evals' },
  { id: 'feedback', label: 'Feedback' },
  { id: 'checkpoints', label: 'Checkpoints' },
];

export function formatDateTime(value: string): string {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value || '-';
  const dd = String(date.getDate()).padStart(2, '0');
  const mm = String(date.getMonth() + 1).padStart(2, '0');
  const yyyy = date.getFullYear();
  const hh = String(date.getHours()).padStart(2, '0');
  const min = String(date.getMinutes()).padStart(2, '0');
  const sec = String(date.getSeconds()).padStart(2, '0');
  return `${dd}-${mm}-${yyyy} ${hh}:${min}:${sec}`;
}

export function formatPercent(value: number): string {
  if (!Number.isFinite(value)) return '0%';
  return `${Math.round(value * 100)}%`;
}

export function parseTerms(value: string): string[] {
  return String(value || '')
    .split(',')
    .map((item) => item.trim())
    .filter(Boolean);
}

export function compactJson(value: unknown): string {
  try {
    return JSON.stringify(value ?? {}, null, 2);
  } catch {
    return String(value ?? '');
  }
}

export function formatEvalCategory(value: string): string {
  const option = EVAL_CATEGORY_OPTIONS.find((item) => item.value === value);
  if (option) return option.label;
  return String(value || 'Manual')
    .replace(/[_-]+/g, ' ')
    .replace(/\b\w/g, (char) => char.toUpperCase());
}
