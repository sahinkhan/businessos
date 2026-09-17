import React, { useState } from 'react';
import { Drawer } from '../components/overlays/Drawer';
import { useNotifications } from './NotificationContext';
import { NotificationCategory } from './types';
import { Button } from '../components/actions/Button';
import { CheckCheck, Trash2, CheckCircle, AlertTriangle, AlertCircle, Info } from 'lucide-react';
import { useI18n } from '../i18n/I18nContext';

export interface NotificationDrawerProps {
  isOpen: boolean;
  onClose: () => void;
}

export const NotificationDrawer: React.FC<NotificationDrawerProps> = ({ isOpen, onClose }) => {
  const { notifications, markAsRead, markAllAsRead, clearAll } = useNotifications();
  const [filter, setFilter] = useState<NotificationCategory>('all');
  const { t } = useI18n();

  const filtered = notifications.filter((n) => {
    if (filter === 'unread') return !n.read;
    if (filter === 'actionable') return Boolean(n.actionUrl);
    return true;
  });

  return (
    <Drawer
      isOpen={isOpen}
      onClose={onClose}
      title={t('nav.notifications')}
      closeLabel={t('notifications.close')}
      width="400px"
      footer={
        <div style={{ display: 'flex', justifyContent: 'space-between', width: '100%' }}>
          <Button variant="ghost" size="sm" leftIcon={<Trash2 size={14} />} onClick={clearAll}>
            {t('notifications.clear_all')}
          </Button>
          <Button
            variant="ghost"
            size="sm"
            leftIcon={<CheckCheck size={14} />}
            onClick={markAllAsRead}
          >
            {t('notifications.mark_all_read')}
          </Button>
        </div>
      }
    >
      {/* Category Pills */}
      <div style={{ display: 'flex', gap: '8px', marginBottom: '16px' }}>
        {(['all', 'unread', 'actionable'] as NotificationCategory[]).map((cat) => (
          <button
            key={cat}
            type="button"
            onClick={() => setFilter(cat)}
            style={{
              padding: '4px 12px',
              borderRadius: '9999px',
              fontSize: '0.75rem',
              fontWeight: 500,
              border: 'none',
              cursor: 'pointer',
              textTransform: 'capitalize',
              backgroundColor:
                filter === cat ? 'var(--color-action-primary)' : 'var(--color-surface-subtle)',
              color: filter === cat ? 'white' : 'var(--color-text-primary)',
            }}
          >
            {t(`notifications.filter.${cat}`)}
          </button>
        ))}
      </div>

      {/* Notifications List */}
      <div style={{ display: 'flex', flexDirection: 'column', gap: '10px' }}>
        {filtered.length === 0 ? (
          <div
            style={{
              textAlign: 'center',
              padding: '32px 0',
              color: 'var(--color-text-muted)',
              fontSize: '0.875rem',
            }}
          >
            {t('notifications.empty')}
          </div>
        ) : (
          filtered.map((item) => {
            const icon =
              item.severity === 'success' ? (
                <CheckCircle size={16} color="var(--color-status-success)" />
              ) : item.severity === 'warning' ? (
                <AlertTriangle size={16} color="var(--color-status-warning)" />
              ) : item.severity === 'error' ? (
                <AlertCircle size={16} color="var(--color-status-danger)" />
              ) : (
                <Info size={16} color="var(--color-status-info)" />
              );

            return (
              <div
                key={item.id}
                onClick={() => !item.read && markAsRead(item.id)}
                style={{
                  padding: '12px',
                  borderRadius: '6px',
                  backgroundColor: item.read ? 'transparent' : 'var(--color-surface-subtle)',
                  border: '1px solid var(--color-border-subtle)',
                  cursor: 'pointer',
                  display: 'flex',
                  gap: '10px',
                  alignItems: 'flex-start',
                }}
              >
                <div style={{ marginTop: '2px', flexShrink: 0 }}>{icon}</div>
                <div style={{ flex: 1 }}>
                  <div
                    style={{
                      display: 'flex',
                      justifyContent: 'space-between',
                      alignItems: 'center',
                    }}
                  >
                    <h5
                      style={{
                        fontSize: '0.875rem',
                        fontWeight: 600,
                        color: 'var(--color-text-primary)',
                      }}
                    >
                      {item.title}
                    </h5>
                    {!item.read && (
                      <span
                        style={{
                          width: '8px',
                          height: '8px',
                          borderRadius: '50%',
                          backgroundColor: 'var(--color-action-primary)',
                        }}
                      />
                    )}
                  </div>
                  <p
                    style={{
                      fontSize: '0.8125rem',
                      color: 'var(--color-text-secondary)',
                      marginTop: '2px',
                    }}
                  >
                    {item.message}
                  </p>
                  {item.actionUrl && item.actionLabel && (
                    <Button
                      variant="outline"
                      size="sm"
                      style={{ marginTop: '8px', fontSize: '0.75rem', height: '26px' }}
                      onClick={(e) => {
                        e.stopPropagation();
                        markAsRead(item.id);
                      }}
                    >
                      {item.actionLabel}
                    </Button>
                  )}
                </div>
              </div>
            );
          })
        )}
      </div>
    </Drawer>
  );
};
