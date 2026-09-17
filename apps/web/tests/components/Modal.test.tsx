import { describe, it, expect, vi } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';
import { Modal } from '../../src/components/overlays/Modal';
import { Button } from '../../src/components/actions/Button';
import { useState } from 'react';

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

  it('moves focus inside, traps both tab directions, and restores the trigger', () => {
    const Harness = () => {
      const [open, setOpen] = useState(false);
      return (
        <>
          <button onClick={() => setOpen(true)}>Open</button>
          <Modal
            isOpen={open}
            onClose={() => setOpen(false)}
            title="Focus test"
            footer={<button onClick={() => setOpen(false)}>Finish</button>}
          >
            <button>First action</button>
          </Modal>
        </>
      );
    };
    render(<Harness />);
    const trigger = screen.getByText('Open');
    trigger.focus();
    fireEvent.click(trigger);
    const close = screen.getByLabelText('Close dialog');
    expect(close).toHaveFocus();
    const finish = screen.getByText('Finish');
    finish.focus();
    fireEvent.keyDown(window, { key: 'Tab' });
    expect(close).toHaveFocus();
    close.focus();
    fireEvent.keyDown(window, { key: 'Tab', shiftKey: true });
    expect(finish).toHaveFocus();
    fireEvent.click(finish);
    expect(trigger).toHaveFocus();
  });
});
