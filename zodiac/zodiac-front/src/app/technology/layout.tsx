import type { Metadata } from 'next';
import { documentTitleForPath } from '@/lib/pageTitles';

export const metadata: Metadata = { title: documentTitleForPath('/technology') };

export default function TechnologyLayout({ children }: { children: React.ReactNode }) {
  return children;
}
