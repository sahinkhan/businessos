import React, { useState, useRef, useEffect, useId } from 'react';
import { Building2, ChevronDown, Check } from 'lucide-react';
import { useScope } from './ScopeContext';
import { useI18n } from '../i18n/I18nContext';

export const ScopeSwitcher: React.FC = () => {
  const { scope, tenants, isLoading, setTenant, setCompany, setSite } = useScope();
  const { t } = useI18n();
  const [isOpen, setIsOpen] = useState(false);
  const containerRef = useRef<HTMLDivElement>(null);
  const triggerRef = useRef<HTMLButtonElement>(null);
  const companyRef = useRef<HTMLButtonElement>(null);
  const siteRef = useRef<HTMLButtonElement>(null);
  const pendingFocus = useRef<
    | { kind: 'company'; tenantId: string; companyId: string; transitionObserved: boolean }
    | { kind: 'site'; tenantId: string; transitionObserved: boolean }
    | null
  >(null);
  const tenantSelectId = useId();

  useEffect(() => {
    const handleOutside = (e: MouseEvent) => {
      if (containerRef.current && !containerRef.current.contains(e.target as Node)) {
        pendingFocus.current = null;
        setIsOpen(false);
      }
    };
    document.addEventListener('mousedown', handleOutside);
    return () => document.removeEventListener('mousedown', handleOutside);
  }, []);

  useEffect(() => {
    const pending = pendingFocus.current;
    if (!pending) return;
    if (isLoading || tenants.length === 0 || !scope.companyId) {
      pending.transitionObserved = true;
      return;
    }
    if (!pending.transitionObserved) return;

    const activeTenant = tenants.find((tenant) => tenant.id === scope.tenantId);
    const activeCompany = activeTenant?.groups
      .find((group) => group.id === scope.groupId)
      ?.companies.find((company) => company.id === scope.companyId);
    if (!activeCompany || scope.tenantId !== pending.tenantId) {
      pendingFocus.current = null;
      return;
    }

    const target =
      pending.kind === 'company' && scope.companyId === pending.companyId && isOpen
        ? (siteRef.current ?? companyRef.current ?? triggerRef.current)
        : triggerRef.current;
    pendingFocus.current = null;
    const activeElement = document.activeElement;
    if (activeElement === document.body || containerRef.current?.contains(activeElement)) {
      target?.focus();
    }
  }, [isLoading, scope, tenants, isOpen]);

  const currentTenant = tenants.find((t) => t.id === scope.tenantId) || tenants[0];

  return (
    <div ref={containerRef} style={{ position: 'relative' }}>
      <button
        ref={triggerRef}
        type="button"
        disabled={tenants.length === 0}
        onClick={() => {
          if (isOpen) pendingFocus.current = null;
          setIsOpen(!isOpen);
        }}
        aria-expanded={isOpen}
        aria-label={t('scope.switch')}
        style={{
          display: 'flex',
          alignItems: 'center',
          gap: '8px',
          padding: '6px 10px',
          borderRadius: '6px',
          backgroundColor: 'var(--color-surface-subtle)',
          border: '1px solid var(--color-border-subtle)',
          color: 'var(--color-text-primary)',
          fontSize: '0.8125rem',
          cursor: 'pointer',
        }}
      >
        <Building2 size={16} color="var(--color-action-primary)" />
        <div style={{ textAlign: 'left', lineHeight: 1.2 }}>
          <div style={{ fontWeight: 600 }}>{scope.companyName || t('scope.select')}</div>
          <div style={{ fontSize: '0.6875rem', color: 'var(--color-text-muted)' }}>
            {scope.siteName}
          </div>
        </div>
        <ChevronDown size={14} color="var(--color-text-muted)" />
      </button>

      {isOpen && (
        <div
          className="businessos-scope-popover"
          role="dialog"
          aria-label={t('scope.selector')}
          onKeyDown={(event) => {
            if (event.key === 'Escape') {
              pendingFocus.current = null;
              setIsOpen(false);
              triggerRef.current?.focus();
            }
          }}
          style={{
            position: 'absolute',
            top: '100%',
            left: 0,
            marginTop: '6px',
            width: '320px',
            backgroundColor: 'var(--color-surface-card)',
            border: '1px solid var(--color-border-subtle)',
            borderRadius: '8px',
            boxShadow: 'var(--shadow-dropdown)',
            zIndex: 1400,
            padding: '12px',
          }}
        >
          {/* Tenant selection */}
          <div style={{ marginBottom: '12px' }}>
            <label
              htmlFor={tenantSelectId}
              style={{
                fontSize: '0.75rem',
                fontWeight: 600,
                color: 'var(--color-text-muted)',
                display: 'block',
                marginBottom: '4px',
              }}
            >
              {t('scope.tenant')}
            </label>
            <select
              id={tenantSelectId}
              value={scope.tenantId}
              onChange={(e) => setTenant(e.target.value)}
              style={{
                width: '100%',
                padding: '6px 8px',
                borderRadius: '4px',
                border: '1px solid var(--color-border-default)',
                backgroundColor: 'var(--color-surface-card)',
                color: 'var(--color-text-primary)',
                fontSize: '0.8125rem',
              }}
            >
              {tenants.map((t) => (
                <option key={t.id} value={t.id}>
                  {t.name}
                </option>
              ))}
            </select>
          </div>

          {/* Companies & Sites in Tenant */}
          <div style={{ maxHeight: '220px', overflowY: 'auto' }}>
            <div
              style={{
                fontSize: '0.75rem',
                fontWeight: 600,
                color: 'var(--color-text-muted)',
                display: 'block',
                marginBottom: '6px',
              }}
            >
              {t('scope.entities_sites')}
            </div>
            {currentTenant?.groups.map((group) => (
              <div key={group.id} style={{ marginBottom: '8px' }}>
                <div
                  style={{
                    fontSize: '0.6875rem',
                    fontWeight: 600,
                    color: 'var(--color-text-secondary)',
                    padding: '2px 4px',
                  }}
                >
                  {group.name}
                </div>
                {group.companies.map((company) => {
                  const isCurrentCompany = company.id === scope.companyId;
                  return (
                    <div key={company.id} style={{ marginLeft: '6px', marginBottom: '4px' }}>
                      <button
                        ref={isCurrentCompany ? companyRef : null}
                        type="button"
                        aria-current={isCurrentCompany ? 'true' : undefined}
                        onClick={(event) => {
                          pendingFocus.current =
                            event.detail === 0
                              ? {
                                  kind: 'company',
                                  tenantId: scope.tenantId,
                                  companyId: company.id,
                                  transitionObserved: false,
                                }
                              : null;
                          setCompany(company.id);
                        }}
                        style={{
                          width: '100%',
                          border: 0,
                          textAlign: 'start',
                          fontFamily: 'inherit',
                          fontSize: '0.8125rem',
                          fontWeight: isCurrentCompany ? 600 : 400,
                          padding: '4px 6px',
                          borderRadius: '4px',
                          cursor: 'pointer',
                          backgroundColor: isCurrentCompany
                            ? 'var(--color-surface-subtle)'
                            : 'transparent',
                          color: isCurrentCompany
                            ? 'var(--color-action-primary)'
                            : 'var(--color-text-primary)',
                          display: 'flex',
                          alignItems: 'center',
                          justifyContent: 'space-between',
                        }}
                      >
                        <span>
                          {company.name} ({company.code})
                        </span>
                        {isCurrentCompany && <Check size={14} />}
                      </button>

                      {/* Sites */}
                      {isCurrentCompany && (
                        <div style={{ marginLeft: '12px', marginTop: '2px' }}>
                          {company.sites.map((site) => {
                            const isCurrentSite = site.id === scope.siteId;
                            return (
                              <button
                                key={site.id}
                                ref={
                                  site.id ===
                                  (company.sites.find((item) => item.id === scope.siteId)?.id ??
                                    company.sites[0]?.id)
                                    ? siteRef
                                    : null
                                }
                                type="button"
                                aria-current={isCurrentSite ? 'true' : undefined}
                                onClick={(e) => {
                                  e.stopPropagation();
                                  pendingFocus.current =
                                    e.detail === 0
                                      ? {
                                          kind: 'site',
                                          tenantId: scope.tenantId,
                                          transitionObserved: false,
                                        }
                                      : null;
                                  setSite(site.id);
                                  setIsOpen(false);
                                }}
                                style={{
                                  display: 'block',
                                  width: '100%',
                                  border: 0,
                                  textAlign: 'start',
                                  fontFamily: 'inherit',
                                  fontSize: '0.75rem',
                                  padding: '3px 6px',
                                  borderRadius: '4px',
                                  cursor: 'pointer',
                                  color: isCurrentSite
                                    ? 'var(--color-action-primary)'
                                    : 'var(--color-text-secondary)',
                                  backgroundColor: isCurrentSite
                                    ? 'var(--color-surface-subtle)'
                                    : 'transparent',
                                  fontWeight: isCurrentSite ? 600 : 400,
                                }}
                              >
                                • {site.name}
                              </button>
                            );
                          })}
                        </div>
                      )}
                    </div>
                  );
                })}
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
};
