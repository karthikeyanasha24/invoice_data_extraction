import type { Metadata } from 'next';
import { documentTitleForPath } from '@/lib/pageTitles';

export const metadata: Metadata = { title: documentTitleForPath('/overview') };

export default function OverviewLayout({ children }: { children: React.ReactNode }) {
  return children;
}
