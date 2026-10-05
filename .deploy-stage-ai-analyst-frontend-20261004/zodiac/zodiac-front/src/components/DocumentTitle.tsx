'use client';

import { useEffect } from 'react';
import { usePathname } from 'next/navigation';
import { documentTitleForPath } from '@/lib/pageTitles';

/** Keep the browser title aligned after client navigation and Next metadata races. */
export default function DocumentTitle() {
  const pathname = usePathname();
  const title = documentTitleForPath(pathname || '/');

  useEffect(() => {
    document.title = title;
    const t0 = window.setTimeout(() => {
      document.title = title;
    }, 0);
    const t1 = window.setTimeout(() => {
      document.title = title;
    }, 300);
    return () => {
      window.clearTimeout(t0);
      window.clearTimeout(t1);
    };
  }, [title, pathname]);

  return null;
}
