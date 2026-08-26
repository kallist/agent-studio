import { render as testingLibraryRender, type RenderOptions } from "@testing-library/react";
import type { ReactElement } from "react";

import { I18nProvider } from "@/i18n/provider";
import type { Locale } from "@/i18n/config";

export * from "@testing-library/react";

export function render(ui: ReactElement, options?: RenderOptions & { locale?: Locale }) {
  const { locale = "en", ...renderOptions } = options ?? {};
  return testingLibraryRender(ui, {
    ...renderOptions,
    wrapper: ({ children }) => <I18nProvider initialLocale={locale}>{children}</I18nProvider>,
  });
}
