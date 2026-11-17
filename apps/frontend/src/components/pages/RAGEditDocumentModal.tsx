import { useEffect, useState } from 'react';

import { ModalPortal } from '../common/ModalPortal';

export function EditDocumentModal({
  docs,
  onClose,
  onSave,
  isSaving,
}: {
  docs: any[];
  onClose: () => void;
  onSave: (data: any) => void;
  isSaving: boolean;
}) {
  const safeDocs = docs.length > 0 ? docs : [{}];
  const primaryDoc = safeDocs[0];
  const isBulkEdit = safeDocs.length > 1;
  const [accessType, setAccessType] = useState<string>(
    primaryDoc.access_profiles?.includes('private')
      ? 'private'
      : primaryDoc.access_profiles?.includes('all')
      ? 'all'
      : 'private'
  );

  useEffect(() => {
    setAccessType(
      primaryDoc.access_profiles?.includes('private')
        ? 'private'
        : primaryDoc.access_profiles?.includes('all')
        ? 'all'
        : 'private'
    );
  }, [primaryDoc]);

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    const finalProfiles: string[] = accessType === 'all' ? ['all'] : ['private'];
    onSave({ access_profiles: finalProfiles });
  };

  return (
    <ModalPortal zIndex="z-[300]" className="items-start justify-center p-4">
      <div
        className="rounded-2xl shadow-2xl overflow-hidden max-w-md w-full border-0"
        style={{
          background: 'rgba(255,255,255,0.72)',
          backdropFilter: 'blur(20px) saturate(180%)',
          WebkitBackdropFilter: 'blur(20px) saturate(180%)',
        }}
      >
        <div className="px-5 py-4 flex items-center gap-3 bg-oracle-dark-gray">
          <div className="min-w-0">
            <h2 className="text-lg font-semibold text-white">
              {isBulkEdit ? 'Edit Document Access' : 'Edit Document Access'}
            </h2>
            <p
              className="text-xs text-gray-200 truncate"
              title={
                isBulkEdit
                  ? `${safeDocs.length} selected documents`
                  : primaryDoc.original_name || primaryDoc.filename
              }
            >
              {isBulkEdit
                ? `${safeDocs.length} selected documents`
                : primaryDoc.original_name || primaryDoc.filename}
            </p>
          </div>
          <div className="ml-auto" />
          <button
            type="button"
            onClick={onClose}
            className="p-1.5 rounded-lg hover:bg-white/10 transition-colors text-gray-200"
            aria-label="Close edit document modal"
          >
            <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
            </svg>
          </button>
        </div>

        <div className="bg-white p-6">
          <form onSubmit={handleSubmit}>
          {/* Access Type */}
          <div className="mb-5">
            <label className="block text-sm font-medium text-oracle-dark-gray mb-3">Access Type</label>
            <div className="grid grid-cols-2 gap-2">
              <label
                className={`flex flex-col items-center gap-2 p-3 rounded-lg border-2 cursor-pointer transition-all ${
                  accessType === 'private'
                    ? 'border-oracle-red bg-oracle-red/5'
                    : 'border-oracle-border hover:border-oracle-red/50'
                }`}
              >
                <input
                  type="radio"
                  name="accessType"
                  value="private"
                  checked={accessType === 'private'}
                  onChange={() => setAccessType('private')}
                  className="sr-only"
                />
                <svg className={`w-6 h-6 ${accessType === 'private' ? 'text-oracle-red' : 'text-oracle-light-gray'}`} fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 15v2m-6 4h12a2 2 0 002-2v-6a2 2 0 00-2-2H6a2 2 0 00-2 2v6a2 2 0 002 2zm10-10V7a4 4 0 00-8 0v4h8z" />
                </svg>
                <span className={`text-xs font-medium ${accessType === 'private' ? 'text-oracle-red' : 'text-oracle-medium-gray'}`}>Private</span>
              </label>
              <label
                className={`flex flex-col items-center gap-2 p-3 rounded-lg border-2 cursor-pointer transition-all ${
                  accessType === 'all'
                    ? 'border-oracle-red bg-oracle-red/5'
                    : 'border-oracle-border hover:border-oracle-red/50'
                }`}
              >
                <input
                  type="radio"
                  name="accessType"
                  value="all"
                  checked={accessType === 'all'}
                  onChange={() => setAccessType('all')}
                  className="sr-only"
                />
                <svg className={`w-6 h-6 ${accessType === 'all' ? 'text-oracle-red' : 'text-oracle-light-gray'}`} fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M3.055 11H5a2 2 0 012 2v1a2 2 0 002 2 2 2 0 012 2v2.945M8 3.935V5.5A2.5 2.5 0 0010.5 8h.5a2 2 0 012 2 2 2 0 104 0 2 2 0 012-2h1.064M15 20.488V18a2 2 0 012-2h3.064M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
                </svg>
                <span className={`text-xs font-medium ${accessType === 'all' ? 'text-oracle-red' : 'text-oracle-medium-gray'}`}>All Users</span>
              </label>
            </div>
          </div>

          {/* Footer */}
          <div className="-mx-6 -mb-6 mt-6 flex border-t border-gray-100">
            <button
              type="button"
              onClick={onClose}
              disabled={isSaving}
              className="flex-1 py-4 text-sm font-medium text-oracle-medium-gray transition-colors hover:bg-gray-50 disabled:cursor-not-allowed disabled:opacity-50"
            >
              Cancel
            </button>
            <div className="w-px bg-gray-100" />
            <button
              type="submit"
              disabled={isSaving}
              className="flex-1 bg-oracle-red py-4 text-sm font-semibold text-white transition-colors hover:bg-oracle-red/90 disabled:cursor-not-allowed disabled:opacity-50"
            >
              {isSaving ? 'Saving...' : 'Save'}
            </button>
          </div>
          </form>
        </div>
      </div>
    </ModalPortal>
  );
}
