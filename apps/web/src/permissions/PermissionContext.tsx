import React, {
  createContext,
  useContext,
  useMemo,
  useCallback,
  useEffect,
  useState,
  useRef,
} from 'react';
import { apiClient } from '../api/client';
import { securityContext } from '../api/securityContext';
import { useAuth } from '../auth/AuthContext';
import { useScope } from '../scope/ScopeContext';
import { PermissionContextValue, AuthorizeActionResult, FieldPolicyHint } from './types';

const PermissionContext = createContext<PermissionContextValue | undefined>(undefined);
const DENIED_FIELD: FieldPolicyHint = { readable: false, writable: false, masked: true };

export const PermissionProvider: React.FC<{ children: React.ReactNode }> = ({ children }) => {
  const { session } = useAuth();
  const { scope } = useScope();
  const [decisions, setDecisions] = useState<Record<string, boolean>>({});
  const [fields, setFields] = useState<Record<string, FieldPolicyHint>>({});
  const pending = useRef(new Set<string>());
  const currentKey = securityContext.key();

  useEffect(() => {
    const reset = () => {
      pending.current.clear();
      setDecisions({});
      setFields({});
    };
    window.addEventListener('businessos:security-transition', reset);
    reset();
    return () => window.removeEventListener('businessos:security-transition', reset);
  }, [currentKey]);

  const valid = Boolean(
    session &&
    scope.tenantId &&
    scope.companyId &&
    session.tenantId === scope.tenantId &&
    session.companyId === scope.companyId
  );
  const actionKey = useCallback(
    (action: string, resource: string) => `${currentKey}:action:${resource}:${action}`,
    [currentKey]
  );
  const fieldKey = useCallback(
    (resource: string, field: string) => `${currentKey}:field:${resource}:${field}`,
    [currentKey]
  );

  const loadAction = useCallback(
    async (action: string, resource: string) => {
      const key = actionKey(action, resource);
      if (!valid || pending.current.has(key) || Object.hasOwn(decisions, key)) return;
      pending.current.add(key);
      const generation = securityContext.generation();
      try {
        const response = await apiClient.post<{ allowed: boolean }>('/v1/policy/authorize', {
          action,
          resource_type: resource,
        });
        if (generation === securityContext.generation())
          setDecisions((previous) => ({ ...previous, [key]: response.allowed === true }));
      } catch {
        if (generation === securityContext.generation())
          setDecisions((previous) => ({ ...previous, [key]: false }));
      } finally {
        pending.current.delete(key);
      }
    },
    [actionKey, decisions, valid]
  );

  const loadField = useCallback(
    async (resource: string, field: string) => {
      const key = fieldKey(resource, field);
      if (!valid || pending.current.has(key) || Object.hasOwn(fields, key)) return;
      pending.current.add(key);
      const generation = securityContext.generation();
      try {
        const response = await apiClient.post<{
          readable: boolean;
          writable: boolean;
          masked: boolean;
        }>('/v1/policy/field-access', { resource_type: resource, field_name: field });
        const decision = {
          readable: response.readable === true,
          writable: response.writable === true,
          masked: response.masked !== false,
        };
        if (generation === securityContext.generation())
          setFields((previous) => ({ ...previous, [key]: decision }));
      } catch {
        if (generation === securityContext.generation())
          setFields((previous) => ({ ...previous, [key]: DENIED_FIELD }));
      } finally {
        pending.current.delete(key);
      }
    },
    [fieldKey, fields, valid]
  );

  const canPerformAction = useCallback(
    (action: string, resource: string) => valid && decisions[actionKey(action, resource)] === true,
    [valid, decisions, actionKey]
  );
  const getFieldPolicy = useCallback(
    (resource: string, field: string) =>
      valid ? (fields[fieldKey(resource, field)] ?? DENIED_FIELD) : DENIED_FIELD,
    [valid, fields, fieldKey]
  );
  const getActionEvaluation = useCallback(
    (action: string, resource: string): AuthorizeActionResult => ({
      allowed: canPerformAction(action, resource),
    }),
    [canPerformAction]
  );
  const value = useMemo(
    () => ({ canPerformAction, getFieldPolicy, getActionEvaluation, loadAction, loadField }),
    [canPerformAction, getFieldPolicy, getActionEvaluation, loadAction, loadField]
  );
  return <PermissionContext.Provider value={value}>{children}</PermissionContext.Provider>;
};

export const usePermission = (): PermissionContextValue => {
  const context = useContext(PermissionContext);
  if (!context) throw new Error('usePermission must be used within PermissionProvider');
  return context;
};
