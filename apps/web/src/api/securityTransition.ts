export type SecurityTransitionRunner = <T>(operation: () => Promise<T>) => Promise<T>;

/** Serialize operations that can rotate or revoke the browser's opaque session cookie. */
export function createSecurityTransitionCoordinator(): SecurityTransitionRunner {
  let transitionTail: Promise<void> | null = null;
  return <T>(operation: () => Promise<T>): Promise<T> => {
    let result: Promise<T>;
    if (transitionTail) {
      result = transitionTail.then(operation, operation);
    } else {
      try {
        result = Promise.resolve(operation());
      } catch (error: unknown) {
        result = Promise.reject(error);
      }
    }
    const settled = result.then(
      () => undefined,
      () => undefined
    );
    transitionTail = settled;
    void settled.finally(() => {
      if (transitionTail === settled) transitionTail = null;
    });
    return result;
  };
}
