import type { Metadata } from 'next';
import { documentTitleForPath } from '@/lib/pageTitles';

export const metadata: Metadata = { title: documentTitleForPath('/dashboard') };

export default function DashboardLayout({ children }: { children: React.ReactNode }) {
  return children;
}
