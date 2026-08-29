import type { Metadata } from 'next';
import { documentTitleForPath } from '@/lib/pageTitles';

export const metadata: Metadata = { title: documentTitleForPath('/settings') };

export default function SettingsLayout({ children }: { children: React.ReactNode }) {
  return children;
}
