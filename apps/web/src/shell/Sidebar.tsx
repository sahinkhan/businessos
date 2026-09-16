import React from 'react';
import { NavLink } from 'react-router-dom';
import { useNavigation } from '../navigation/NavigationContext';
import { Icon } from '../design-system/icons/iconRegistry';

export const Sidebar: React.FC = () => {
  const { groups, isSidebarCollapsed } = useNavigation();

  const sidebarWidth = isSidebarCollapsed ? '64px' : '240px';

  return (
    <aside
      role="navigation"
      aria-label="Main Navigation"
      style={{
        width: sidebarWidth,
        minWidth: sidebarWidth,
        backgroundColor: 'var(--color-surface-card)',
        borderRight: '1px solid var(--color-border-subtle)',
        display: 'flex',
        flexDirection: 'column',
        height: 'calc(100vh - 56px)',
        position: 'sticky',
        top: '56px',
        transition: 'width 200ms cubic-bezier(0.4, 0, 0.2, 1)',
        overflowX: 'hidden',
        overflowY: 'auto',
      }}
    >
      <div style={{ padding: '12px 8px', display: 'flex', flexDirection: 'column', gap: '16px' }}>
        {groups.map((group) => (
          <div key={group.id}>
            {!isSidebarCollapsed && (
              <div
                style={{
                  padding: '4px 12px',
                  fontSize: '0.6875rem',
                  fontWeight: 600,
                  color: 'var(--color-text-muted)',
                  textTransform: 'uppercase',
                  letterSpacing: '0.05em',
                }}
              >
                {group.label}
              </div>
            )}
            <div style={{ display: 'flex', flexDirection: 'column', gap: '2px', marginTop: '4px' }}>
              {group.items.map((item) => (
                <NavLink
                  key={item.id}
                  to={item.path}
                  end={item.path === '/'}
                  style={({ isActive }) => ({
                    display: 'flex',
                    alignItems: 'center',
                    gap: '10px',
                    padding: isSidebarCollapsed ? '8px 0' : '8px 12px',
                    justifyContent: isSidebarCollapsed ? 'center' : 'flex-start',
                    borderRadius: '6px',
                    fontSize: '0.875rem',
                    fontWeight: isActive ? 600 : 500,
                    textDecoration: 'none',
                    color: isActive ? 'var(--color-action-primary)' : 'var(--color-text-secondary)',
                    backgroundColor: isActive ? 'var(--color-surface-subtle)' : 'transparent',
                    transition: 'all 150ms ease',
                  })}
                  title={isSidebarCollapsed ? item.label : undefined}
                >
                  <Icon name={item.icon || 'Circle'} size={18} />
                  {!isSidebarCollapsed && <span style={{ flex: 1 }}>{item.label}</span>}
                  {!isSidebarCollapsed && item.badge && (
                    <span
                      style={{
                        padding: '1px 6px',
                        borderRadius: '9999px',
                        backgroundColor: 'var(--color-surface-subtle)',
                        fontSize: '0.6875rem',
                        fontWeight: 600,
                      }}
                    >
                      {item.badge}
                    </span>
                  )}
                </NavLink>
              ))}
            </div>
          </div>
        ))}
      </div>
    </aside>
  );
};
