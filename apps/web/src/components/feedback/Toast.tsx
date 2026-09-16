import React, { createContext, useContext, useState, useCallback } from 'react';
import { CheckCircle2, AlertTriangle, AlertCircle, Info, X } from 'lucide-react';

export type ToastType = 'success' | 'warning' | 'danger' | 'info';

export interface ToastItem {
  id: string;
  type: ToastType;
  title: string;
  description?: string;
  duration?: number;
}

export interface ToastContextValue {
  toasts: ToastItem[];
  showToast: (toast: Omit<ToastItem, 'id'>) => string;
  dismissToast: (id: string) => void;
  success: (title: string, description?: string) => string;
  error: (title: string, description?: string) => string;
  warning: (title: string, description?: string) => string;
  info: (title: string, description?: string) => string;
}

const ToastContext = createContext<ToastContextValue | undefined>(undefined);

export const ToastProvider: React.FC<{ children: React.ReactNode }> = ({ children }) => {
  const [toasts, setToasts] = useState<ToastItem[]>([]);

  const dismissToast = useCallback((id: string) => {
    setToasts((prev) => prev.filter((t) => t.id !== id));
  }, []);

  const showToast = useCallback(
    (toast: Omit<ToastItem, 'id'>) => {
      const id = 'toast_' + Math.random().toString(36).substring(2, 9);
      const newToast: ToastItem = { ...toast, id };
      setToasts((prev) => [...prev, newToast]);

      const duration = toast.duration ?? 4000;
      if (duration > 0) {
        setTimeout(() => {
          dismissToast(id);
        }, duration);
      }
      return id;
    },
    [dismissToast]
  );

  const success = useCallback(
    (title: string, description?: string) => showToast({ type: 'success', title, description }),
    [showToast]
  );
  const error = useCallback(
    (title: string, description?: string) => showToast({ type: 'danger', title, description }),
    [showToast]
  );
  const warning = useCallback(
    (title: string, description?: string) => showToast({ type: 'warning', title, description }),
    [showToast]
  );
  const info = useCallback(
    (title: string, description?: string) => showToast({ type: 'info', title, description }),
    [showToast]
  );

  return (
    <ToastContext.Provider
      value={{ toasts, showToast, dismissToast, success, error, warning, info }}
    >
      {children}
      <div
        role="region"
        aria-label="Notifications"
        style={{
          position: 'fixed',
          bottom: '24px',
          right: '24px',
          display: 'flex',
          flexDirection: 'column',
          gap: '8px',
          zIndex: 1600,
          maxWidth: '380px',
          width: '100%',
          pointerEvents: 'none',
        }}
      >
        {toasts.map((toast) => {
          const icon =
            toast.type === 'success' ? (
              <CheckCircle2 size={18} color="var(--color-status-success)" />
            ) : toast.type === 'warning' ? (
              <AlertTriangle size={18} color="var(--color-status-warning)" />
            ) : toast.type === 'danger' ? (
              <AlertCircle size={18} color="var(--color-status-danger)" />
            ) : (
              <Info size={18} color="var(--color-status-info)" />
            );

          return (
            <div
              key={toast.id}
              role="status"
              aria-live="polite"
              style={{
                pointerEvents: 'auto',
                display: 'flex',
                alignItems: 'flex-start',
                gap: '12px',
                padding: '12px 14px',
                borderRadius: '8px',
                backgroundColor: 'var(--color-surface-card)',
                border: '1px solid var(--color-border-subtle)',
                boxShadow: 'var(--shadow-dropdown)',
                animation: 'bos-slide-up 200ms ease',
              }}
            >
              <div style={{ flexShrink: 0, marginTop: '2px' }}>{icon}</div>
              <div style={{ flex: 1 }}>
                <div
                  style={{
                    fontWeight: 600,
                    fontSize: '0.875rem',
                    color: 'var(--color-text-primary)',
                  }}
                >
                  {toast.title}
                </div>
                {toast.description && (
                  <div
                    style={{
                      fontSize: '0.8125rem',
                      color: 'var(--color-text-secondary)',
                      marginTop: '2px',
                    }}
                  >
                    {toast.description}
                  </div>
                )}
              </div>
              <button
                type="button"
                onClick={() => dismissToast(toast.id)}
                aria-label="Close notification"
                style={{
                  background: 'none',
                  border: 'none',
                  cursor: 'pointer',
                  color: 'var(--color-text-muted)',
                  padding: '2px',
                  borderRadius: '4px',
                }}
              >
                <X size={14} />
              </button>
            </div>
          );
        })}
      </div>
    </ToastContext.Provider>
  );
};

export const useToast = (): ToastContextValue => {
  const ctx = useContext(ToastContext);
  if (!ctx) {
    throw new Error('useToast must be used within ToastProvider');
  }
  return ctx;
};
