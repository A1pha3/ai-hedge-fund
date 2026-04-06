import React from 'react';

type ErrorBoundaryProps = {
  children: React.ReactNode;
};

type ErrorBoundaryState = {
  hasError: boolean;
};

export class ErrorBoundary extends React.Component<ErrorBoundaryProps, ErrorBoundaryState> {
  public constructor(props: ErrorBoundaryProps) {
    super(props);
    this.state = { hasError: false };
  }

  public static getDerivedStateFromError(): ErrorBoundaryState {
    return { hasError: true };
  }

  public componentDidCatch(error: Error): void {
    console.error('Unhandled React render error', error);
  }

  private handleReload = (): void => {
    window.location.reload();
  };

  public render(): React.ReactNode {
    if (this.state.hasError) {
      return (
        <div className="flex min-h-screen flex-col items-center justify-center gap-4 bg-background px-6 text-center">
          <div className="max-w-md space-y-2">
            <h1 className="text-2xl font-semibold tracking-tight">界面发生异常</h1>
            <p className="text-sm text-muted-foreground">页面组件崩溃了，但应用仍然存活。请刷新页面后重试。</p>
          </div>
          <button
            className="inline-flex h-10 items-center justify-center rounded-md bg-primary px-4 py-2 text-sm font-medium text-primary-foreground transition-colors hover:opacity-90"
            onClick={this.handleReload}
            type="button"
          >
            刷新页面
          </button>
        </div>
      );
    }

    return this.props.children;
  }
}
