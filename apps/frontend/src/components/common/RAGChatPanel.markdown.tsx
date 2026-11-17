import {
  cloneElement,
  isValidElement,
  type ComponentPropsWithoutRef,
  type ReactElement,
  type ReactNode,
} from 'react';
export function stripInlineSourcesSection(value: string): string {
  const text = String(value || '').trim();
  if (!text) return '';
  const cleanedLines = text
    .split('\n')
    .filter((line) => {
      const trimmed = line.trim();
      if (!trimmed) return true;
      if (/^\**\s*(sources?|fuentes?|citations?)\s*:?\**\s*$/i.test(trimmed)) return false;
      if (/^[-*]\s*\**\s*(source|fuente)\b/i.test(trimmed)) return false;
      return true;
    });
  return stripInlineCitationMarkers(cleanedLines.join('\n'))
    .replace(/\n{3,}/g, '\n\n')
    .trim();
}

export function stripInlineCitationMarkers(value: string): string {
  return String(value || '')
    .replace(/(^|[\s(])\[(?:\d{1,3})(?:\s*,\s*\d{1,3})*\](?=([\s).,;:]|$))/g, '$1')
    .replace(/[ \t]+([.,;:])/g, '$1');
}

export const MARKDOWN_TABLE_PATTERN = /(^|\n)\|.+\|\n\|(?:\s*:?-+:?\s*\|)+/m;

export function messageContainsMarkdownTable(value: string): boolean {
  return MARKDOWN_TABLE_PATTERN.test(String(value || ''));
}

export function ChatMarkdownTable({ children }: ComponentPropsWithoutRef<'table'>) {
  return (
    <div className="chat-markdown-table-scroll not-prose my-3 w-full max-w-full overflow-x-auto overscroll-x-contain rounded-xl border border-gray-200 bg-white shadow-sm">
      <table className="w-max min-w-full table-auto border-collapse text-left text-xs text-oracle-dark-gray [&_tbody_tr:nth-child(even)]:bg-gray-50/60">
        {children}
      </table>
    </div>
  );
}

export function ChatMarkdownThead({ children }: ComponentPropsWithoutRef<'thead'>) {
  return <thead className="bg-gray-50">{children}</thead>;
}

export function ChatMarkdownTh({ children }: ComponentPropsWithoutRef<'th'>) {
  return (
    <th className="border-b border-gray-200 px-4 py-3 align-top text-left text-[11px] font-semibold uppercase tracking-wide text-oracle-dark-gray whitespace-nowrap">
      {children}
    </th>
  );
}

export function ChatMarkdownTd({ children }: ComponentPropsWithoutRef<'td'>) {
  return (
    <td className="min-w-[7rem] max-w-[28rem] border-t border-gray-100 px-4 py-3 align-top leading-5 whitespace-normal break-words text-oracle-medium-gray">
      {children}
    </td>
  );
}

export function ChatMarkdownH2({ children }: ComponentPropsWithoutRef<'h2'>) {
  return (
    <h2 className="mt-3 border-b border-gray-200 pb-1 text-[15px] font-semibold leading-6 text-oracle-dark-gray first:mt-0">
      {children}
    </h2>
  );
}

export function ChatMarkdownH3({ children }: ComponentPropsWithoutRef<'h3'>) {
  return <h3 className="mt-2 text-sm font-semibold leading-5 text-oracle-dark-gray">{children}</h3>;
}

export function ChatMarkdownP({ children }: ComponentPropsWithoutRef<'p'>) {
  return <p className="my-1.5 leading-6 text-oracle-dark-gray">{children}</p>;
}

export function ChatMarkdownUl({ children }: ComponentPropsWithoutRef<'ul'>) {
  return <ul className="my-2 space-y-1.5 pl-5 leading-6 marker:text-oracle-red">{children}</ul>;
}

