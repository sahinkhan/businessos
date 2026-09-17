import { useCallback, useEffect } from 'react';
import { useBeforeUnload, useBlocker } from 'react-router-dom';
import { useI18n } from '../../i18n/I18nContext';

export const useUnsavedChanges = (isDirty: boolean, message?: string) => {
  const { t } = useI18n();
  const resolvedMessage = message ?? t('forms.unsaved');
  useBeforeUnload(
    useCallback(
      (event: BeforeUnloadEvent) => {
        if (!isDirty) return;
        event.preventDefault();
        event.returnValue = resolvedMessage;
      },
      [isDirty, resolvedMessage]
    )
  );

  const blocker = useBlocker(isDirty);

  useEffect(() => {
    if (blocker.state !== 'blocked') return;
    if (window.confirm(resolvedMessage)) blocker.proceed();
    else blocker.reset();
  }, [blocker, resolvedMessage]);

  const confirmNavigation = useCallback(
    () => !isDirty || window.confirm(resolvedMessage),
    [isDirty, resolvedMessage]
  );

  return { confirmNavigation };
};
