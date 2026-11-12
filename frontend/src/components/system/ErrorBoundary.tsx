"use client";

import { AlertTriangle, RotateCcw } from "lucide-react";
import { Component, type ErrorInfo, type ReactNode } from "react";

import { Button } from "@/components/ui/button";

interface Props {
  label: string;
  children: ReactNode;
  /** Compact inline fallback for a single panel instead of the whole page. */
  inline?: boolean;
}

interface State {
  error: Error | null;
}

/** Contains a crash to one panel (or the app) and offers a retry. Error details are never shown to users. */
export class ErrorBoundary extends Component<Props, State> {
  state: State = { error: null };

  static getDerivedStateFromError(error: Error): State {
    return { error };
  }

  componentDidCatch(error: Error, info: ErrorInfo): void {
    if (process.env.NODE_ENV !== "production") console.error(`[${this.props.label}]`, error, info.componentStack);
  }

  render(): ReactNode {
    if (!this.state.error) return this.props.children;
    return (
      <div role="alert" data-testid="error-boundary"
        className={this.props.inline ? "rounded-lg border border-level-error/30 p-4 text-sm" : "flex min-h-[40vh] flex-col items-center justify-center gap-3 p-6 text-sm"}>
        <p className="flex items-center gap-2 text-level-error"><AlertTriangle className="h-4 w-4" aria-hidden /> {this.props.label} hit an unexpected problem.</p>
        <p className="text-muted-foreground">Your tasks are saved on the server. Reload this panel to continue.</p>
        <Button size="sm" variant="outline" onClick={() => this.setState({ error: null })}>
          <RotateCcw aria-hidden /> Try again
        </Button>
      </div>
    );
  }
}
