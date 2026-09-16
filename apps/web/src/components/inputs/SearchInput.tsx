import { useState, useEffect, forwardRef } from 'react';
import { Search, X } from 'lucide-react';
import { TextInput, TextInputProps } from './TextInput';

export interface SearchInputProps extends Omit<TextInputProps, 'onChange'> {
  value?: string;
  onSearchChange?: (val: string) => void;
  debounceMs?: number;
}

export const SearchInput = forwardRef<HTMLInputElement, SearchInputProps>(
  (
    {
      value: externalValue = '',
      onSearchChange,
      debounceMs = 250,
      placeholder = 'Search...',
      ...rest
    },
    ref
  ) => {
    const [localValue, setLocalValue] = useState(externalValue);

    useEffect(() => {
      setLocalValue(externalValue);
    }, [externalValue]);

    useEffect(() => {
      const handler = setTimeout(() => {
        if (localValue !== externalValue) {
          onSearchChange?.(localValue);
        }
      }, debounceMs);
      return () => clearTimeout(handler);
    }, [localValue, debounceMs, onSearchChange, externalValue]);

    return (
      <TextInput
        ref={ref}
        type="search"
        placeholder={placeholder}
        value={localValue}
        onChange={(e) => setLocalValue(e.target.value)}
        leftElement={<Search size={16} />}
        rightElement={
          localValue ? (
            <button
              type="button"
              onClick={() => {
                setLocalValue('');
                onSearchChange?.('');
              }}
              aria-label="Clear search"
              style={{ background: 'none', border: 'none', cursor: 'pointer', padding: 0 }}
            >
              <X size={14} />
            </button>
          ) : undefined
        }
        {...rest}
      />
    );
  }
);
SearchInput.displayName = 'SearchInput';
