const TITLES: { prefix: string; title: string }[] = [
  { prefix: '/dashboard/ai', title: 'AI Analyst · BridgeEDI' },
  { prefix: '/overview', title: 'Overview · BridgeEDI' },
  { prefix: '/dashboard', title: 'EDI operations · BridgeEDI' },
  { prefix: '/sat-documents', title: 'SAT documents · BridgeEDI' },
  { prefix: '/invoices-v2', title: 'Invoices · BridgeEDI' },
  { prefix: '/settings', title: 'Settings · BridgeEDI' },
  { prefix: '/customers', title: 'Customers · BridgeEDI' },
  { prefix: '/admin/account-mapping', title: 'RFC to G/L mapping · BridgeEDI' },
  { prefix: '/admin/supplier-tokens', title: 'Supplier API access · BridgeEDI' },
  { prefix: '/customer-users', title: 'Customer users · BridgeEDI' },
  { prefix: '/workspace', title: 'Workspaces · BridgeEDI' },
];

export function documentTitleForPath(pathname: string): string {
  const path = pathname || '/';
  for (const row of TITLES) {
    if (path === row.prefix || path.startsWith(row.prefix + '/')) return row.title;
  }
  return 'BridgeEDI';
}
