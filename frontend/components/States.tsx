"use client";

import { AlertTriangle, Info, RefreshCw, Database } from "lucide-react";
import clsx from "clsx";


/**
 * Shared error / empty / loading components — keeps the UI consistent across
 * every page and gives users actionable hints when things go wrong instead of
 * raw ECONNRESET / 500 errors.
 */

export function ErrorState({ title, message, hint, onRetry }:
  { title?: string; message: string; hint?: string; onRetry?: () => void }) {
  // Detect the typical "backend unreachable" / proxy timeout messages
  const isProxy = /ECONNRESET|socket hang up|ECONNREFUSED|fetch failed/i.test(message);
  const isTimeout = /timeout|504/i.test(message);
  const is500 = /500|Internal Server Error/i.test(message);

  let suggestion = hint;
  if (!suggestion) {
    if (isProxy) suggestion = "The backend is unreachable or restarted mid-request. Check that the backend is running and try again.";
    else if (isTimeout) suggestion = "The request took longer than the proxy timeout (3 min). The endpoint may be too heavy — try a smaller lookback or wait and retry.";
    else if (is500) suggestion = "The backend hit an internal error. Check logs/backend.log for the traceback.";
  }

  return (
    <div className="bg-accent-red/5 border border-accent-red/30 rounded-lg p-6 my-4">
      <div className="flex items-start gap-3">
        <AlertTriangle className="w-6 h-6 text-accent-red shrink-0 mt-0.5" />
        <div className="flex-1">
          <h3 className="font-bold text-accent-red text-base">
            {title || "Something went wrong"}
          </h3>
          <p className="text-[12px] text-text-secondary mt-1 break-all">
            {message}
          </p>
          {suggestion && (
            <p className="text-[11px] text-text-muted mt-2 italic">
              {suggestion}
            </p>
          )}
          {onRetry && (
            <button onClick={onRetry}
              className="mt-3 inline-flex items-center gap-1.5 text-[11px] bg-accent-red/10 hover:bg-accent-red/20 text-accent-red px-3 py-1.5 rounded font-semibold">
              <RefreshCw className="w-3 h-3" /> Retry
            </button>
          )}
        </div>
      </div>
    </div>
  );
}


export function EmptyState({ title, message, action }:
  { title: string; message: string; action?: { label: string; onClick: () => void } }) {
  return (
    <div className="bg-bg-surface border border-bg-line rounded-lg p-8 my-4 text-center">
      <Database className="w-10 h-10 text-text-muted/40 mx-auto mb-3" />
      <h3 className="font-bold text-text-primary text-base">{title}</h3>
      <p className="text-[12px] text-text-muted mt-2 max-w-md mx-auto">{message}</p>
      {action && (
        <button onClick={action.onClick}
          className="mt-4 bg-accent-amber text-white px-4 py-2 rounded font-bold text-sm hover:bg-accent-gold">
          {action.label}
        </button>
      )}
    </div>
  );
}


export function InfoBanner({ children, type = "info" }:
  { children: React.ReactNode; type?: "info" | "warning" }) {
  const cls = type === "warning"
    ? "bg-accent-amber/5 border-accent-amber/30 text-accent-amber"
    : "bg-accent-blue/5 border-accent-blue/30 text-accent-blue";
  return (
    <div className={clsx("border rounded-md px-3 py-2 text-[11px] flex items-start gap-2", cls)}>
      <Info className="w-3.5 h-3.5 shrink-0 mt-0.5" />
      <div className="flex-1">{children}</div>
    </div>
  );
}


export function LoadingSkeleton({ lines = 3, height = "h-12" }:
  { lines?: number; height?: string }) {
  return (
    <div className="space-y-2 my-4">
      {Array.from({ length: lines }).map((_, i) => (
        <div key={i} className={clsx("skeleton rounded", height)} />
      ))}
    </div>
  );
}


export function CardSkeleton({ count = 3 }: { count?: number }) {
  return (
    <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
      {Array.from({ length: count }).map((_, i) => (
        <div key={i} className="bg-bg-surface border border-bg-line rounded-lg p-4">
          <div className="skeleton h-5 w-1/3 rounded mb-3" />
          <div className="skeleton h-3 w-full rounded mb-2" />
          <div className="skeleton h-3 w-2/3 rounded" />
        </div>
      ))}
    </div>
  );
}
