import type { KeyboardEvent, RefObject } from 'react';

import {
  getComposerChipClassName,
  getInlineChipClassName,
  SelectorChipIcon,
  type ComposerInlinePart,
  type SelectorSuggestion,
  type SelectorSuggestionGroup,
} from './RAGChatPanel.composer';

type RAGChatComposerProps = {
  placeholder: string;
  input: string;
  loading: boolean;
  inputRef: RefObject<HTMLTextAreaElement>;
  inlineParts: ComposerInlinePart[];
  showOverlay: boolean;
  showSuggestions: boolean;
  suggestionGroups: SelectorSuggestionGroup[];
  selectedSuggestionIndex: number;
  onInputChange: (value: string) => void;
  onInputFocus: () => void;
  onInputBlur: () => void;
  onCaretUpdate: () => void;
  onInputKeyDown: (event: KeyboardEvent<HTMLTextAreaElement>) => void;
  onSearch: () => void;
  onApplySuggestion: (suggestion: SelectorSuggestion) => void;
};

export function RAGChatComposer({
  placeholder,
  input,
  loading,
  inputRef,
  inlineParts,
  showOverlay,
  showSuggestions,
  suggestionGroups,
  selectedSuggestionIndex,
  onInputChange,
  onInputFocus,
  onInputBlur,
  onCaretUpdate,
  onInputKeyDown,
  onSearch,
  onApplySuggestion,
}: RAGChatComposerProps) {
  let suggestionOffset = 0;

  return (
    <div className="relative w-full">
      <div className="chat-composer-surface w-full rounded-2xl border border-oracle-border bg-white px-3 py-2 shadow-sm flex items-end gap-2">
        <div className="relative min-w-0 flex-1">
          {showOverlay ? (
            <div
              aria-hidden="true"
              className="pointer-events-none absolute inset-x-0 top-0 max-h-56 overflow-hidden py-1 text-sm leading-6 text-oracle-dark-gray"
            >
              <div className="min-w-0 whitespace-pre-wrap break-words">
                {inlineParts.map((part) =>
                  part.type === 'text' ? (
                    <span key={part.id} className="whitespace-pre-wrap break-words">
                      {part.value}
                    </span>
                  ) : part.type === 'caret' ? (
                    <span
                      key={part.id}
                      className="mx-px inline-block h-5 w-px animate-pulse bg-oracle-dark-gray align-text-bottom"
                    />
                  ) : (
                    <span
                      key={part.id}
                      className={`${getInlineChipClassName(getComposerChipClassName(part.chip.tone))} align-middle`}
                      title={part.chip.label}
                    >
                      <SelectorChipIcon tone={part.chip.tone} />
                      <span className="min-w-0 truncate">{part.chip.label}</span>
                    </span>
                  )
                )}
              </div>
            </div>
          ) : null}
          <textarea
            ref={inputRef}
            rows={1}
            value={input}
            onChange={(event) => onInputChange(event.target.value)}
            onFocus={onInputFocus}
            onBlur={onInputBlur}
            onClick={onCaretUpdate}
            onKeyUp={onCaretUpdate}
            onSelect={onCaretUpdate}
            onKeyDown={onInputKeyDown}
            placeholder={placeholder}
            aria-label={placeholder}
            spellCheck={false}
            autoCorrect="off"
            autoCapitalize="off"
            autoComplete="off"
            data-gramm="false"
            data-gramm-editor="false"
            data-enable-grammarly="false"
            className={`chat-composer-input block max-h-56 min-h-8 min-w-[12rem] w-full resize-none overflow-hidden bg-transparent border-0 py-1 text-sm leading-6 outline-none ${
              showOverlay
                ? 'chat-composer-input--overlay text-transparent caret-transparent placeholder:text-transparent decoration-transparent'
                : 'text-oracle-dark-gray placeholder:text-oracle-medium-gray selection:bg-gray-200 selection:text-oracle-dark-gray'
            }`}
          />
        </div>
        <button
          type="button"
          onClick={onSearch}
          disabled={loading || !input.trim()}
          className="mb-0.5 shrink-0 p-2 rounded-full bg-oracle-red text-white hover:bg-red-700 disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
          title="Send"
          aria-label="Send"
        >
          <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
            <path d="M22 2L11 13" />
            <path d="M22 2L15 22L11 13L2 9L22 2Z" />
          </svg>
        </button>
      </div>
      {showSuggestions ? (
        <div className="chat-suggestion-menu absolute bottom-[calc(100%+0.5rem)] left-0 right-0 z-30 max-h-[min(18rem,40vh)] overflow-x-hidden overflow-y-auto rounded-2xl border border-gray-200 bg-white shadow-xl">
          {suggestionGroups.map((group) => {
            const startIndex = suggestionOffset;
            suggestionOffset += group.items.length;
            return (
              <div key={group.key} className="border-b border-gray-100 last:border-b-0">
                <div className="px-3 pt-2 text-[10px] font-semibold uppercase tracking-wide text-oracle-light-gray">
                  {group.label}
                </div>
                <div className="p-2">
                  {group.items.map((item, itemIndex) => {
                    const suggestionIndex = startIndex + itemIndex;
                    const selected = suggestionIndex === selectedSuggestionIndex;
                    return (
                      <button
                        key={item.id}
                        type="button"
                        onMouseDown={(event) => event.preventDefault()}
                        onClick={() => onApplySuggestion(item)}
                        className={`flex w-full items-start justify-between gap-3 rounded-xl px-3 py-2 text-left transition-colors ${
                          selected
                            ? 'chat-suggestion-item-selected bg-gray-100 text-oracle-dark-gray ring-1 ring-inset ring-gray-200'
                            : 'hover:bg-gray-50 text-oracle-dark-gray'
                        }`}
                      >
                        <span className="min-w-0">
                          <span className="block truncate text-xs font-semibold">{item.label}</span>
                          {item.description ? (
                            <span className="block text-[11px] text-oracle-medium-gray">{item.description}</span>
                          ) : null}
                        </span>
                        <span className="chat-suggestion-kind-badge shrink-0 rounded-full border border-gray-200 bg-gray-50 px-2 py-0.5 text-[10px] font-medium text-oracle-medium-gray">
                          {item.kind === 'file' ? 'Archivo' : item.kind === 'field' ? 'Campo' : 'Metadata'}
                        </span>
                      </button>
                    );
                  })}
                </div>
              </div>
            );
          })}
        </div>
      ) : null}
    </div>
  );
}
