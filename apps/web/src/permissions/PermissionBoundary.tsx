import React from 'react';
import { usePermission } from './PermissionContext';
import { Tooltip } from '../components/overlays/Tooltip';

export interface PermissionBoundaryProps {
  action: string;
  resource: string;
  fallback?: React.ReactNode;
  disableInsteadOfHide?: boolean;
  children: React.ReactElement;
}

export const PermissionBoundary: React.FC<PermissionBoundaryProps> = ({
  action,
  resource,
  fallback = null,
  disableInsteadOfHide = false,
  children,
}) => {
  const { getActionEvaluation } = usePermission();
  const evalResult = getActionEvaluation(action, resource);

  if (evalResult.allowed) {
    return children;
  }

  if (disableInsteadOfHide) {
    const disabledChild = React.cloneElement(children, {
      disabled: true,
      'aria-disabled': 'true',
    });

    return (
      <Tooltip content={evalResult.reason || 'You do not have permission to perform this action'}>
        <span style={{ display: 'inline-block', cursor: 'not-allowed' }}>{disabledChild}</span>
      </Tooltip>
    );
  }

  return <>{fallback}</>;
};
