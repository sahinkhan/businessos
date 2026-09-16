import { forwardRef } from 'react';
import { Calendar } from 'lucide-react';
import { TextInput, TextInputProps } from './TextInput';

export type DateInputProps = Omit<TextInputProps, 'type'>;

export const DateInput = forwardRef<HTMLInputElement, DateInputProps>((props, ref) => {
  return <TextInput ref={ref} type="date" leftElement={<Calendar size={16} />} {...props} />;
});
DateInput.displayName = 'DateInput';
