import React, { createContext, useContext, useMemo, useCallback } from 'react';
import { useAuth } from '../auth/AuthContext';
import { PermissionContextValue, AuthorizeActionResult, FieldPolicyHint } from './types';

const PermissionContext = createContext<PermissionContextValue | undefined>(undefined);

export const PermissionProvider: React.FC<{ children: React.ReactNode }> = ({ children }) => {
  const { user } = useAuth();

  // Consumes policy hints without duplicating backend engine
  const canPerformAction = useCallback(
    (action: string, resource: string): boolean => {
      if (!user) return false;
      if (user.roles.includes('admin') || user.permissions.includes('*')) return true;
      const required = `${resource}:${action}`;
      return user.permissions.includes(required) || user.permissions.includes(action);
    },
    [user]
  );

  const getActionEvaluation = useCallback(
    (action: string, resource: string): AuthorizeActionResult => {
      const allowed = canPerformAction(action, resource);
      return {
        allowed,
        reason: allowed
          ? undefined
          : `Authorization denied: Missing policy grant for ${resource}:${action}`,
      };
    },
    [canPerformAction]
  );

  const getFieldPolicy = useCallback((_resource: string, _fieldName: string): FieldPolicyHint => {
    // Default standard field policy
    return {
      readable: true,
      writable: true,
      masked: false,
    };
  }, []);

  const value = useMemo(
    () => ({
      canPerformAction,
      getFieldPolicy,
      getActionEvaluation,
    }),
    [canPerformAction, getFieldPolicy, getActionEvaluation]
  );

  return <PermissionContext.Provider value={value}>{children}</PermissionContext.Provider>;
};

export const usePermission = (): PermissionContextValue => {
  const ctx = useContext(PermissionContext);
  if (!ctx) throw new Error('usePermission must be used within PermissionProvider');
  return ctx;
};
