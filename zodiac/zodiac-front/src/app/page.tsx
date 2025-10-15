'use client';

import { useEffect, useState, Suspense } from 'react';
import { useRouter, useSearchParams } from 'next/navigation';
import { useAuth } from '@/contexts/AuthContext';
import AuthForm from '@/components/AuthForm';
import LoadingSpinner from '@/components/LoadingSpinner';

function HomeContent() {
  const { isAuthenticated, loading, clearAuthData } = useAuth();
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

  // Clear auth data when showing login/signup pages to prevent stale data
  useEffect(() => {
    if (!isClient) return;
    
    if (!isAuthenticated && !loading) {
      console.log('🔐 Home - Clearing auth data before showing login/signup');
      clearAuthData();
    }
  }, [isAuthenticated, loading, clearAuthData, isClient]);

  useEffect(() => {
    if (!isClient) return;
    
    if (isAuthenticated && !loading) {
      router.push('/dashboard');
    }
  }, [isAuthenticated, loading, router, isClient]);

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
