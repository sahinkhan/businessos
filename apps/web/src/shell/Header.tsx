import React from 'react';
import { Menu, Sun, Moon, Bell, Search, Globe } from 'lucide-react';
import { useNavigation } from '../navigation/NavigationContext';
import { useTheme } from '../design-system/theme/ThemeContext';
import { useI18n } from '../i18n/I18nContext';
import { useNotifications } from '../notifications/NotificationContext';
import { ScopeSwitcher } from '../scope/ScopeSwitcher';
import { UserMenu } from './UserMenu';
import { IconButton } from '../components/actions/IconButton';
import { Dropdown } from '../components/overlays/Dropdown';

export interface HeaderProps {
  onOpenNotifications: () => void;
}

export const Header: React.FC<HeaderProps> = ({ onOpenNotifications }) => {
  const { toggleSidebar, setMobileDrawerOpen } = useNavigation();
  const { resolvedTheme, toggleTheme } = useTheme();
  const { locale, setLocale } = useI18n();
  const { unreadCount } = useNotifications();

  return (
    <header
      role="banner"
      style={{
        height: '56px',
        backgroundColor: 'var(--color-surface-header)',
        borderBottom: '1px solid var(--color-border-subtle)',
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'space-between',
        padding: '0 16px',
        position: 'sticky',
        top: 0,
        zIndex: 100,
      }}
    >
      {/* Left side: Hamburger, Logo, Scope */}
      <div style={{ display: 'flex', alignItems: 'center', gap: '12px' }}>
        <IconButton
          icon={<Menu size={18} />}
          aria-label="Toggle navigation menu"
          variant="ghost"
          size="sm"
          onClick={() => {
            if (window.innerWidth < 768) {
              setMobileDrawerOpen(true);
            } else {
              toggleSidebar();
            }
          }}
        />
        <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
          <span
            style={{
              fontSize: '1.125rem',
              fontWeight: 700,
              color: 'var(--color-text-primary)',
              letterSpacing: '-0.5px',
            }}
          >
            BusinessOS
          </span>
          <span
            style={{
              fontSize: '0.6875rem',
              backgroundColor: 'var(--color-surface-subtle)',
              color: 'var(--color-action-primary)',
              padding: '1px 6px',
              borderRadius: '9999px',
              fontWeight: 600,
            }}
          >
            v0.4.5
          </span>
        </div>
        <div style={{ marginLeft: '8px' }}>
          <ScopeSwitcher />
        </div>
      </div>

      {/* Right side: Global search trigger, Notifications, Theme toggle, Locale, User menu */}
      <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
        <button
          type="button"
          onClick={() => {
            window.dispatchEvent(new KeyboardEvent('keydown', { key: 'k', metaKey: true }));
          }}
          aria-label="Search or run command"
          style={{
            display: 'flex',
            alignItems: 'center',
            gap: '8px',
            padding: '4px 10px',
            borderRadius: '6px',
            backgroundColor: 'var(--color-surface-subtle)',
            border: '1px solid var(--color-border-subtle)',
            color: 'var(--color-text-muted)',
            fontSize: '0.8125rem',
            cursor: 'pointer',
            height: '32px',
          }}
        >
          <Search size={14} />
          <span>Search...</span>
          <kbd
            style={{
              padding: '1px 4px',
              borderRadius: '3px',
              backgroundColor: 'var(--color-surface-card)',
              border: '1px solid var(--color-border-subtle)',
              fontSize: '0.625rem',
              lineHeight: 1,
            }}
          >
            ⌘K
          </kbd>
        </button>

        {/* Notifications */}
        <div style={{ position: 'relative' }}>
          <IconButton
            icon={<Bell size={18} />}
            aria-label={`Notifications (${unreadCount} unread)`}
            variant="ghost"
            size="sm"
            onClick={onOpenNotifications}
          />
          {unreadCount > 0 && (
            <span
              style={{
                position: 'absolute',
                top: '4px',
                right: '4px',
                width: '8px',
                height: '8px',
                backgroundColor: 'var(--color-action-danger)',
                borderRadius: '50%',
                pointerEvents: 'none',
              }}
            />
          )}
        </div>

        {/* Language selector */}
        <Dropdown
          trigger={
            <IconButton
              icon={<Globe size={18} />}
              aria-label="Select Language"
              variant="ghost"
              size="sm"
            />
          }
          items={[
            {
              id: 'en',
              label: 'English (LTR)' + (locale === 'en' ? ' ✓' : ''),
              onClick: () => setLocale('en'),
            },
            {
              id: 'ar',
              label: 'العربية (RTL)' + (locale === 'ar' ? ' ✓' : ''),
              onClick: () => setLocale('ar'),
            },
            {
              id: 'es',
              label: 'Español (LTR)' + (locale === 'es' ? ' ✓' : ''),
              onClick: () => setLocale('es'),
            },
          ]}
        />

        {/* Theme toggle */}
        <IconButton
          icon={resolvedTheme === 'dark' ? <Sun size={18} /> : <Moon size={18} />}
          aria-label="Toggle Theme"
          variant="ghost"
          size="sm"
          onClick={toggleTheme}
        />

        <div
          style={{
            height: '20px',
            width: '1px',
            backgroundColor: 'var(--color-border-subtle)',
            margin: '0 4px',
          }}
        />

        {/* User profile menu */}
        <UserMenu />
      </div>
    </header>
  );
};
