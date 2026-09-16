import React from 'react';
import { Button } from '../components/actions/Button';

export interface WizardStep {
  id: string;
  title: string;
}

export interface WizardPageShellProps {
  title: string;
  steps: WizardStep[];
  currentStepIndex: number;
  onNext?: () => void;
  onPrev?: () => void;
  onFinish?: () => void;
  isSubmitting?: boolean;
  children: React.ReactNode;
}

export const WizardPageShell: React.FC<WizardPageShellProps> = ({
  title,
  steps,
  currentStepIndex,
  onNext,
  onPrev,
  onFinish,
  isSubmitting,
  children,
}) => {
  const isLast = currentStepIndex === steps.length - 1;

  return (
    <div style={{ maxWidth: '800px', margin: '0 auto', width: '100%' }}>
      <h1
        style={{
          fontSize: '1.5rem',
          fontWeight: 700,
          color: 'var(--color-text-primary)',
          marginBottom: '20px',
        }}
      >
        {title}
      </h1>

      {/* Step indicator */}
      <div style={{ display: 'flex', alignItems: 'center', marginBottom: '32px', gap: '12px' }}>
        {steps.map((step, idx) => {
          const isDone = idx < currentStepIndex;
          const isCurrent = idx === currentStepIndex;

          return (
            <React.Fragment key={step.id}>
              <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                <div
                  style={{
                    width: '28px',
                    height: '28px',
                    borderRadius: '50%',
                    display: 'flex',
                    alignItems: 'center',
                    justifyContent: 'center',
                    fontSize: '0.8125rem',
                    fontWeight: 600,
                    backgroundColor:
                      isDone || isCurrent
                        ? 'var(--color-action-primary)'
                        : 'var(--color-surface-subtle)',
                    color: isDone || isCurrent ? 'white' : 'var(--color-text-muted)',
                  }}
                >
                  {idx + 1}
                </div>
                <span
                  style={{
                    fontSize: '0.875rem',
                    fontWeight: isCurrent ? 600 : 400,
                    color: isCurrent ? 'var(--color-text-primary)' : 'var(--color-text-muted)',
                  }}
                >
                  {step.title}
                </span>
              </div>
              {idx < steps.length - 1 && (
                <div
                  style={{ flex: 1, height: '2px', backgroundColor: 'var(--color-border-subtle)' }}
                />
              )}
            </React.Fragment>
          );
        })}
      </div>

      <div style={{ marginBottom: '24px' }}>{children}</div>

      <div
        style={{
          display: 'flex',
          justifyContent: 'space-between',
          borderTop: '1px solid var(--color-border-subtle)',
          paddingTop: '16px',
        }}
      >
        <Button
          variant="secondary"
          onClick={onPrev}
          disabled={currentStepIndex === 0 || isSubmitting}
        >
          Previous
        </Button>
        {isLast ? (
          <Button variant="primary" onClick={onFinish} isLoading={isSubmitting}>
            Finish Setup
          </Button>
        ) : (
          <Button variant="primary" onClick={onNext} disabled={isSubmitting}>
            Next
          </Button>
        )}
      </div>
    </div>
  );
};
