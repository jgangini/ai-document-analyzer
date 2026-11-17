import { useState } from 'react';
import api from '../../services/apiClient';
import { useToast } from '../../context/ToastContext';
import { APP_DISPLAY_NAME } from '../../config/branding';

interface Props {
  data: any;
  onNext: (data: any) => void;
  onBack: () => void;
  isFirstStep: boolean;
  isLastStep: boolean;
}

export function InstallationStep({ data, onNext, onBack: _onBack }: Props) {
  const { showToast } = useToast();
  const [installing, setInstalling] = useState(false);
  const [installResult, setInstallResult] = useState<any>(null);
  const [logs, setLogs] = useState<string[]>([]);

  const appendLogs = (entries: string[]) => {
    setLogs((prev) => {
      const next = [...prev];
      for (const entry of entries) {
        if (!entry.trim()) continue;
        if (next[next.length - 1] === entry) continue;
        next.push(entry);
      }
      return next;
    });
  };

  const buildInstallErrorMessage = (error: any): string => {
    const detail = error?.response?.data?.detail;
    if (typeof detail === 'string' && detail.trim()) return detail;
    if (detail && typeof detail === 'object') {
      if (Array.isArray(detail.errors) && detail.errors.length) {
        return detail.errors.map((entry: any) => `${entry.file}: ${entry.error}`).join(' | ');
      }
      if (typeof detail.message === 'string' && detail.message.trim()) return detail.message;
    }
    return error?.message || 'Installation failed';
  };

  const handleInstall = async () => {
    setInstalling(true);
    setInstallResult(null);
    setLogs([
      'Resolving database configuration...',
      'Discovering scripts from apps/backend/db/bootstrap/sql/*.sql ...',
    ]);

    try {
      const dbConfig = data?.database;
      if (!dbConfig?.walletPath || !dbConfig?.walletPassword || !dbConfig?.username || !dbConfig?.password || !dbConfig?.dsn) {
        throw new Error('Database configuration is incomplete. Please go back and re-test the connection.');
      }

      // 1. Execute SQL scripts dynamically from apps/backend/db/bootstrap/sql
      appendLogs([
        'This may take some time.',
        '-----------------------------------------------------------',
      ]);

      const response = await api.post('/setup/installation', {
        admin_email: data.adminEmail,
        admin_password: data.adminPassword,
        wallet_path: dbConfig.walletPath,
        wallet_password: dbConfig.walletPassword,
        user: dbConfig.username,
        password: dbConfig.password,
        dsn: dbConfig.dsn,
      });
      const discovered = Array.isArray(response.data?.discovered) ? response.data.discovered : [];
      const executed = Array.isArray(response.data?.executed) ? response.data.executed : [];
      const errors = Array.isArray(response.data?.errors) ? response.data.errors : [];

      if (executed.length) {
        appendLogs([
          '-----------------------------------------------------------',
          'Installed setup scripts:',
        ]);
        executed.forEach((script: string) => {
          appendLogs([`  - ${script}`]);
        });
        appendLogs([`✓ Total installed scripts: ${executed.length}`]);
      } else if (discovered.length) {
        appendLogs([`No scripts were executed. Discovered: ${discovered.length}`]);
      }

      // 2. Check execution errors
      if (errors.length > 0) {
        appendLogs([
          '-----------------------------------------------------------',
          '✗ Database setup failed with errors:',
        ]);
        errors.forEach((err: any) => {
          appendLogs([`  - ${err.file}: ${err.error}`]);
        });
        throw new Error('Database setup failed');
      }

      // 3. Administrator user created
      appendLogs([
        '-----------------------------------------------------------',
        `✓ Administrator user created: ${data.adminEmail}`,
        '-----------------------------------------------------------',
        '✓ Installation completed successfully!',
      ]);
      
      setInstallResult({ success: true, ...response.data });
      showToast('Installation completed successfully!');
    } catch (error: any) {
      const errorMsg = buildInstallErrorMessage(error);
      appendLogs([`✗ Error: ${errorMsg}`]);
      setInstallResult({
        success: false,
        message: errorMsg,
      });
      showToast(errorMsg);
    } finally {
      setInstalling(false);
    }
  };

  const handleNext = () => {
    if (!installResult?.success) {
      alert('You must complete the installation successfully first');
      return;
    }
    onNext({ installation: installResult });
  };

  return (
    <div className="bg-white rounded-lg shadow-md p-8 max-w-4xl mx-auto">
      <h2 className="text-2xl font-semibold mb-6">Installation</h2>

      <div className="bg-blue-50 border border-blue-200 rounded p-3 mb-6">
        <div className="flex items-start gap-2">
          <svg className="w-4 h-4 text-blue-600 flex-shrink-0 mt-0.5" fill="currentColor" viewBox="0 0 20 20">
            <path fillRule="evenodd" d="M18 10a8 8 0 11-16 0 8 8 0 0116 0zm-7-4a1 1 0 11-2 0 1 1 0 012 0zM9 9a1 1 0 000 2v3a1 1 0 001 1h1a1 1 0 100-2v-3a1 1 0 00-1-1H9z" clipRule="evenodd"></path>
          </svg>
          <div className="text-xs text-blue-800">
            <strong>Install {APP_DISPLAY_NAME} into the configured database.</strong>
            <br />
            {APP_DISPLAY_NAME} will import the database installation files into your Database instance.
          </div>
        </div>
      </div>

      {/* Install Button */}
      {!installResult && (
        <div className="mb-6">
          <button
            onClick={handleInstall}
            disabled={installing}
            className="btn-secondary flex items-center gap-2"
          >
            {installing ? (
              <div className="animate-spin rounded-full h-4 w-4 border-2 border-gray-400 border-t-transparent"></div>
            ) : (
              <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 16v1a3 3 0 003 3h10a3 3 0 003-3v-1m-4-4l-4 4m0 0l-4-4m4 4V4" />
              </svg>
            )}
            {installing ? 'Installing...' : 'Install'}
          </button>
        </div>
      )}

      {/* Installation Log */}
      {logs.length > 0 && (
        <div className="mb-6">
          <h3 className="text-sm font-semibold mb-2">Installation Log</h3>
          <div className="p-4 bg-gray-50 border border-gray-200 rounded font-mono text-xs max-h-96 overflow-y-auto">
            {logs.map((log, index) => (
              <div key={index} className="text-gray-700 mb-1">
                {log}
              </div>
            ))}
          </div>
        </div>
      )}

      {installResult && installResult.success && (
        <div className="p-3 rounded mb-6 text-sm bg-green-50 text-green-800 border border-green-200">
          {installResult.message || 'Installation completed successfully!'}
        </div>
      )}

      {installResult && !installResult.success && (
        <div className="p-3 rounded mb-6 text-sm bg-red-50 text-red-800 border border-red-200">
          {installResult.message || 'Installation failed'}
        </div>
      )}

      {/* Next Button */}
      {installResult?.success && (
        <div className="flex justify-end mt-8">
          <button
            onClick={handleNext}
            className="btn-primary flex items-center gap-2"
          >
            <span>Next</span>
            <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 5l7 7-7 7" />
            </svg>
          </button>
        </div>
      )}
    </div>
  );
}
