import React from 'react';
import { AlignJustify } from 'lucide-react';
import { Dropdown } from '../overlays/Dropdown';
import { Button } from '../actions/Button';
import { TableDensity } from './types';

export interface DensityToggleProps {
  density: TableDensity;
  onChange: (d: TableDensity) => void;
}

export const DensityToggle: React.FC<DensityToggleProps> = ({ density, onChange }) => {
  return (
    <Dropdown
      trigger={
        <Button variant="outline" size="sm" leftIcon={<AlignJustify size={14} />}>
          Density
        </Button>
      }
      items={[
        {
          id: 'compact',
          label: 'Compact' + (density === 'compact' ? ' ✓' : ''),
          onClick: () => onChange('compact'),
        },
        {
          id: 'normal',
          label: 'Normal' + (density === 'normal' ? ' ✓' : ''),
          onClick: () => onChange('normal'),
        },
        {
          id: 'comfortable',
          label: 'Comfortable' + (density === 'comfortable' ? ' ✓' : ''),
          onClick: () => onChange('comfortable'),
        },
      ]}
    />
  );
};
