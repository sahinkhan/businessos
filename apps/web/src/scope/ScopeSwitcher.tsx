import React, { useEffect, useRef, useState } from 'react';
import { Building2, Check, ChevronDown } from 'lucide-react';
import { useScope } from './ScopeContext';

export const ScopeSwitcher: React.FC = () => {
  const { scope, tenants, status, error, setTenant, setCompany, setSite } = useScope();
  const [isOpen, setIsOpen] = useState(false);
  const containerRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const handleOutside = (event: MouseEvent) => {
      if (containerRef.current && !containerRef.current.contains(event.target as Node)) {
        setIsOpen(false);
      }
    };
    document.addEventListener('mousedown', handleOutside);
    return () => document.removeEventListener('mousedown', handleOutside);
  }, []);

  if (!scope || status === 'loading' || status === 'unavailable') {
    return (
      <button type="button" disabled aria-label="Organization scope unavailable">
        <Building2 size={16} />{' '}
        {status === 'loading' ? 'Loading scope…' : (error ?? 'Scope unavailable')}
      </button>
    );
  }

  const currentTenant = tenants.find((tenant) => tenant.id === scope.tenantId);

  return (
    <div ref={containerRef} style={{ position: 'relative' }}>
      <button
        type="button"
        onClick={() => setIsOpen((open) => !open)}
        aria-expanded={isOpen}
        aria-label="Switch organization scope"
        disabled={status === 'switching'}
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
        <span>
          {scope.companyName} · {scope.siteName}
        </span>
        <ChevronDown size={14} />
      </button>
      {isOpen && currentTenant && (
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
          <label htmlFor="tenant-scope">Tenant</label>
          <select
            id="tenant-scope"
            value={scope.tenantId}
            onChange={(event) => void setTenant(event.target.value)}
          >
            {tenants.map((tenant) => (
              <option key={tenant.id} value={tenant.id}>
                {tenant.name}
              </option>
            ))}
          </select>
          {currentTenant.groups.map((group) => (
            <div key={group.id}>
              <strong>{group.name}</strong>
              {group.companies.map((company) => (
                <div key={company.id}>
                  <button type="button" onClick={() => void setCompany(company.id)}>
                    {company.name} {company.id === scope.companyId && <Check size={14} />}
                  </button>
                  {company.id === scope.companyId &&
                    company.sites.map((site) => (
                      <button
                        type="button"
                        key={site.id}
                        onClick={() => {
                          void setSite(site.id);
                          setIsOpen(false);
                        }}
                      >
                        {site.name} {site.id === scope.siteId && <Check size={14} />}
                      </button>
                    ))}
                </div>
              ))}
            </div>
          ))}
        </div>
      )}
    </div>
  );
};
