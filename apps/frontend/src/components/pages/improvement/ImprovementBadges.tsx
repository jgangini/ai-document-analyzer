export function StatusPill({ value }: { value: string }) {
  const normalized = String(value || '').toLowerCase();
  const tone =
    normalized === 'completed' || normalized === 'passed'
      ? 'border-emerald-200 bg-emerald-50 text-emerald-700'
      : normalized === 'failed'
        ? 'border-red-200 bg-red-50 text-red-700'
        : normalized === 'running'
          ? 'border-blue-200 bg-blue-50 text-blue-700'
          : 'border-amber-200 bg-amber-50 text-amber-700';
  return (
    <span className={`inline-flex items-center rounded-full border px-2 py-0.5 text-[11px] font-semibold ${tone}`}>
      {value || 'pending'}
    </span>
  );
}

export function MetricTile({ label, value, detail }: { label: string; value: string; detail?: string }) {
  return (
    <div className="rounded-lg border border-oracle-border bg-white px-4 py-3 shadow-sm">
      <p className="text-[11px] font-semibold uppercase tracking-wide text-oracle-light-gray">{label}</p>
      <p className="mt-1 text-2xl font-semibold text-oracle-dark-gray">{value}</p>
      {detail ? <p className="mt-1 text-xs text-oracle-medium-gray">{detail}</p> : null}
    </div>
  );
}
