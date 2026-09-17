import React, { useEffect, useState } from 'react';
import { useAuth } from './AuthContext';
import { Modal } from '../components/overlays/Modal';
import { Button } from '../components/actions/Button';

export const SessionExpiryModal: React.FC = () => {
  const { session, refreshSession, logout, isAuthenticated } = useAuth();
  const [showWarning, setShowWarning] = useState(false);
  const [secondsRemaining, setSecondsRemaining] = useState(0);

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
      title="Session Expiration Warning"
      footer={
        <>
          <Button variant="secondary" onClick={() => void logout()}>
            Log out now
          </Button>
          <Button
            variant="primary"
            onClick={async () => {
              await refreshSession();
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
        {Math.max(1, Math.ceil(secondsRemaining / 60))} minute(s).
      </p>
    </Modal>
  );
};
