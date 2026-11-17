export function Footer() {
  return (
    <div className="app-footer px-4 py-2 text-center text-[11px] leading-5">
      <span>
        Made with{' '}
        <span className="inline-block translate-y-[1px] px-0.5 text-[15px] leading-none text-oracle-red">
          &#9829;
        </span>{' '}
        at AI CloudTech
      </span>
      <span className="mx-2 text-white/35">&middot;</span>
      <span>Developed by </span>
      <a
        href="https://www.linkedin.com/in/joelgangini"
        target="_blank"
        rel="noopener noreferrer"
        className="font-medium text-oracle-red transition-colors hover:text-[#e45d4c] hover:underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-oracle-red/35 focus-visible:ring-offset-2 focus-visible:ring-offset-[#171412]"
      >
        Joel Gangini
      </a>
    </div>
  );
}
