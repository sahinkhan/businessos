import React, { useState } from 'react';
import { Card } from '../components/structure/Card';
import { FormField } from '../components/form/FormField';
import { FormSection } from '../components/form/FormSection';
import { FormActions } from '../components/form/FormActions';
import { FormErrorSummary } from '../components/form/FormErrorSummary';
import { useUnsavedChanges } from '../components/form/useUnsavedChanges';
import { TextInput } from '../components/inputs/TextInput';
import { TextArea } from '../components/inputs/TextArea';
import { NumberInput } from '../components/inputs/NumberInput';
import { MoneyInput } from '../components/inputs/MoneyInput';
import { Select } from '../components/inputs/Select';
import { MultiSelect } from '../components/inputs/MultiSelect';
import { Checkbox } from '../components/inputs/Checkbox';
import { Switch } from '../components/inputs/Switch';
import { DateInput } from '../components/inputs/DateInput';
import { useToast } from '../components/feedback/Toast';

export const FormsDemoPage: React.FC = () => {
  const [title, setTitle] = useState('');
  const [description, setDescription] = useState('');
  const [quantity, setQuantity] = useState<number | ''>(10);
  const [amount, setAmount] = useState<number | ''>(2500.0);
  const [currency, setCurrency] = useState('USD');
  const [category, setCategory] = useState('');
  const [tags, setTags] = useState<string[]>(['tech']);
  const [isUrgent, setIsUrgent] = useState(false);
  const [sendAlert, setSendAlert] = useState(true);
  const [dueDate, setDueDate] = useState('2026-10-01');
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [errors, setErrors] = useState<Array<{ fieldId: string; label: string; message: string }>>(
    []
  );

  const isDirty = Boolean(title || description);
  useUnsavedChanges(isDirty);

  const toast = useToast();

  const handleSubmit = (e?: React.FormEvent) => {
    if (e) e.preventDefault();
    const newErrors = [];

    if (!title.trim()) {
      newErrors.push({
        fieldId: 'form_title',
        label: 'Document Title',
        message: 'Title is mandatory',
      });
    }
    if (!category) {
      newErrors.push({
        fieldId: 'form_category',
        label: 'Category',
        message: 'Please select an item category',
      });
    }

    setErrors(newErrors);

    if (newErrors.length > 0) {
      toast.error('Validation Error', 'Please correct the highlighted fields.');
      return;
    }

    setIsSubmitting(true);
    setTimeout(() => {
      setIsSubmitting(false);
      toast.success('Form Saved', 'Enterprise record successfully updated.');
    }, 1000);
  };

  return (
    <div
      style={{
        maxWidth: '800px',
        margin: '0 auto',
        display: 'flex',
        flexDirection: 'column',
        gap: '20px',
      }}
    >
      <div>
        <h1 style={{ fontSize: '1.5rem', fontWeight: 700, color: 'var(--color-text-primary)' }}>
          Enterprise Form &amp; Input Primitives
        </h1>
        <p style={{ fontSize: '0.875rem', color: 'var(--color-text-secondary)', marginTop: '4px' }}>
          Demonstrating accessible form fields, auto-wired label/help/error IDs, money input,
          multi-select, and unsaved changes safety.
        </p>
      </div>

      <Card>
        <form
          onSubmit={(e) => {
            e.preventDefault();
            handleSubmit();
          }}
        >
          <FormErrorSummary errors={errors} />

          <FormSection
            title="General Information"
            description="Basic document identifiers and categorization"
          >
            <FormField
              id="form_title"
              label="Document Title"
              required
              error={errors.find((err) => err.fieldId === 'form_title')?.message}
              helpText="Provide a descriptive name for this record"
            >
              <TextInput
                value={title}
                onChange={(e) => setTitle(e.target.value)}
                placeholder="e.g. Master Supply Agreement 2026"
              />
            </FormField>

            <FormField label="Description" optional helpText="Detailed background information">
              <TextArea
                value={description}
                onChange={(e) => setDescription(e.target.value)}
                showCount
                maxLength={200}
                placeholder="Enter description..."
              />
            </FormField>

            <FormField
              id="form_category"
              label="Category"
              required
              error={errors.find((err) => err.fieldId === 'form_category')?.message}
            >
              <Select
                value={category}
                onChange={(e) => setCategory(e.target.value)}
                placeholder="Select category..."
                options={[
                  { value: 'procurement', label: 'Procurement' },
                  { value: 'finance', label: 'Financial Accounting' },
                  { value: 'logistics', label: 'Warehouse & Logistics' },
                  { value: 'tech', label: 'Information Technology' },
                ]}
              />
            </FormField>
          </FormSection>

          <FormSection
            title="Financial &amp; Logistics"
            description="Numerical quantities, values, and schedules"
          >
            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '16px' }}>
              <FormField label="Units / Quantity">
                <NumberInput value={quantity} onChange={setQuantity} min={1} max={1000} />
              </FormField>

              <FormField label="Financial Commitment">
                <MoneyInput
                  value={amount}
                  currency={currency}
                  onValueChange={(val, cur) => {
                    setAmount(val);
                    setCurrency(cur);
                  }}
                />
              </FormField>
            </div>

            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '16px' }}>
              <FormField label="Target Effective Date">
                <DateInput value={dueDate} onChange={(e) => setDueDate(e.target.value)} />
              </FormField>

              <FormField label="Classification Tags">
                <MultiSelect
                  value={tags}
                  onChange={setTags}
                  options={[
                    { value: 'tech', label: 'Technology' },
                    { value: 'urgent', label: 'High Priority' },
                    { value: 'audit', label: 'Subject to Audit' },
                    { value: 'cross_site', label: 'Cross-Site Allocation' },
                  ]}
                />
              </FormField>
            </div>
          </FormSection>

          <FormSection title="Workflow Policies">
            <div style={{ display: 'flex', flexDirection: 'column', gap: '12px' }}>
              <Checkbox
                label="Expedited Multi-Approver Routing"
                description="Flags record for immediate leadership review"
                checked={isUrgent}
                onChange={(e) => setIsUrgent(e.target.checked)}
              />
              <Switch
                label="Send automated audit notification to site administrator"
                checked={sendAlert}
                onChange={setSendAlert}
              />
            </div>
          </FormSection>

          <FormActions
            onSubmit={handleSubmit}
            onCancel={() => {
              setTitle('');
              setDescription('');
              toast.info('Form Reset', 'Reverted unsaved edits.');
            }}
            isSubmitting={isSubmitting}
            submitLabel="Commit Changes"
          />
        </form>
      </Card>
    </div>
  );
};
