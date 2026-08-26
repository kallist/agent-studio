"use client";

import { Icon } from "@/components/icons";
import { SUPPORTED_LOCALES, type Locale } from "@/i18n/config";
import { useI18n } from "@/i18n/provider";

export function LanguageSwitcher() {
  const { locale, setLocale, t } = useI18n();
  return (
    <label className="language-switcher">
      <span className="sr-only">{t("language.label")}</span>
      <Icon name="language" />
      <select aria-label={t("language.label")} value={locale} onChange={(event) => setLocale(event.target.value as Locale)}>
        {SUPPORTED_LOCALES.map((value) => <option key={value} value={value}>{value === "en" ? t("language.english") : t("language.chinese")}</option>)}
      </select>
    </label>
  );
}
