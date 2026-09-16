import React from 'react';
import { usePermission } from './PermissionContext';

export interface FieldPolicyWrapperProps {
  resource: string;
  field: string;
  children: React.ReactElement;
}

export const FieldPolicyWrapper: React.FC<FieldPolicyWrapperProps> = ({
  resource,
  field,
  children,
}) => {
  const { getFieldPolicy } = usePermission();
  const policy = getFieldPolicy(resource, field);

  if (!policy.readable) {
    return null;
  }

  if (policy.masked) {
    return <span style={{ color: 'var(--color-text-muted)', fontStyle: 'italic' }}>••••••••</span>;
  }

  if (!policy.writable) {
    return React.cloneElement(children, {
      disabled: true,
      readOnly: true,
    });
  }

  return children;
};
