import React from 'react';

export type ExtensionPoint =
  | 'shell.header.tools'
  | 'shell.sidebar.footer'
  | 'page.actions'
  | 'record.detail.tabs'
  | 'settings.sections';

export interface ExtensionDefinition {
  id: string;
  slot: ExtensionPoint;
  priority?: number;
  component: React.ComponentType<any>;
}
