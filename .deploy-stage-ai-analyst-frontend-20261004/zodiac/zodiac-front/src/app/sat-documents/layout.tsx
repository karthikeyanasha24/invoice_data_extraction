import type { Metadata } from 'next';
import { documentTitleForPath } from '@/lib/pageTitles';

export const metadata: Metadata = { title: documentTitleForPath('/sat-documents') };

export default function SATDocumentsLayout({ children }: { children: React.ReactNode }) {
  return children;
}
