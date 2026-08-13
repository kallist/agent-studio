"use client";

import { forwardRef, useEffect, useRef, type ReactNode } from "react";

import { Icon, type IconName } from "@/components/icons";
import type { RunStatus } from "@/lib/api";
import type { ToastMessage } from "@/lib/studio-types";

export function PageHeader({ eyebrow, title, description, action }: { eyebrow: string; title: string; description: string; action?: ReactNode }) {
  return (
    <header className="page-header">
      <div>
        <p className="eyebrow">{eyebrow}</p>
        <h1>{title}</h1>
        <p className="page-description">{description}</p>
      </div>
      {action && <div className="page-actions">{action}</div>}
    </header>
  );
}

export const Button = forwardRef<HTMLButtonElement, React.ButtonHTMLAttributes<HTMLButtonElement> & { icon?: IconName; variant?: "primary" | "secondary" | "ghost" | "danger" }>(function Button({ children, icon, variant = "primary", className = "", ...props }, ref) {
  return <button ref={ref} className={`button button-${variant} ${className}`.trim()} {...props}>{icon && <Icon name={icon} />}{children}</button>;
});

export function StatusBadge({ status }: { status: RunStatus | "ready" | "needs-key" | "idle" }) {
  const label: Record<typeof status, string> = {
    pending: "Pending", running: "Running", completed: "Succeeded", failed: "Failed", cancelled: "Cancelled", ready: "Ready", "needs-key": "Needs key", idle: "Idle",
  };
  return <span className={`status-badge status-${status}`}><span />{label[status]}</span>;
}

export function EmptyState({ icon, title, description, action }: { icon: IconName; title: string; description: string; action?: ReactNode }) {
  return <div className="empty-state"><span className="empty-icon"><Icon name={icon} /></span><h3>{title}</h3><p>{description}</p>{action}</div>;
}

export function LoadingSkeleton({ rows = 3 }: { rows?: number }) {
  return <div className="skeleton-stack" aria-label="Loading content" aria-live="polite">{Array.from({ length: rows }, (_, index) => <span key={index} className="skeleton-row" />)}</div>;
}

export function ErrorBanner({ message, onRetry, onDismiss }: { message: string; onRetry?: () => void; onDismiss: () => void }) {
  return <div className="error-banner" role="alert"><span className="error-icon"><Icon name="error" /></span><div><strong>Something went wrong</strong><p>{message}</p></div><div className="error-actions">{onRetry && <Button variant="secondary" icon="refresh" onClick={onRetry}>Retry</Button>}<button className="icon-button" onClick={onDismiss} aria-label="Dismiss error"><Icon name="close" /></button></div></div>;
}

export function ToastRegion({ toast, onDismiss }: { toast: ToastMessage | null; onDismiss: () => void }) {
  useEffect(() => {
    if (!toast) return;
    const timeout = window.setTimeout(onDismiss, 4200);
    return () => window.clearTimeout(timeout);
  }, [toast, onDismiss]);
  if (!toast) return null;
  return <div className={`toast toast-${toast.tone}`} role={toast.tone === "error" ? "alert" : "status"}><span><Icon name={toast.tone === "success" ? "check" : toast.tone === "error" ? "error" : "info"} /></span><div><strong>{toast.title}</strong><p>{toast.message}</p></div><button onClick={onDismiss} aria-label="Dismiss notification"><Icon name="close" /></button></div>;
}

export function ConfirmDialog({ open, title, description, confirmLabel, danger = false, onConfirm, onCancel }: { open: boolean; title: string; description: string; confirmLabel: string; danger?: boolean; onConfirm: () => void; onCancel: () => void }) {
  const cancelRef = useRef<HTMLButtonElement>(null);
  useEffect(() => {
    if (!open) return;
    cancelRef.current?.focus();
    const onKey = (event: KeyboardEvent) => { if (event.key === "Escape") onCancel(); };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open, onCancel]);
  if (!open) return null;
  return <div className="dialog-backdrop" role="presentation" onMouseDown={(event) => { if (event.currentTarget === event.target) onCancel(); }}><div className="confirm-dialog" role="dialog" aria-modal="true" aria-labelledby="confirm-title" aria-describedby="confirm-description"><span className={`dialog-icon ${danger ? "danger" : ""}`}><Icon name={danger ? "trash" : "info"} /></span><h2 id="confirm-title">{title}</h2><p id="confirm-description">{description}</p><div className="dialog-actions"><Button ref={cancelRef} variant="secondary" onClick={onCancel}>Cancel</Button><Button variant={danger ? "danger" : "primary"} onClick={onConfirm}>{confirmLabel}</Button></div></div></div>;
}

export function formatRelativeTime(value: string): string {
  const delta = Date.now() - new Date(value).getTime();
  if (delta < 60_000) return "Just now";
  if (delta < 3_600_000) return `${Math.floor(delta / 60_000)}m ago`;
  if (delta < 86_400_000) return `${Math.floor(delta / 3_600_000)}h ago`;
  return new Intl.DateTimeFormat("en", { month: "short", day: "numeric" }).format(new Date(value));
}
