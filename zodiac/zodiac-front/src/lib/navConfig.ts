export type NavItem = {
  id: string;
  label: string;
  path: string;
  description: string;
  icon: string;
  adminOnly?: boolean;
};

export type NavGroup = {
  id: string;
  label: string;
  items: NavItem[];
};

export const SUPPORTED_INVESTIGATIONS = [
  { label: 'Highest-profit products', question: 'Show the products with the highest profits.' },
  { label: 'What changed this month?', question: 'Show monthly revenue.' },
  { label: 'Products driving growth', question: 'Which products grew the most?' },
  { label: 'Inventory versus sales', question: 'Show inventory versus sales.' },
  { label: 'Why did margin decline?', question: 'Which products had the biggest margin decline?' },
  { label: 'Customers behind the change', question: 'Show their customers.' },
  { label: 'Supplier concentration', question: 'Show supplier concentration.' },
];

export function adminNavGroups(opts: { isAdmin: boolean; workspaceUi: boolean }): NavGroup[] {
  const groups: NavGroup[] = [
    {
      id: 'understand',
      label: 'Understand',
      items: [
        {
          id: 'overview',
          label: 'Overview',
          path: '/overview',
          description: 'Business snapshot and what to investigate',
          icon: 'LayoutDashboard',
        },
      ],
    },
    {
      id: 'ask',
      label: 'Ask',
      items: [
        {
          id: 'ai-analyst',
          label: 'AI Analyst',
          path: '/dashboard/ai',
          description: 'Governed questions over SAP data',
          icon: 'Sparkles',
        },
      ],
    },
    {
      id: 'operate',
      label: 'Operate',
      items: [
        {
          id: 'edi',
          label: 'EDI operations',
          path: '/dashboard',
          description: 'Inbound SAT and outbound invoice operations',
          icon: 'ArrowDownToLine',
        },
        {
          id: 'invoices',
          label: 'Invoices',
          path: '/invoices-v2',
          description: 'Validate and convert invoices',
          icon: 'FileText',
        },
        {
          id: 'sat-documents',
          label: 'SAT documents',
          path: '/sat-documents',
          description: 'CFDI intake, merge, and send to SAP',
          icon: 'Receipt',
        },
      ],
    },
    {
      id: 'manage',
      label: 'Manage',
      items: [
        {
          id: 'customers',
          label: 'Customers',
          path: '/customers',
          description: 'EDI customer accounts',
          icon: 'Building2',
        },
        ...(opts.workspaceUi
          ? [
              {
                id: 'workspaces',
                label: 'Workspaces',
                path: '/workspace',
                description: 'Per-customer workspace',
                icon: 'Boxes',
              },
            ]
          : []),
        ...(opts.isAdmin
          ? [
              {
                id: 'customer-users',
                label: 'Customer users',
                path: '/customer-users',
                description: 'Users and customer assignments',
                icon: 'Users',
                adminOnly: true,
              },
            ]
          : []),
        {
          id: 'account-mapping',
          label: 'RFC to G/L mapping',
          path: '/admin/account-mapping',
          description: 'Map supplier RFC codes to SAP G/L accounts',
          icon: 'MapPin',
        },
        {
          id: 'supplier-tokens',
          label: 'Supplier API access',
          path: '/admin/supplier-tokens',
          description: 'Tokens for supplier document intake',
          icon: 'Key',
        },
        {
          id: 'settings',
          label: 'Settings',
          path: '/settings',
          description: 'Profile, security, and API access',
          icon: 'Settings',
        },
      ],
    },
  ];
  return groups;
}

export function isNavActive(pathname: string, item: NavItem): boolean {
  if (item.path === '/dashboard') return pathname === '/dashboard';
  if (item.path === '/overview') return pathname === '/overview';
  return pathname === item.path || pathname.startsWith(item.path + '/');
}
