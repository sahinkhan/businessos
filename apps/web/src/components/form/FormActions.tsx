import React from 'react';
import { Button } from '../actions/Button';
import { useI18nText } from '../../i18n/I18nContext';

export interface FormActionsProps {
  onSubmit?: () => void;
  onCancel?: () => void;
  onReset?: () => void;
  submitLabel?: string;
  cancelLabel?: string;
  resetLabel?: string;
  isSubmitting?: boolean;
  isValid?: boolean;
  align?: 'left' | 'right' | 'space-between';
}

export const FormActions: React.FC<FormActionsProps> = ({
  onSubmit,
  onCancel,
  onReset,
  submitLabel,
  cancelLabel,
  resetLabel,
  isSubmitting = false,
  isValid = true,
  align = 'right',
}) => {
  const { t } = useI18nText();
  return (
    <div
      style={{
        display: 'flex',
        alignItems: 'center',
        justifyContent:
          align === 'right' ? 'flex-end' : align === 'left' ? 'flex-start' : 'space-between',
        gap: '8px',
        marginTop: '24px',
        paddingTop: '16px',
        borderTop: '1px solid var(--color-border-subtle)',
      }}
    >
      {onReset && (
        <Button variant="ghost" size="md" onClick={onReset} disabled={isSubmitting}>
          {resetLabel ?? t('common.reset')}
        </Button>
      )}
      <div style={{ display: 'flex', gap: '8px' }}>
        {onCancel && (
          <Button variant="secondary" size="md" onClick={onCancel} disabled={isSubmitting}>
            {cancelLabel ?? t('common.cancel')}
          </Button>
        )}
        <Button
          variant="primary"
          size="md"
          type="submit"
          onClick={onSubmit}
          isLoading={isSubmitting}
          disabled={!isValid || isSubmitting}
        >
          {submitLabel ?? t('common.save_changes')}
        </Button>
      </div>
    </div>
  );
};
