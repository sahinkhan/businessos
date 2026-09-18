export interface NavItem {
  id: string;
  /** Translation resource key. Official contributions must provide this field. */
  labelKey?: string;
  /** Legacy/custom display label fallback for third-party contributions. */
  label?: string;
  path: string;
  /** Optional reference to a registered route ID in RouteRegistry */
  routeId?: string;
  icon?: string;
  groupKey?: string;
  order?: number;
  badge?: string | number;
  requiredPermission?: {
    action: string;
    resource: string;
  };
}

export interface NavGroup {
  id: string;
  labelKey?: string;
  label?: string;
  order?: number;
  items: NavItem[];
}
