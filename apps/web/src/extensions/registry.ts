import { ExtensionDefinition, ExtensionPoint } from './types';

class ExtensionRegistry {
  private extensions: Map<string, ExtensionDefinition> = new Map();

  public register(extension: ExtensionDefinition): void {
    this.extensions.set(extension.id, extension);
  }

  public unregister(id: string): void {
    this.extensions.delete(id);
  }

  public getForSlot(slot: ExtensionPoint): ExtensionDefinition[] {
    return Array.from(this.extensions.values())
      .filter((ext) => ext.slot === slot)
      .sort((a, b) => (b.priority ?? 0) - (a.priority ?? 0));
  }
}

export const extensionRegistry = new ExtensionRegistry();
