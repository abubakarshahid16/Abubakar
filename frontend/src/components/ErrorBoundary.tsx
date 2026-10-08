/**
 * Last-resort screen for a render error.
 *
 * Without a boundary one thrown render leaves a blank white page. This shows
 * a plain message and a reload button. It deliberately shows NO error text,
 * stack or component name: either could carry document text, and the console
 * keeps the detail for whoever is debugging.
 */
import { Component, type ErrorInfo, type ReactNode } from "react";

interface State { failed: boolean }

export class ErrorBoundary extends Component<{ children: ReactNode }, State> {
  state: State = { failed: false };

  static getDerivedStateFromError(): State {
    return { failed: true };
  }

  componentDidCatch(error: Error, _info: ErrorInfo) {
    // Class and message only: never the component stack, which can embed
    // props. The message of a render error is code, not a document.
    // eslint-disable-next-line no-console
    console.error("Screen failed to render:", error.name);
  }

  render() {
    if (!this.state.failed) return this.props.children;
    return (
      <div
        role="alert"
        className="mx-auto mt-24 max-w-md space-y-3 rounded-[var(--radius-md)] border border-ink-700 bg-ink-850 p-6 text-slateish-200"
      >
        <h1 className="text-lg font-semibold text-slateish-100">Something went wrong</h1>
        <p className="text-sm">
          This screen could not be shown. Your documents are not affected.
          Reloading usually fixes it; you may need to sign in again.
        </p>
        <button
          type="button"
          onClick={() => window.location.reload()}
          className="rounded-[var(--radius-sm)] bg-ink-700 px-3 py-1.5 text-sm text-slateish-100"
        >
          Reload
        </button>
      </div>
    );
  }
}
