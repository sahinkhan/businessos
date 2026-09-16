import { describe, it, expect } from 'vitest';
import { render } from '@testing-library/react';
import axe from 'axe-core';
import { Button } from '../../src/components/actions/Button';
import { FormField } from '../../src/components/form/FormField';
import { TextInput } from '../../src/components/inputs/TextInput';
import { Alert } from '../../src/components/feedback/Alert';

describe('Automated WCAG AA Accessibility Audits', () => {
  it('Button primitive satisfies axe-core accessibility standards', async () => {
    const { container } = render(<Button variant="primary">Accessible Action</Button>);
    const results = await axe.run(container);
    expect(results.violations).toEqual([]);
  });

  it('FormField primitive with label and input satisfies axe-core', async () => {
    const { container } = render(
      <FormField id="acc_name" label="Full Name" helpText="Legal naming" required>
        <TextInput />
      </FormField>
    );
    const results = await axe.run(container);
    expect(results.violations).toEqual([]);
  });

  it('Alert feedback primitive satisfies axe-core standards', async () => {
    const { container } = render(
      <Alert severity="warning" title="Audit Required">
        Review required documentation before proceeding.
      </Alert>
    );
    const results = await axe.run(container);
    expect(results.violations).toEqual([]);
  });
});
