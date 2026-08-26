"use client";

import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState, type ReactNode } from "react";

import { DEFAULT_LOCALE, LOCALE_COOKIE, LOCALE_COOKIE_MAX_AGE, normalizeLocale, type Locale } from "@/i18n/config";
import { en } from "@/i18n/messages/en";
import { zhCN } from "@/i18n/messages/zh-CN";
import type { MessageKey, TranslationValues } from "@/i18n/types";

export type TranslationKey = MessageKey<typeof en>;
export type Translate = (key: TranslationKey, values?: TranslationValues) => string;

const dictionaries = { en, "zh-CN": zhCN };

interface I18nContextValue {
  locale: Locale;
  setLocale: (locale: Locale) => void;
  t: Translate;
  formatDate: (value: string | Date, options?: Intl.DateTimeFormatOptions) => string;
  formatNumber: (value: number, options?: Intl.NumberFormatOptions) => string;
}

const I18nContext = createContext<I18nContextValue | null>(null);

function lookup(dictionary: unknown, key: string): string | undefined {
  let current: unknown = dictionary;
  for (const segment of key.split(".")) {
    if (!current || typeof current !== "object" || !(segment in current)) return undefined;
    current = (current as Record<string, unknown>)[segment];
  }
  return typeof current === "string" ? current : undefined;
}

export function interpolate(template: string, values: TranslationValues = {}): string {
  return template.replace(/\{([A-Za-z][A-Za-z0-9_]*)\}/g, (placeholder, name: string) => (
    Object.hasOwn(values, name) ? String(values[name]) : placeholder
  ));
}

export function createTranslator(localeValue: unknown): Translate {
  const locale = normalizeLocale(localeValue);
  return (key, values) => {
    const localized = lookup(dictionaries[locale], key);
    const fallback = lookup(en, key);
    if (localized === undefined && process.env.NODE_ENV !== "production") {
      console.warn(`Missing translation: ${locale}.${key}`);
    }
    return interpolate(localized ?? fallback ?? en.common.errors.generic, values);
  };
}

export function I18nProvider({ initialLocale = DEFAULT_LOCALE, children }: { initialLocale?: unknown; children: ReactNode }) {
  const [locale, setLocaleState] = useState<Locale>(() => normalizeLocale(initialLocale));
  const localeRef = useRef(locale);

  const setLocale = useCallback((nextLocale: Locale) => {
    const normalized = normalizeLocale(nextLocale);
    localeRef.current = normalized;
    setLocaleState(normalized);
    document.documentElement.lang = normalized;
    try {
      document.cookie = `${LOCALE_COOKIE}=${encodeURIComponent(normalized)}; Path=/; Max-Age=${LOCALE_COOKIE_MAX_AGE}; SameSite=Lax`;
    } catch {
      // Cookie persistence can fail in privacy-restricted browsers; session state still works.
    }
  }, []);

  useEffect(() => {
    document.documentElement.lang = locale;
  }, [locale]);

  const t = useCallback<Translate>((key, values) => createTranslator(localeRef.current)(key, values), []);

  const value = useMemo<I18nContextValue>(() => ({
    locale,
    setLocale,
    t,
    formatDate: (input, options) => new Intl.DateTimeFormat(locale, options).format(new Date(input)),
    formatNumber: (input, options) => new Intl.NumberFormat(locale, options).format(input),
  }), [locale, setLocale, t]);

  return <I18nContext.Provider value={value}>{children}</I18nContext.Provider>;
}

export function useI18n(): I18nContextValue {
  const context = useContext(I18nContext);
  if (!context) throw new Error("useI18n must be used within I18nProvider");
  return context;
}
