import { useMemo } from 'react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';

import {
  buildSourceHighlightTerms,
  buildSourcePreviewMarkdownComponents,
} from './RAGChatPanel.markdown';
import { GlassModal } from './GlassModal';
import { LoadingState } from './LoadingState';

type RAGChatSourcePreviewModalProps = {
  open: boolean;
  title: string;
  pageNumber: number;
  imageUri: string;
  markdown: string;
  evidenceSnippet: string;
  loading: boolean;
  imageError: string;
  markdownError: string;
  onClose: () => void;
  onCopyMarkdown: () => void;
};

export function RAGChatSourcePreviewModal({
  open,
  title,
  pageNumber,
  imageUri,
  markdown,
  evidenceSnippet,
  loading,
  imageError,
  markdownError,
  onClose,
  onCopyMarkdown,
}: RAGChatSourcePreviewModalProps) {
  const highlightTerms = useMemo(() => buildSourceHighlightTerms(evidenceSnippet), [evidenceSnippet]);
  const markdownComponents = useMemo(
    () => buildSourcePreviewMarkdownComponents(highlightTerms),
    [highlightTerms]
  );

  return (
    <GlassModal
      open={open}
      onClose={onClose}
      containerClassName="items-start justify-center p-4"
      panelClassName="w-full max-w-6xl mt-8 border-0 overflow-hidden"
    >
      <div className="px-5 py-4 flex items-center gap-3 bg-oracle-dark-gray">
        <div className="min-w-0">
          <h2 className="text-lg font-semibold text-white truncate">Source Page Preview</h2>
          {title && (
            <p className="text-xs text-gray-300 truncate" title={title}>
              {title}
            </p>
          )}
        </div>
        <div className="ml-auto" />
        <button
          type="button"
          onClick={onClose}
          className="p-1.5 rounded-lg hover:bg-white/10 transition-colors text-gray-200"
          aria-label="Close source preview"
        >
          <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
          </svg>
        </button>
      </div>
      <div className="p-0 bg-white/80 h-[78vh] min-h-[500px] overflow-hidden">
        {loading ? (
          <div className="h-full min-h-[360px] flex items-center justify-center">
            <LoadingState size="sm" label="Loading cited page..." textClassName="text-oracle-medium-gray" />
          </div>
        ) : (
          <div className="grid h-full min-h-0 grid-cols-1 overflow-hidden md:grid-cols-2">
            <div className="flex min-h-0 flex-col border-r border-oracle-border">
              <div className="flex min-h-[46px] flex-shrink-0 items-center justify-between border-b border-oracle-border bg-gray-50 px-4 py-2">
                <span className="text-sm font-medium text-oracle-dark-gray">Page Image Preview</span>
                <span className="text-xs text-oracle-light-gray">Page {pageNumber || '?'}</span>
              </div>
              <div className="min-h-0 flex-1 overflow-auto bg-white">
                {imageUri ? (
                  <div className="flex min-h-full items-start justify-center bg-white">
                    <img
                      src={imageUri}
                      alt={title || 'Source page'}
                      className="block w-full max-w-none bg-white"
                    />
                  </div>
                ) : (
                  <div className="m-4 flex h-[calc(100%-2rem)] min-h-[320px] items-center justify-center rounded-xl border border-dashed border-gray-300 bg-white px-6 text-center">
                    <div>
                      <p className="text-sm font-medium text-oracle-dark-gray">Preview unavailable</p>
                      <p className="mt-1 text-xs leading-5 text-oracle-light-gray">
                        {imageError || 'The rendered page image was not generated for this page.'}
                      </p>
                    </div>
                  </div>
                )}
              </div>
            </div>

            <div className="flex min-h-0 flex-col overflow-hidden">
              <div className="flex min-h-[46px] flex-shrink-0 items-center justify-between border-b border-oracle-border bg-gray-50 px-4 py-2">
                <span className="text-sm font-medium text-oracle-dark-gray">Markdown Content</span>
                <div className="flex items-center gap-1.5">
                  <button
                    type="button"
                    disabled
                    className="p-1.5 rounded border border-gray-300 text-gray-400 opacity-40 cursor-not-allowed"
                    title="Previous page disabled for cited-page preview"
                    aria-label="Previous page"
                  >
                    <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15 19l-7-7 7-7" />
                    </svg>
                  </button>
                  <button
                    type="button"
                    disabled
                    className="p-1.5 rounded border border-gray-300 text-gray-400 opacity-40 cursor-not-allowed"
                    title="Next page disabled for cited-page preview"
                    aria-label="Next page"
                  >
                    <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 5l7 7-7 7" />
                    </svg>
                  </button>
                  <button
                    type="button"
                    onClick={onCopyMarkdown}
                    disabled={Boolean(markdownError || !markdown)}
                    className="p-1.5 rounded border border-gray-300 text-gray-600 hover:bg-gray-100 disabled:opacity-40 disabled:cursor-not-allowed"
                    title="Copy Markdown"
                    aria-label="Copy Markdown"
                  >
                    <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M8 16H6a2 2 0 01-2-2V6a2 2 0 012-2h8a2 2 0 012 2v2m-6 12h8a2 2 0 002-2v-8a2 2 0 00-2-2h-8a2 2 0 00-2 2v8a2 2 0 002 2z" />
                    </svg>
                  </button>
                </div>
              </div>
              <div className="min-h-0 flex-1 overflow-auto bg-white p-3">
                {markdownError ? (
                  <div className="rounded-lg border border-red-200 bg-red-50 p-4 text-sm leading-6 text-red-800">
                    {markdownError}
                  </div>
                ) : (
                  <div className="prose prose-sm max-w-none text-[13px] leading-5 text-oracle-dark-gray [&_h1]:mb-2 [&_h1]:mt-4 [&_h1]:text-lg [&_h1]:font-bold [&_mark]:box-decoration-clone">
                    <ReactMarkdown remarkPlugins={[remarkGfm]} components={markdownComponents}>
                      {markdown}
                    </ReactMarkdown>
                  </div>
                )}
              </div>
            </div>
          </div>
        )}
      </div>
    </GlassModal>
  );
}
