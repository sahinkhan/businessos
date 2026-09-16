export type NotificationSeverity = 'info' | 'success' | 'warning' | 'error';
export type NotificationCategory = 'all' | 'unread' | 'actionable';

export interface NotificationItem {
  id: string;
  title: string;
  message: string;
  severity: NotificationSeverity;
  timestamp: number;
  read: boolean;
  actionUrl?: string;
  actionLabel?: string;
}

export interface NotificationContextValue {
  notifications: NotificationItem[];
  unreadCount: number;
  markAsRead: (id: string) => void;
  markAllAsRead: () => void;
  clearNotification: (id: string) => void;
  clearAll: () => void;
  addNotification: (item: Omit<NotificationItem, 'id' | 'timestamp' | 'read'>) => void;
}
