import { describe, expect, it } from 'vitest';
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';

describe('module contribution architecture', () => {
  it('keeps the root router generic so future modules require no router edit', () => {
    const source = readFileSync(resolve(process.cwd(), 'src/app/routes.tsx'), 'utf8');
    expect(source).toContain('routeRegistry.getSnapshot');
    expect(source).not.toContain('DashboardOverview');
    expect(source).not.toContain('DataTableDemoPage');
  });
});
