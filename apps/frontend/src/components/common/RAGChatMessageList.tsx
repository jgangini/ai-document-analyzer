import type { RefObject } from 'react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';

import type { RAGScopeOptions } from '../../services/apiTypes';
import {
  buildUserMessagePresentation,
  getInlineChipClassName,
  getUserMessageChipClassName,
  SelectorChipIcon,
} from './RAGChatPanel.composer';
import { CHAT_MARKDOWN_COMPONENTS, messageContainsMarkdownTable } from './RAGChatPanel.markdown';
import { formatInferredScopeLabel } from './RAGChatPanel.messages';
import { formatTime, type FeedbackKind, type Message, type Source } from './RAGChatPanel.types';
import { LoadingState } from './LoadingState';

type RAGChatMessageListProps = {
  listRef: RefObject<HTMLDivElement>;
  loadingConversation: boolean;
  messages: Message[];
  loading: boolean;
  loadingElapsedSeconds: number;
  assistantDisplayName: string;
  assistantAvatarUrl: string;
  assistantAvatarLetter: string;
  showAssistantAvatarImage: boolean;
  userInitials: string;
  userFirstName: string;
  scopeOptions: RAGScopeOptions | null | undefined;
  copiedMessageId: string | null;
  messageFeedback: Record<string, FeedbackKind>;
  onAssistantAvatarImageError: () => void;
  onOpenSourcePreview: (source: Source) => void;
  onCopyAssistantAnswer: (message: Message, messageIndex: number) => void | Promise<void>;
  onMessageFeedback: (message: Message, messageIndex: number, kind: FeedbackKind) => void;
};

type AssistantIdentityProps = Pick<
  RAGChatMessageListProps,
  'assistantDisplayName' | 'assistantAvatarUrl' | 'assistantAvatarLetter' | 'showAssistantAvatarImage' | 'onAssistantAvatarImageError'
>;

function resolveSourcePreviewTarget(source: Source): Source | null {
  const pageNumber = Number(source.page_number ?? 0);
  if (!Number.isFinite(pageNumber) || pageNumber <= 0) return null;
  if (source.file_id) {
    return { ...source, page_number: pageNumber };
  }
  return null;
}

function RAGChatAssistantAvatar({
  assistantDisplayName,
  assistantAvatarUrl,
  assistantAvatarLetter,
  showAssistantAvatarImage,
  onAssistantAvatarImageError,
}: AssistantIdentityProps) {
  return (
    <div className="w-8 h-8 rounded-xl bg-oracle-red flex items-center justify-center flex-shrink-0 overflow-hidden mt-0.5">
      {showAssistantAvatarImage ? (
        <img
          src={assistantAvatarUrl}
          alt={assistantDisplayName}
          className="w-full h-full object-cover rounded-xl"
          onError={onAssistantAvatarImageError}
        />
      ) : (
        <span className="text-white text-xs font-bold">{assistantAvatarLetter}</span>
      )}
    </div>
  );
}

function RAGChatUserAvatar({ userInitials }: { userInitials: string }) {
  return (
    <div className="w-8 h-8 rounded-xl bg-oracle-dark-gray flex items-center justify-center flex-shrink-0 overflow-hidden mt-0.5">
      <span className="text-white text-xs font-bold">{userInitials}</span>
    </div>
  );
}

function RAGChatUserMessage({
  message,
  scopeOptions,
}: {
  message: Message;
  scopeOptions: RAGScopeOptions | null | undefined;
}) {
  const presentation = buildUserMessagePresentation(message.text, scopeOptions, message.telemetry);
  const hasInlineChips = presentation.inlineParts.some((part) => part.type === 'chip');

  if (hasInlineChips) {
    return (
      <div className="min-w-0 max-w-full overflow-hidden">
        <div className="whitespace-pre-wrap break-words text-right text-sm leading-relaxed text-white">
          {presentation.inlineParts.map((part) =>
            part.type === 'text' ? (
              <span key={part.id} className="whitespace-pre-wrap break-words">
                {part.value}
              </span>
            ) : (
              <span
                key={part.id}
                className={`${getInlineChipClassName(getUserMessageChipClassName(part.chip.tone))} align-middle`}
                title={part.chip.label}
              >
                <SelectorChipIcon tone={part.chip.tone} />
                <span className="min-w-0 truncate">{part.chip.label}</span>
              </span>
            )
          )}
        </div>
      </div>
    );
  }

  return (
    <div className="min-w-0 max-w-full overflow-hidden">
      <div className="space-y-2 text-white">
        <div className="whitespace-pre-wrap break-words text-right text-sm leading-relaxed">
          {presentation.bodyText}
        </div>
        {presentation.selectorChips.length > 0 ? (
          <div className="flex flex-wrap justify-end gap-1.5">
            {presentation.selectorChips.map((chip) => (
              <span
                key={chip.id}
                className={getInlineChipClassName(getUserMessageChipClassName(chip.tone))}
                title={chip.label}
              >
                <SelectorChipIcon tone={chip.tone} />
                <span className="min-w-0 truncate">{chip.label}</span>
              </span>
            ))}
          </div>
        ) : null}
      </div>
    </div>
  );
}

