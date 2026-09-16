import React from 'react';

export interface FormSectionProps {
  title: string;
  description?: string;
  children: React.ReactNode;
  actions?: React.ReactNode;
}

export const FormSection: React.FC<FormSectionProps> = ({
  title,
  description,
  children,
  actions,
}) => {
  return (
    <div
      style={{
        marginBottom: '24px',
        borderBottom: '1px solid var(--color-border-subtle)',
        paddingBottom: '20px',
      }}
    >
      <div
        style={{
          display: 'flex',
          alignItems: 'flex-start',
          justifyContent: 'space-between',
          marginBottom: '14px',
        }}
      >
        <div>
          <h4 style={{ fontSize: '1rem', fontWeight: 600, color: 'var(--color-text-primary)' }}>
            {title}
          </h4>
          {description && (
            <p
              style={{
                fontSize: '0.8125rem',
                color: 'var(--color-text-secondary)',
                marginTop: '2px',
              }}
            >
              {description}
            </p>
          )}
        </div>
        {actions && <div>{actions}</div>}
      </div>
      <div>{children}</div>
    </div>
  );
};
