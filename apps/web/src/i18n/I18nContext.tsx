import React, { createContext, useContext, useState, useEffect, useMemo, useCallback } from 'react';
import { SupportedLocale, TextDirection, I18nContextValue } from './types';
import { en } from './translations/en';
import { ar } from './translations/ar';
import { es } from './translations/es';

const dictionaries: Record<SupportedLocale, Record<string, string>> = { en, ar, es };
const directionMap: Record<SupportedLocale, TextDirection> = { en: 'ltr', ar: 'rtl', es: 'ltr' };
const STORAGE_KEY = 'businessos.locale';

const I18nContext = createContext<I18nContextValue | undefined>(undefined);

export const I18nProvider: React.FC<{
  children: React.ReactNode;
  defaultLocale?: SupportedLocale;
}> = ({ children, defaultLocale = 'en' }) => {
  const [locale, setLocaleState] = useState<SupportedLocale>(() => {
    try {
      const stored = localStorage.getItem(STORAGE_KEY);
      if (stored === 'en' || stored === 'ar' || stored === 'es') return stored;
    } catch {
      // ignore
    }
    return defaultLocale;
  });

  const direction = directionMap[locale];

  useEffect(() => {
    document.documentElement.lang = locale;
    document.documentElement.dir = direction;
  }, [locale, direction]);

  const setLocale = (newLocale: SupportedLocale) => {
    setLocaleState(newLocale);
    try {
      localStorage.setItem(STORAGE_KEY, newLocale);
    } catch {
      // ignore
    }
  };

  const t = useCallback(
    (key: string, params?: Record<string, string | number>): string => {
      let str = dictionaries[locale]?.[key] || dictionaries.en[key] || key;
      if (params) {
        Object.entries(params).forEach(([k, v]) => {
          str = str.replace(new RegExp(`{${k}}`, 'g'), String(v));
        });
      }
      return str;
    },
    [locale]
  );

  const formatNumber = useCallback(
    (val: number, options?: Intl.NumberFormatOptions) => {
      return new Intl.NumberFormat(locale, options).format(val);
    },
    [locale]
  );

  const tp = useCallback(
    (key: string, count: number, params?: Record<string, string | number>): string => {
      const category = new Intl.PluralRules(locale).select(count);
      const selectedKey = dictionaries[locale]?.[`${key}.${category}`]
        ? `${key}.${category}`
        : `${key}.other`;
      let value =
        dictionaries[locale]?.[selectedKey] ??
        dictionaries.en[selectedKey] ??
        dictionaries.en[`${key}.other`] ??
        key;
      for (const [name, replacement] of Object.entries({ count, ...params })) {
        value = value.replace(new RegExp(`{${name}}`, 'g'), String(replacement));
      }
      return value;
    },
    [locale]
  );

  const formatCurrency = useCallback(
    (val: number, currency = 'USD') => {
      return new Intl.NumberFormat(locale, { style: 'currency', currency }).format(val);
    },
    [locale]
  );

  const formatDate = useCallback(
    (date: Date | string | number, options?: Intl.DateTimeFormatOptions) => {
      const d = typeof date === 'object' ? date : new Date(date);
      return new Intl.DateTimeFormat(locale, options).format(d);
    },
    [locale]
  );

  const formatDateTime = useCallback(
    (date: Date | string | number) => {
      const d = typeof date === 'object' ? date : new Date(date);
      return new Intl.DateTimeFormat(locale, {
        dateStyle: 'medium',
        timeStyle: 'short',
      }).format(d);
    },
    [locale]
  );

  const value = useMemo(
    () => ({
      locale,
      direction,
      setLocale,
      t,
      tp,
      formatNumber,
      formatCurrency,
      formatDate,
      formatDateTime,
    }),
    [locale, direction, t, tp, formatNumber, formatCurrency, formatDate, formatDateTime]
  );

  return <I18nContext.Provider value={value}>{children}</I18nContext.Provider>;
};

export const useI18n = (): I18nContextValue => {
  const ctx = useContext(I18nContext);
  if (!ctx) throw new Error('useI18n must be used within I18nProvider');
  return ctx;
};

/** Reusable primitives use English resources when rendered outside the application provider. */
export const useI18nText = (): Pick<I18nContextValue, 't' | 'tp'> => {
  const ctx = useContext(I18nContext);
  const t = useCallback(
    (key: string, params?: Record<string, string | number>) => {
      let value = ctx?.t(key, params) ?? en[key] ?? key;
      for (const [name, replacement] of Object.entries(params ?? {})) {
        value = value.replace(new RegExp(`{${name}}`, 'g'), String(replacement));
      }
      return value;
    },
    [ctx]
  );
  const tp = useCallback(
    (key: string, count: number, params?: Record<string, string | number>) =>
      ctx?.tp(key, count, params) ??
      t(`${key}.${count === 1 ? 'one' : 'other'}`, { count, ...params }),
    [ctx, t]
  );
  return { t, tp };
};
