import { SettingsFieldHint } from './SettingsFieldHint';

type SettingsNumberFieldProps = {
  label: string;
  value: number;
  onChange?: (value: number) => void;
  hint?: string;
  min?: number;
  max?: number;
  disabled?: boolean;
  emptyValue?: number;
};

export function SettingsNumberField({
  label,
  value,
  onChange,
  hint,
  min = 1,
  max,
  disabled = false,
  emptyValue = min,
}: SettingsNumberFieldProps) {
  return (
    <div>
      <label className="block text-sm font-medium mb-1">{label}</label>
      <input
        type="number"
        value={value}
        onChange={(event) => onChange?.(Number(event.target.value || emptyValue))}
        className={`input-oracle${disabled ? ' bg-gray-100 text-oracle-medium-gray' : ''}`}
        min={min}
        max={max}
        disabled={disabled}
      />
      {hint ? <SettingsFieldHint>{hint}</SettingsFieldHint> : null}
    </div>
  );
}
