import React from 'react';
import { HelpCircle } from 'lucide-react';
import { Button } from '../../components/actions/Button';
import { useNavigate } from 'react-router-dom';
import { useI18n } from '../../i18n/I18nContext';

export const NotFoundPage: React.FC = () => {
  const navigate = useNavigate();
  const { t } = useI18n();

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
          backgroundColor: 'var(--color-surface-subtle)',
          color: 'var(--color-text-muted)',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
          marginBottom: '16px',
        }}
      >
        <HelpCircle size={32} />
      </div>
      <h1
        style={{
          fontSize: '1.5rem',
          fontWeight: 700,
          color: 'var(--color-text-primary)',
          marginBottom: '8px',
        }}
      >
        {t('errors.not_found_title')}
      </h1>
      <p
        style={{
          fontSize: '0.875rem',
          color: 'var(--color-text-secondary)',
          maxWidth: '420px',
          marginBottom: '24px',
        }}
      >
        {t('errors.not_found_body')}
      </p>
      <Button variant="primary" onClick={() => navigate('/')}>
        {t('errors.return_dashboard')}
      </Button>
    </div>
  );
};
