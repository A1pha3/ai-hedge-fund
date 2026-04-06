import { fireEvent, render, screen } from '@testing-library/react';
import { describe, expect, it, vi, beforeEach, afterEach } from 'vitest';

import { ErrorBoundary } from './ErrorBoundary';

function ThrowingComponent(): JSX.Element {
  throw new Error('boom');
}

describe('ErrorBoundary', () => {
  const originalLocation = window.location;
  const consoleErrorSpy = vi.spyOn(console, 'error').mockImplementation(() => undefined);

  beforeEach(() => {
    Object.defineProperty(window, 'location', {
      configurable: true,
      value: {
        ...originalLocation,
        reload: vi.fn() as () => void,
      },
    });
  });

  afterEach(() => {
    Object.defineProperty(window, 'location', {
      configurable: true,
      value: originalLocation,
    });
    consoleErrorSpy.mockClear();
  });

  it('renders a fallback when a child crashes', () => {
    render(
      <ErrorBoundary>
        <ThrowingComponent />
      </ErrorBoundary>,
    );

    expect(screen.getByText('界面发生异常')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: '刷新页面' })).toBeInTheDocument();
  });

  it('reloads the page from the fallback action', () => {
    render(
      <ErrorBoundary>
        <ThrowingComponent />
      </ErrorBoundary>,
    );

    fireEvent.click(screen.getByRole('button', { name: '刷新页面' }));
    expect(window.location.reload).toHaveBeenCalledTimes(1);
  });
});
