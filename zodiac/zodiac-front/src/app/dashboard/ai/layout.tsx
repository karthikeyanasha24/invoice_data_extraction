import type { Metadata } from 'next';
import { documentTitleForPath } from '@/lib/pageTitles';

export const metadata: Metadata = { title: documentTitleForPath('/dashboard/ai') };

export default function AIAnalystLayout({ children }: { children: React.ReactNode }) {
  return children;
}
