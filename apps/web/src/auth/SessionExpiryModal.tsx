import React, { useState, useEffect } from 'react';
import { useAuth } from './AuthContext';
import { Modal } from '../components/overlays/Modal';
import { Button } from '../components/actions/Button';
import { useI18n } from '../i18n/I18nContext';

export const SessionExpiryModal: React.FC = () => {
  const { session, refreshToken, logout, isAuthenticated } = useAuth();
  const { t, formatNumber } = useI18n();
  const [showWarning, setShowWarning] = useState(false);
  const [secondsRemaining, setSecondsRemaining] = useState<number>(0);

  useEffect(() => {
    if (!isAuthenticated || !session) {
      setShowWarning(false);
      return;
    }

    const interval = setInterval(() => {
      const nowSec = Math.floor(Date.now() / 1000);
      const remaining = session.expiresAt - nowSec;
      setSecondsRemaining(remaining);

      // Show warning when 5 minutes or less remain
      if (remaining > 0 && remaining <= 300) {
        setShowWarning(true);
      } else if (remaining <= 0) {
        setShowWarning(false);
      } else {
        setShowWarning(false);
      }
    }, 5000);

    return () => clearInterval(interval);
  }, [isAuthenticated, session, logout]);

  if (!showWarning) return null;
  const minutesRemaining = Math.max(1, Math.ceil(secondsRemaining / 60));

  return (
    <Modal
      isOpen={showWarning}
      onClose={() => setShowWarning(false)}
      title={t('session.expiration_warning')}
      closeLabel={t('common.close_dialog')}
      footer={
        <>
          <Button variant="secondary" onClick={() => logout()}>
            {t('session.logout_now')}
          </Button>
          <Button
            variant="primary"
            onClick={async () => {
              await refreshToken();
              setShowWarning(false);
            }}
          >
            {t('session.extend')}
          </Button>
        </>
      }
    >
      <p style={{ color: 'var(--color-text-secondary)', fontSize: '0.875rem' }}>
        {t(minutesRemaining === 1 ? 'session.expires_one' : 'session.expires_many', {
          minutes: formatNumber(minutesRemaining),
        })}
      </p>
    </Modal>
  );
};
