import { useCallback } from 'react';

export const useTelemetry = () => {
  const trackEvent = useCallback((eventName: string, properties?: Record<string, any>) => {
    // Phase 4.5 client-side telemetry hook
    if (import.meta.env?.DEV) {
      console.log(`[Telemetry] ${eventName}`, properties);
    }
  }, []);

  return { trackEvent };
};
