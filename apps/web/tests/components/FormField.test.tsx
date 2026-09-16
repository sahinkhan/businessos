import { describe, it, expect } from 'vitest';
import { render, screen } from '@testing-library/react';
import { FormField } from '../../src/components/form/FormField';
import { TextInput } from '../../src/components/inputs/TextInput';

describe('FormField Primitive', () => {
  it('associates label, input, helpText and error with correct aria attributes', () => {
    render(
      <FormField
        id="user_email"
        label="Business Email"
        required
        helpText="Use company domain"
        error="Email is already in use"
      >
        <TextInput />
      </FormField>
    );

    const label = screen.getByText('Business Email');
    expect(label).toBeInTheDocument();
    expect(screen.getByText('*')).toHaveAttribute('aria-hidden', 'true');

    const input = screen.getByRole('textbox');
    expect(input).toHaveAttribute('id', 'user_email');
    expect(input).toHaveAttribute('aria-invalid', 'true');
    expect(input).toHaveAttribute('aria-required', 'true');

    const error = screen.getByRole('alert');
    expect(error).toHaveTextContent('Email is already in use');

    const describedBy = input.getAttribute('aria-describedby');
    expect(describedBy).toContain('user_email-help');
    expect(describedBy).toContain('user_email-error');
  });
});
