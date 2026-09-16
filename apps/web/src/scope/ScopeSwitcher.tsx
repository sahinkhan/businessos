import React, { useState, useRef, useEffect } from 'react';
import { Building2, ChevronDown, Check } from 'lucide-react';
import { useScope } from './ScopeContext';

export const ScopeSwitcher: React.FC = () => {
  const { scope, tenants, setTenant, setCompany, setSite } = useScope();
  const [isOpen, setIsOpen] = useState(false);
  const containerRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const handleOutside = (e: MouseEvent) => {
      if (containerRef.current && !containerRef.current.contains(e.target as Node)) {
        setIsOpen(false);
      }
    };
    document.addEventListener('mousedown', handleOutside);
    return () => document.removeEventListener('mousedown', handleOutside);
  }, []);

  const currentTenant = tenants.find((t) => t.id === scope.tenantId) || tenants[0];

  return (
    <div ref={containerRef} style={{ position: 'relative' }}>
      <button
        type="button"
        onClick={() => setIsOpen(!isOpen)}
        aria-expanded={isOpen}
        aria-label="Switch organization scope"
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
          outline: 'none',
        }}
      >
        <Building2 size={16} color="var(--color-action-primary)" />
        <div style={{ textAlign: 'left', lineHeight: 1.2 }}>
          <div style={{ fontWeight: 600 }}>{scope.companyName}</div>
          <div style={{ fontSize: '0.6875rem', color: 'var(--color-text-muted)' }}>
            {scope.siteName}
          </div>
        </div>
        <ChevronDown size={14} color="var(--color-text-muted)" />
      </button>

      {isOpen && (
        <div
          role="dialog"
          aria-label="Scope Selector"
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
              style={{
                fontSize: '0.75rem',
                fontWeight: 600,
                color: 'var(--color-text-muted)',
                display: 'block',
                marginBottom: '4px',
              }}
            >
              TENANT
            </label>
            <select
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
            <label
              style={{
                fontSize: '0.75rem',
                fontWeight: 600,
                color: 'var(--color-text-muted)',
                display: 'block',
                marginBottom: '6px',
              }}
            >
              LEGAL ENTITIES & SITES
            </label>
            {currentTenant.groups.map((group) => (
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
                      <div
                        onClick={() => {
                          setCompany(company.id);
                        }}
                        style={{
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
                      </div>

                      {/* Sites */}
                      {isCurrentCompany && (
                        <div style={{ marginLeft: '12px', marginTop: '2px' }}>
                          {company.sites.map((site) => {
                            const isCurrentSite = site.id === scope.siteId;
                            return (
                              <div
                                key={site.id}
                                onClick={(e) => {
                                  e.stopPropagation();
                                  setSite(site.id);
                                  setIsOpen(false);
                                }}
                                style={{
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
                              </div>
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
