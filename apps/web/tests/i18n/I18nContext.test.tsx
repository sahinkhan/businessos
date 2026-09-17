import { describe, it, expect } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';
import { I18nProvider, useI18n } from '../../src/i18n/I18nContext';

const TestI18nComponent = () => {
  const { locale, direction, t, tp, setLocale, formatCurrency } = useI18n();
  return (
    <div>
      <div data-testid="locale">{locale}</div>
      <div data-testid="dir">{direction}</div>
      <div data-testid="search">{t('common.search')}</div>
      <div data-testid="currency">{formatCurrency(1500, 'USD')}</div>
      <div data-testid="plural-one">{tp('auth.session_minutes', 1)}</div>
      <div data-testid="plural-two">{tp('auth.session_minutes', 2)}</div>
      <button onClick={() => setLocale('ar')}>Switch to Arabic</button>
    </div>
  );
};

describe('Internationalization & RTL Engine', () => {
  it('handles locale switching and RTL direction changes', () => {
    render(
      <I18nProvider>
        <TestI18nComponent />
      </I18nProvider>
    );

    expect(screen.getByTestId('locale')).toHaveTextContent('en');
    expect(screen.getByTestId('dir')).toHaveTextContent('ltr');
    expect(screen.getByTestId('search')).toHaveTextContent('Search...');
    expect(screen.getByTestId('plural-one')).toHaveTextContent('1 minute.');
    expect(screen.getByTestId('plural-two')).toHaveTextContent('2 minutes.');

    fireEvent.click(screen.getByText('Switch to Arabic'));

    expect(screen.getByTestId('locale')).toHaveTextContent('ar');
    expect(screen.getByTestId('dir')).toHaveTextContent('rtl');
    expect(screen.getByTestId('search')).toHaveTextContent('بحث...');
    expect(screen.getByTestId('plural-two')).toHaveTextContent('دقيقتين');
    expect(document.documentElement.dir).toBe('rtl');
  });
});
