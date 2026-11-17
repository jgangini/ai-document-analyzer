import React, { useState, useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import api from '../../services/apiClient';
import { useToast } from '../../context/ToastContext';

type GenAIModelOption = { id: string; display_name: string };
const DEFAULT_REGION = 'us-chicago-1';
const DEFAULT_GENAI_MODEL = 'google.gemini-2.5-flash';

function buildInferenceUrl(region: string): string {
  const normalizedRegion = (region || '').trim().toLowerCase();
  if (!normalizedRegion) {
    return '';
  }
  return `https://inference.generativeai.${normalizedRegion}.oci.oraclecloud.com`;
}

interface Props {
  data: any;
  onNext: (data: any) => void;
  onBack: () => void;
  isFirstStep: boolean;
  isLastStep: boolean;
  onSetupComplete?: () => void;
}

export function DocumentUnderstandingStep({ onBack: _onBack, onSetupComplete }: Props) {
  const navigate = useNavigate();
  const { showToast } = useToast();
  const [config, setConfig] = useState({
    compartment_id: '',
    user: '',
    fingerprint: '',
    tenancy: '',
    region: DEFAULT_REGION,
    key_file: '',
    namespace: '',
    bucket_name: 'app_doc',
    classifier_model_id: '',
    extract_actas_model_id: '',
    extract_contratos_model_id: '',
    extract_prospectos_model_id: '',
    inference_url: buildInferenceUrl(DEFAULT_REGION),
    generative_model: DEFAULT_GENAI_MODEL,
  });
  const [keyFile, setKeyFile] = useState<File | null>(null);
  const [uploadingKey, setUploadingKey] = useState(false);
  const [dragActive, setDragActive] = useState(false);
  
  const [testingDU, setTestingDU] = useState(false);
  const [testResultDU, setTestResultDU] = useState<any>(null);
  const [savingDU, setSavingDU] = useState(false);
  const [savedDU, setSavedDU] = useState(false);
  
  const [testingOS, setTestingOS] = useState(false);
  const [testResultOS, setTestResultOS] = useState<any>(null);
  const [savingOS, setSavingOS] = useState(false);
  const [savedOS, setSavedOS] = useState(false);

  const [testingGenAI, setTestingGenAI] = useState(false);
  const [testResultGenAI, setTestResultGenAI] = useState<any>(null);
  const [savingGenAI, setSavingGenAI] = useState(false);
  const [savedGenAI, setSavedGenAI] = useState(false);

  const [generativeModels, setGenerativeModels] = useState<GenAIModelOption[]>([]);
  const [loadingGenAIModels, setLoadingGenAIModels] = useState(false);

  const selectedGenerativeInList = generativeModels.some(
    (model) => model.id === config.generative_model
  );
  
  useEffect(() => {
    if (!savedDU) return;
    let cancelled = false;
    setLoadingGenAIModels(true);
    const defaultGenerativeDisplay = DEFAULT_GENAI_MODEL;

    api.get('/setup/list-genai-models')
      .then((res) => {
        if (cancelled) return;
        const genList = res.data.generative_models || [];
        setGenerativeModels(genList);
        const genDefault = genList.find((m: GenAIModelOption) =>
          m.display_name === defaultGenerativeDisplay || m.id === defaultGenerativeDisplay);
        setConfig((prev) => ({
          ...prev,
          generative_model: genDefault?.id || DEFAULT_GENAI_MODEL,
        }));
      })
      .catch(() => {
        if (cancelled) return;
        setGenerativeModels([]);
        setConfig((prev) => ({
          ...prev,
          generative_model: DEFAULT_GENAI_MODEL,
        }));
      })
      .finally(() => {
        if (!cancelled) setLoadingGenAIModels(false);
      });
    return () => { cancelled = true; };
  }, [savedDU]);
  
  const uploadKeyFile = async (file: File) => {
    setUploadingKey(true);
    const formData = new FormData();
    formData.append('file', file);
    try {
      const response = await api.post('/setup/upload-key', formData, {
        headers: { 'Content-Type': 'multipart/form-data' },
      });
      setConfig({ ...config, key_file: response.data.key_path });
      setKeyFile(file);
    } catch (error: any) {
      alert(`Error: ${error.response?.data?.detail || 'Error uploading key'}`);
      setKeyFile(null);
    } finally {
      setUploadingKey(false);
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
      if (file.name.endsWith('.pem')) {
        uploadKeyFile(file);
      } else {
        alert('Please upload a PEM file');
      }
    }
  };

  const handleKeyFileChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    if (e.target.files && e.target.files[0]) {
      uploadKeyFile(e.target.files[0]);
    }
  };

  const handleTestDU = async () => {
    setTestingDU(true);
    setTestResultDU(null);
    try {
      const response = await api.post('/setup/test-oci', config);
      setTestResultDU({ success: true, ...response.data });
    } catch (error: any) {
      setTestResultDU({
        success: false,
        message: error.response?.data?.detail || 'OCI connection failed',
      });
    } finally {
      setTestingDU(false);
    }
  };

  const handleSaveDU = async () => {
    if (!testResultDU?.success) {
      alert('Please test the connection successfully first');
      return;
    }

    setSavingDU(true);
    try {
      await api.post('/setup/save-oci-config', config);
      setSavedDU(true);
    } catch (error: any) {
      alert(`Error: ${error.response?.data?.detail || 'Error saving configuration'}`);
    } finally {
      setSavingDU(false);
    }
  };

  const handleTestOS = async () => {
    if (!savedDU) {
      alert('Please save API Key configuration first');
      return;
    }

    setTestingOS(true);
    setTestResultOS(null);
    try {
      const response = await api.post('/setup/test-object-storage', {
        namespace: config.namespace,
        bucket_name: config.bucket_name,
      });
      setTestResultOS({ success: true, ...response.data });
    } catch (error: any) {
      setTestResultOS({
        success: false,
        message: error.response?.data?.detail || 'Object Storage validation failed',
      });
    } finally {
      setTestingOS(false);
    }
  };

  const handleSaveOS = async () => {
    if (!testResultOS?.success) {
      alert('Please test the connection successfully first');
      return;
    }

    setSavingOS(true);
    try {
      await api.post('/setup/save-oci-config', config);
      setSavedOS(() => true);
    } catch (error: any) {
      alert(`Error: ${error.response?.data?.detail || 'Error saving configuration'}`);
    } finally {
      setSavingOS(false);
    }
  };

  const handleTestGenAI = async () => {
    setTestingGenAI(true);
    setTestResultGenAI(null);
    try {
      const response = await api.post('/setup/test-generative-ai', {
        inference_url: config.inference_url,
        generative_model: config.generative_model,
      });
      setTestResultGenAI({ success: true, ...response.data });
    } catch (error: any) {
      setTestResultGenAI({
        success: false,
        message: error.response?.data?.detail || 'Generative AI validation failed',
      });
    } finally {
      setTestingGenAI(false);
    }
  };

  const handleSaveGenAI = async () => {
    if (!testResultGenAI?.success) {
      alert('Please test the connection successfully first');
      return;
    }

    setSavingGenAI(true);
    try {
      await api.post('/setup/save-generative-ai-config', {
        inference_url: config.inference_url,
        generative_model: config.generative_model,
      });
      setSavedGenAI(true);
    } catch (error: any) {
      alert(`Error: ${error.response?.data?.detail || 'Error saving configuration'}`);
    } finally {
      setSavingGenAI(false);
    }
  };

  const handleFinish = async () => {
    if (!savedDU || !savedOS || !savedGenAI) {
      alert('Please save all configurations first');
      return;
    }

    try {
      await api.post('/setup/complete');
      showToast('Setup completed successfully! You can now log in to the application.');
      if (onSetupComplete) {
        onSetupComplete();
      }
      navigate('/login');
    } catch (error: any) {
      showToast(error.response?.data?.detail || 'Error completing setup');
    }
  };

  return (
    <div className="bg-white rounded-lg shadow-md p-8">
      <h2 className="text-2xl font-semibold mb-2">OCI Services Configuration</h2>
      
      <div className="bg-blue-50 border border-blue-200 rounded p-3 mb-6">
        <div className="flex items-start gap-2">
          <svg className="w-4 h-4 text-blue-600 flex-shrink-0 mt-0.5" fill="currentColor" viewBox="0 0 20 20">
            <path fillRule="evenodd" d="M18 10a8 8 0 11-16 0 8 8 0 0116 0zm-7-4a1 1 0 11-2 0 1 1 0 012 0zM9 9a1 1 0 000 2v3a1 1 0 001 1h1a1 1 0 100-2v-3a1 1 0 00-1-1H9z" clipRule="evenodd"></path>
          </svg>
          <div className="text-xs text-blue-800">
            <strong>Configure Oracle Cloud Infrastructure (OCI) for Object Storage and Generative AI.</strong>
            <br />
            Docling handles OCR locally; these credentials are only for storage, embeddings/retrieval support, and answer generation services.
          </div>
        </div>
      </div>

      <div className="mb-6">
        {/* Section title */}
        <h3 className="font-semibold text-lg mb-4 text-gray-800">API Key</h3>
        
        {/* Grid de campos OCI */}
        <div className="mb-4">
          <label className="block text-sm font-medium mb-1">Compartment ID *</label>
          <input
            type="text"
            value={config.compartment_id}
            onChange={(e) => setConfig({ ...config, compartment_id: e.target.value })}
            className="input-oracle"
            placeholder="ocid1.compartment.oc1..<>"
          />
        </div>

        <div className="grid grid-cols-2 gap-4 mb-4">
          <div>
            <label className="block text-sm font-medium mb-1">User *</label>
            <input
              type="text"
              value={config.user}
              onChange={(e) => setConfig({ ...config, user: e.target.value })}
              className="input-oracle"
              placeholder="ocid1.user.oc1..<>"
            />
          </div>

          <div>
            <label className="block text-sm font-medium mb-1">Finger Print *</label>
            <input
              type="text"
              value={config.fingerprint}
              onChange={(e) => setConfig({ ...config, fingerprint: e.target.value })}
              className="input-oracle"
              placeholder="fingerprint"
            />
          </div>
        </div>

        <div className="grid grid-cols-2 gap-4 mb-4">
          <div>
            <label className="block text-sm font-medium mb-1">Tenancy *</label>
            <input
              type="text"
              value={config.tenancy}
              onChange={(e) => setConfig({ ...config, tenancy: e.target.value })}
              className="input-oracle"
              placeholder="ocid.tenancy.oc1..<>"
            />
          </div>

          <div>
            <label className="block text-sm font-medium mb-1">Region *</label>
            <input
              type="text"
              value={config.region}
              onChange={(e) => {
                const nextRegion = e.target.value;
                setConfig((prev) => ({
                  ...prev,
                  region: nextRegion,
                  inference_url: buildInferenceUrl(nextRegion),
                }));
              }}
              className="input-oracle"
              placeholder="us-chicago-1"
            />
          </div>
        </div>

        {/* Key File Upload - Drag and Drop */}
        <div className="mb-4">
          <label className="block text-sm font-medium mb-2">Key File (PEM) *</label>
          <div
            className={`py-4 px-6 border-2 border-dashed rounded-lg text-center transition-all ${
              dragActive
                ? 'border-oracle-red bg-red-50'
                : 'border-oracle-border bg-gray-50 hover:bg-gray-100'
            }`}
            onDragEnter={handleDrag}
            onDragLeave={handleDrag}
            onDragOver={handleDrag}
            onDrop={handleDrop}
          >
            {uploadingKey ? (
              <div className="text-gray-600">
                <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-oracle-red mx-auto mb-2"></div>
                <div>Uploading key file...</div>
              </div>
            ) : (
              <>
                <div className="text-gray-600 mb-1">
                  <strong>Drag and Drop</strong>
                </div>
                <div className="text-sm text-gray-500 mb-1">Select a PEM file or drop one here</div>
                <input
                  id="key-upload"
                  type="file"
                  accept=".pem"
                  onChange={handleKeyFileChange}
                  className="hidden"
                />
                <label
                  htmlFor="key-upload"
                  className="text-oracle-blue-link hover:underline text-sm cursor-pointer"
                >
                  Select file
                </label>
              </>
            )}
          </div>
          
          {keyFile && (
            <div className="mt-2 flex items-center justify-between p-2 bg-gray-50 rounded border border-gray-200">
              <span className="text-sm text-gray-600">Selected File: {keyFile.name}</span>
              <button
                onClick={() => {
                  setKeyFile(null);
                  setConfig({ ...config, key_file: '' });
                }}
                className="text-red-600 hover:text-red-800 text-xl leading-none"
              >
                ✕
              </button>
            </div>
          )}
          
          {config.key_file && (
            <p className="mt-2 text-sm text-green-600">✓ Key file uploaded successfully</p>
          )}
        </div>

        {/* Mensajes de resultado OCI API key */}
        {testResultDU && (
          <div
            className={`p-3 rounded mb-4 text-sm ${
              testResultDU.success ? 'bg-green-50 text-green-800 border border-green-200' : 'bg-red-50 text-red-800 border border-red-200'
            }`}
          >
            {testResultDU.message}
          </div>
        )}

        {/* Botones de Test y Save para OCI API key */}
        <div className="flex gap-3 mb-6">
          <button
            onClick={handleTestDU}
            disabled={testingDU || !config.key_file}
            className="btn-secondary flex items-center gap-2"
          >
            {testingDU ? (
              <div className="animate-spin rounded-full h-4 w-4 border-2 border-gray-400 border-t-transparent"></div>
            ) : (
              <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 12l2 2 4-4m6 2a9 9 0 11-18 0 9 9 0 0118 0z" />
              </svg>
            )}
            {testingDU ? 'Testing...' : 'Test connection'}
          </button>

          <button
            onClick={handleSaveDU}
            disabled={!testResultDU?.success || savingDU || savedDU}
            className="btn-secondary flex items-center gap-2"
          >
            {savingDU ? (
              <div className="animate-spin rounded-full h-4 w-4 border-2 border-gray-400 border-t-transparent"></div>
            ) : savedDU ? (
              <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M5 13l4 4L19 7" />
              </svg>
            ) : (
              <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M8 7H5a2 2 0 00-2 2v9a2 2 0 002 2h14a2 2 0 002-2V9a2 2 0 00-2-2h-3m-1 4l-3 3m0 0l-3-3m3 3V4" />
              </svg>
            )}
            {savingDU ? 'Saving...' : savedDU ? 'Saved' : 'Save configuration'}
          </button>
        </div>
      </div>

      {/* Section 2: Object Storage */}
      <div className="mb-6">
        <h3 className="font-semibold text-lg mb-4 text-gray-800">Object Storage</h3>
        
        <div className="mb-4">
          <label className="block text-sm font-medium mb-1">Namespace *</label>
          <input
            type="text"
            value={config.namespace}
            onChange={(e) => setConfig({ ...config, namespace: e.target.value })}
            className="input-oracle"
            placeholder="Namespace"
          />
        </div>

        <div className="mb-4">
          <div>
            <label className="block text-sm font-medium mb-1">Bucket Name *</label>
            <input
              type="text"
              value={config.bucket_name}
              onChange={(e) => setConfig({ ...config, bucket_name: e.target.value })}
              className="input-oracle"
              placeholder="app_doc"
            />
          </div>
        </div>

        {/* Message when API Key is not saved */}
        {!savedDU && (
          <div className="p-3 rounded mb-4 text-sm bg-yellow-50 text-yellow-800 border border-yellow-200">
            Please save API Key configuration first before testing Object Storage.
          </div>
        )}

        {/* Mensajes de resultado Object Storage */}
        {testResultOS && (
          <div
            className={`p-3 rounded mb-4 text-sm ${
              testResultOS.success ? 'bg-green-50 text-green-800 border border-green-200' : 'bg-red-50 text-red-800 border border-red-200'
            }`}
          >
            {testResultOS.message}
          </div>
        )}

        {/* Botones de Test y Save para Object Storage */}
        <div className="flex gap-3 mb-6">
          <button
            onClick={handleTestOS}
            disabled={testingOS || !savedDU || !config.namespace || !config.bucket_name}
            className="btn-secondary flex items-center gap-2"
          >
            {testingOS ? (
              <div className="animate-spin rounded-full h-4 w-4 border-2 border-gray-400 border-t-transparent"></div>
            ) : (
              <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 12l2 2 4-4m6 2a9 9 0 11-18 0 9 9 0 0118 0z" />
              </svg>
            )}
            {testingOS ? 'Testing...' : 'Test connection'}
          </button>

          <button
            onClick={handleSaveOS}
            disabled={!testResultOS?.success || savingOS || savedOS}
            className="btn-secondary flex items-center gap-2"
          >
            {savingOS ? (
              <div className="animate-spin rounded-full h-4 w-4 border-2 border-gray-400 border-t-transparent"></div>
            ) : savedOS ? (
              <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M5 13l4 4L19 7" />
              </svg>
            ) : (
              <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M8 7H5a2 2 0 00-2 2v9a2 2 0 002 2h14a2 2 0 002-2V9a2 2 0 00-2-2h-3m-1 4l-3 3m0 0l-3-3m3 3V4" />
              </svg>
            )}
            {savingOS ? 'Saving...' : savedOS ? 'Saved' : 'Save configuration'}
          </button>
        </div>
      </div>

      {/* Section 3: Generative AI */}
      <div className="mb-6">
        <h3 className="font-semibold text-lg mb-4 text-gray-800">Generative AI</h3>

        <div className="mb-4">
          <label className="block text-sm font-medium mb-1">Inference URL</label>
          <div className="input-oracle bg-gray-50 text-gray-700">
            {config.inference_url || 'No disponible'}
          </div>
          <p className="mt-1 text-xs text-gray-600">
            Automatically derived from OCI region.
          </p>
        </div>

        <div className="mb-4">
          <label className="block text-sm font-medium mb-1">Generative AI Model *</label>
          <select
            value={config.generative_model}
            onChange={(e) => setConfig({ ...config, generative_model: e.target.value })}
            className="input-oracle w-full"
            disabled={loadingGenAIModels || !savedDU}
          >
            <option value="">
              {loadingGenAIModels ? 'Loading...' : !savedDU ? 'Save API Key first' : generativeModels.length === 0 ? 'No models in tenant' : 'Select model'}
            </option>
            {!selectedGenerativeInList && config.generative_model && (
              <option value={config.generative_model}>{config.generative_model}</option>
            )}
            {generativeModels.map((m) => (
              <option key={m.id} value={m.id}>{m.display_name}</option>
            ))}
          </select>
        </div>

        {testResultGenAI && (
          <div
            className={`p-3 rounded mb-4 text-sm ${
              testResultGenAI.success ? 'bg-green-50 text-green-800 border border-green-200' : 'bg-red-50 text-red-800 border border-red-200'
            }`}
          >
            {testResultGenAI.message}
          </div>
        )}

        {!savedDU && (
          <div className="p-3 rounded mb-4 text-sm bg-yellow-50 text-yellow-800 border border-yellow-200">
            Please save API Key configuration first before testing Generative AI.
          </div>
        )}

        <div className="flex gap-3 mb-6">
          <button
            onClick={handleTestGenAI}
            disabled={testingGenAI || !config.inference_url?.trim() || !config.generative_model?.trim()}
            className="btn-secondary flex items-center gap-2"
          >
            {testingGenAI ? (
              <div className="animate-spin rounded-full h-4 w-4 border-2 border-gray-400 border-t-transparent"></div>
            ) : (
              <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 12l2 2 4-4m6 2a9 9 0 11-18 0 9 9 0 0118 0z" />
              </svg>
            )}
            {testingGenAI ? 'Testing...' : 'Test connection'}
          </button>

          <button
            onClick={handleSaveGenAI}
            disabled={!testResultGenAI?.success || savingGenAI || savedGenAI}
            className="btn-secondary flex items-center gap-2"
          >
            {savingGenAI ? (
              <div className="animate-spin rounded-full h-4 w-4 border-2 border-gray-400 border-t-transparent"></div>
            ) : savedGenAI ? (
              <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M5 13l4 4L19 7" />
              </svg>
            ) : (
              <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M8 7H5a2 2 0 00-2 2v9a2 2 0 002 2h14a2 2 0 002-2V9a2 2 0 00-2-2h-3m-1 4l-3 3m0 0l-3-3m3 3V4" />
              </svg>
            )}
            {savingGenAI ? 'Saving...' : savedGenAI ? 'Saved' : 'Save configuration'}
          </button>
        </div>
      </div>

      {/* Finish Installation button: habilitado solo cuando las tres configuraciones están guardadas */}
      <div className="flex justify-end mt-8">
        <button
          onClick={handleFinish}
          disabled={!savedDU || !savedOS || !savedGenAI}
          className="btn-primary"
          title={(!savedDU || !savedOS || !savedGenAI) ? 'Guarda las tres configuraciones (API Key, Object Storage y Generative AI) para continuar' : undefined}
        >
          Finish Installation
        </button>
      </div>
    </div>
  );
}
