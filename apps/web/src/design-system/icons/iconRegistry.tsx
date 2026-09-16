import React from 'react';
import {
  LayoutDashboard,
  Settings,
  Bell,
  Search,
  Globe,
  Sun,
  Moon,
  Check,
  CheckCheck,
  CheckCircle,
  AlertTriangle,
  AlertCircle,
  AlertOctagon,
  Info,
  ChevronDown,
  ChevronUp,
  ChevronRight,
  ChevronLeft,
  ChevronsLeft,
  ChevronsRight,
  ArrowRight,
  ArrowLeft,
  ArrowUpRight,
  Plus,
  Trash2,
  Edit,
  Download,
  Upload,
  Filter,
  User,
  Users,
  Building,
  Building2,
  Shield,
  ShieldAlert,
  ShieldCheck,
  HelpCircle,
  Table,
  CheckSquare,
  Layers,
  LayoutTemplate,
  MoreHorizontal,
  MoreVertical,
  X,
  Sliders,
  Palette,
  RefreshCw,
  CornerDownLeft,
  Menu,
  Home,
  LogOut,
  SlidersHorizontal,
  Columns,
  Eye,
  Calendar,
  Clock,
  DollarSign,
  FileText,
  Folder,
  Circle,
} from 'lucide-react';

export type IconSize = 'xs' | 'sm' | 'md' | 'lg' | 'xl';

const sizeMap: Record<IconSize, number> = {
  xs: 14,
  sm: 16,
  md: 20,
  lg: 24,
  xl: 32,
};

export interface IconProps extends React.SVGProps<SVGSVGElement> {
  name: string;
  size?: IconSize | number;
  className?: string;
  'aria-label'?: string;
}

const ICON_MAP: Record<string, React.ComponentType<any>> = {
  layoutdashboard: LayoutDashboard,
  settings: Settings,
  bell: Bell,
  search: Search,
  globe: Globe,
  sun: Sun,
  moon: Moon,
  check: Check,
  checkcheck: CheckCheck,
  checkcircle: CheckCircle,
  alerttriangle: AlertTriangle,
  alertcircle: AlertCircle,
  alertoctagon: AlertOctagon,
  info: Info,
  chevrondown: ChevronDown,
  chevronup: ChevronUp,
  chevronright: ChevronRight,
  chevronleft: ChevronLeft,
  chevronsleft: ChevronsLeft,
  chevronsright: ChevronsRight,
  arrowright: ArrowRight,
  arrowleft: ArrowLeft,
  arrowupright: ArrowUpRight,
  plus: Plus,
  trash2: Trash2,
  edit: Edit,
  download: Download,
  upload: Upload,
  filter: Filter,
  user: User,
  users: Users,
  building: Building,
  building2: Building2,
  shield: Shield,
  shieldalert: ShieldAlert,
  shieldcheck: ShieldCheck,
  helpcircle: HelpCircle,
  table: Table,
  checksquare: CheckSquare,
  layers: Layers,
  layouttemplate: LayoutTemplate,
  morehorizontal: MoreHorizontal,
  morevertical: MoreVertical,
  x: X,
  sliders: Sliders,
  palette: Palette,
  refreshcw: RefreshCw,
  cornerdownleft: CornerDownLeft,
  menu: Menu,
  home: Home,
  logout: LogOut,
  slidershorizontal: SlidersHorizontal,
  columns: Columns,
  eye: Eye,
  calendar: Calendar,
  clock: Clock,
  dollarsign: DollarSign,
  filetext: FileText,
  folder: Folder,
  circle: Circle,
};

export const Icon: React.FC<IconProps> = ({
  name,
  size = 'md',
  className = '',
  'aria-label': ariaLabel,
  ...rest
}) => {
  const pixelSize = typeof size === 'number' ? size : sizeMap[size] || 20;
  const normalizedKey = name.toLowerCase().replace(/[-_]/g, '');

  const Component = ICON_MAP[normalizedKey] || HelpCircle;

  return (
    <Component
      size={pixelSize}
      className={className}
      aria-label={ariaLabel}
      aria-hidden={!ariaLabel}
      {...rest}
    />
  );
};
