import React from 'react';
import { Link, useLocation } from 'react-router-dom';
import { ChevronRight, Home } from 'lucide-react';
import { useI18n } from '../i18n/I18nContext';

export const Breadcrumbs: React.FC = () => {
  const location = useLocation();
  const { t } = useI18n();
  const pathnames = location.pathname.split('/').filter(Boolean);

  if (pathnames.length === 0) return null;

  return (
    <nav
      aria-label={t('shell.breadcrumb')}
      style={{
        display: 'flex',
        alignItems: 'center',
        gap: '6px',
        fontSize: '0.8125rem',
        color: 'var(--color-text-muted)',
        marginBottom: '16px',
      }}
    >
      <Link
        to="/"
        style={{
          display: 'inline-flex',
          alignItems: 'center',
          color: 'var(--color-text-muted)',
          textDecoration: 'none',
        }}
        aria-label={t('shell.dashboard_home')}
      >
        <Home size={14} />
      </Link>
      {pathnames.map((name, index) => {
        const routeTo = `/${pathnames.slice(0, index + 1).join('/')}`;
        const isLast = index === pathnames.length - 1;
        const formatted = name
          .split('-')
          .map((s) => s.charAt(0).toUpperCase() + s.slice(1))
          .join(' ');

        return (
          <React.Fragment key={routeTo}>
            <ChevronRight size={12} style={{ opacity: 0.5 }} />
            {isLast ? (
              <span
                aria-current="page"
                style={{ fontWeight: 600, color: 'var(--color-text-primary)' }}
              >
                {formatted}
              </span>
            ) : (
              <Link
                to={routeTo}
                style={{ color: 'var(--color-text-muted)', textDecoration: 'none' }}
              >
                {formatted}
              </Link>
            )}
          </React.Fragment>
        );
      })}
    </nav>
  );
};
