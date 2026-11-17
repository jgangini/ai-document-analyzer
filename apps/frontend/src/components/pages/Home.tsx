import { useQuery } from '@tanstack/react-query';

import { Layout } from '../common/Layout';
import { useAppBranding } from '../../hooks/useAppBranding';
import { handleUnauthorizedApiResponse } from '../../lib/apiAuthFailure';

type FileSummary = {
  file_id: number;
  status: string;
  page_count: number;
};

type StatKind = 'documents' | 'processed' | 'pages';

async function listHomeFiles(): Promise<FileSummary[]> {
  const token = localStorage.getItem('token');
  const response = await fetch('/api/files', {
    headers: {
      'Content-Type': 'application/json',
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
    },
  });
  handleUnauthorizedApiResponse(response, '/files');
  if (!response.ok) {
    throw new Error(`Failed to load files (${response.status})`);
  }
  const payload = await response.json();
  return payload?.items ?? [];
}

function StatIcon({ kind }: { kind: StatKind }) {
  if (kind === 'processed') {
    return (
      <svg className="h-5 w-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.8} d="M9 12.75l2 2 4-5.5" />
        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.8} d="M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
      </svg>
    );
  }
  if (kind === 'pages') {
    return (
      <svg className="h-5 w-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.8} d="M7 3.75h7.25L19 8.5v11.75H7V3.75z" />
        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.8} d="M14 3.75V9h5M4.75 6.75v13.5h11.5" />
      </svg>
    );
  }
  return (
    <svg className="h-5 w-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.8} d="M5 7.75A2.75 2.75 0 017.75 5h8.5A2.75 2.75 0 0119 7.75v8.5A2.75 2.75 0 0116.25 19h-8.5A2.75 2.75 0 015 16.25v-8.5z" />
      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.8} d="M8 9h8M8 12h8M8 15h5" />
    </svg>
  );
}

export function Home() {
  const { appName } = useAppBranding();

  const filesQuery = useQuery({
    queryKey: ['files', 'list'],
    queryFn: listHomeFiles,
  });

  const files = filesQuery.data ?? [];
  const totalDocuments = files.length;
  const processedDocuments = files.filter((item) => item.status === 'completed').length;
  const totalIndexedPages = files.reduce((acc, item) => acc + Number(item.page_count || 0), 0);
  const completionRate = totalDocuments > 0 ? Math.round((processedDocuments / totalDocuments) * 100) : 0;
  const statCards = [
    { label: 'Documents', value: totalDocuments, kind: 'documents' as const, caption: 'Files available for governed search' },
    { label: 'Processed', value: processedDocuments, kind: 'processed' as const, caption: 'Ready to answer with evidence' },
    { label: 'Pages', value: totalIndexedPages, kind: 'pages' as const, caption: 'Indexed pages in the corpus' },
  ];
  const processedSummary = `${processedDocuments} of ${totalDocuments} documents processed`;

  return (
    <Layout>
      <div className="space-y-6">
        <section className="app-card app-red-glow-card rounded-3xl px-6 py-7 sm:px-8 lg:px-10">
          <div className="grid gap-8 lg:grid-cols-[minmax(0,1fr)_minmax(420px,0.82fr)] lg:items-end">
            <div>
              <p className="app-kicker">Document intelligence workspace</p>
              <h1 className="app-page-title mt-3 max-w-3xl text-4xl font-semibold leading-tight sm:text-5xl">
                {appName}
              </h1>
              <p className="app-page-description mt-4 max-w-2xl text-sm leading-6 sm:text-[15px]">
                Explore case files, identify key documents, and validate grounded answers across metadata and document evidence.
              </p>
            </div>

            <div className="home-stats-grid grid gap-3 sm:grid-cols-3">
              {statCards.map((stat) => (
                <div key={stat.label} className="home-stat-card rounded-2xl p-4">
                  <p className="home-stat-label">{stat.label}</p>
                  <div className="mt-2 flex items-baseline gap-1.5">
                    <p className="home-stat-value text-3xl font-semibold leading-none tracking-[-0.03em]">
                      {stat.value}
                    </p>
                    <span className="home-stat-icon inline-flex h-5 w-5 shrink-0 translate-y-[2px] items-center justify-center">
                      <StatIcon kind={stat.kind} />
                    </span>
                  </div>
                  <p className="home-stat-caption mt-4 text-xs leading-5">{stat.caption}</p>
                </div>
              ))}
            </div>
          </div>
        </section>

        <section className="home-light-card home-ingestion-card rounded-3xl p-6 sm:p-7">
          <div className="flex flex-col gap-4 lg:flex-row lg:items-start lg:justify-between">
            <div>
              <p className="text-[11px] font-bold uppercase tracking-[0.18em] text-oracle-red">
                Corpus ingestion
              </p>
              <h2 className="home-light-title mt-2 text-2xl font-semibold tracking-[-0.03em]">
                Ingestion status
              </h2>
            </div>
          </div>
          <p className="home-light-muted mt-4 w-full max-w-none text-sm leading-6">
            Completed documents are ready for retrieval across chat and RAG. Pending or failed files remain visible in the workflow so the team can retry, inspect, or repair them without leaving the workspace.
          </p>
          <div className="mt-6 flex flex-col gap-2 text-xs font-semibold uppercase tracking-[0.12em] sm:flex-row sm:items-center sm:justify-between">
            <span className="home-progress-note">{processedSummary}</span>
            <span className="home-progress-note home-progress-note--right">{completionRate}% ready</span>
          </div>
          <div className="home-progress-track mt-3 h-3 overflow-hidden rounded-full">
            <div
              className="home-progress-fill h-full rounded-full transition-all duration-500"
              style={{ width: `${completionRate}%` }}
            />
          </div>
        </section>
      </div>
    </Layout>
  );
}
