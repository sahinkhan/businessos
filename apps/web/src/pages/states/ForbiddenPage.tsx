import React from 'react';
import { ShieldAlert } from 'lucide-react';
import { Button } from '../../components/actions/Button';
import { useNavigate } from 'react-router-dom';

export const ForbiddenPage: React.FC = () => {
  const navigate = useNavigate();

  return (
    <div
      style={{
        display: 'flex',
        flexDirection: 'column',
        alignItems: 'center',
        justifyContent: 'center',
        padding: '64px 20px',
        textAlign: 'center',
      }}
    >
      <div
        style={{
          width: '64px',
          height: '64px',
          borderRadius: '50%',
          backgroundColor: 'var(--color-status-danger-bg)',
          color: 'var(--color-status-danger)',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
          marginBottom: '16px',
        }}
      >
        <ShieldAlert size={32} />
      </div>
      <h1
        style={{
          fontSize: '1.5rem',
          fontWeight: 700,
          color: 'var(--color-text-primary)',
          marginBottom: '8px',
        }}
      >
        403 - Authorization Denied
      </h1>
      <p
        style={{
          fontSize: '0.875rem',
          color: 'var(--color-text-secondary)',
          maxWidth: '420px',
          marginBottom: '24px',
        }}
      >
        Your account does not possess the requisite policy permissions to view or interact with this
        resource. Contact your enterprise system administrator.
      </p>
      <Button variant="primary" onClick={() => navigate('/')}>
        Return to Dashboard
      </Button>
    </div>
  );
};
