import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { I18nProvider, useI18n } from '../../src/i18n/I18nContext';
import { navigationRegistry } from '../../src/navigation/registry';
import { ar } from '../../src/i18n/translations/ar';
import { es } from '../../src/i18n/translations/es';
import { Modal } from '../../src/components/overlays/Modal';
import { ErrorState } from '../../src/components/feedback/ErrorState';
import { SearchInput } from '../../src/components/inputs/SearchInput';

const ArabicNavigation = () => {
  const { t } = useI18n();
  const dashboard = navigationRegistry.getAll().find((item) => item.id === 'nav_dashboard');
  const administration = navigationRegistry
    .getGroups()
    .find((group) => group.labelKey === 'nav.group.administration');
  return (
    <>
      <span>{t(dashboard?.labelKey ?? '')}</span>
      <span>{t(administration?.labelKey ?? '')}</span>
      <Modal isOpen onClose={() => {}} closeLabel={t('modal.close')} title="اختبار">
        <p>محتوى</p>
      </Modal>
      <ErrorState onRetry={() => {}} />
      <SearchInput value="بحث" onSearchChange={() => {}} />
      <span>{t('missing.translation.key')}</span>
    </>
  );
};

describe('official navigation and reusable-control translations', () => {
  it('defines every official navigation resource in each supported non-English locale', () => {
    for (const item of navigationRegistry.getAll()) {
      expect(item.labelKey).toBeTruthy();
      expect(ar[item.labelKey!]).toBeTruthy();
      expect(es[item.labelKey!]).toBeTruthy();
    }
    for (const group of navigationRegistry.getGroups()) {
      expect(group.labelKey).toBeTruthy();
      expect(ar[group.labelKey!]).toBeTruthy();
      expect(es[group.labelKey!]).toBeTruthy();
    }
  });

  it('renders translated navigation text and a translated modal accessibility label', () => {
    render(
      <I18nProvider defaultLocale="ar">
        <ArabicNavigation />
      </I18nProvider>
    );
    expect(screen.getByText('لوحة التحكم')).toBeInTheDocument();
    expect(screen.getByText('الإدارة')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'إغلاق مربع الحوار' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'إعادة المحاولة' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'مسح البحث' })).toBeInTheDocument();
    expect(screen.getByText('missing.translation.key')).toBeInTheDocument();
  });
});
