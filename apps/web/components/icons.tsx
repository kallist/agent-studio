import type { SVGProps } from "react";

export type IconName =
  | "agents"
  | "arrow"
  | "bolt"
  | "builder"
  | "calculator"
  | "check"
  | "chevron"
  | "clock"
  | "close"
  | "dashboard"
  | "database"
  | "error"
  | "evaluation"
  | "http"
  | "info"
  | "knowledge"
  | "language"
  | "memory"
  | "menu"
  | "model"
  | "play"
  | "playground"
  | "plus"
  | "refresh"
  | "runs"
  | "send"
  | "settings"
  | "spark"
  | "terminal"
  | "tool"
  | "trash";

const paths: Record<IconName, React.ReactNode> = {
  dashboard: <><rect x="3" y="3" width="7" height="7" rx="2"/><rect x="14" y="3" width="7" height="7" rx="2"/><rect x="3" y="14" width="7" height="7" rx="2"/><rect x="14" y="14" width="7" height="7" rx="2"/></>,
  agents: <><circle cx="9" cy="8" r="3"/><path d="M3.5 20v-2a5.5 5.5 0 0 1 11 0v2M16 4.5a3 3 0 0 1 0 5.8M17 14a5 5 0 0 1 3.5 4.8V20"/></>,
  builder: <><path d="M14.7 6.3a4 4 0 0 0-5-5L7 4l3 3 2.7-2.7a4 4 0 0 0 2 2z"/><path d="m9 7-6.3 6.3a2.4 2.4 0 0 0 3.4 3.4L12.4 10M14 14l6 6M17 11l-3 3"/></>,
  playground: <><path d="M4 4h16v16H4z"/><path d="m8 9 3 3-3 3M13 15h3"/></>,
  runs: <><circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/></>,
  plus: <path d="M12 5v14M5 12h14"/>,
  play: <path d="m9 7 8 5-8 5z"/>,
  send: <><path d="m3 11 18-8-8 18-2.5-7.5z"/><path d="M10.5 13.5 21 3"/></>,
  trash: <><path d="M4 7h16M9 7V4h6v3M7 7l1 13h8l1-13M10 11v5M14 11v5"/></>,
  close: <path d="m6 6 12 12M18 6 6 18"/>,
  check: <path d="m5 12 4 4L19 6"/>,
  error: <><circle cx="12" cy="12" r="9"/><path d="M12 7v6M12 17h.01"/></>,
  evaluation: <><path d="M9 11l2 2 4-5"/><path d="M6 3h12v18H6z"/><path d="M9 17h6"/></>,
  info: <><circle cx="12" cy="12" r="9"/><path d="M12 11v6M12 7h.01"/></>,
  refresh: <><path d="M20 7v5h-5"/><path d="M19 12a7 7 0 1 0-2 5"/></>,
  chevron: <path d="m9 6 6 6-6 6"/>,
  clock: <><circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/></>,
  terminal: <><path d="m5 7 4 5-4 5M12 17h7"/></>,
  tool: <><path d="M14.7 6.3a4 4 0 0 0-5-5L7 4l3 3 2.7-2.7a4 4 0 0 0 2 2z"/><path d="m9 7-6 6a2.8 2.8 0 0 0 4 4l6-6"/></>,
  calculator: <><rect x="5" y="3" width="14" height="18" rx="2"/><path d="M8 7h8M8 11h.01M12 11h.01M16 11h.01M8 15h.01M12 15h.01M16 15h.01M8 18h.01M12 18h4"/></>,
  knowledge: <><path d="M4 5a3 3 0 0 1 3-2h5v17H7a3 3 0 0 0-3 2z"/><path d="M20 5a3 3 0 0 0-3-2h-5v17h5a3 3 0 0 1 3 2z"/></>,
  language: <><circle cx="12" cy="12" r="9"/><path d="M3 12h18M12 3a14 14 0 0 1 0 18M12 3a14 14 0 0 0 0 18"/></>,
  http: <><circle cx="12" cy="12" r="9"/><path d="M3 12h18M12 3a14 14 0 0 1 0 18M12 3a14 14 0 0 0 0 18"/></>,
  database: <><ellipse cx="12" cy="5" rx="7" ry="3"/><path d="M5 5v7c0 1.7 3.1 3 7 3s7-1.3 7-3V5M5 12v7c0 1.7 3.1 3 7 3s7-1.3 7-3v-7"/></>,
  model: <><circle cx="12" cy="12" r="3"/><circle cx="12" cy="12" r="8"/><path d="M4.5 8h15M4.5 16h15"/></>,
  memory: <><path d="M8 4a3 3 0 0 0-3 3v2a3 3 0 0 0 0 6v2a3 3 0 0 0 3 3M16 4a3 3 0 0 1 3 3v2a3 3 0 0 1 0 6v2a3 3 0 0 1-3 3M8 4c2 0 4 1 4 3v10c0 2-2 3-4 3M16 4c-2 0-4 1-4 3"/></>,
  settings: <><circle cx="12" cy="12" r="3"/><path d="M19 13.5v-3l-2-.7-.7-1.7.9-1.9-2.1-2.1-1.9.9-1.7-.7L10.5 2h-3l-.7 2-1.7.7-1.9-.9-2.1 2.1.9 1.9-.7 1.7-2 .7v3l2 .7.7 1.7-.9 1.9 2.1 2.1 1.9-.9 1.7.7.7 2h3l.7-2 1.7-.7 1.9.9 2.1-2.1-.9-1.9.7-1.7z" transform="scale(.8) translate(3 3)"/></>,
  spark: <><path d="m12 3 1.2 4.8L18 9l-4.8 1.2L12 15l-1.2-4.8L6 9l4.8-1.2z"/><path d="m18.5 15 .6 2.4 2.4.6-2.4.6-.6 2.4-.6-2.4-2.4-.6 2.4-.6z"/></>,
  bolt: <path d="m13 2-8 12h7l-1 8 8-12h-7z"/>,
  arrow: <path d="M5 12h14M14 7l5 5-5 5"/>,
  menu: <path d="M4 7h16M4 12h16M4 17h16"/>,
};

export function Icon({ name, ...props }: { name: IconName } & SVGProps<SVGSVGElement>) {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true" {...props}>
      {paths[name]}
    </svg>
  );
}
