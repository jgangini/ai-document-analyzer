import { useState } from 'react';
import api from '../../services/apiClient';

const DEFAULT_DSN = 'ora26ai_medium';
const PREFERRED_DSN_SUFFIXES = ['_medium', '_high', '_tp', '_low', '_tpurgent'];

function pickPreferredDsn(aliases: string[], selectedDsn?: string): string {
  const normalizedSelectedDsn = (selectedDsn || '').trim();
  if (normalizedSelectedDsn && aliases.includes(normalizedSelectedDsn)) {
    return normalizedSelectedDsn;
  }

  for (const suffix of PREFERRED_DSN_SUFFIXES) {
    const match = aliases.find((alias) => alias.toLowerCase().endsWith(suffix));
    if (match) {
      return match;
    }
  }

  return normalizedSelectedDsn || aliases[0] || DEFAULT_DSN;
}

interface Props {
  data: any;
  onNext: (data: any) => void;
  onBack: () => void;
  isFirstStep: boolean;
  isLastStep: boolean;
}

export function DatabaseConfigStep({ onNext, onBack: _onBack }: Props) {
  const [walletFile, setWalletFile] = useState<File | null>(null);
  const [walletPassword, setWalletPassword] = useState('');
  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const [dsn, setDsn] = useState(DEFAULT_DSN);
  const [dsnOptions, setDsnOptions] = useState<string[]>([]);
  const [walletPath, setWalletPath] = useState('');
  const [testing, setTesting] = useState(false);
  const [testResult, setTestResult] = useState<any>(null);
  const [uploading, setUploading] = useState(false);
  const [uploadError, setUploadError] = useState('');
  const [dragActive, setDragActive] = useState(false);
  const [showPassword, setShowPassword] = useState(false);
  const [showWalletPassword, setShowWalletPassword] = useState(false);

  const buildUploadErrorMessage = (error: any): string => {
    const status = error?.response?.status;
    const responseData = error?.response?.data;
    let detail = '';

    if (typeof responseData === 'string') {
      detail = responseData;
    } else if (responseData?.detail) {
      detail = String(responseData.detail);
    } else if (responseData?.message) {
      detail = String(responseData.message);
    } else if (error?.message) {
      detail = String(error.message);
    }

    if (status && detail) return `(${status}) ${detail}`;
    if (detail) return detail;
    return 'Error al subir wallet';
  };

  const loadWalletDsns = async (uploadedWalletPath: string) => {
    try {
      const response = await api.post('/setup/list-wallet-dsns', {
        wallet_path: uploadedWalletPath,
      });
      const aliases = Array.isArray(response.data?.dsns) ? response.data.dsns : [];
      if (!aliases.length) {
        setDsnOptions([]);
        setUploadError('Wallet uploaded, but no TNS aliases were found in tnsnames.ora');
        return;
      }
      setDsnOptions(aliases);
      setDsn(pickPreferredDsn(aliases, response.data?.selected_dsn));
    } catch (error: any) {
      setDsnOptions([]);
      const detail = error?.response?.data?.detail || 'Could not read tnsnames.ora aliases';
      setUploadError(`Wallet uploaded, but aliases could not be loaded: ${detail}`);
    }
  };

  const uploadWallet = async (file: File) => {
    setUploadError('');
    setWalletPath('');
    setWalletFile(null);
    setDsnOptions([]);
    setUploading(true);
    const formData = new FormData();
    formData.append('file', file);

    try {
      const response = await api.post('/setup/upload-wallet', formData, {
        headers: { 'Content-Type': 'multipart/form-data' },
        timeout: 30000,
      });
      const uploadedWalletPath = response.data.wallet_path;
      setWalletPath(uploadedWalletPath);
      setWalletFile(file);
      const aliases = Array.isArray(response.data?.dsns) ? response.data.dsns : [];
      if (aliases.length) {
        setDsnOptions(aliases);
        setDsn(pickPreferredDsn(aliases, response.data?.selected_dsn));
      } else {
        await loadWalletDsns(uploadedWalletPath);
      }
    } catch (error: any) {
      const errorMessage = buildUploadErrorMessage(error);
      setUploadError(errorMessage);
      alert(`Error: ${errorMessage}`);
      setWalletPath('');
      setWalletFile(null);
    } finally {
      setUploading(false);
    }
  };

  const handleDrag = (e: React.DragEvent) => {
    e.preventDefault();
    e.stopPropagation();
    if (e.type === "dragenter" || e.type === "dragover") {
      setDragActive(true);
    } else if (e.type === "dragleave") {
      setDragActive(false);
    }
  };

  const handleDrop = (e: React.DragEvent) => {
    e.preventDefault();
    e.stopPropagation();
    setDragActive(false);
    
    if (e.dataTransfer.files && e.dataTransfer.files[0]) {
      const file = e.dataTransfer.files[0];
      if (file.name.toLowerCase().endsWith('.zip')) {
        uploadWallet(file);
      } else {
        setUploadError('Please upload a ZIP file (.zip)');
        alert('Please upload a ZIP file');
      }
    }
  };

  const handleFileChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    if (e.target.files && e.target.files[0]) {
      const selectedFile = e.target.files[0];
      if (!selectedFile.name.toLowerCase().endsWith('.zip')) {
        setUploadError('Please upload a ZIP file (.zip)');
        alert('Please upload a ZIP file');
      } else {
        uploadWallet(selectedFile);
      }
    }
    // Allow selecting the same file again after a failed upload.
    e.target.value = '';
  };

  const handleTestConnection = async () => {
    if (!walletPath) {
      alert('Please upload the wallet file first');
      return;
    }
    if (!walletPassword.trim()) {
      alert('Wallet password is required');
      return;
    }

    setTesting(true);
    setTestResult(null);

    try {
      const payload = {
        wallet_path: walletPath,
        wallet_password: walletPassword,
        user: username,
        password: password,
        dsn: dsn,
      };

      const response = await api.post('/setup/test-db', payload);
      await api.post('/setup/save-db-runtime', payload);

      setTestResult({
        success: true,
        ...response.data,
        message: 'Database connection successful and saved for runtime',
      });
    } catch (error: any) {
      setTestResult({
        success: false,
        message: error.response?.data?.detail || 'Connection error',
      });
    } finally {
      setTesting(false);
    }
  };

  const handleNext = () => {
    if (!testResult?.success) {
      alert('Please test the connection successfully first');
      return;
    }
    onNext({
      database: {
        walletPath,
        walletPassword,
        username,
        password,
        dsn,
      },
    });
  };

  return (
    <div className="bg-white rounded-lg shadow-md p-8 max-w-4xl mx-auto">
      <h2 className="text-2xl font-semibold mb-2">Database Configuration</h2>
      
      <div className="bg-blue-50 border border-blue-200 rounded p-3 mb-6">
        <div className="flex items-start gap-2">
          <svg className="w-4 h-4 text-blue-600 flex-shrink-0 mt-0.5" fill="currentColor" viewBox="0 0 20 20">
            <path fillRule="evenodd" d="M18 10a8 8 0 11-16 0 8 8 0 0116 0zm-7-4a1 1 0 11-2 0 1 1 0 012 0zM9 9a1 1 0 000 2v3a1 1 0 001 1h1a1 1 0 100-2v-3a1 1 0 00-1-1H9z" clipRule="evenodd"></path>
          </svg>
          <div className="text-xs text-blue-800">
            <strong>Configure a 26ai database connection for storage and search.</strong>
            <br />
            The details below have been pre-populated with the local Oracle Database 26ai Free container.
            <br />
            Later these can be changed to install to a production ready database.
          </div>
        </div>
      </div>

      {/* Wallet Upload */}
      <div className="mb-6">
        <label className="block text-sm font-medium mb-1">Wallet ZIP</label>
        <div
          className={`py-4 px-6 border-2 border-dashed rounded-lg text-center transition-all cursor-pointer ${
            dragActive
              ? 'border-oracle-red bg-red-50'
              : 'border-gray-300 bg-gray-50 hover:bg-gray-100'
          }`}
          onDragEnter={handleDrag}
          onDragLeave={handleDrag}
          onDragOver={handleDrag}
          onDrop={handleDrop}
        >
          {uploading ? (
            <div className="text-gray-600">
              <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-oracle-red mx-auto mb-2"></div>
              <div>Uploading wallet...</div>
            </div>
          ) : (
            <>
              <div className="text-gray-600 mb-1">
                <strong>Drag and Drop</strong>
              </div>
              <div className="text-sm text-gray-500 mb-1">Select a file or drop one here</div>
              <input
                id="wallet-upload"
                type="file"
                accept=".zip"
                onChange={handleFileChange}
                className="hidden"
              />
              <label
                htmlFor="wallet-upload"
                className="text-oracle-blue-link hover:underline text-sm cursor-pointer"
              >
                Select file
              </label>
            </>
          )}
        </div>
        {walletFile && (
          <div className="mt-2 flex items-center justify-between p-2 bg-gray-50 rounded border border-gray-200">
            <span className="text-sm text-gray-600">Selected File: {walletFile.name}</span>
            <button
              onClick={() => {
                setWalletFile(null);
                setWalletPath('');
              }}
              className="text-red-600 hover:text-red-800 text-xl leading-none"
            >
              ✕
            </button>
          </div>
        )}
        
        {walletPath && (
          <p className="mt-2 text-sm text-green-600">✓ Wallet uploaded successfully</p>
        )}

        {uploadError && (
          <p className="mt-2 text-sm text-red-600">✕ {uploadError}</p>
        )}
      </div>

      {/* Connection Alias + Wallet Password */}
      {walletPath && (
        <div className="grid grid-cols-2 gap-4 mb-4">
          <div>
            <label className="block text-sm font-medium mb-1">Connection (TNS alias) *</label>
            {dsnOptions.length ? (
              <select
                value={dsn}
                onChange={(e) => setDsn(e.target.value)}
                className="input-oracle w-full"
              >
                {dsnOptions.map((alias) => (
                  <option key={alias} value={alias}>
                    {alias}
                  </option>
                ))}
              </select>
            ) : (
              <input
                type="text"
                value={dsn}
                onChange={(e) => setDsn(e.target.value)}
                className="input-oracle w-full"
                placeholder={DEFAULT_DSN}
              />
            )}
            <p className="text-xs text-gray-500 mt-1">
              Alias loaded from <code>tnsnames.ora</code>.
            </p>
          </div>

          <div>
            <label className="block text-sm font-medium mb-1">Wallet Password *</label>
            <div className="relative">
              <input
                type={showWalletPassword ? 'text' : 'password'}
                value={walletPassword}
                onChange={(e) => setWalletPassword(e.target.value)}
                className="input-oracle w-full pr-10"
                placeholder="Wallet password"
              />
              <button
                type="button"
                onClick={() => setShowWalletPassword((prev) => !prev)}
                className="absolute right-3 top-1/2 -translate-y-1/2 text-gray-400 hover:text-gray-600"
                title={showWalletPassword ? 'Hide password' : 'Show password'}
                aria-label={showWalletPassword ? 'Hide password' : 'Show password'}
              >
                {showWalletPassword ? (
                  <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M13.875 18.825A10.05 10.05 0 0112 19c-4.478 0-8.268-2.943-9.543-7a9.97 9.97 0 011.563-3.029m5.858.908a3 3 0 114.243 4.243M9.878 9.878l4.242 4.242M9.88 9.88l-3.29-3.29m7.532 7.532l3.29 3.29M3 3l3.59 3.59m0 0A9.953 9.953 0 0112 5c4.478 0 8.268 2.943 9.543 7a10.025 10.025 0 01-4.132 5.411m0 0L21 21" />
                  </svg>
                ) : (
                  <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15 12a3 3 0 11-6 0 3 3 0 016 0z" />
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M2.458 12C3.732 7.943 7.523 5 12 5c4.478 0 8.268 2.943 9.542 7-1.274 4.057-5.064 7-9.542 7-4.477 0-8.268-2.943-9.542-7z" />
                  </svg>
                )}
              </button>
            </div>
            <p className="text-xs text-gray-500 mt-1">
              Required for OCI wallet downloaded from the console.
            </p>
          </div>
        </div>
      )}

      {/* Connection Details */}
      <div className="grid grid-cols-2 gap-4 mb-6">
        <div>
          <label className="block text-sm font-medium mb-1">Username *</label>
          <input
            type="text"
            value={username}
            onChange={(e) => setUsername(e.target.value)}
            className="input-oracle"
            placeholder="app_doc"
          />
        </div>

        <div>
          <label className="block text-sm font-medium mb-1">Password *</label>
          <div className="relative">
            <input
              type={showPassword ? 'text' : 'password'}
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              className="input-oracle pr-10"
            />
            <button
              type="button"
              onClick={() => setShowPassword((prev) => !prev)}
              className="absolute right-3 top-1/2 -translate-y-1/2 text-gray-400 hover:text-gray-600"
              title={showPassword ? 'Hide password' : 'Show password'}
              aria-label={showPassword ? 'Hide password' : 'Show password'}
            >
              {showPassword ? (
                <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M13.875 18.825A10.05 10.05 0 0112 19c-4.478 0-8.268-2.943-9.543-7a9.97 9.97 0 011.563-3.029m5.858.908a3 3 0 114.243 4.243M9.878 9.878l4.242 4.242M9.88 9.88l-3.29-3.29m7.532 7.532l3.29 3.29M3 3l3.59 3.59m0 0A9.953 9.953 0 0112 5c4.478 0 8.268 2.943 9.543 7a10.025 10.025 0 01-4.132 5.411m0 0L21 21" />
                </svg>
              ) : (
                <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15 12a3 3 0 11-6 0 3 3 0 016 0z" />
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M2.458 12C3.732 7.943 7.523 5 12 5c4.478 0 8.268 2.943 9.542 7-1.274 4.057-5.064 7-9.542 7-4.477 0-8.268-2.943-9.542-7z" />
                </svg>
              )}
            </button>
          </div>
        </div>
      </div>

      {testResult && (
        <div
          className={`p-3 rounded mb-6 text-sm ${
            testResult.success ? 'bg-green-50 text-green-800 border border-green-200' : 'bg-red-50 text-red-800 border border-red-200'
          }`}
        >
          {testResult.message}
        </div>
      )}

      {/* Navigation */}
      <div className="flex justify-between mt-8">
        <button
          onClick={handleTestConnection}
          disabled={testing || !walletPath || !walletPassword.trim() || !username || !password || !dsn}
          className="btn-secondary flex items-center gap-2"
        >
          {testing ? (
            <div className="animate-spin rounded-full h-4 w-4 border-2 border-gray-400 border-t-transparent"></div>
          ) : (
            <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 12l2 2 4-4m6 2a9 9 0 11-18 0 9 9 0 0118 0z" />
            </svg>
          )}
          {testing ? 'Testing...' : 'Test connection'}
        </button>
        <button
          onClick={handleNext}
          disabled={!testResult?.success}
          className="btn-primary flex items-center gap-2"
        >
          <span>Next</span>
          <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 5l7 7-7 7" />
          </svg>
        </button>
      </div>
    </div>
  );
}
