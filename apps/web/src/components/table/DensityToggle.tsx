import React from 'react';
import { AlignJustify } from 'lucide-react';
import { Dropdown } from '../overlays/Dropdown';
import { Button } from '../actions/Button';
import { TableDensity } from './types';
import { useI18nText } from '../../i18n/I18nContext';

export interface DensityToggleProps {
  density: TableDensity;
  onChange: (d: TableDensity) => void;
}

export const DensityToggle: React.FC<DensityToggleProps> = ({ density, onChange }) => {
  const { t } = useI18nText();
  return (
    <Dropdown
      trigger={
        <Button variant="outline" size="sm" leftIcon={<AlignJustify size={14} />}>
          {t('table.density')}
        </Button>
      }
      items={[
        {
          id: 'compact',
          label: t('table.density.compact') + (density === 'compact' ? ' ✓' : ''),
          onClick: () => onChange('compact'),
        },
        {
          id: 'normal',
          label: t('table.density.normal') + (density === 'normal' ? ' ✓' : ''),
          onClick: () => onChange('normal'),
        },
        {
          id: 'comfortable',
          label: t('table.density.comfortable') + (density === 'comfortable' ? ' ✓' : ''),
          onClick: () => onChange('comfortable'),
        },
      ]}
    />
  );
};
