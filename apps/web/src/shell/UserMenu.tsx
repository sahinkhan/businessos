import React from 'react';
import { useAuth } from '../auth/AuthContext';
import { Dropdown } from '../components/overlays/Dropdown';
import { User, LogOut, ShieldCheck } from 'lucide-react';

export const UserMenu: React.FC = () => {
  const { user, logout } = useAuth();

  if (!user) return null;

  const initials = user.name
    .split(' ')
    .map((s) => s.charAt(0))
    .join('')
    .substring(0, 2)
    .toUpperCase();

  const trigger = (
    <button
      type="button"
      aria-label="User profile and settings"
      style={{
        display: 'flex',
        alignItems: 'center',
        gap: '8px',
        background: 'none',
        border: 'none',
        cursor: 'pointer',
        padding: '2px 4px',
        borderRadius: '6px',
        outline: 'none',
      }}
    >
      <div
        style={{
          width: '32px',
          height: '32px',
          borderRadius: '50%',
          backgroundColor: 'var(--color-action-primary)',
          color: 'white',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
          fontSize: '0.8125rem',
          fontWeight: 600,
        }}
      >
        {initials || 'U'}
      </div>
    </button>
  );

  return (
    <Dropdown
      trigger={trigger}
      items={[
        {
          id: 'user_header',
          label: (
            <div style={{ lineHeight: 1.3 }}>
              <div style={{ fontWeight: 600 }}>{user.name}</div>
              <div style={{ fontSize: '0.75rem', color: 'var(--color-text-muted)' }}>
                {user.email}
              </div>
              <div style={{ display: 'flex', gap: '4px', marginTop: '4px' }}>
                {user.roles.map((r) => (
                  <span
                    key={r}
                    style={{
                      fontSize: '0.6875rem',
                      padding: '1px 6px',
                      backgroundColor: 'var(--color-surface-subtle)',
                      borderRadius: '4px',
                      color: 'var(--color-action-primary)',
                      fontWeight: 600,
                    }}
                  >
                    {r}
                  </span>
                ))}
              </div>
            </div>
          ),
          onClick: () => {},
        },
        { divider: true },
        {
          id: 'opt_profile',
          label: 'Account Details',
          icon: <User size={14} />,
          onClick: () => {},
        },
        {
          id: 'opt_security',
          label: 'Security & Tokens',
          icon: <ShieldCheck size={14} />,
          onClick: () => {},
        },
        { divider: true },
        {
          id: 'opt_logout',
          label: 'Sign out',
          icon: <LogOut size={14} />,
          danger: true,
          onClick: () => logout(),
        },
      ]}
    />
  );
};
