type LoadingStateProps = {
  label?: string;
  size?: 'sm' | 'md' | 'lg';
  className?: string;
  textClassName?: string;
};

const SIZE_STYLES: Record<NonNullable<LoadingStateProps['size']>, { spinner: string; text: string }> = {
  sm: {
    spinner: 'h-8 w-8 border-b-2 mb-2',
    text: 'text-sm',
  },
  md: {
    spinner: 'h-12 w-12 border-b-2 mb-4',
    text: 'text-base',
  },
  lg: {
    spinner: 'h-14 w-14 border-b-2 mb-4',
    text: 'text-lg',
  },
};

export function LoadingState({
  label = 'Loading...',
  size = 'md',
  className = '',
  textClassName = 'text-gray-600',
}: LoadingStateProps) {
  const resolvedSize = SIZE_STYLES[size];
  return (
    <div className={['text-center', className].filter(Boolean).join(' ')}>
      <div
        className={[
          'animate-spin rounded-full border-oracle-red mx-auto',
          resolvedSize.spinner,
        ].join(' ')}
      />
      <p className={[resolvedSize.text, textClassName].filter(Boolean).join(' ')}>{label}</p>
    </div>
  );
}
