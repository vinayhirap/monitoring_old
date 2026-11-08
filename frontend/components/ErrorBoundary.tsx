"use client";

/**
 * ErrorBoundary — catches any render-time JS error in a React subtree
 * and shows a clean fallback instead of the white-screen-of-death.
 *
 * Wrap the portal/admin shells with this so a single buggy panel
 * doesn't kill the whole page. The user always sees SOMETHING — even
 * if it's "this section couldn't load" with a Reload button.
 *
 * Why a class component? React only supports `componentDidCatch` /
 * `getDerivedStateFromError` on class components. There is no hook
 * equivalent.
 */

import React from "react";
import { AlertTriangle, RefreshCw } from "lucide-react";


type Props = {
  children: React.ReactNode;
  fallback?: (error: Error, reset: () => void) => React.ReactNode;
  // Section label shown in the fallback ("Recommendations", "Symbol page", etc.)
  scope?: string;
};

type State = {
  error: Error | null;
};


export class ErrorBoundary extends React.Component<Props, State> {
  state: State = { error: null };

  static getDerivedStateFromError(error: Error): State {
    return { error };
  }

  componentDidCatch(error: Error, info: React.ErrorInfo) {
    // Log to console with the component stack so the developer can find
    // the offending file. In production, ship this to your error tracker
    // (Sentry / Datadog / Bugsnag) — wire up here when ready.
    console.error(
      `[ErrorBoundary${this.props.scope ? ` :: ${this.props.scope}` : ""}]`,
      error,
      info.componentStack,
    );
  }

  reset = () => this.setState({ error: null });

  render() {
    if (this.state.error) {
      if (this.props.fallback) {
        return this.props.fallback(this.state.error, this.reset);
      }
      return <DefaultFallback error={this.state.error} reset={this.reset} scope={this.props.scope} />;
    }
    return this.props.children;
  }
}


function DefaultFallback({ error, reset, scope }:
                          { error: Error; reset: () => void; scope?: string }) {
  return (
    <div className="bg-bg-surface border border-accent-red/40 rounded-lg p-6 my-4">
      <div className="flex items-start gap-3">
        <div className="w-9 h-9 rounded-full bg-accent-red/15 flex items-center justify-center shrink-0">
          <AlertTriangle className="w-5 h-5 text-accent-red" />
        </div>
        <div className="flex-1 min-w-0">
          <h3 className="text-sm font-bold text-text-primary">
            {scope ? `${scope} could not load` : "Something went wrong"}
          </h3>
          <p className="text-[12px] text-text-secondary mt-1">
            A rendering error occurred. The rest of the application is unaffected.
            If this keeps happening on the same page, share the message below with support.
          </p>
          <details className="mt-2 text-[10px] text-text-muted">
            <summary className="cursor-pointer hover:text-text-secondary">Technical details</summary>
            <pre className="mt-1 p-2 bg-bg-base rounded overflow-auto max-h-32 text-[10px]">
              {error.name}: {error.message}
            </pre>
          </details>
          <div className="flex gap-2 mt-3">
            <button onClick={reset}
              className="text-[11px] font-semibold flex items-center gap-1 bg-accent-amber text-white px-3 py-1.5 rounded hover:bg-accent-gold">
              <RefreshCw className="w-3 h-3" /> Try again
            </button>
            <button onClick={() => typeof window !== "undefined" && window.location.reload()}
              className="text-[11px] text-text-muted hover:text-text-primary px-3 py-1.5">
              Reload page
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