export function ChatMarkdownOl({ children }: ComponentPropsWithoutRef<'ol'>) {
  return <ol className="my-2 space-y-2 pl-5 leading-6 marker:font-semibold marker:text-oracle-red">{children}</ol>;
}

export function ChatMarkdownLi({ children }: ComponentPropsWithoutRef<'li'>) {
  return <li className="pl-1 leading-6 text-oracle-dark-gray">{children}</li>;
}

export function ChatMarkdownStrong({ children }: ComponentPropsWithoutRef<'strong'>) {
  return <strong className="font-semibold text-oracle-dark-gray">{children}</strong>;
}

export function ChatMarkdownCode({ children }: ComponentPropsWithoutRef<'code'>) {
  return (
    <code className="rounded border border-gray-200 bg-gray-50 px-1 py-0.5 text-[0.82em] text-oracle-dark-gray">
      {children}
    </code>
  );
}

export const CHAT_MARKDOWN_COMPONENTS = {
  h2: ChatMarkdownH2,
  h3: ChatMarkdownH3,
  p: ChatMarkdownP,
  ul: ChatMarkdownUl,
  ol: ChatMarkdownOl,
  li: ChatMarkdownLi,
  strong: ChatMarkdownStrong,
  code: ChatMarkdownCode,
  table: ChatMarkdownTable,
  thead: ChatMarkdownThead,
  th: ChatMarkdownTh,
  td: ChatMarkdownTd,
};

export const SOURCE_HIGHLIGHT_STOPWORDS = new Set([
  'ante',
  'aqui',
  'cada',
  'como',
  'con',
  'cual',
  'cuales',
  'cuando',
  'del',
  'desde',
  'donde',
  'esta',
  'este',
  'esto',
  'estos',
  'para',
  'pero',
  'porque',
  'segun',
  'sobre',
  'tambien',
  'the',
  'that',
  'this',
  'with',
]);

export function extractDocumentPageMarkdown(markdown: string, pageNumber: number): string {
  const content = String(markdown || '');
  const normalizedPage = Math.max(1, Math.floor(Number(pageNumber) || 1));
  const headingRegex = /^##\s+Page\s+(\d+)\s*$/gim;
  const matches = Array.from(content.matchAll(headingRegex));
  if (matches.length === 0) return content.trim();

  for (let index = 0; index < matches.length; index += 1) {
    const current = matches[index];
    const next = matches[index + 1];
    const currentPage = Number(current[1]);
    if (currentPage !== normalizedPage || current.index === undefined) continue;
    const sectionStart = current.index + current[0].length;
    const sectionEnd = next?.index ?? content.length;
    return content.slice(sectionStart, sectionEnd).trim();
  }
  return '';
}

export function cleanPageMarkdownForPreview(markdown: string): string {
  return String(markdown || '')
    .replace(/<\s*!?-{2,}\s*images?\s*-{2,}\s*>/gi, '')
    .replace(/\n{3,}/g, '\n\n')
    .trim();
}

export function buildSourceHighlightTerms(snippet: string): string[] {
  const text = String(snippet || '')
    .replace(/\s+/g, ' ')
    .trim();
  if (!text) return [];

  const seen = new Set<string>();
  const terms: string[] = [];
  const words = text.match(/[\p{L}\p{N}]{4,}/gu) || [];
  for (const word of words) {
    const normalized = word.toLocaleLowerCase();
    if (SOURCE_HIGHLIGHT_STOPWORDS.has(normalized) || /^\d+$/.test(normalized) || seen.has(normalized)) {
      continue;
    }
    seen.add(normalized);
    terms.push(word);
    if (terms.length >= 18) break;
  }
  return terms.sort((left, right) => right.length - left.length);
}

export function escapeRegExp(value: string): string {
  return String(value || '').replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
}

