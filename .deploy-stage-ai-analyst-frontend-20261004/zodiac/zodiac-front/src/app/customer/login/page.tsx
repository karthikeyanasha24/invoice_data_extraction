'use client';

import { FormEvent, useEffect, useState } from 'react';
import Link from 'next/link';
import { useRouter } from 'next/navigation';
import { Eye, EyeOff, Lock, Mail } from 'lucide-react';
import { useAuth } from '@/contexts/AuthContext';
import {
  CUSTOMER_HOME_PATH,
  CUSTOMER_LOGIN_PATH,
  isCustomerPortalUser,
} from '@/lib/customerPortal';
import LoadingSpinner from '@/components/LoadingSpinner';

export default function CustomerLoginPage() {
  const { user, isAuthenticated, loading, login, logout } = useAuth();
  const router = useRouter();
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [showPassword, setShowPassword] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');

  useEffect(() => {
    if (loading) return;
    if (isAuthenticated && user) {
      if (isCustomerPortalUser(user)) {
        router.replace(CUSTOMER_HOME_PATH);
      }
      // Admins staying logged in see the form with a note — they can use admin login.
    }
  }, [loading, isAuthenticated, user, router]);

  const handleSubmit = async (e: FormEvent) => {
    e.preventDefault();
    setBusy(true);
    setError('');
    try {
      await login(email.trim(), password);
      // Read fresh user from login response via AuthContext after setState —
      // fetchUser to verify role immediately.
      const { authApi } = await import('@/lib/api');
      const me = await authApi.fetchUser();
      if (!isCustomerPortalUser(me)) {
        logout();
        setError(
          'This login is for customer portal accounts only. Administrators should use the admin sign-in.'
        );
        return;
      }
      router.replace(CUSTOMER_HOME_PATH);
    } catch (err: any) {
      setError(err?.message || 'Login failed. Check your email and password.');
    } finally {
      setBusy(false);
    }
  };

  if (loading) {
    return (
      <div className="flex min-h-screen items-center justify-center bg-slate-50">
        <LoadingSpinner size="lg" text="Loading..." />
      </div>
    );
  }

  return (
    <div className="min-h-screen bg-gradient-to-br from-emerald-50 via-white to-slate-100">
      <div className="mx-auto flex min-h-screen max-w-md flex-col justify-center px-4 py-10">
        <div className="mb-8 text-center">
          <div className="mx-auto flex h-14 w-14 items-center justify-center rounded-2xl bg-emerald-600 text-lg font-bold text-white shadow">
            CP
          </div>
          <h1 className="mt-4 text-2xl font-semibold text-slate-900">Customer Portal</h1>
          <p className="mt-2 text-sm text-slate-600">
            Sign in to your exclusive workspace. You will only see your organization&apos;s data.
          </p>
        </div>

        <div className="rounded-2xl border border-slate-200 bg-white p-6 shadow-sm sm:p-8">
          <form className="space-y-4" onSubmit={handleSubmit}>
            <div>
              <label htmlFor="customer-email" className="mb-1.5 block text-sm font-medium text-slate-700">
                Email
              </label>
              <div className="relative">
                <Mail className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-slate-400" />
                <input
                  id="customer-email"
                  type="email"
                  autoComplete="email"
                  required
                  value={email}
                  onChange={(e) => {
                    setEmail(e.target.value);
                    setError('');
                  }}
                  className="w-full rounded-lg border border-slate-300 py-2.5 pl-10 pr-3 text-sm focus:border-emerald-500 focus:outline-none focus:ring-2 focus:ring-emerald-500/30"
                  placeholder="you@company.com"
                />
              </div>
            </div>
            <div>
              <label htmlFor="customer-password" className="mb-1.5 block text-sm font-medium text-slate-700">
                Password
              </label>
              <div className="relative">
                <Lock className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-slate-400" />
                <input
                  id="customer-password"
                  type={showPassword ? 'text' : 'password'}
                  autoComplete="current-password"
                  required
                  value={password}
                  onChange={(e) => {
                    setPassword(e.target.value);
                    setError('');
                  }}
                  className="w-full rounded-lg border border-slate-300 py-2.5 pl-10 pr-10 text-sm focus:border-emerald-500 focus:outline-none focus:ring-2 focus:ring-emerald-500/30"
                  placeholder="Your password"
                />
                <button
                  type="button"
                  className="absolute right-3 top-1/2 -translate-y-1/2 text-slate-400"
                  onClick={() => setShowPassword((v) => !v)}
                  aria-label={showPassword ? 'Hide password' : 'Show password'}
                >
                  {showPassword ? <EyeOff className="h-4 w-4" /> : <Eye className="h-4 w-4" />}
                </button>
              </div>
            </div>

            {error && (
              <div className="rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-700">
                {error}
              </div>
            )}

            <button
              type="submit"
              disabled={busy}
              className="w-full rounded-lg bg-emerald-600 py-2.5 text-sm font-semibold text-white hover:bg-emerald-700 disabled:opacity-60"
            >
              {busy ? 'Signing in…' : 'Sign in to portal'}
            </button>
          </form>

          <p className="mt-6 text-center text-xs text-slate-500">
            Administrator?{' '}
            <Link href="/" className="font-medium text-slate-700 underline hover:text-slate-900">
              Admin sign-in
            </Link>
            <span className="mx-1">·</span>
            <span className="font-mono text-slate-400">{CUSTOMER_LOGIN_PATH}</span>
          </p>
        </div>
      </div>
    </div>
  );
}
