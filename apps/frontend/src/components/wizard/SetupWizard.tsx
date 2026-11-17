import React, { useState } from 'react';
import { UserConfigStep } from './UserConfigStep';
import { DatabaseConfigStep } from './DatabaseConfigStep';
import { InstallationStep } from './InstallationStep';
import { DocumentUnderstandingStep } from './DocumentUnderstandingStep';
import { Footer } from '../common/Footer';

const STEPS = [
  { id: 1, name: 'User configuration' },
  { id: 2, name: 'Database configuration' },
  { id: 3, name: 'Installation' },
  { id: 4, name: 'OCI services' },
];

interface SetupWizardProps {
  onSetupComplete?: () => void;
}

export function SetupWizard({ onSetupComplete }: SetupWizardProps) {
  const [currentStep, setCurrentStep] = useState(1);
  const [setupData, setSetupData] = useState<any>({});
  const currentStepInfo = STEPS.find((step) => step.id === currentStep) ?? STEPS[0];
  const progressPercent = ((currentStep - 1) / Math.max(STEPS.length - 1, 1)) * 100;

  const handleNext = (stepData: any) => {
    setSetupData({ ...setupData, ...stepData });
    if (currentStep < 4) {
      setCurrentStep(currentStep + 1);
    }
  };

  const handleBack = () => {
    if (currentStep > 1) {
      setCurrentStep(currentStep - 1);
    }
  };

  const renderStep = () => {
    const props = {
      data: setupData,
      onNext: handleNext,
      onBack: handleBack,
      isFirstStep: currentStep === 1,
      isLastStep: currentStep === 4,
      onSetupComplete: onSetupComplete,
    };

    switch (currentStep) {
      case 1:
        return <UserConfigStep {...props} />;
      case 2:
        return <DatabaseConfigStep {...props} />;
      case 3:
        return <InstallationStep {...props} />;
      case 4:
        return <DocumentUnderstandingStep {...props} />;
      default:
        return null;
    }
  };

  return (
    <div className="setup-shell-light flex min-h-screen flex-col bg-oracle-bg-gray pb-12 text-oracle-dark-gray">
      {/* Stepper */}
      <div className="app-content-layer border-b border-oracle-border bg-white shadow-sm">
        <div className="mx-auto max-w-5xl px-4 py-5 sm:px-6 sm:py-6 lg:px-8">
          <div className="mb-5">
            <p className="text-xs font-semibold uppercase tracking-[0.18em] text-oracle-red">
              Application setup
            </p>
          </div>

          <div className="hidden items-start justify-between md:flex">
            {STEPS.map((step, index) => (
              <React.Fragment key={step.id}>
                <div className="flex w-32 flex-col items-center">
                  <div
                    className={`relative flex h-10 w-10 items-center justify-center rounded-full text-sm font-semibold ${
                      step.id === currentStep
                        ? 'bg-oracle-red text-white'
                        : step.id < currentStep
                        ? 'bg-emerald-600 text-white'
                        : 'bg-gray-100 text-oracle-medium-gray'
                    }`}
                  >
                    {step.id < currentStep ? (
                      <svg aria-hidden="true" className="h-5 w-5" fill="none" viewBox="0 0 24 24">
                        <path
                          d="M5 12.5l4.3 4.2L19 7"
                          stroke="currentColor"
                          strokeLinecap="round"
                          strokeLinejoin="round"
                          strokeWidth="2.4"
                        />
                      </svg>
                    ) : (
                      step.id
                    )}
                  </div>
                  <span className="mt-2 text-center text-sm leading-5 text-oracle-medium-gray">{step.name}</span>
                </div>
                {index < STEPS.length - 1 && (
                  <div className="flex min-w-10 flex-1 items-center px-2 pt-5">
                    <div className={`h-1 w-full rounded-full ${step.id < currentStep ? 'bg-emerald-600' : 'bg-gray-200'}`} />
                  </div>
                )}
              </React.Fragment>
            ))}
          </div>

          <div className="md:hidden">
            <div className="h-2 overflow-hidden rounded-full bg-gray-200">
              <div
                className="h-full rounded-full bg-oracle-red transition-all duration-300"
                style={{ width: `${progressPercent}%` }}
              />
            </div>
            <div className="mt-3 flex items-center justify-between gap-3">
              <div>
                <p className="text-sm font-semibold text-oracle-dark-gray">{currentStepInfo.name}</p>
                <p className="text-xs text-oracle-light-gray">Complete this step to continue.</p>
              </div>
              <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-full bg-oracle-red text-sm font-semibold text-white">
                {currentStep}
              </div>
            </div>
          </div>
        </div>
      </div>

      {/* Step Content */}
      <div className="app-content-layer mx-auto w-full max-w-5xl flex-1 px-4 py-6 pb-20 sm:px-6 sm:py-8 lg:px-8">
        {renderStep()}
      </div>

      <Footer />
    </div>
  );
}
