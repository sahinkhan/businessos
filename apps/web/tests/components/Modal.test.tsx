import { describe, it, expect, vi } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';
import { Modal } from '../../src/components/overlays/Modal';
import { Button } from '../../src/components/actions/Button';

describe('Modal Primitive', () => {
  it('renders with accessibility attributes and closes on Escape key', () => {
    const handleClose = vi.fn();
    render(
      <Modal
        isOpen={true}
        onClose={handleClose}
        title="Confirm Operation"
        footer={<Button onClick={handleClose}>Dismiss</Button>}
      >
        <p>Operational body description</p>
      </Modal>
    );

    const dialog = screen.getByRole('dialog');
    expect(dialog).toBeInTheDocument();
    expect(dialog).toHaveAttribute('aria-modal', 'true');
    expect(screen.getByText('Confirm Operation')).toBeInTheDocument();
    expect(screen.getByText('Operational body description')).toBeInTheDocument();

    // Escape key press
    fireEvent.keyDown(window, { key: 'Escape' });
    expect(handleClose).toHaveBeenCalledTimes(1);
  });

  it('does not render when isOpen is false', () => {
    render(
      <Modal isOpen={false} onClose={() => {}} title="Hidden Dialog">
        Content
      </Modal>
    );

    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
  });
});
