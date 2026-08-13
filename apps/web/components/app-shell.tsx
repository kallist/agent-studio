"use client";

import { Icon, type IconName } from "@/components/icons";
import type { StudioView } from "@/lib/studio-types";

const navigation: Array<{ id: StudioView; label: string; icon: IconName }> = [
  { id: "dashboard", label: "Dashboard", icon: "dashboard" },
  { id: "agents", label: "Agents", icon: "agents" },
  { id: "builder", label: "Agent Builder", icon: "builder" },
  { id: "playground", label: "Playground", icon: "playground" },
  { id: "run", label: "Run Detail", icon: "runs" },
];

const titles: Record<StudioView, string> = {
  dashboard: "Workspace overview",
  agents: "Agent definitions",
  builder: "Configure an agent",
  playground: "Test and inspect",
  run: "Execution detail",
};

export function AppShell({ view, hasRun, onNavigate, children }: { view: StudioView; hasRun: boolean; onNavigate: (view: StudioView) => void; children: React.ReactNode }) {
  return (
    <div className="app-shell">
      <a className="skip-link" href="#main-content">Skip to content</a>
      <aside className="sidebar">
        <button className="wordmark" onClick={() => onNavigate("dashboard")} aria-label="Agent Studio dashboard">
          <span className="wordmark-icon"><Icon name="spark" /></span>
          <span><strong>Agent Studio</strong><small>Developer workspace</small></span>
        </button>
        <nav className="primary-nav" aria-label="Primary navigation">
          <p>Workspace</p>
          {navigation.map((item) => {
            const disabled = item.id === "run" && !hasRun;
            return (
              <button key={item.id} className={view === item.id ? "nav-item active" : "nav-item"} onClick={() => onNavigate(item.id)} aria-current={view === item.id ? "page" : undefined} disabled={disabled} title={disabled ? "Run an agent to view details" : undefined}>
                <Icon name={item.icon} />
                <span>{item.label}</span>
                {item.id === "playground" && <kbd>⌘↵</kbd>}
              </button>
            );
          })}
        </nav>
        <div className="sidebar-footer">
          <div className="environment-card"><span className="environment-icon"><Icon name="terminal" /></span><div><strong>Local workspace</strong><small><span /> API connected</small></div></div>
          <p>Agent Studio <span>v0.1</span></p>
        </div>
      </aside>
      <div className="workspace">
        <header className="workspace-topbar">
          <div><p>Agent Studio</p><strong>{titles[view]}</strong></div>
          <div className="topbar-meta"><span className="connection-pill"><span /> Connected</span><button className="avatar-button" aria-label="Workspace profile">AS</button></div>
        </header>
        <main id="main-content" className={`content content-${view}`}>{children}</main>
      </div>
    </div>
  );
}
