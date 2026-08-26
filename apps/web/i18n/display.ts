import type { Translate, TranslationKey } from "@/i18n/provider";

const statusKeys: Record<string, TranslationKey> = {
  pending: "common.states.pending", running: "common.states.running", completed: "common.states.completed", failed: "common.states.failed", cancelled: "common.states.cancelled",
  queued: "common.states.queued", processing: "common.states.processing", pass: "common.states.pass", fail: "common.states.fail", error: "common.states.error",
  ready: "common.states.ready", "needs-key": "common.states.needsKey", idle: "common.states.idle",
};

const terminationKeys: Record<string, TranslationKey> = {
  max_steps: "runs.terminationReasons.maxSteps", timeout: "runs.terminationReasons.timeout", cancelled: "runs.terminationReasons.cancelled", tool_error: "runs.terminationReasons.toolError", provider_error: "runs.terminationReasons.providerError", completed: "runs.terminationReasons.completed", failed: "runs.terminationReasons.failed",
};

export function displayStatus(t: Translate, status: string | null | undefined): string {
  if (!status) return t("common.states.pending");
  const key = statusKeys[status];
  return key ? t(key) : status;
}

export function displayTermination(t: Translate, reason: string | null | undefined): string {
  if (!reason) return t("common.values.notAvailable");
  const key = terminationKeys[reason];
  return key ? t(key) : reason;
}
