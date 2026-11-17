import React, { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { useAuth } from '../../context/AuthContext';
import { AppBrand } from '../common/AppBrand';
import { useAppBranding } from '../../hooks/useAppBranding';
import autonomousDatabaseSvg from '../../assets/oci/autonomous-database.svg?raw';
import generativeAiSvg from '../../assets/oci/generative-ai.svg?raw';
import objectStorageSvg from '../../assets/oci/object-storage.svg?raw';

function makeMonochromeOracleSvg(svg: string) {
  return svg
    .replace(/<\?xml[\s\S]*?\?>/g, '')
    .replace(/<metadata[\s\S]*?<\/metadata>/gi, '')
    .replace(/<style[\s\S]*?<\/style>/gi, '')
    .replace(/class="(?:st1|cls-1)"/g, 'fill="currentColor"')
    .replace(/class="(?:st0|cls-2)"/g, 'style="display:none"')
    .replace(
      /<svg\b([^>]*)>/i,
      '<svg$1 class="h-full w-full" aria-hidden="true" focusable="false">'
    );
}

const oracleServices = [
  {
    name: 'Autonomous Database',
    description: 'Vector search, metadata records, and governed application data.',
    iconSvg: makeMonochromeOracleSvg(autonomousDatabaseSvg),
  },
  {
    name: 'Object Storage',
    description: 'Source PDFs, page renders, extraction JSON, and evidence artifacts.',
    iconSvg: makeMonochromeOracleSvg(objectStorageSvg),
  },
  {
    name: 'Generative AI',
    description: 'Grounded answers and reasoning over cited document context.',
    iconSvg: makeMonochromeOracleSvg(generativeAiSvg),
  },
];

const reviewSignals = ['Metadata routing', 'Evidence traceability', 'Document review'];

export function LoginForm() {
  const navigate = useNavigate();
  const { login } = useAuth();
  const { appName } = useAppBranding();
  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(false);
  const [showPassword, setShowPassword] = useState(false);
  const [rememberMe, setRememberMe] = useState(false);
  const [focusedField, setFocusedField] = useState<'email' | 'password' | null>(null);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError('');
    setLoading(true);

    try {
      await login(username, password);
      navigate('/home');
    } catch (err: any) {
      setError(err.response?.data?.detail || 'Login failed. Please check your credentials.');
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="login-shell-dark flex min-h-screen flex-col">
      <main className="flex flex-1 items-start justify-center px-4 py-5 sm:px-6 md:items-center md:py-8 lg:px-8">
        <div className="w-full max-w-6xl">
          <div className="login-card-shell grid md:grid-cols-[0.9fr_1.1fr] lg:grid-cols-[1.04fr_0.96fr]">
            <section className="login-card-panel login-card-panel--hero relative overflow-hidden bg-oracle-dark-gray px-5 py-6 text-white sm:px-7 md:min-h-[590px] md:px-6 md:py-7 lg:min-h-[640px] lg:px-12 lg:py-10">
              <div className="pointer-events-none absolute -left-20 -top-16 h-80 w-80 rounded-full bg-oracle-red/20 blur-3xl" />
              <div className="pointer-events-none absolute left-24 top-14 h-64 w-64 rounded-full bg-[#d9a38e]/10 blur-3xl" />
              <div className="pointer-events-none absolute bottom-8 right-8 h-72 w-72 translate-x-1/4 translate-y-1/4 rounded-full bg-white/6 blur-3xl" />
              <div className="pointer-events-none absolute inset-0 bg-[linear-gradient(140deg,rgba(255,255,255,0.07)_0,transparent_42%,rgba(0,0,0,0.18)_100%)]" />

              <div className="relative z-10 flex h-full flex-col">
                <AppBrand
                  className="gap-3"
                  logoClassName="h-3.5 opacity-90"
                  title="Oracle Cloud Infrastructure"
                  titleClassName="text-[12px] font-semibold tracking-[0.01em] text-white/56"
                  dividerClassName="h-4 bg-white opacity-18"
                />

                <div className="mt-8 max-w-lg md:mt-10 lg:mt-16">
                  <p className="text-[11px] font-semibold uppercase tracking-[0.22em] text-[#d9cbc4]">
                    Secure document intelligence
                  </p>
                  <h1 className="mt-3 max-w-md text-[2rem] font-semibold leading-[1.03] tracking-[-0.045em] text-white sm:text-[2.35rem] md:text-[2.2rem] lg:text-5xl">
                    {appName}
                  </h1>
                  <p className="mt-4 max-w-md text-sm leading-6 text-white/74 lg:mt-5 lg:text-[15px] lg:leading-7">
                    Explore case files, identify key documents, and review grounded answers with clear evidence from your document collection.
                  </p>
                </div>

                <div className="mt-6 hidden max-w-md grid-cols-3 gap-2.5 md:grid lg:mt-8">
                  {reviewSignals.map((signal) => (
                    <div
                      key={signal}
                      className="rounded-lg border border-white/10 bg-white/[0.055] px-3 py-3 shadow-[inset_0_1px_0_rgba(255,255,255,0.08)]"
                    >
                      <span className="block h-1 w-7 rounded-full bg-oracle-red" />
                      <span className="mt-3 block text-[11px] font-semibold uppercase leading-4 tracking-[0.11em] text-white/78">
                        {signal}
                      </span>
                    </div>
                  ))}
                </div>

                <div className="mt-8 hidden lg:mt-auto lg:block lg:pt-10">
                  <div className="flex items-end justify-between gap-4">
                    <p className="text-[11px] font-semibold uppercase tracking-[0.18em] text-white/62">
                      Oracle services in use
                    </p>
                    <span className="hidden text-[11px] text-white/40 sm:inline">
                      OCI backed workflow
                    </span>
                  </div>
                  <div className="mt-3 overflow-hidden rounded-xl border border-white/10 bg-black/12 shadow-[inset_0_1px_0_rgba(255,255,255,0.05)]">
                    {oracleServices.map((service) => (
                      <div
                        key={service.name}
                        className="group grid grid-cols-[3.25rem_1fr] items-center gap-3 border-b border-white/10 px-3.5 py-3 last:border-b-0 transition-colors duration-200 hover:bg-white/[0.05]"
                      >
                        <span className="flex h-8 w-8 items-center justify-center justify-self-center text-white/92 transition-transform duration-200 group-hover:scale-105">
                          <span
                            aria-hidden="true"
                            className="block h-full w-full"
                            dangerouslySetInnerHTML={{ __html: service.iconSvg }}
                          />
                        </span>
                        <span className="block min-w-0 pl-1">
                          <span className="block text-[13px] font-semibold text-white">
                            {service.name}
                          </span>
                          <span className="mt-0.5 block text-[11px] leading-4 text-white/63">
                            {service.description}
                          </span>
                        </span>
                      </div>
                    ))}
                  </div>
                </div>
              </div>
            </section>

            <section className="login-card-panel login-card-panel--form relative flex min-h-0 items-center justify-center bg-[#fbfaf8] px-5 py-8 sm:px-8 md:min-h-[590px] md:px-7 md:py-8 lg:min-h-[640px] lg:px-10">
              <div className="w-full max-w-[430px]">
                <div className="mb-7">
                  <div className="inline-flex items-center gap-2 rounded-full border border-[#e6ded7] bg-white px-3 py-1 text-[11px] font-semibold uppercase tracking-[0.16em] text-oracle-medium-gray shadow-sm">
                    <span className="h-1.5 w-1.5 rounded-full bg-oracle-red" />
                    Private workspace
                  </div>
                  <h2 className="mt-5 text-[1.85rem] font-semibold leading-tight tracking-[-0.035em] text-[#171412] sm:text-[2rem]">
                    Sign in to continue
                  </h2>
                  <p className="mt-2 text-sm leading-6 text-gray-600">
                    Use your configured project account to access {appName}.
                  </p>
                </div>

                {error && (
                  <div className="mb-4 rounded-lg border border-red-200 bg-red-50 p-3 text-sm text-red-800" role="alert">
                    {error}
                  </div>
                )}

                <form onSubmit={handleSubmit} className="space-y-4">
                  <div>
                    <label htmlFor="login-email" className="mb-1.5 block text-sm font-semibold text-[#2f2b28]">
                      Email
                    </label>
                    <input
                      id="login-email"
                      type="text"
                      value={username}
                      onChange={(e) => setUsername(e.target.value)}
                      onPointerDown={() => setFocusedField('email')}
                      onFocus={() => setFocusedField('email')}
                      onBlur={() => setFocusedField(null)}
                      className={`login-input-oracle ${focusedField === 'email' ? 'login-input-oracle--focused' : ''}`}
                      placeholder="name@company.com"
                      required
                    />
                  </div>

                  <div>
                    <label htmlFor="login-password" className="mb-1.5 block text-sm font-semibold text-[#2f2b28]">
                      Password
                    </label>
                    <div className="relative">
                      <input
                        id="login-password"
                        type={showPassword ? 'text' : 'password'}
                        value={password}
                        onChange={(e) => setPassword(e.target.value)}
                        onPointerDown={() => setFocusedField('password')}
                        onFocus={() => setFocusedField('password')}
                        onBlur={() => setFocusedField(null)}
                        className={`login-input-oracle pr-11 ${focusedField === 'password' ? 'login-input-oracle--focused' : ''}`}
                        placeholder="Enter your password"
                        required
                      />
                      <button
                        type="button"
                        onClick={() => setShowPassword(!showPassword)}
                        aria-label={showPassword ? 'Hide password' : 'Show password'}
                        className="absolute right-2.5 top-1/2 -translate-y-1/2 rounded-md p-1.5 text-gray-500 transition-colors hover:bg-gray-100 hover:text-gray-900 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-oracle-red/40"
                      >
                        <svg className="h-5 w-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                          {showPassword ? (
                            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M13.875 18.825A10.05 10.05 0 0112 19c-4.478 0-8.268-2.943-9.543-7a9.97 9.97 0 011.563-3.029m5.858.908a3 3 0 114.243 4.243M9.878 9.878l4.242 4.242M9.88 9.88l-3.29-3.29m7.532 7.532l3.29 3.29M3 3l3.59 3.59m0 0A9.953 9.953 0 0112 5c4.478 0 8.268 2.943 9.543 7a10.025 10.025 0 01-4.132 5.411m0 0L21 21" />
                          ) : (
                            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15 12a3 3 0 11-6 0 3 3 0 016 0z M2.458 12C3.732 7.943 7.523 5 12 5c4.478 0 8.268 2.943 9.542 7-1.274 4.057-5.064 7-9.542 7-4.477 0-8.268-2.943-9.542-7z" />
                          )}
                        </svg>
                      </button>
                    </div>
                  </div>

                  <div className="flex items-center justify-between gap-4 pt-1">
                    <label className="flex cursor-pointer items-center gap-2">
                      <input
                        type="checkbox"
                        checked={rememberMe}
                        onChange={(e) => setRememberMe(e.target.checked)}
                        className="h-4 w-4 rounded border-gray-300 text-oracle-red focus:ring-oracle-red"
                      />
                      <span className="text-sm text-gray-700">Remember me</span>
                    </label>
                    <a href="#" className="text-sm font-medium text-oracle-blue-link transition hover:text-[#034f91] hover:underline">
                      Forgot password?
                    </a>
                  </div>

                  <button
                    type="submit"
                    disabled={loading}
                    className="inline-flex h-12 w-full items-center justify-center gap-2 rounded-lg bg-oracle-red px-6 py-2 font-semibold text-white shadow-[0_14px_30px_rgba(199,70,52,0.22)] transition duration-200 hover:bg-[#b63d2e] focus-visible:outline-none focus-visible:ring-4 focus-visible:ring-oracle-red/25 focus-visible:ring-offset-2 disabled:cursor-not-allowed disabled:opacity-60"
                  >
                    {loading && (
                      <span
                        aria-hidden="true"
                        className="h-4 w-4 animate-spin rounded-full border-2 border-white/45 border-t-white"
                      />
                    )}
                    {loading ? 'Signing in...' : 'Sign In'}
                  </button>
                </form>
              </div>
            </section>
          </div>

          <footer className="mt-5 text-center text-[11px] leading-5 text-white/75">
            <span>
              Made with <span className="inline-block translate-y-[1px] px-0.5 text-[15px] leading-none text-oracle-red">&#9829;</span> at AI CloudTech
            </span>
            <span className="mx-2 text-white/40">&middot;</span>
            <span>
              Developed by{' '}
              <a
                href="https://www.linkedin.com/in/joelgangini"
                target="_blank"
                rel="noopener noreferrer"
                className="font-medium text-oracle-red transition-colors hover:text-[#e45d4c] hover:underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-oracle-red/35 focus-visible:ring-offset-2 focus-visible:ring-offset-[#171412]"
              >
                Joel Gangini
              </a>
            </span>
          </footer>
        </div>
      </main>
    </div>
  );
}
