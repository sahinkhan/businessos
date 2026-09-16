export interface AppConfig {
  apiUrl: string;
  environment: 'development' | 'staging' | 'production';
  version: string;
}

export const appConfig: AppConfig = {
  apiUrl: import.meta.env.VITE_API_URL || '/api',
  environment: (import.meta.env.MODE as any) || 'development',
  version: '0.4.5',
};
