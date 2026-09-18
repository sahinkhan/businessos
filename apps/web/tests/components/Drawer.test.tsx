import { fireEvent, render, screen } from '@testing-library/react';
import { useState } from 'react';
import { describe, expect, it } from 'vitest';
import { Drawer } from '../../src/components/overlays/Drawer';

describe('Drawer', () => {
  it('moves focus inside, traps focus, closes on Escape, and restores focus', () => {
    const Harness = () => {
      const [open, setOpen] = useState(false);
      return (
        <>
          <button onClick={() => setOpen(true)}>Open navigation</button>
          <Drawer
            isOpen={open}
            onClose={() => setOpen(false)}
            title="Navigation"
            closeLabel="Close navigation"
          >
            <a href="/dashboard">Dashboard</a>
          </Drawer>
        </>
      );
    };

    render(<Harness />);
    const trigger = screen.getByText('Open navigation');
    trigger.focus();
    fireEvent.click(trigger);
    const close = screen.getByLabelText('Close navigation');
    const link = screen.getByText('Dashboard');
    expect(close).toHaveFocus();
    link.focus();
    fireEvent.keyDown(window, { key: 'Tab' });
    expect(close).toHaveFocus();
    close.focus();
    fireEvent.keyDown(window, { key: 'Tab', shiftKey: true });
    expect(link).toHaveFocus();
    fireEvent.keyDown(window, { key: 'Escape' });
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
    expect(trigger).toHaveFocus();
  });

  it('closes when the overlay is selected', () => {
    const Harness = () => {
      const [open, setOpen] = useState(true);
      return (
        <Drawer isOpen={open} onClose={() => setOpen(false)} title="Navigation">
          Content
        </Drawer>
      );
    };
    render(<Harness />);
    fireEvent.click(screen.getByRole('dialog'));
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
  });

  it('keeps controlled input focus through rerenders and restores focus after reopen', () => {
    const Harness = () => {
      const [open, setOpen] = useState(false);
      const [value, setValue] = useState('');
      return (
        <>
          <button onClick={() => setOpen(true)}>Open editor</button>
          <Drawer isOpen={open} onClose={() => setOpen(false)} title="Editor">
            <input
              aria-label="Record name"
              value={value}
              onChange={(event) => setValue(event.target.value)}
            />
            <button>Last action</button>
          </Drawer>
        </>
      );
    };
    render(<Harness />);
    const trigger = screen.getByText('Open editor');
    trigger.focus();
    fireEvent.click(trigger);
    const input = screen.getByRole('textbox', { name: 'Record name' });
    input.focus();
    fireEvent.change(input, { target: { value: 'ABC' } });
    expect(input).toHaveFocus();
    fireEvent.keyDown(window, { key: 'Tab' });
    fireEvent.keyDown(window, { key: 'Tab', shiftKey: true });
    fireEvent.keyDown(window, { key: 'Escape' });
    expect(trigger).toHaveFocus();
    fireEvent.click(trigger);
    expect(screen.getByRole('button', { name: 'Close' })).toHaveFocus();
  });
});
