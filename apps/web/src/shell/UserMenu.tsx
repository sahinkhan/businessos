import React from 'react';
import { useAuth } from '../auth/AuthContext';
import { Dropdown } from '../components/overlays/Dropdown';
import { LogOut, ShieldCheck, User } from 'lucide-react';

export const UserMenu: React.FC = () => {
  const { user, logout } = useAuth();
  if (!user) return null;

  const initials = user.name
    .split(' ')
    .map((part) => part.charAt(0))
    .join('')
    .substring(0, 2)
    .toUpperCase();

  const trigger = (
    <button type="button" aria-label="User profile and settings">
      <span>{initials || 'U'}</span>
    </button>
  );

  return (
    <Dropdown
      trigger={trigger}
      items={[
        {
          id: 'user_header',
          label: (
            <div>
              <strong>{user.name}</strong>
              <div>{user.email}</div>
            </div>
          ),
          onClick: () => undefined,
        },
        { divider: true },
        {
          id: 'opt_profile',
          label: 'Account Details',
          icon: <User size={14} />,
          onClick: () => undefined,
        },
        {
          id: 'opt_security',
          label: 'Session Security',
          icon: <ShieldCheck size={14} />,
          onClick: () => undefined,
        },
        { divider: true },
        {
          id: 'opt_logout',
          label: 'Sign out',
          icon: <LogOut size={14} />,
          danger: true,
          onClick: () => void logout(),
        },
      ]}
    />
  );
};
