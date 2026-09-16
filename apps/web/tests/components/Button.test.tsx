import { describe, it, expect, vi } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';
import { Button } from '../../src/components/actions/Button';

describe('Button Primitive', () => {
  it('renders children and responds to click', () => {
    const handleClick = vi.fn();
    render(<Button onClick={handleClick}>Submit Action</Button>);

    const btn = screen.getByRole('button', { name: /submit action/i });
    expect(btn).toBeInTheDocument();
    fireEvent.click(btn);
    expect(handleClick).toHaveBeenCalledTimes(1);
  });

  it('renders loading spinner and disables button when isLoading=true', () => {
    const handleClick = vi.fn();
    render(
      <Button isLoading onClick={handleClick}>
        Save Data
      </Button>
    );

    const btn = screen.getByRole('button');
    expect(btn).toBeDisabled();
    expect(btn).toHaveAttribute('aria-busy', 'true');
    fireEvent.click(btn);
    expect(handleClick).not.toHaveBeenCalled();
  });

  it('supports variants and sizes', () => {
    const { rerender } = render(
      <Button variant="danger" size="lg">
        Delete
      </Button>
    );
    expect(screen.getByRole('button')).toHaveClass('bos-button--danger');
    expect(screen.getByRole('button')).toHaveClass('bos-button--lg');

    rerender(
      <Button variant="outline" size="sm">
        Cancel
      </Button>
    );
    expect(screen.getByRole('button')).toHaveClass('bos-button--outline');
    expect(screen.getByRole('button')).toHaveClass('bos-button--sm');
  });
});