export function highlightText(value: string, highlightTerms: string[]): ReactNode {
  if (!highlightTerms.length) return value;
  const pattern = highlightTerms.map(escapeRegExp).filter(Boolean).join('|');
  if (!pattern) return value;
  const regex = new RegExp(`(${pattern})`, 'gi');
  const parts = String(value).split(regex);
  return parts.map((part, index) => {
    if (!part) return null;
    const isMatch = highlightTerms.some((term) => term.toLocaleLowerCase() === part.toLocaleLowerCase());
    if (!isMatch) return part;
    return (
      <mark
        key={`${part}-${index}`}
        className="rounded bg-yellow-200 px-0.5 text-oracle-dark-gray ring-1 ring-yellow-300"
      >
        {part}
      </mark>
    );
  });
}

export function highlightInlineChildren(children: ReactNode, highlightTerms: string[]): ReactNode {
  if (!highlightTerms.length) return children;
  if (typeof children === 'string' || typeof children === 'number') {
    return highlightText(String(children), highlightTerms);
  }
  if (Array.isArray(children)) {
    return children.map((child, index) => (
      <span key={index}>{highlightInlineChildren(child, highlightTerms)}</span>
    ));
  }
  if (isValidElement(children)) {
    const element = children as ReactElement<{ children?: ReactNode }>;
    return cloneElement(element, undefined, highlightInlineChildren(element.props.children, highlightTerms));
  }
  return children;
}

export function buildSourcePreviewMarkdownComponents(highlightTerms: string[]) {
  const highlight = (children: ReactNode) => highlightInlineChildren(children, highlightTerms);
  return {
    h2: ({ children }: ComponentPropsWithoutRef<'h2'>) => (
      <h2 className="mt-3 border-b border-gray-200 pb-1 text-base font-semibold leading-6 text-oracle-dark-gray first:mt-0">
        {highlight(children)}
      </h2>
    ),
    h3: ({ children }: ComponentPropsWithoutRef<'h3'>) => (
      <h3 className="mt-2 text-sm font-semibold leading-5 text-oracle-dark-gray">{highlight(children)}</h3>
    ),
    p: ({ children }: ComponentPropsWithoutRef<'p'>) => (
      <p className="my-1.5 text-[13px] leading-6 text-oracle-dark-gray">{highlight(children)}</p>
    ),
    ul: ({ children }: ComponentPropsWithoutRef<'ul'>) => (
      <ul className="my-2 space-y-1.5 pl-5 leading-6 marker:text-oracle-red">{children}</ul>
    ),
    ol: ({ children }: ComponentPropsWithoutRef<'ol'>) => (
      <ol className="my-2 space-y-2 pl-5 leading-6 marker:font-semibold marker:text-oracle-red">{children}</ol>
    ),
    li: ({ children }: ComponentPropsWithoutRef<'li'>) => (
      <li className="pl-1 leading-6 text-oracle-dark-gray">{highlight(children)}</li>
    ),
    strong: ({ children }: ComponentPropsWithoutRef<'strong'>) => (
      <strong className="font-semibold text-oracle-dark-gray">{highlight(children)}</strong>
    ),
    code: ({ children }: ComponentPropsWithoutRef<'code'>) => (
      <code className="rounded border border-gray-200 bg-gray-50 px-1 py-0.5 text-[0.82em] text-oracle-dark-gray">
        {highlight(children)}
      </code>
    ),
    table: ChatMarkdownTable,
    thead: ChatMarkdownThead,
    th: ({ children }: ComponentPropsWithoutRef<'th'>) => (
      <th className="border-b border-gray-200 px-4 py-3 align-top text-left text-[11px] font-semibold uppercase tracking-wide text-oracle-dark-gray whitespace-nowrap">
        {highlight(children)}
      </th>
    ),
    td: ({ children }: ComponentPropsWithoutRef<'td'>) => (
      <td className="border-t border-gray-100 px-4 py-3 align-top leading-5 whitespace-normal break-words text-oracle-medium-gray">
        {highlight(children)}
      </td>
    ),
  };
}
