import { useResolvedAppName } from '../../context/AppBrandingContext';

type AppBrandProps = {
  className?: string;
  logoClassName?: string;
  title?: string;
  titleClassName?: string;
  dividerClassName?: string;
};

export function AppBrand({
  className = '',
  logoClassName = 'h-5',
  title,
  titleClassName = 'text-xl font-semibold',
  dividerClassName = 'h-8 bg-white opacity-30',
}: AppBrandProps) {
  const appName = useResolvedAppName();
  const resolvedTitle = title ?? appName;

  return (
    <div className={`flex items-center gap-4 ${className}`}>
      <svg className={`${logoClassName} shrink-0`} viewBox="0 0 32 20.4" xmlns="http://www.w3.org/2000/svg" aria-hidden="true">
        <path fill="#C74634" d="M9.9,20.1c-5.5,0-9.9-4.4-9.9-9.9c0-5.5,4.4-9.9,9.9-9.9h11.6c5.5,0,9.9,4.4,9.9,9.9c0,5.5-4.4,9.9-9.9,9.9H9.9 M21.2,16.6c3.6,0,6.4-2.9,6.4-6.4c0-3.6-2.9-6.4-6.4-6.4h-11c-3.6,0-6.4,2.9-6.4,6.4s2.9,6.4,6.4,6.4H21.2"></path>
      </svg>
      <div className={`w-px ${dividerClassName}`} />
      <span className={titleClassName}>{resolvedTitle}</span>
    </div>
  );
}
