import { describe, it, expect } from 'vitest';
import { navigationRegistry } from '../../src/navigation/registry';

describe('Navigation Registry', () => {
  it('registers navigation items dynamically and groups them', () => {
    navigationRegistry.register({
      id: 'custom_reports',
      label: 'Financial Statements',
      path: '/reports/financial',
      group: 'Reporting',
      order: 5,
    });

    const items = navigationRegistry.getAll();
    const registered = items.find((i) => i.id === 'custom_reports');
    expect(registered).toBeDefined();
    expect(registered?.label).toBe('Financial Statements');

    const groups = navigationRegistry.getGroups();
    const reportGroup = groups.find((g) => g.label === 'Reporting');
    expect(reportGroup).toBeDefined();
    expect(reportGroup?.items.some((i) => i.id === 'custom_reports')).toBe(true);

    navigationRegistry.unregister('custom_reports');
  });
});
