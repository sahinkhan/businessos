import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { createMemoryRouter, Link, RouterProvider } from 'react-router-dom';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { useUnsavedChanges } from '../../src/components/form/useUnsavedChanges';
import { I18nProvider } from '../../src/i18n/I18nContext';

const Editor = ({ dirty }: { dirty: boolean }) => {
  useUnsavedChanges(dirty);
  return <Link to="/destination">Leave editor</Link>;
};

const renderRouter = (dirty: boolean) => {
  const router = createMemoryRouter([
    { path: '/', element: <Editor dirty={dirty} /> },
    { path: '/destination', element: <div>Destination</div> },
  ]);
  render(
    <I18nProvider>
      <RouterProvider router={router} />
    </I18nProvider>
  );
};

afterEach(() => {
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});

describe('router-aware unsaved changes', () => {
  it('blocks a dirty internal navigation when the user cancels', async () => {
    vi.spyOn(window, 'confirm').mockReturnValue(false);
    renderRouter(true);
    fireEvent.click(screen.getByText('Leave editor'));
    await waitFor(() => expect(window.confirm).toHaveBeenCalledTimes(1));
    expect(screen.queryByText('Destination')).not.toBeInTheDocument();
  });

  it('continues a dirty internal navigation when the user confirms', async () => {
    const NativeRequest = globalThis.Request;
    class CompatibleRequest extends NativeRequest {
      constructor(input: RequestInfo | URL, init?: RequestInit) {
        super(input, init ? { ...init, signal: undefined } : init);
      }
    }
    vi.stubGlobal('Request', CompatibleRequest);
    vi.spyOn(window, 'confirm').mockReturnValue(true);
    renderRouter(true);
    fireEvent.click(screen.getByText('Leave editor'));
    await waitFor(() => expect(screen.getByText('Destination')).toBeInTheDocument());
    expect(window.confirm).toHaveBeenCalledTimes(1);
  });
});
