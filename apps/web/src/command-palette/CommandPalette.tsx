import React, { useState, useEffect, useRef } from 'react';
import { useNavigate } from 'react-router-dom';
import { Search, ArrowRight, CornerDownLeft } from 'lucide-react';
import { navigationRegistry } from '../navigation/registry';
import { useTheme } from '../design-system/theme/ThemeContext';
import { useScope } from '../scope/ScopeContext';

export interface CommandItem {
  id: string;
  label: string;
  category: string;
  action: () => void;
  keywords?: string[];
}

export const CommandPalette: React.FC = () => {
  const [isOpen, setIsOpen] = useState(false);
  const [query, setQuery] = useState('');
  const [selectedIndex, setSelectedIndex] = useState(0);
  const navigate = useNavigate();
  const { toggleTheme } = useTheme();
  const { tenants, setTenant } = useScope();
  const inputRef = useRef<HTMLInputElement>(null);

  // Keyboard shortcut: Cmd+K / Ctrl+K
  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === 'k') {
        e.preventDefault();
        setIsOpen((prev) => !prev);
      } else if (e.key === 'Escape' && isOpen) {
        setIsOpen(false);
      }
    };
    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, [isOpen]);

  useEffect(() => {
    if (isOpen) {
      setQuery('');
      setSelectedIndex(0);
      setTimeout(() => inputRef.current?.focus(), 50);
    }
  }, [isOpen]);

  // Aggregate command items
  const commands: CommandItem[] = [
    ...navigationRegistry.getAll().map((nav) => ({
      id: nav.id,
      label: `Go to ${nav.label}`,
      category: 'Navigation',
      action: () => navigate(nav.path),
      keywords: [nav.label.toLowerCase(), nav.path],
    })),
    {
      id: 'cmd_theme_toggle',
      label: 'Toggle Theme (Light / Dark)',
      category: 'Preferences',
      action: () => toggleTheme(),
      keywords: ['theme', 'dark', 'light', 'mode'],
    },
    ...tenants.map((t) => ({
      id: `cmd_tenant_${t.id}`,
      label: `Switch Tenant to ${t.name}`,
      category: 'Scope Switcher',
      action: () => setTenant(t.id),
      keywords: ['tenant', 'switch', t.name.toLowerCase()],
    })),
  ];

  const filteredCommands = commands.filter((cmd) => {
    if (!query) return true;
    const q = query.toLowerCase();
    return (
      cmd.label.toLowerCase().includes(q) ||
      cmd.category.toLowerCase().includes(q) ||
      cmd.keywords?.some((k) => k.includes(q))
    );
  });

  const handleKeyDownInList = (e: React.KeyboardEvent) => {
    if (e.key === 'ArrowDown') {
      e.preventDefault();
      setSelectedIndex((prev) => (prev + 1) % Math.max(1, filteredCommands.length));
    } else if (e.key === 'ArrowUp') {
      e.preventDefault();
      setSelectedIndex(
        (prev) => (prev - 1 + filteredCommands.length) % Math.max(1, filteredCommands.length)
      );
    } else if (e.key === 'Enter') {
      e.preventDefault();
      const cmd = filteredCommands[selectedIndex];
      if (cmd) {
        cmd.action();
        setIsOpen(false);
      }
    }
  };

  if (!isOpen) return null;

  return (
    <div
      role="dialog"
      aria-modal="true"
      aria-label="Command Palette"
      style={{
        position: 'fixed',
        inset: 0,
        backgroundColor: 'var(--color-surface-overlay)',
        zIndex: 1400,
        display: 'flex',
        alignItems: 'flex-start',
        justifyContent: 'center',
        paddingTop: '15vh',
      }}
      onClick={(e) => {
        if (e.target === e.currentTarget) setIsOpen(false);
      }}
    >
      <div
        style={{
          width: '100%',
          maxWidth: '560px',
          backgroundColor: 'var(--color-surface-card)',
          borderRadius: '10px',
          border: '1px solid var(--color-border-subtle)',
          boxShadow: 'var(--shadow-modal)',
          overflow: 'hidden',
          display: 'flex',
          flexDirection: 'column',
          animation: 'bos-scale-in 150ms ease',
        }}
        onKeyDown={handleKeyDownInList}
      >
        <div
          style={{
            display: 'flex',
            alignItems: 'center',
            padding: '12px 16px',
            borderBottom: '1px solid var(--color-border-subtle)',
            gap: '10px',
          }}
        >
          <Search size={18} color="var(--color-text-muted)" />
          <input
            ref={inputRef}
            type="text"
            value={query}
            onChange={(e) => {
              setQuery(e.target.value);
              setSelectedIndex(0);
            }}
            placeholder="Type a command or search destination..."
            style={{
              flex: 1,
              background: 'transparent',
              border: 'none',
              outline: 'none',
              fontSize: '1rem',
              color: 'var(--color-text-primary)',
            }}
          />
          <kbd
            style={{
              padding: '2px 6px',
              borderRadius: '4px',
              backgroundColor: 'var(--color-surface-subtle)',
              border: '1px solid var(--color-border-subtle)',
              fontSize: '0.6875rem',
              color: 'var(--color-text-muted)',
            }}
          >
            ESC
          </kbd>
        </div>

        <div style={{ maxHeight: '340px', overflowY: 'auto', padding: '8px' }}>
          {filteredCommands.length === 0 ? (
            <div
              style={{
                padding: '24px',
                textAlign: 'center',
                color: 'var(--color-text-muted)',
                fontSize: '0.875rem',
              }}
            >
              No commands found matching "{query}"
            </div>
          ) : (
            filteredCommands.map((cmd, idx) => {
              const isSelected = idx === selectedIndex;
              return (
                <div
                  key={cmd.id}
                  onClick={() => {
                    cmd.action();
                    setIsOpen(false);
                  }}
                  onMouseEnter={() => setSelectedIndex(idx)}
                  style={{
                    display: 'flex',
                    alignItems: 'center',
                    justifyContent: 'space-between',
                    padding: '8px 12px',
                    borderRadius: '6px',
                    cursor: 'pointer',
                    backgroundColor: isSelected ? 'var(--color-surface-subtle)' : 'transparent',
                    color: isSelected ? 'var(--color-action-primary)' : 'var(--color-text-primary)',
                    fontSize: '0.875rem',
                  }}
                >
                  <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                    <ArrowRight size={14} style={{ opacity: isSelected ? 1 : 0.4 }} />
                    <span style={{ fontWeight: isSelected ? 600 : 400 }}>{cmd.label}</span>
                  </div>
                  <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                    <span style={{ fontSize: '0.75rem', color: 'var(--color-text-muted)' }}>
                      {cmd.category}
                    </span>
                    {isSelected && <CornerDownLeft size={12} color="var(--color-text-muted)" />}
                  </div>
                </div>
              );
            })
          )}
        </div>
      </div>
    </div>
  );
};
