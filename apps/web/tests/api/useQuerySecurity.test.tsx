import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { queryCache } from '../../src/api/queryCache';
import { useQuery } from '../../src/api/useQuery';
import { AuthProvider } from '../../src/auth/AuthContext';
import { ScopeProvider, useScope } from '../../src/scope/ScopeContext';
import { MockScopeAdapter } from '../../src/scope/mockScopeAdapter';
import { TEST_SESSION, TEST_TENANTS } from '../fixtures/security';

interface Deferred<T> {
  promise: Promise<T>;
  resolve: (value: T) => void;
}

function deferred<T>(): Deferred<T> {
  let resolve!: (value: T) => void;
  return { promise: new Promise<T>((done) => (resolve = done)), resolve };
}

const QueryConsumer = ({ fetcher }: { fetcher: (signal?: AbortSignal) => Promise<string> }) => {
  const { data } = useQuery('security-sensitive', fetcher);
  const { setTenant } = useScope();
  return (
    <>
      <span data-testid="result">{data ?? 'empty'}</span>
      <button onClick={() => void setTenant('tenant_two')}>Switch tenant</button>
    </>
  );
};

const renderQuery = (fetcher: (signal?: AbortSignal) => Promise<string>) =>
  render(
    <AuthProvider initialSession={TEST_SESSION}>
      <ScopeProvider adapter={new MockScopeAdapter(TEST_TENANTS)}>
        <QueryConsumer fetcher={fetcher} />
      </ScopeProvider>
    </AuthProvider>
  );

describe('query security-context isolation', () => {
  beforeEach(() => queryCache.clear());

  it('ignores a delayed response after an authoritative tenant transition', async () => {
    const tenantA = deferred<string>();
    const tenantB = deferred<string>();
    const fetcher = vi
      .fn<(signal?: AbortSignal) => Promise<string>>()
      .mockImplementationOnce(() => tenantA.promise)
      .mockImplementationOnce(() => tenantB.promise);
    renderQuery(fetcher);
    await waitFor(() => expect(fetcher).toHaveBeenCalledTimes(1));

    fireEvent.click(screen.getByText('Switch tenant'));
    await waitFor(() => expect(fetcher).toHaveBeenCalledTimes(2));
    tenantA.resolve('tenant-a-secret');
    await Promise.resolve();
    expect(screen.getByTestId('result')).not.toHaveTextContent('tenant-a-secret');
    tenantB.resolve('tenant-b-result');
    await waitFor(() => expect(screen.getByTestId('result')).toHaveTextContent('tenant-b-result'));
  });

  it('does not cache or publish a response after component unmount', async () => {
    const pending = deferred<string>();
    const fetcher = vi.fn(() => pending.promise);
    const view = renderQuery(fetcher);
    await waitFor(() => expect(fetcher).toHaveBeenCalled());
    view.unmount();
    pending.resolve('late-secret');
    await Promise.resolve();
    expect(queryCache.size()).toBe(0);
  });
});
