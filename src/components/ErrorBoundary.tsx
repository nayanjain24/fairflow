import React from 'react';
import { AlertTriangle, RotateCcw } from 'lucide-react';

interface ErrorBoundaryProps {
  children: React.ReactNode;
  variant?: 'page' | 'inline';
  fallbackTitle?: string;
}

interface ErrorBoundaryState {
  hasError: boolean;
  errorMessage: string;
}

export class ErrorBoundary extends React.Component<ErrorBoundaryProps, ErrorBoundaryState> {
  constructor(props: ErrorBoundaryProps) {
    super(props);
    this.state = { hasError: false, errorMessage: '' };
  }

  static getDerivedStateFromError(error: Error): ErrorBoundaryState {
    return {
      hasError: true,
      errorMessage: error?.message || 'Unexpected rendering error',
    };
  }

  componentDidCatch(error: Error, info: React.ErrorInfo): void {
    console.error('[FairFlow ErrorBoundary]', error, info.componentStack);
  }

  private handleReset = (): void => {
    this.setState({ hasError: false, errorMessage: '' });
  };

  render(): React.ReactNode {
    if (!this.state.hasError) {
      return this.props.children;
    }

    const { variant = 'page', fallbackTitle } = this.props;

    if (variant === 'inline') {
      return (
        <div
          role="alert"
          className="h-full min-h-[220px] w-full rounded-glass border border-[#f26a1b]/40 bg-[#090724]/90 p-6 flex flex-col items-center justify-center text-center gap-3"
        >
          <AlertTriangle className="h-6 w-6 text-[#f26a1b]" />
          <div className="space-y-1 max-w-md">
            <div className="font-mono text-xs font-semibold uppercase tracking-wider text-[#f26a1b]">
              {fallbackTitle || 'Component fallback active'}
            </div>
            <p className="text-xs text-[var(--mute)]">{this.state.errorMessage}</p>
          </div>
          <button
            type="button"
            onClick={this.handleReset}
            className="btn-secondary !py-1.5 !px-3 !text-xs font-mono"
          >
            <RotateCcw className="h-3.5 w-3.5" />
            Retry widget
          </button>
        </div>
      );
    }

    return (
      <div className="min-h-screen bg-[#06051a] text-[var(--text)] flex items-center justify-center p-6">
        <div className="max-w-lg w-full glass-card border border-[#f26a1b]/50 p-8 space-y-4 text-center">
          <div className="mx-auto w-12 h-12 rounded-2xl bg-[#f26a1b]/15 border border-[#f26a1b]/40 flex items-center justify-center">
            <AlertTriangle className="h-6 w-6 text-[#f26a1b]" />
          </div>
          <h1 className="text-xl font-semibold text-white">
            {fallbackTitle || 'FairFlow encountered a UI error'}
          </h1>
          <p className="font-mono text-xs text-[var(--mute)] break-words">
            {this.state.errorMessage}
          </p>
          <div className="pt-2 flex items-center justify-center gap-3">
            <button type="button" onClick={this.handleReset} className="btn-secondary !text-xs">
              Try recovering view
            </button>
            <button
              type="button"
              onClick={() => window.location.reload()}
              className="btn-primary !text-xs"
            >
              Reload application
            </button>
          </div>
        </div>
      </div>
    );
  }
}
