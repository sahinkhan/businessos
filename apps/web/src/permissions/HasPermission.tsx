import React from 'react';
import { usePermission } from './PermissionContext';

export interface HasPermissionProps {
  action: string;
  resource: string;
  children: (allowed: boolean) => React.ReactNode;
}

export const HasPermission: React.FC<HasPermissionProps> = ({ action, resource, children }) => {
  const { canPerformAction } = usePermission();
  const allowed = canPerformAction(action, resource);
  return <>{children(allowed)}</>;
};
