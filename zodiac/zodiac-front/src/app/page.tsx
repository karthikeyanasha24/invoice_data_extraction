'use client';

import { useEffect, useState } from 'react';
import { useRouter, useSearchParams } from 'next/navigation';
import { useAuth } from '@/contexts/AuthContext';
import AuthForm from '@/components/AuthForm';
import LoadingSpinner from '@/components/LoadingSpinner';

export default function Home() {
  const { isAuthenticated, loading, clearAuthData } = useAuth();
  const router = useRouter();
  const searchParams = useSearchParams();
  const [isLogin, setIsLogin] = useState(true); // Default to sign in

  // Check URL parameters for auth mode
  useEffect(() => {
    const mode = searchParams.get('mode');
    if (mode === 'signup') {
      setIsLogin(false);
    } else if (mode === 'signin') {
      setIsLogin(true);
    }
  }, [searchParams]);

  // Clear auth data when showing login/signup pages to prevent stale data
  useEffect(() => {
    if (!isAuthenticated && !loading) {
      console.log('🔐 Home - Clearing auth data before showing login/signup');
      clearAuthData();
    }
  }, [isAuthenticated, loading, clearAuthData]);

  useEffect(() => {
    if (isAuthenticated && !loading) {
      router.push('/dashboard');
    }
  }, [isAuthenticated, loading, router]);

  const handleToggleMode = () => {
    setIsLogin(!isLogin);
    // Update URL without page reload
    const newMode = !isLogin ? 'signin' : 'signup';
    router.replace(`/?mode=${newMode}`, { scroll: false });
  };

  if (loading) {
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