function RAGChatMarkdownMessage({ text }: { text: string }) {
  return (
    <div className="min-w-0 max-w-full overflow-hidden">
      <div className="max-w-none min-w-0 space-y-2 break-words text-sm leading-relaxed">
        <ReactMarkdown remarkPlugins={[remarkGfm]} components={CHAT_MARKDOWN_COMPONENTS}>
          {text}
        </ReactMarkdown>
      </div>
    </div>
  );
}

function RAGChatSourceChips({
  citedSources,
  onOpenSourcePreview,
}: {
  citedSources: Source[] | undefined;
  onOpenSourcePreview: (source: Source) => void;
}) {
  if (!citedSources || citedSources.length === 0) return null;

  return (
    <div className="mt-2 pt-1.5 space-y-2">
      <div>
        <p className="text-[10px] font-semibold text-oracle-light-gray uppercase tracking-wide mb-1.5">
          Cited in answer
        </p>
        <div className="flex flex-wrap gap-1.5">
          {citedSources.map((source, index) => {
            const previewTarget = resolveSourcePreviewTarget(source);
            const canOpenPreview = Boolean(previewTarget?.file_id && previewTarget?.page_number);
            const resolvedPageNumber = Number(previewTarget?.page_number ?? source.page_number ?? 0);
            const normalizedPageNumber =
              Number.isFinite(resolvedPageNumber) && resolvedPageNumber > 0
                ? resolvedPageNumber
                : undefined;
            const sourceLabel = String(source.name || '').trim() || `page ${normalizedPageNumber ?? '?'}`;

            return (
              <button
                key={`cited-${source.doc_id}-${index}`}
                type="button"
                className={`inline-flex items-center gap-1 px-2 py-0.5 rounded-full border text-[10px] max-w-[200px] transition-colors ${
                  canOpenPreview
                    ? 'bg-gray-100 border-gray-300 text-gray-700 hover:bg-gray-200'
                    : 'bg-gray-50 border-gray-200 text-gray-500 cursor-default'
                }`}
                title={sourceLabel}
                onClick={() => {
                  if (previewTarget) {
                    onOpenSourcePreview(previewTarget);
                  }
                }}
                disabled={!canOpenPreview}
              >
                <svg className="w-2.5 h-2.5 flex-shrink-0 text-oracle-light-gray" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z" />
                </svg>
                <span className="truncate">{sourceLabel}</span>
              </button>
            );
          })}
        </div>
      </div>
    </div>
  );
}

