import React, { useState } from 'react';
import { SettingsPageShell } from '../layouts/SettingsPageShell';
import { Card } from '../components/structure/Card';
import { FormField } from '../components/form/FormField';
import { FormActions } from '../components/form/FormActions';
import { Select } from '../components/inputs/Select';
import { Switch } from '../components/inputs/Switch';
import { useTheme } from '../design-system/theme/ThemeContext';
import { useI18n } from '../i18n/I18nContext';
import { useToast } from '../components/feedback/Toast';
import { Sliders, Shield, Palette, Globe } from 'lucide-react';

export const SettingsPage: React.FC = () => {
  const [activeCategory, setActiveCategory] = useState('preferences');
  const { theme, setTheme } = useTheme();
  const { locale, setLocale } = useI18n();
  const toast = useToast();

  const [compactDefault, setCompactDefault] = useState(false);
  const [reducedMotion, setReducedMotion] = useState(false);

  return (
    <SettingsPageShell
      title="System Preferences &amp; Settings"
      categories={[
        { id: 'preferences', label: 'User Preferences', icon: <Sliders size={16} /> },
        { id: 'appearance', label: 'Appearance & Theme', icon: <Palette size={16} /> },
        { id: 'localization', label: 'Language & Locale', icon: <Globe size={16} /> },
        { id: 'security', label: 'Security & Access', icon: <Shield size={16} /> },
      ]}
      activeCategoryId={activeCategory}
      onSelectCategory={setActiveCategory}
    >
      <Card title={activeCategory.toUpperCase()}>
        {activeCategory === 'preferences' && (
          <div>
            <FormField
              label="Default Table Density"
              helpText="Select preferred default row spacing"
            >
              <Switch
                label="Prefer Compact Density on load"
                checked={compactDefault}
                onChange={setCompactDefault}
              />
            </FormField>
            <FormField
              label="Accessibility"
              helpText="Reduced motion overrides all animated transitions"
            >
              <Switch
                label="Prefers Reduced Motion"
                checked={reducedMotion}
                onChange={setReducedMotion}
              />
            </FormField>
            <FormActions
              onSubmit={() =>
                toast.success('Preferences Saved', 'User preferences updated successfully.')
              }
            />
          </div>
        )}

        {activeCategory === 'appearance' && (
          <div>
            <FormField
              label="Interface Theme"
              helpText="Select Light, Dark, or automatically inherit system setting"
            >
              <Select
                value={theme}
                onChange={(e) => setTheme(e.target.value as any)}
                options={[
                  { value: 'system', label: 'System Automatic' },
                  { value: 'light', label: 'Enterprise Light' },
                  { value: 'dark', label: 'Enterprise Dark' },
                ]}
              />
            </FormField>
            <FormActions
              onSubmit={() => toast.success('Theme Applied', `Theme switched to ${theme}.`)}
            />
          </div>
        )}

        {activeCategory === 'localization' && (
          <div>
            <FormField
              label="Active Locale"
              helpText="Switches language dictionary, RTL/LTR layout, and date formats"
            >
              <Select
                value={locale}
                onChange={(e) => setLocale(e.target.value as any)}
                options={[
                  { value: 'en', label: 'English (US) - LTR' },
                  { value: 'ar', label: 'العربية (Arabic) - RTL' },
                  { value: 'es', label: 'Español (Spanish) - LTR' },
                ]}
              />
            </FormField>
            <FormActions
              onSubmit={() => toast.success('Locale Updated', `Active locale set to ${locale}.`)}
            />
          </div>
        )}

        {activeCategory === 'security' && (
          <div>
            <p
              style={{
                fontSize: '0.875rem',
                color: 'var(--color-text-secondary)',
                marginBottom: '16px',
              }}
            >
              Your session is authenticated via enterprise JWT credentials. Authorization policies
              are evaluated on backend gateways for every state-mutating operation.
            </p>
            <FormActions
              onSubmit={() =>
                toast.info(
                  'Security Audit',
                  'No policy violations detected for the current session.'
                )
              }
              submitLabel="Verify Token Validity"
            />
          </div>
        )}
      </Card>
    </SettingsPageShell>
  );
};
