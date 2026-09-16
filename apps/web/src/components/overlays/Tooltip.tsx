import React, { useState } from 'react';

export interface TooltipProps {
  content: React.ReactNode;
  children: React.ReactElement;
  position?: 'top' | 'bottom' | 'left' | 'right';
  delayMs?: number;
}

export const Tooltip: React.FC<TooltipProps> = ({
  content,
  children,
  position = 'top',
  delayMs = 200,
}) => {
  const [isVisible, setIsVisible] = useState(false);
  const [timeoutId, setTimeoutId] = useState<number | null>(null);

  const handleMouseEnter = () => {
    const id = window.setTimeout(() => {
      setIsVisible(true);
    }, delayMs);
    setTimeoutId(id);
  };

  const handleMouseLeave = () => {
    if (timeoutId) clearTimeout(timeoutId);
    setIsVisible(false);
  };

  const positionStyles: React.CSSProperties =
    position === 'top'
      ? { bottom: '100%', left: '50%', transform: 'translateX(-50%)', marginBottom: '6px' }
      : position === 'bottom'
        ? { top: '100%', left: '50%', transform: 'translateX(-50%)', marginTop: '6px' }
        : position === 'left'
          ? { right: '100%', top: '50%', transform: 'translateY(-50%)', marginRight: '6px' }
          : { left: '100%', top: '50%', transform: 'translateY(-50%)', marginLeft: '6px' };

  return (
    <div
      style={{ position: 'relative', display: 'inline-flex' }}
      onMouseEnter={handleMouseEnter}
      onMouseLeave={handleMouseLeave}
      onFocus={handleMouseEnter}
      onBlur={handleMouseLeave}
    >
      {children}
      {isVisible && content && (
        <div
          role="tooltip"
          style={{
            position: 'absolute',
            ...positionStyles,
            backgroundColor: 'var(--color-surface-sidebar)',
            color: 'white',
            padding: '4px 8px',
            borderRadius: '4px',
            fontSize: '0.75rem',
            whiteSpace: 'nowrap',
            zIndex: 1500,
            pointerEvents: 'none',
            boxShadow: 'var(--shadow-dropdown)',
          }}
        >
          {content}
        </div>
      )}
    </div>
  );
};
