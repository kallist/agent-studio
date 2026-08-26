import type { Metadata } from "next";
import { cookies } from "next/headers";

import { I18nProvider } from "@/i18n/provider";
import { LOCALE_COOKIE, normalizeLocale } from "@/i18n/config";
import "./globals.css";

export const metadata: Metadata = {
  title: "Agent Studio",
  description: "Build and inspect observable AI agent runs.",
};

export default async function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  const cookieStore = await cookies();
  const initialLocale = normalizeLocale(cookieStore.get(LOCALE_COOKIE)?.value);
  return (
    <html lang={initialLocale} data-scroll-behavior="smooth">
      <body><I18nProvider initialLocale={initialLocale}>{children}</I18nProvider></body>
    </html>
  );
}
