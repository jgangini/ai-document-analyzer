import { lazy, Suspense } from 'react';
import { Navigate, Route } from 'react-router-dom';

import { LoadingState } from '../components/common/LoadingState';

const SetupWizard = lazy(() =>
  import('../components/wizard/SetupWizard').then((module) => ({ default: module.SetupWizard }))
);

type SetupRoutesProps = {
  onSetupComplete: () => void;
};

export function SetupRoutes({ onSetupComplete }: SetupRoutesProps) {
  return (
    <>
      <Route
        path="/setup"
        element={
          <Suspense fallback={<LoadingState size="sm" label="Loading..." />}>
            <SetupWizard onSetupComplete={onSetupComplete} />
          </Suspense>
        }
      />
      <Route path="*" element={<Navigate to="/setup" replace />} />
    </>
  );
}
