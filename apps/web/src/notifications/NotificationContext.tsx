import React, { createContext, useContext, useState, useMemo, useCallback } from 'react';
import { NotificationItem, NotificationContextValue } from './types';

const NotificationContext = createContext<NotificationContextValue | undefined>(undefined);

const INITIAL_NOTIFICATIONS: NotificationItem[] = [
  {
    id: 'notif_1',
    title: 'Batch Approval Required',
    message: '3 invoices exceed single-approver threshold ($50,000 USD).',
    severity: 'warning',
    timestamp: Date.now() - 1000 * 60 * 15,
    read: false,
    actionUrl: '#',
    actionLabel: 'Review Invoices',
  },
  {
    id: 'notif_2',
    title: 'Site Integration Active',
    message: 'Operating Site SEA-01 synchronized telemetry successfully.',
    severity: 'success',
    timestamp: Date.now() - 1000 * 60 * 60 * 2,
    read: true,
  },
  {
    id: 'notif_3',
    title: 'System Maintenance Window',
    message: 'Scheduled zero-downtime ledger reconciliation tonight at 02:00 UTC.',
    severity: 'info',
    timestamp: Date.now() - 1000 * 60 * 60 * 12,
    read: true,
  },
];

export const NotificationProvider: React.FC<{ children: React.ReactNode }> = ({ children }) => {
  const [notifications, setNotifications] = useState<NotificationItem[]>(INITIAL_NOTIFICATIONS);

  const unreadCount = useMemo(() => notifications.filter((n) => !n.read).length, [notifications]);

  const markAsRead = useCallback((id: string) => {
    setNotifications((prev) => prev.map((n) => (n.id === id ? { ...n, read: true } : n)));
  }, []);

  const markAllAsRead = useCallback(() => {
    setNotifications((prev) => prev.map((n) => ({ ...n, read: true })));
  }, []);

  const clearNotification = useCallback((id: string) => {
    setNotifications((prev) => prev.filter((n) => n.id !== id));
  }, []);

  const clearAll = useCallback(() => {
    setNotifications([]);
  }, []);

  const addNotification = useCallback(
    (item: Omit<NotificationItem, 'id' | 'timestamp' | 'read'>) => {
      const newItem: NotificationItem = {
        ...item,
        id: 'notif_' + Math.random().toString(36).substring(2, 9),
        timestamp: Date.now(),
        read: false,
      };
      setNotifications((prev) => [newItem, ...prev]);
    },
    []
  );

  const value = useMemo(
    () => ({
      notifications,
      unreadCount,
      markAsRead,
      markAllAsRead,
      clearNotification,
      clearAll,
      addNotification,
    }),
    [
      notifications,
      unreadCount,
      markAsRead,
      markAllAsRead,
      clearNotification,
      clearAll,
      addNotification,
    ]
  );

  return <NotificationContext.Provider value={value}>{children}</NotificationContext.Provider>;
};

export const useNotifications = (): NotificationContextValue => {
  const ctx = useContext(NotificationContext);
  if (!ctx) throw new Error('useNotifications must be used within NotificationProvider');
  return ctx;
};
