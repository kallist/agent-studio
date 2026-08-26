"use client";

import { forwardRef, useEffect, useRef, type ReactNode } from "react";

import { Icon, type IconName } from "@/components/icons";
import type { RunStatus } from "@/lib/api";
import type { ToastMessage } from "@/lib/studio-types";
import { displayStatus } from "@/i18n/display";
import { useI18n } from "@/i18n/provider";

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
  const { t } = useI18n();
  const label = status === "completed" ? t("common.states.succeeded") : displayStatus(t, status);
  return <span className={`status-badge status-${status}`}><span />{label}</span>;
}

export function EmptyState({ icon, title, description, action }: { icon: IconName; title: string; description: string; action?: ReactNode }) {
  return <div className="empty-state"><span className="empty-icon"><Icon name={icon} /></span><h3>{title}</h3><p>{description}</p>{action}</div>;
}

export function LoadingSkeleton({ rows = 3 }: { rows?: number }) {
  const { t } = useI18n();
  return <div className="skeleton-stack" aria-label={t("common.loading.content")} aria-live="polite">{Array.from({ length: rows }, (_, index) => <span key={index} className="skeleton-row" />)}</div>;
}

export function ErrorBanner({ message, onRetry, onDismiss }: { message: string; onRetry?: () => void; onDismiss: () => void }) {
  const { t } = useI18n();
  return <div className="error-banner" role="alert"><span className="error-icon"><Icon name="error" /></span><div><strong>{t("common.errors.title")}</strong><p>{message}</p></div><div className="error-actions">{onRetry && <Button variant="secondary" icon="refresh" onClick={onRetry}>{t("common.actions.retry")}</Button>}<button className="icon-button" onClick={onDismiss} aria-label={t("common.errors.dismiss")}><Icon name="close" /></button></div></div>;
}

export function ToastRegion({ toast, onDismiss }: { toast: ToastMessage | null; onDismiss: () => void }) {
  const { t } = useI18n();
  useEffect(() => {
    if (!toast) return;
    const timeout = window.setTimeout(onDismiss, 4200);
    return () => window.clearTimeout(timeout);
  }, [toast, onDismiss]);
  if (!toast) return null;
  return <div className={`toast toast-${toast.tone}`} role={toast.tone === "error" ? "alert" : "status"}><span><Icon name={toast.tone === "success" ? "check" : toast.tone === "error" ? "error" : "info"} /></span><div><strong>{toast.title}</strong><p>{toast.message}</p></div><button onClick={onDismiss} aria-label={t("common.errors.notificationDismiss")}><Icon name="close" /></button></div>;
}

export function ConfirmDialog({ open, title, description, confirmLabel, danger = false, onConfirm, onCancel }: { open: boolean; title: string; description: string; confirmLabel: string; danger?: boolean; onConfirm: () => void; onCancel: () => void }) {
  const { t } = useI18n();
  const dialogRef = useRef<HTMLDialogElement>(null);
  const cancelRef = useRef<HTMLButtonElement>(null);
  const cancelCallbackRef = useRef(onCancel);
  useEffect(() => { cancelCallbackRef.current = onCancel; }, [onCancel]);
  useEffect(() => {
    if (!open) return;
    const dialog = dialogRef.current;
    if (!dialog) return;
    const opener = document.activeElement instanceof HTMLElement ? document.activeElement : null;
    if (typeof dialog.showModal === "function") dialog.showModal();
    else dialog.setAttribute("open", "");
    cancelRef.current?.focus();
    return () => {
      if (dialog.open && typeof dialog.close === "function") dialog.close();
      else dialog.removeAttribute("open");
      opener?.focus();
    };
  }, [open]);
  if (!open) return null;
  return <dialog ref={dialogRef} className="confirm-dialog" aria-labelledby="confirm-title" aria-describedby="confirm-description" onCancel={(event) => { event.preventDefault(); cancelCallbackRef.current(); }} onMouseDown={(event) => { if (event.currentTarget === event.target) cancelCallbackRef.current(); }}><span className={`dialog-icon ${danger ? "danger" : ""}`}><Icon name={danger ? "trash" : "info"} /></span><h2 id="confirm-title">{title}</h2><p id="confirm-description">{description}</p><div className="dialog-actions"><Button ref={cancelRef} variant="secondary" onClick={onCancel}>{t("common.actions.cancel")}</Button><Button variant={danger ? "danger" : "primary"} onClick={onConfirm}>{confirmLabel}</Button></div></dialog>;
}

export function useRelativeTime(): (value: string) => string {
  const { locale, t } = useI18n();
  return (value: string) => {
  const delta = Date.now() - new Date(value).getTime();
  if (delta < 60_000) return t("common.relativeTime.justNow");
  if (delta < 3_600_000) return t("common.relativeTime.minutesAgo", { count: Math.floor(delta / 60_000) });
  if (delta < 86_400_000) return t("common.relativeTime.hoursAgo", { count: Math.floor(delta / 3_600_000) });
  return new Intl.DateTimeFormat(locale, { month: "short", day: "numeric" }).format(new Date(value));
  };
}
