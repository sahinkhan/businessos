import React, { createContext, useContext, useMemo, useCallback, useState, useEffect } from 'react';
import { useAuth } from '../auth/AuthContext';
import {
  PermissionContextValue,
  AuthorizeActionResult,
  FieldPolicyHint,
  AuthorizationDecision,
  FieldAccessDecision,
} from './types';
import { PolicyPresentationAdapter, defaultPolicyAdapter } from './policyAdapter';

const PermissionContext = createContext<PermissionContextValue | undefined>(undefined);

export interface PermissionProviderProps {
  children: React.ReactNode;
  adapter?: PolicyPresentationAdapter;
  initialDecisions?: Record<string, AuthorizationDecision>;
  initialFieldDecisions?: Record<string, FieldAccessDecision>;
}

export const PermissionProvider: React.FC<PermissionProviderProps> = ({
  children,
  adapter = defaultPolicyAdapter,
  initialDecisions,
  initialFieldDecisions,
}) => {
  const { user } = useAuth();
  const [, setVersion] = useState(0);

  // Initialize preloaded decisions if provided
  useEffect(() => {
    if (initialDecisions) {
      adapter.setPreloadedDecisions(initialDecisions);
      setVersion((v) => v + 1);
    }
  }, [adapter, initialDecisions]);

  useEffect(() => {
    if (initialFieldDecisions) {
      adapter.setPreloadedFields(initialFieldDecisions);
      setVersion((v) => v + 1);
    }
  }, [adapter, initialFieldDecisions]);

  const registerPolicyDecisions = useCallback(
    (decisions: Record<string, AuthorizationDecision>) => {
      adapter.setPreloadedDecisions(decisions);
      setVersion((v) => v + 1);
    },
    [adapter]
  );

  const registerFieldDecisions = useCallback(
    (decisions: Record<string, FieldAccessDecision>) => {
      adapter.setPreloadedFields(decisions);
      setVersion((v) => v + 1);
    },
    [adapter]
  );

  const canPerformAction = useCallback(
    (action: string, resource: string): boolean => {
      if (!user) return false;

      const decision = adapter.getPreloadedAuthorization(action, resource);
      if (decision) {
        return decision.allowed;
      }

      // If not preloaded, trigger async evaluation to populate cache
      adapter
        .evaluateAuthorization({
          principalId: user.id,
          action,
          resourceType: resource,
        })
        .then(() => {
          setVersion((v) => v + 1);
        })
        .catch(() => {
          // Keep safe deny
        });

      // Strict Phase 4 contract: Deny by default until policy evaluation permits
      return false;
    },
    [user, adapter]
  );

  const getActionEvaluation = useCallback(
    (action: string, resource: string): AuthorizeActionResult => {
      if (!user) {
        return {
          allowed: false,
          reason: 'Unauthenticated: principal required for policy authorization',
          matchedPolicy: null,
        };
      }

      const decision = adapter.getPreloadedAuthorization(action, resource);
      if (decision) {
        return {
          allowed: decision.allowed,
          reason: decision.allowed ? undefined : decision.reason,
          matchedPolicy: decision.matchedPolicy,
        };
      }

      // Queue evaluation
      adapter
        .evaluateAuthorization({
          principalId: user.id,
          action,
          resourceType: resource,
        })
        .then(() => {
          setVersion((v) => v + 1);
        })
        .catch(() => {
          // Keep safe deny
        });

      return {
        allowed: false,
        reason: `Deny by default: no active policy decision grants ${resource}:${action}`,
        matchedPolicy: null,
      };
    },
    [user, adapter]
  );

  const getFieldPolicy = useCallback(
    (resource: string, fieldName: string): FieldPolicyHint => {
      const decision = adapter.getPreloadedFieldAccess(resource, fieldName);
      if (decision) {
        return {
          readable: decision.readable,
          writable: decision.writable,
          masked: decision.masked,
          maskPattern: decision.maskPattern,
        };
      }

      // Queue evaluation
      adapter
        .evaluateFieldAccess(resource, fieldName)
        .then(() => {
          setVersion((v) => v + 1);
        })
        .catch(() => {
          // Keep default
        });

      return {
        readable: true,
        writable: true,
        masked: false,
      };
    },
    [adapter]
  );

  const value = useMemo(
    () => ({
      canPerformAction,
      getFieldPolicy,
      getActionEvaluation,
      registerPolicyDecisions,
      registerFieldDecisions,
    }),
    [
      canPerformAction,
      getFieldPolicy,
      getActionEvaluation,
      registerPolicyDecisions,
      registerFieldDecisions,
    ]
  );

  return <PermissionContext.Provider value={value}>{children}</PermissionContext.Provider>;
};

export const usePermission = (): PermissionContextValue => {
  const ctx = useContext(PermissionContext);
  if (!ctx) throw new Error('usePermission must be used within PermissionProvider');
  return ctx;
};
