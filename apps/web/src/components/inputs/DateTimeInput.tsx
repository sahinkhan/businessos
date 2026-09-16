import { forwardRef } from 'react';
import { Calendar } from 'lucide-react';
import { TextInput, TextInputProps } from './TextInput';

export type DateTimeInputProps = Omit<TextInputProps, 'type'>;

export const DateTimeInput = forwardRef<HTMLInputElement, DateTimeInputProps>((props, ref) => {
  return (
    <TextInput ref={ref} type="datetime-local" leftElement={<Calendar size={16} />} {...props} />
  );
});
DateTimeInput.displayName = 'DateTimeInput';
