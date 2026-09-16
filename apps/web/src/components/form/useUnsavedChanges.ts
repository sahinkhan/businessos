import { useEffect, useCallback } from 'react';

export const useUnsavedChanges = (
  isDirty: boolean,
  message = 'You have unsaved changes. Are you sure you want to leave?'
) => {
  useEffect(() => {
    const handleBeforeUnload = (event: BeforeUnloadEvent) => {
      if (isDirty) {
        event.preventDefault();
        event.returnValue = message;
        return message;
      }
    };

    window.addEventListener('beforeunload', handleBeforeUnload);
    return () => window.removeEventListener('beforeunload', handleBeforeUnload);
  }, [isDirty, message]);

  const confirmNavigation = useCallback(() => {
    if (!isDirty) return true;
    return window.confirm(message);
  }, [isDirty, message]);

  return { confirmNavigation };
};
