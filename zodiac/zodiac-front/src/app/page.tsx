'use client';

import { useEffect, useState, Suspense } from 'react';
import { useRouter, useSearchParams } from 'next/navigation';
import { useAuth } from '@/contexts/AuthContext';
import AuthForm from '@/components/AuthForm';
import LoadingSpinner from '@/components/LoadingSpinner';

function HomeContent() {
  const { user, isAuthenticated, loading, clearAuthData } = useAuth();
  const router = useRouter();
  const searchParams = useSearchParams();
  const [isLogin, setIsLogin] = useState(true);
  const [isClient, setIsClient] = useState(false);

  // Ensure we're on the client side before rendering
  useEffect(() => {
    setIsClient(true);
  }, []);

  // Check URL parameters for auth mode
  useEffect(() => {
    if (!isClient) return;
    
    const mode = searchParams.get('mode');
    if (mode === 'signup') {
      setIsLogin(false);
    } else if (mode === 'signin') {
      setIsLogin(true);
    }
  }, [searchParams, isClient]);

  // Only clear auth data if there is no stored token at all (true fresh session).
  // Do NOT wipe the token when the server is temporarily unreachable — the token
  // is still valid and should restore the session once the server is back.
  useEffect(() => {
    if (!isClient) return;
    if (!isAuthenticated && !loading) {
      const hasToken = typeof window !== 'undefined' && !!localStorage.getItem('access_token');
      if (!hasToken) {
        console.log('🔐 Home - No token present, showing login/signup');
        clearAuthData(); // safe: nothing to wipe, just resets state
      } else {
        console.log('🔐 Home - Token present but auth check failed (server may be restarting); preserving session');
      }
    }
  }, [isAuthenticated, loading, clearAuthData, isClient]);

  useEffect(() => {
    if (!isClient) return;
    
    if (isAuthenticated && !loading && user) {
      if (user.is_customer_user && !user.is_admin) {
        // Phase 11 — dedicated customer portal (not admin shell)
        router.push('/customer/overview');
      } else {
        router.push('/dashboard');
      }
    }
  }, [isAuthenticated, loading, router, isClient, user]);

  const handleToggleMode = () => {
    setIsLogin(!isLogin);
    // Update URL without page reload
    const newMode = !isLogin ? 'signin' : 'signup';
    router.replace(`/?mode=${newMode}`, { scroll: false });
  };

  // Show loading during SSR and initial client hydration
  if (!isClient || loading) {
    return (
      <div className="min-h-screen flex items-center justify-center bg-gray-50">
        <LoadingSpinner size="lg" text="Loading..." />
      </div>
    );
  }

  if (!isAuthenticated) {
    return (
      <div className="min-h-screen bg-gray-50">
        <AuthForm isLogin={isLogin} onToggleMode={handleToggleMode} />
      </div>
    );
  }

  // This will be replaced by the redirect, but keeping as fallback
  return (
    <div className="min-h-screen flex items-center justify-center bg-gray-50">
      <LoadingSpinner size="lg" text="Redirecting..." />
    </div>
  );
}

export default function Home() {
  return (
    <Suspense fallback={
      <div className="min-h-screen flex items-center justify-center bg-gray-50">
        <LoadingSpinner size="lg" text="Loading..." />
      </div>
    }>
      <HomeContent />
    </Suspense>
  );
}
