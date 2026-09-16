import React from 'react';

export interface FormPageShellProps {
  title: string;
  description?: string;
  children: React.ReactNode;
}

export const FormPageShell: React.FC<FormPageShellProps> = ({ title, description, children }) => {
  return (
    <div style={{ maxWidth: '840px', width: '100%', margin: '0 auto' }}>
      <div style={{ marginBottom: '24px' }}>
        <h1 style={{ fontSize: '1.5rem', fontWeight: 700, color: 'var(--color-text-primary)' }}>
          {title}
        </h1>
        {description && (
          <p
            style={{ fontSize: '0.875rem', color: 'var(--color-text-secondary)', marginTop: '4px' }}
          >
            {description}
          </p>
        )}
      </div>
      <div>{children}</div>
    </div>
  );
};
