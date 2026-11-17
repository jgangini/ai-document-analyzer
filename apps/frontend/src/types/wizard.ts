export interface WizardData {
  adminPassword?: string;
  database?: {
    walletPath: string;
    username: string;
    password: string;
    dsn: string;
  };
  installation?: any;
  oci?: {
    compartment_id: string;
    user: string;
    fingerprint: string;
    tenancy: string;
    region: string;
    key_file: string;
  };
}

export interface TestResult {
  success: boolean;
  message: string;
}
