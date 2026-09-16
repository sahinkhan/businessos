import React, { useState, useEffect } from 'react';
import { useAuth } from './AuthContext';
import { Modal } from '../components/overlays/Modal';
import { Button } from '../components/actions/Button';

export const SessionExpiryModal: React.FC = () => {
  const { session, refreshToken, logout, isAuthenticated } = useAuth();
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
        logout();
      } else {
        setShowWarning(false);
      }
    }, 5000);

    return () => clearInterval(interval);
  }, [isAuthenticated, session, logout]);

  if (!showWarning) return null;

  return (
    <Modal
      isOpen={showWarning}
      onClose={() => setShowWarning(false)}
      title="Session Expiration Warning"
      footer={
        <>
          <Button variant="secondary" onClick={() => logout()}>
            Log out now
          </Button>
          <Button
            variant="primary"
            onClick={async () => {
              await refreshToken();
              setShowWarning(false);
            }}
          >
            Extend session
          </Button>
        </>
      }
    >
      <p style={{ color: 'var(--color-text-secondary)', fontSize: '0.875rem' }}>
        Your active session will expire in approximately{' '}
        {Math.max(1, Math.ceil(secondsRemaining / 60))} minute(s). Would you like to extend your
        session?
      </p>
    </Modal>
  );
};