function RAGChatMessageActions({
  message,
  messageIndex,
  copiedMessageId,
  messageFeedback,
  onCopyAssistantAnswer,
  onMessageFeedback,
}: Pick<
  RAGChatMessageListProps,
  'copiedMessageId' | 'messageFeedback' | 'onCopyAssistantAnswer' | 'onMessageFeedback'
> & {
  message: Message;
  messageIndex: number;
}) {
  return (
    <div className="-mt-1 px-1">
      <div className="inline-flex items-center gap-2">
        <button
          type="button"
          className={`inline-flex items-center justify-center transition-colors ${
            copiedMessageId === message.messageId
              ? 'text-emerald-600'
              : 'text-oracle-medium-gray hover:text-oracle-dark-gray'
          } hover:drop-shadow-[0_2px_4px_rgba(0,0,0,0.25)]`}
          title="Copy answer"
          aria-label="Copy answer"
          onClick={() => void onCopyAssistantAnswer(message, messageIndex)}
        >
          <svg className="w-[15px] h-[15px]" fill="currentColor" viewBox="0 0 24 24" xmlns="http://www.w3.org/2000/svg">
            <path d="M21,8H9A1,1,0,0,0,8,9V21a1,1,0,0,0,1,1H21a1,1,0,0,0,1-1V9A1,1,0,0,0,21,8ZM20,20H10V10H20ZM6,15a1,1,0,0,1-1,1H3a1,1,0,0,1-1-1V3A1,1,0,0,1,3,2H15a1,1,0,0,1,1,1V5a1,1,0,0,1-2,0V4H4V14H5A1,1,0,0,1,6,15Z" />
          </svg>
        </button>
        <button
          type="button"
          className={`inline-flex items-center justify-center transition-colors ${
            messageFeedback[message.messageId] === 'up'
              ? 'text-emerald-600'
              : 'text-oracle-medium-gray hover:text-oracle-dark-gray'
          } hover:drop-shadow-[0_2px_4px_rgba(0,0,0,0.25)]`}
          title="Helpful response"
          aria-label="Mark response as helpful"
          onClick={() => onMessageFeedback(message, messageIndex, 'up')}
        >
          <svg className="w-[15px] h-[15px]" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path
              strokeLinecap="round"
              strokeLinejoin="round"
              strokeWidth={1.8}
              d="M14 9V5a3 3 0 00-3-3l-1 5-3 4v10h10.5a2.5 2.5 0 002.45-2l1-7A2.5 2.5 0 0018.5 9H14z"
            />
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.8} d="M7 11H4a1 1 0 00-1 1v8a1 1 0 001 1h3" />
          </svg>
        </button>
        <button
          type="button"
          className={`inline-flex items-center justify-center transition-colors ${
            messageFeedback[message.messageId] === 'down'
              ? 'text-rose-600'
              : 'text-oracle-medium-gray hover:text-oracle-dark-gray'
          } hover:drop-shadow-[0_2px_4px_rgba(0,0,0,0.25)]`}
          title="Not helpful response"
          aria-label="Mark response as not helpful"
          onClick={() => onMessageFeedback(message, messageIndex, 'down')}
        >
          <svg className="w-[15px] h-[15px] rotate-180" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path
              strokeLinecap="round"
              strokeLinejoin="round"
              strokeWidth={1.8}
              d="M14 9V5a3 3 0 00-3-3l-1 5-3 4v10h10.5a2.5 2.5 0 002.45-2l1-7A2.5 2.5 0 0018.5 9H14z"
            />
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.8} d="M7 11H4a1 1 0 00-1 1v8a1 1 0 001 1h3" />
          </svg>
        </button>
      </div>
    </div>
  );
}

function RAGChatLoadingMessage({
  loadingElapsedSeconds,
  ...identityProps
}: AssistantIdentityProps & {
  loadingElapsedSeconds: number;
}) {
  return (
    <div className="flex gap-2.5 flex-row">
      <RAGChatAssistantAvatar {...identityProps} />
      <div className="flex flex-col gap-1">
        <div className="flex items-center gap-2 px-1">
          <span className="text-[11px] font-semibold text-oracle-medium-gray">
            {identityProps.assistantDisplayName}
          </span>
          <span className="text-[10px] text-oracle-light-gray">{`${loadingElapsedSeconds} seg`}</span>
        </div>
        <div className="rounded-2xl rounded-tl-sm px-4 py-3 bg-white border border-gray-200 shadow-sm flex items-center gap-1.5">
          <span className="w-1.5 h-1.5 rounded-full bg-oracle-light-gray animate-bounce" style={{ animationDelay: '0ms' }} />
          <span className="w-1.5 h-1.5 rounded-full bg-oracle-light-gray animate-bounce" style={{ animationDelay: '150ms' }} />
          <span className="w-1.5 h-1.5 rounded-full bg-oracle-light-gray animate-bounce" style={{ animationDelay: '300ms' }} />
        </div>
      </div>
    </div>
  );
}

