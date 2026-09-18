import React from 'react';
import { useAuth } from '../auth/AuthContext';
import { Dropdown } from '../components/overlays/Dropdown';
import { LogOut, ShieldCheck, User } from 'lucide-react';
import { useI18n } from '../i18n/I18nContext';

export const UserMenu: React.FC = () => {
  const { user, logout } = useAuth();
  const { t } = useI18n();
  if (!user) return null;

  const initials = user.name
    .split(' ')
    .map((part) => part.charAt(0))
    .join('')
    .substring(0, 2)
    .toUpperCase();

  const trigger = (
    <button type="button" aria-label={t('shell.user_menu')}>
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
          label: t('shell.account_details'),
          icon: <User size={14} />,
          onClick: () => undefined,
        },
        {
          id: 'opt_security',
          label: t('shell.session_security'),
          icon: <ShieldCheck size={14} />,
          onClick: () => undefined,
        },
        { divider: true },
        {
          id: 'opt_logout',
          label: t('nav.logout'),
          icon: <LogOut size={14} />,
          danger: true,
          onClick: () => void logout(),
        },
      ]}
    />
  );
};
