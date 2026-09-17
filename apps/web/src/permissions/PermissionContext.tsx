import React, {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
} from 'react';
import { useAuth } from '../auth/AuthContext';
import { useScope } from '../scope/ScopeContext';
import { PolicyPresentationAdapter, defaultPolicyAdapter } from './policyAdapter';
import {
  AuthorizeActionResult,
  FieldPolicyHint,
  PermissionContextValue,
  PolicySecurityContext,
} from './types';

const PermissionContext = createContext<PermissionContextValue | undefined>(undefined);
const FAIL_CLOSED_FIELD: FieldPolicyHint = {
  readable: false,
  writable: false,
  masked: true,
};

export interface PermissionProviderProps {
  children: React.ReactNode;
  adapter?: PolicyPresentationAdapter;
}

export const PermissionProvider: React.FC<PermissionProviderProps> = ({
  children,
  adapter = defaultPolicyAdapter,
}) => {
  const { user, isAuthenticated } = useAuth();
  const { scope, status } = useScope();
  const [version, setVersion] = useState(0);
  const pending = useRef(new Set<string>());

  const securityContext = useMemo<PolicySecurityContext | null>(
    () =>
      isAuthenticated && user && scope && status === 'ready'
        ? {
            principalId: user.id,
            tenantId: scope.tenantId,
            legalEntityId: scope.legalEntityId,
            companyId: scope.companyId,
            siteId: scope.siteId,
          }
        : null,
    [isAuthenticated, user, scope, status]
  );

  const securityKey = securityContext
    ? [
        securityContext.principalId,
        securityContext.tenantId,
        securityContext.legalEntityId ?? '',
        securityContext.companyId ?? '',
        securityContext.siteId ?? '',
      ].join('|')
    : 'untrusted';

  useEffect(() => {
    adapter.clearCache();
    pending.current.clear();
    setVersion((current) => current + 1);
  }, [adapter, securityKey]);

  const queueAuthorization = useCallback(
    (action: string, resource: string) => {
      if (!securityContext) return;
      const key = `action|${securityKey}|${resource}|${action}`;
      if (pending.current.has(key)) return;
      pending.current.add(key);
      void adapter
        .evaluateAuthorization({
          ...securityContext,
          action,
          resourceType: resource,
        })
        .finally(() => {
          pending.current.delete(key);
          setVersion((current) => current + 1);
        });
    },
    [adapter, securityContext, securityKey]
  );

  const queueField = useCallback(
    (resource: string, fieldName: string) => {
      if (!securityContext) return;
      const key = `field|${securityKey}|${resource}|${fieldName}`;
      if (pending.current.has(key)) return;
      pending.current.add(key);
      void adapter.evaluateFieldAccess(resource, fieldName, securityContext).finally(() => {
        pending.current.delete(key);
        setVersion((current) => current + 1);
      });
    },
    [adapter, securityContext, securityKey]
  );

  const canPerformAction = useCallback(
    (action: string, resource: string): boolean => {
      void version;
      if (!securityContext) return false;
      const decision = adapter.getCachedAuthorization(action, resource, securityContext);
      if (!decision) queueAuthorization(action, resource);
      return decision?.allowed === true;
    },
    [adapter, queueAuthorization, securityContext, version]
  );

  const getActionEvaluation = useCallback(
    (action: string, resource: string): AuthorizeActionResult => {
      void version;
      if (!securityContext) {
        return {
          allowed: false,
          reason: 'Deny by default: trusted principal and scope required',
          matchedPolicy: null,
        };
      }
      const decision = adapter.getCachedAuthorization(action, resource, securityContext);
      if (!decision) {
        queueAuthorization(action, resource);
        return {
          allowed: false,
          reason: 'Deny by default: policy decision pending',
          matchedPolicy: null,
        };
      }
      return {
        allowed: decision.allowed,
        reason: decision.allowed ? undefined : decision.reason,
        matchedPolicy: decision.matchedPolicy,
      };
    },
    [adapter, queueAuthorization, securityContext, version]
  );

  const getFieldPolicy = useCallback(
    (resource: string, fieldName: string): FieldPolicyHint => {
      void version;
      if (!securityContext) return FAIL_CLOSED_FIELD;
      const decision = adapter.getCachedFieldAccess(resource, fieldName, securityContext);
      if (!decision) {
        queueField(resource, fieldName);
        return FAIL_CLOSED_FIELD;
      }
      return {
        readable: decision.readable,
        writable: decision.writable,
        masked: decision.masked,
        maskPattern: decision.maskPattern,
      };
    },
    [adapter, queueField, securityContext, version]
  );

  const value = useMemo<PermissionContextValue>(
    () => ({ canPerformAction, getFieldPolicy, getActionEvaluation }),
    [canPerformAction, getFieldPolicy, getActionEvaluation]
  );

  return <PermissionContext.Provider value={value}>{children}</PermissionContext.Provider>;
};

export const usePermission = (): PermissionContextValue => {
  const context = useContext(PermissionContext);
  if (!context) throw new Error('usePermission must be used within PermissionProvider');
  return context;
};
