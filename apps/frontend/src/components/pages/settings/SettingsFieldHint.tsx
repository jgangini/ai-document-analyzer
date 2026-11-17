import type { ReactNode } from 'react';

export function SettingsFieldHint({ children }: { children: ReactNode }) {
  return <p className="text-xs text-oracle-light-gray mt-1">{children}</p>;
}
