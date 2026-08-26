"use client";

import { Icon, type IconName } from "@/components/icons";
import { LanguageSwitcher } from "@/components/language-switcher";
import { useI18n, type TranslationKey } from "@/i18n/provider";
import type { ApiConnectionStatus } from "@/lib/api";
import type { StudioView } from "@/lib/studio-types";

const navigation: Array<{ id: StudioView; label: TranslationKey; icon: IconName }> = [
  { id: "dashboard", label: "navigation.dashboard", icon: "dashboard" },
  { id: "agents", label: "navigation.agents", icon: "agents" },
  { id: "builder", label: "navigation.builder", icon: "builder" },
  { id: "playground", label: "navigation.playground", icon: "playground" },
  { id: "evaluations", label: "navigation.evaluations", icon: "evaluation" },
  { id: "run", label: "navigation.runDetail", icon: "runs" },
];

const titles: Record<StudioView, TranslationKey> = {
  dashboard: "navigation.dashboardTitle",
  agents: "navigation.agentsTitle",
  builder: "navigation.builderTitle",
  playground: "navigation.playgroundTitle",
  evaluations: "navigation.evaluationsTitle",
  run: "navigation.runTitle",
};

const connectionLabel: Record<ApiConnectionStatus, TranslationKey> = { checking: "navigation.checkingApi", connected: "navigation.apiConnected", offline: "navigation.apiOffline" };

export function AppShell({ view, hasRun, apiStatus, onNavigate, children }: { view: StudioView; hasRun: boolean; apiStatus: ApiConnectionStatus; onNavigate: (view: StudioView) => void; children: React.ReactNode }) {
  const { t } = useI18n();
  return (
    <div className="app-shell">
      <a className="skip-link" href="#main-content">{t("navigation.skip")}</a>
      <aside className="sidebar">
        <div className="sidebar-header"><button className="wordmark" onClick={() => onNavigate("dashboard")} aria-label={t("navigation.dashboardAria")}>
          <span className="wordmark-icon"><Icon name="spark" /></span><span><strong>Agent Studio</strong><small>{t("navigation.developerWorkspace")}</small></span>
        </button><LanguageSwitcher /></div>
        <nav className="primary-nav" aria-label={t("navigation.primary")}>
          <p>{t("navigation.workspace")}</p>
          {navigation.map((item) => {
            const disabled = item.id === "run" && !hasRun;
            return (
              <button key={item.id} className={view === item.id ? "nav-item active" : "nav-item"} onClick={() => onNavigate(item.id)} aria-current={view === item.id ? "page" : undefined} disabled={disabled} title={disabled ? t("navigation.runDisabled") : undefined}>
                <Icon name={item.icon} />
                <span>{t(item.label)}</span>
                {item.id === "playground" && <kbd>⌘↵</kbd>}
              </button>
            );
          })}
        </nav>
        <div className="sidebar-footer">
          <div className={`environment-card connection-${apiStatus}`}><span className="environment-icon"><Icon name="terminal" /></span><div><strong>{t("navigation.localWorkspace")}</strong><small><span />{t(connectionLabel[apiStatus])}</small></div></div>
          <p>Agent Studio <span>v1.0</span></p>
        </div>
      </aside>
      <div className="workspace">
        <header className="workspace-topbar">
          <div><p>Agent Studio</p><strong>{t(titles[view])}</strong></div>
          <div className="topbar-meta"><span className={`connection-pill connection-${apiStatus}`} aria-live="polite"><span />{t(connectionLabel[apiStatus])}</span><button className="avatar-button" aria-label={t("navigation.profile")}>AS</button></div>
        </header>
        <main id="main-content" className={`content content-${view}`}>{children}</main>
      </div>
    </div>
  );
}
