import { useEffect, useMemo, useState } from 'react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';

import { useToast } from '../../context/ToastContext';
import { ragApi } from '../../services/ragApi';
import { LoadingState } from '../common/LoadingState';
import { ModalPortal } from '../common/ModalPortal';
import {
  cleanPageMarkdownForPreview,
  DOCUMENT_MARKDOWN_COMPONENTS,
  repairLooseMarkdownTables,
} from './RAG.model';

export function DocumentViewerModal({
  doc,
  onClose,
}: {
  doc: any;
  onClose: () => void;
}) {
  const [pageImageUrl, setPageImageUrl] = useState<string | null>(null);
  const [pageImageLoading, setPageImageLoading] = useState(false);
  const [pageImageError, setPageImageError] = useState<string | null>(null);
  const [markdownContent, setMarkdownContent] = useState<string>('');
  const [markdownError, setMarkdownError] = useState<string | null>(null);
  const [currentPreviewPage, setCurrentPreviewPage] = useState<number>(1);
  const [loading, setLoading] = useState(true);
  const { showToast } = useToast();

  const markdownByPage = useMemo(() => {
    const content = String(markdownContent || '');
    const pageMap = new Map<number, string>();
    const headingRegex = /^##\s+Page\s+(\d+)\s*$/gim;
    const matches = Array.from(content.matchAll(headingRegex));
    if (matches.length === 0) {
      return pageMap;
    }
    for (let index = 0; index < matches.length; index += 1) {
      const current = matches[index];
      const next = matches[index + 1];
      const pageNumber = Number(current[1]);
      if (Number.isNaN(pageNumber) || pageNumber < 1 || current.index === undefined) continue;
      const sectionStart = current.index + current[0].length;
      const sectionEnd = next?.index ?? content.length;
      const pageSection = content.slice(sectionStart, sectionEnd).trim();
      pageMap.set(pageNumber, pageSection || '_No content available for this page._');
    }
    return pageMap;
  }, [markdownContent]);

  const totalPages = useMemo(() => {
    const fromDoc = Number(doc?.pages || 0);
    if (fromDoc > 0) return fromDoc;
    if (markdownByPage.size === 0) return 1;
    return Math.max(...Array.from(markdownByPage.keys()));
  }, [doc?.pages, markdownByPage]);

  const currentPageMarkdown = useMemo(() => {
    if (markdownByPage.size === 0) {
      return markdownContent;
    }
    return markdownByPage.get(currentPreviewPage) || '';
  }, [markdownByPage, markdownContent, currentPreviewPage]);

  const renderedPageMarkdown = useMemo(
    () => {
      return cleanPageMarkdownForPreview(repairLooseMarkdownTables(currentPageMarkdown));
    },
    [currentPageMarkdown]
  );

  useEffect(() => {
    const loadDocument = async () => {
      setLoading(true);
      setMarkdownError(null);
      try {
        const mdResponse = await ragApi.getDocumentMarkdown(doc.id);
        const markdown = String(mdResponse.data?.markdown ?? '');
        setMarkdownContent(markdown);
      } catch (error: any) {
        const message =
          error?.response?.data?.detail ||
          error?.message ||
          'Markdown extraction could not be loaded.';
        setMarkdownContent('');
        setMarkdownError(String(message));
        showToast('Failed to load document Markdown', 'error');
      } finally {
        setLoading(false);
      }
    };
    loadDocument();
    setCurrentPreviewPage(1);
  }, [doc.id]);

  useEffect(() => {
    setCurrentPreviewPage((prev) => {
      if (prev < 1) return 1;
      if (prev > totalPages) return totalPages;
      return prev;
    });
  }, [totalPages]);

  useEffect(() => {
    let isCancelled = false;

    const loadPageImage = async () => {
      const fileId = Number(doc?.id);
      if (!fileId || Number.isNaN(fileId) || currentPreviewPage < 1) {
        setPageImageUrl(null);
        setPageImageError('Page image is not available for this document.');
        return;
      }

      setPageImageLoading(true);
      setPageImageError(null);
      try {
        const response = await ragApi.getDocumentPageImage(fileId, currentPreviewPage);
        const dataUri = String(response.data?.data_uri || '').trim();
        if (!dataUri) {
          throw new Error('Page image is empty.');
        }
        if (!isCancelled) {
          setPageImageUrl(dataUri);
        }
      } catch {
        if (!isCancelled) {
          setPageImageUrl(null);
          setPageImageError('No se pudo cargar la imagen renderizada de esta pagina.');
        }
      } finally {
        if (!isCancelled) {
          setPageImageLoading(false);
        }
      }
    };

    loadPageImage();
    return () => {
      isCancelled = true;
    };
  }, [doc?.id, currentPreviewPage]);

  const copyMarkdown = () => {
    if (markdownError) return;
    navigator.clipboard.writeText(markdownContent);
    showToast('Markdown copied to clipboard', 'success');
  };

  return (
    <ModalPortal zIndex="z-[300]" className="items-start justify-center p-4">
      <div
        className="rounded-2xl shadow-2xl border border-white/20 overflow-hidden w-full max-w-6xl h-[84vh] flex flex-col border-0"
        style={{
          background: 'rgba(255, 255, 255, 0.72)',
          backdropFilter: 'blur(20px) saturate(180%)',
          WebkitBackdropFilter: 'blur(20px) saturate(180%)',
        }}
      >
        <div className="px-5 py-4 flex items-center gap-3 bg-oracle-dark-gray flex-shrink-0">
          <div className="flex items-center gap-3">
            <div>
              <h2 className="text-lg font-semibold text-white">{doc.original_name || doc.filename}</h2>
              <p className="text-sm text-gray-200">{doc.pages || 0} pages</p>
            </div>
          </div>
          <div className="ml-auto" />
          <button
            onClick={onClose}
            className="p-1.5 rounded-lg hover:bg-white/10 transition-colors text-gray-200"
          >
            <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
            </svg>
          </button>
        </div>

        {/* Content */}
        {loading ? (
          <div className="flex-1 flex items-center justify-center h-full bg-white">
            <LoadingState size="sm" label="Loading document..." textClassName="text-oracle-medium-gray" />
          </div>
        ) : (
          <div className="flex-1 grid grid-cols-2 gap-0 min-h-0 overflow-hidden">
            {/* Left: rendered page image */}
            <div className="flex flex-col border-r border-oracle-border overflow-hidden">
              <div className="flex items-center justify-between py-2 px-4 min-h-[46px] border-b border-oracle-border bg-gray-50 flex-shrink-0">
                <span className="text-sm font-medium text-oracle-dark-gray">Page Image Preview</span>
                <span className="text-xs text-oracle-light-gray">
                  Page {currentPreviewPage} / {totalPages}
                </span>
              </div>
              <div className="flex-1 min-h-0 overflow-auto bg-white">
                {pageImageLoading ? (
                  <div className="m-4 flex h-[calc(100%-2rem)] min-h-[320px] items-center justify-center rounded-xl border border-dashed border-gray-300 bg-white">
                    <LoadingState size="sm" label="Loading page image..." textClassName="text-oracle-medium-gray" />
                  </div>
                ) : pageImageUrl ? (
                  <div className="flex min-h-full items-start justify-center bg-white">
                    <img
                      src={pageImageUrl}
                      alt={`Rendered page ${currentPreviewPage}`}
                      className="block w-full max-w-none bg-white"
                    />
                  </div>
                ) : (
                  <div className="m-4 flex h-[calc(100%-2rem)] min-h-[320px] items-center justify-center rounded-xl border border-dashed border-gray-300 bg-white px-6 text-center">
                    <div>
                      <p className="text-sm font-medium text-oracle-dark-gray">Preview unavailable</p>
                      <p className="mt-1 text-xs leading-5 text-oracle-light-gray">
                        {pageImageError || 'The rendered page image was not generated for this page.'}
                      </p>
                    </div>
                  </div>
                )}
              </div>
            </div>

            {/* Right: Markdown Viewer */}
            <div className="flex flex-col overflow-hidden">
              <div className="flex items-center justify-between py-2 px-4 min-h-[46px] border-b border-oracle-border bg-gray-50 flex-shrink-0">
                <span className="text-sm font-medium text-oracle-dark-gray">Markdown Content</span>
                <div className="flex items-center gap-1.5">
                  <button
                    onClick={() => setCurrentPreviewPage((prev) => Math.max(1, prev - 1))}
                    disabled={currentPreviewPage <= 1}
                    className="p-1.5 rounded border border-gray-300 text-gray-600 hover:bg-gray-100 disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
                    title="Previous page"
                    aria-label="Previous page"
                  >
                    <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15 19l-7-7 7-7" />
                    </svg>
                  </button>
                  <button
                    onClick={() => setCurrentPreviewPage((prev) => Math.min(totalPages, prev + 1))}
                    disabled={currentPreviewPage >= totalPages}
                    className="p-1.5 rounded border border-gray-300 text-gray-600 hover:bg-gray-100 disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
                    title="Next page"
                    aria-label="Next page"
                  >
                    <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 5l7 7-7 7" />
                    </svg>
                  </button>
                  <button
                    onClick={copyMarkdown}
                    disabled={Boolean(markdownError)}
                    className="p-1.5 rounded border border-gray-300 text-gray-600 hover:bg-gray-100 disabled:opacity-40 disabled:cursor-not-allowed"
                    title="Copy Markdown"
                  >
                    <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M8 16H6a2 2 0 01-2-2V6a2 2 0 012-2h8a2 2 0 012 2v2m-6 12h8a2 2 0 002-2v-8a2 2 0 00-2-2h-8a2 2 0 00-2 2v8a2 2 0 002 2z" />
                    </svg>
                  </button>
                </div>
              </div>
              <div className="flex-1 min-h-0 overflow-auto bg-white p-3">
                {markdownError ? (
                  <div className="rounded-lg border border-red-200 bg-red-50 p-4 text-sm leading-6 text-red-800">
                    {markdownError}
                  </div>
                ) : (
                  <div className="prose prose-sm max-w-none text-[13px] leading-5 text-oracle-dark-gray [&_h1]:mb-2 [&_h1]:mt-4 [&_h1]:text-lg [&_h1]:font-bold [&_h2]:mb-2 [&_h2]:mt-3 [&_h2]:border-b [&_h2]:border-gray-200 [&_h2]:pb-1 [&_h2]:text-base [&_h2]:font-semibold [&_h3]:mb-2 [&_h3]:mt-0 [&_h3]:border-b [&_h3]:border-gray-200 [&_h3]:pb-1.5 [&_h3]:text-[13px] [&_h3]:font-semibold [&_h3]:uppercase [&_h3]:tracking-wide [&_h3]:text-oracle-medium-gray [&_ul]:my-2 [&_ul]:list-disc [&_ul]:pl-5 [&_ol]:my-2 [&_ol]:list-decimal [&_ol]:pl-5 [&_li]:my-0.5 [&_strong]:font-semibold [&_code]:rounded [&_code]:bg-gray-100 [&_code]:px-1 [&_code]:text-sm [&_pre]:my-2 [&_pre]:overflow-x-auto [&_pre]:rounded [&_pre]:bg-gray-100 [&_pre]:p-3 [&_pre]:text-sm [&_blockquote]:border-l-4 [&_blockquote]:border-gray-300 [&_blockquote]:pl-4 [&_blockquote]:italic [&_blockquote]:text-gray-600">
                    <ReactMarkdown remarkPlugins={[remarkGfm]} components={DOCUMENT_MARKDOWN_COMPONENTS}>
                      {renderedPageMarkdown}
                    </ReactMarkdown>
                  </div>
                )}
              </div>
            </div>
          </div>
        )}
      </div>
    </ModalPortal>
  );
}
