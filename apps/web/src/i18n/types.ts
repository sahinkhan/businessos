export type SupportedLocale = 'en' | 'ar' | 'es';
export type TextDirection = 'ltr' | 'rtl';

export interface I18nContextValue {
  locale: SupportedLocale;
  direction: TextDirection;
  setLocale: (locale: SupportedLocale) => void;
  t: (key: string, params?: Record<string, string | number>) => string;
  tp: (key: string, count: number, params?: Record<string, string | number>) => string;
  formatNumber: (val: number, options?: Intl.NumberFormatOptions) => string;
  formatCurrency: (val: number, currency?: string) => string;
  formatDate: (date: Date | string | number, options?: Intl.DateTimeFormatOptions) => string;
  formatDateTime: (date: Date | string | number) => string;
}