export function RAGChatMessageList({
  listRef,
  loadingConversation,
  messages,
  loading,
  loadingElapsedSeconds,
  assistantDisplayName,
  assistantAvatarUrl,
  assistantAvatarLetter,
  showAssistantAvatarImage,
  userInitials,
  userFirstName,
  scopeOptions,
  copiedMessageId,
  messageFeedback,
  onAssistantAvatarImageError,
  onOpenSourcePreview,
  onCopyAssistantAnswer,
  onMessageFeedback,
}: RAGChatMessageListProps) {
  const assistantIdentity = {
    assistantDisplayName,
    assistantAvatarUrl,
    assistantAvatarLetter,
    showAssistantAvatarImage,
    onAssistantAvatarImageError,
  };

  return (
    <div
      ref={listRef}
      className="chat-message-list flex-1 min-h-0 overflow-y-auto overflow-x-hidden p-4 flex flex-col gap-5 chat-scrollbar"
    >
      {loadingConversation ? (
        <div className="flex items-center justify-center h-full">
          <LoadingState size="sm" label="Loading chat..." textClassName="text-oracle-medium-gray" />
        </div>
      ) : (
        <>
          {messages.map((message, messageIndex) => {
            const assistantHasMarkdownTable =
              message.role === 'assistant' && messageContainsMarkdownTable(message.text);
            const messageWidthClass =
              message.role === 'assistant' && assistantHasMarkdownTable ? 'flex-1 max-w-full' : 'max-w-[85%]';
            const renderedMessageText =
              message.role === 'user'
                ? buildUserMessagePresentation(message.text, scopeOptions, message.telemetry).bodyText
                : message.text;

            return (
              <div
                key={message.messageId}
                className={`flex min-w-0 gap-2.5 ${message.role === 'user' ? 'flex-row-reverse' : 'flex-row'}`}
              >
                {message.role === 'assistant' ? (
                  <RAGChatAssistantAvatar {...assistantIdentity} />
                ) : (
                  <RAGChatUserAvatar userInitials={userInitials} />
                )}

                <div
                  className={`flex min-w-0 flex-col gap-1 ${messageWidthClass} ${
                    message.role === 'user' ? 'items-end' : 'items-start'
                  }`}
                >
                  <div className="flex items-center gap-2 px-1">
                    <span className="text-[11px] font-semibold text-oracle-medium-gray">
                      {message.role === 'assistant' ? assistantDisplayName : userFirstName}
                    </span>
                    <span className="text-[10px] text-oracle-light-gray">{formatTime(message.timestamp)}</span>
                  </div>

                  <div
                    className={`max-w-full rounded-2xl px-4 py-2.5 text-sm leading-relaxed shadow-sm ${
                      message.role === 'user'
                        ? 'bg-oracle-dark-gray text-white rounded-tr-sm'
                        : message.error
                        ? 'bg-red-50 text-red-700 border border-red-200 rounded-tl-sm'
                        : `chat-assistant-message bg-white text-oracle-dark-gray border border-gray-200 rounded-tl-sm overflow-hidden ${
                            assistantHasMarkdownTable ? 'w-full' : ''
                          }`
                    }`}
                  >
                    {message.role === 'user' ? (
                      <RAGChatUserMessage message={message} scopeOptions={scopeOptions} />
                    ) : (
                      <RAGChatMarkdownMessage text={renderedMessageText} />
                    )}
                    {message.role === 'assistant' && !message.error && formatInferredScopeLabel(message.telemetry) && (
                      <div className="mt-2 inline-flex items-center rounded-full border border-amber-200 bg-amber-50 px-2.5 py-1 text-[10px] font-medium text-amber-800">
                        {formatInferredScopeLabel(message.telemetry)}
                      </div>
                    )}
                    {message.role === 'assistant' && (
                      <RAGChatSourceChips
                        citedSources={message.citedSources}
                        onOpenSourcePreview={onOpenSourcePreview}
                      />
                    )}
                  </div>

                  {message.role === 'assistant' && !message.error && (
                    <RAGChatMessageActions
                      message={message}
                      messageIndex={messageIndex}
                      copiedMessageId={copiedMessageId}
                      messageFeedback={messageFeedback}
                      onCopyAssistantAnswer={onCopyAssistantAnswer}
                      onMessageFeedback={onMessageFeedback}
                    />
                  )}
                </div>
              </div>
            );
          })}

          {loading && (
            <RAGChatLoadingMessage
              {...assistantIdentity}
              loadingElapsedSeconds={loadingElapsedSeconds}
            />
          )}
        </>
      )}
    </div>
  );
}
