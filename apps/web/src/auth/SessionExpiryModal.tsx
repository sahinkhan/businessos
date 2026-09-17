import React, { useEffect, useState } from 'react';
import { useAuth } from './AuthContext';
import { Modal } from '../components/overlays/Modal';
import { Button } from '../components/actions/Button';
import { useI18n } from '../i18n/I18nContext';

export const SessionExpiryModal: React.FC = () => {
  const { session, reloadSession, logout, isAuthenticated } = useAuth();
  const [showWarning, setShowWarning] = useState(false);
  const [secondsRemaining, setSecondsRemaining] = useState(0);
  const { t, tp } = useI18n();

  useEffect(() => {
    if (!isAuthenticated || !session) {
      setShowWarning(false);
      return;
    }
    const update = () => {
      const remaining = session.expiresAt - Math.floor(Date.now() / 1000);
      setSecondsRemaining(remaining);
      setShowWarning(remaining > 0 && remaining <= 300);
      if (remaining <= 0) void logout();
    };
    update();
    const interval = window.setInterval(update, 5000);
    return () => window.clearInterval(interval);
  }, [isAuthenticated, session, logout]);

  if (!showWarning) return null;

  return (
    <Modal
      isOpen
      onClose={() => setShowWarning(false)}
      title={t('auth.session.title')}
      footer={
        <>
          <Button variant="secondary" onClick={() => void logout()}>
            {t('auth.session.logout')}
          </Button>
          <Button
            variant="primary"
            onClick={async () => {
              await reloadSession();
              setShowWarning(false);
            }}
          >
            {t('auth.session.extend')}
          </Button>
        </>
      }
    >
      <p style={{ color: 'var(--color-text-secondary)', fontSize: '0.875rem' }}>
        {tp('auth.session_minutes', Math.max(1, Math.ceil(secondsRemaining / 60)))}
      </p>
    </Modal>
  );
};
