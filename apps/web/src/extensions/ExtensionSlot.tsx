import React from 'react';
import { ExtensionPoint } from './types';
import { extensionRegistry } from './registry';

export interface ExtensionSlotProps {
  slot: ExtensionPoint;
  context?: any;
  className?: string;
}

export const ExtensionSlot: React.FC<ExtensionSlotProps> = ({ slot, context, className }) => {
  const extensions = extensionRegistry.getForSlot(slot);

  if (extensions.length === 0) return null;

  return (
    <div className={className} style={{ display: 'inline-flex', gap: '8px', alignItems: 'center' }}>
      {extensions.map((ext) => {
        const Comp = ext.component;
        return <Comp key={ext.id} context={context} />;
      })}
    </div>
  );
};
