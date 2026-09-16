export interface NavItem {
  id: string;
  label: string;
  path: string;
  icon?: string;
  group?: string;
  order?: number;
  badge?: string | number;
  requiredPermission?: {
    action: string;
    resource: string;
  };
}

export interface NavGroup {
  id: string;
  label: string;
  order?: number;
  items: NavItem[];
}
