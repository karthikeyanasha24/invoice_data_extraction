'use client';

import { useState } from 'react';
import { useAuth } from '@/contexts/AuthContext';
import { cn } from '@/lib/utils';
import { Eye, EyeOff, Mail, User, Lock } from 'lucide-react';
import Footer from './Footer';

interface AuthFormProps {
  isLogin: boolean;
  onToggleMode: () => void;
}

export default function AuthForm({ isLogin, onToggleMode }: AuthFormProps) {
  const [email, setEmail] = useState('');
  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const [showPassword, setShowPassword] = useState(false);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');

  const { login, signup } = useAuth();

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setLoading(true);
    // Don't clear error immediately - let it persist until user interacts with inputs

    try {
      let success = false;
      
      if (isLogin) {
        success = await login(email, password);
      } else {
        success = await signup(email, username, password);
      }

      if (!success) {
        setError(isLogin ? 'Login failed. Please check your credentials and try again.' : 'Signup failed. Please check your information and try again.');
      }
    } catch (err: any) {
      // Use the specific error message from the API
      setError(err.message || 'An unexpected error occurred. Please try again.');
    } finally {
      setLoading(false);
    }
  };

  const handleInputFocus = () => {
    // Clear error when user focuses on any input field
    if (error) {
      setError('');
    }
  };

  const handleInputChange = (setter: (value: string) => void) => (e: React.ChangeEvent<HTMLInputElement>) => {
    // Clear error when user starts typing
    if (error) {
      setError('');
    }
    setter(e.target.value);
  };

  return (
    <div className="min-h-screen flex flex-col bg-gradient-to-br from-slate-50 to-slate-100">
      <div className="flex-1 flex items-center justify-center py-4 px-4 sm:px-6 lg:px-8">
        <div className="w-full max-w-md space-y-6">
          {/* Logo and Branding */}
          <div className="text-center">
            <div className="mx-auto w-16 h-16 bg-gradient-to-br from-blue-600 to-indigo-700 rounded-full flex items-center justify-center shadow-lg">
              <span className="text-white font-bold text-xl">Z</span>
            </div>
            <h1 className="mt-4 text-2xl sm:text-3xl font-bold text-slate-900">Welcome to Zodiac</h1>
            <p className="mt-2 text-sm text-slate-600 max-w-sm mx-auto px-4">
              Zodiac is an AI-powered document management system.
            </p>
            <p className="mt-3 text-xs text-slate-500">
              Customer organization?{' '}
              <a href="/customer/login" className="font-medium text-emerald-700 hover:underline">
                Customer Portal sign-in
              </a>
            </p>
          </div>

          {/* Auth Form */}
          <div className="bg-white rounded-xl shadow-xl p-6 sm:p-8 border border-slate-200">
            <div className="mb-6">
              <h2 className="text-xl sm:text-2xl font-semibold text-slate-900 text-center">
                {isLogin ? 'Sign in to your account' : 'Create your account'}
              </h2>
              <p className="mt-2 text-center text-sm text-slate-600">
                {isLogin ? "Don't have an account? " : 'Already have an account? '}
                <button
                  onClick={onToggleMode}
                  className="font-medium text-blue-600 hover:text-blue-500 transition-colors"
                >
                  {isLogin ? 'Sign up' : 'Sign in'}
                </button>
              </p>
            </div>
            
            <form className="space-y-4 sm:space-y-6" onSubmit={handleSubmit}>
              <div className="space-y-4">
                <div>
                  <label htmlFor="email" className="block text-sm font-medium text-slate-700 mb-2">
                    Email address
                  </label>
                  <div className="relative">
                    <Mail className="absolute left-3 top-1/2 transform -translate-y-1/2 h-5 w-5 text-slate-400" />
                    <input
                      id="email"
                      name="email"
                      type="email"
                      autoComplete="email"
                      required
                      value={email}
                      onChange={handleInputChange(setEmail)}
                      onFocus={handleInputFocus}
                      className="pl-10 appearance-none rounded-lg relative block w-full px-3 py-2.5 sm:py-3 border border-slate-300 placeholder-slate-400 text-slate-900 focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-blue-500 focus:z-10 text-sm transition-colors"
                      placeholder="Enter your email"
                    />
                  </div>
                </div>

                {!isLogin && (
                  <div>
                    <label htmlFor="username" className="block text-sm font-medium text-slate-700 mb-2">
                      Username
                    </label>
                    <div className="relative">
                      <User className="absolute left-3 top-1/2 transform -translate-y-1/2 h-5 w-5 text-slate-400" />
                      <input
                        id="username"
                        name="username"
                        type="text"
                        autoComplete="username"
                        required
                        value={username}
                        onChange={handleInputChange(setUsername)}
                        onFocus={handleInputFocus}
                        className="pl-10 appearance-none rounded-lg relative block w-full px-3 py-2.5 sm:py-3 border border-slate-300 placeholder-slate-400 text-slate-900 focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-blue-500 focus:z-10 text-sm transition-colors"
                        placeholder="Enter your username"
                      />
                    </div>
                  </div>
                )}

                <div>
                  <label htmlFor="password" className="block text-sm font-medium text-slate-700 mb-2">
                    Password
                  </label>
                  <div className="relative">
                    <Lock className="absolute left-3 top-1/2 transform -translate-y-1/2 h-5 w-5 text-slate-400" />
                    <input
                      id="password"
                      name="password"
                      type={showPassword ? 'text' : 'password'}
                      autoComplete={isLogin ? 'current-password' : 'new-password'}
                      required
                      value={password}
                      onChange={handleInputChange(setPassword)}
                      onFocus={handleInputFocus}
                      className="pl-10 pr-10 appearance-none rounded-lg relative block w-full px-3 py-2.5 sm:py-3 border border-slate-300 placeholder-slate-400 text-slate-900 focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-blue-500 focus:z-10 text-sm transition-colors"
                      placeholder="Enter your password"
                    />
                    <button
                      type="button"
                      onClick={() => setShowPassword(!showPassword)}
                      className="absolute right-3 top-1/2 transform -translate-y-1/2 text-slate-400 hover:text-slate-600 transition-colors"
                    >
                      {showPassword ? <EyeOff className="h-5 w-5" /> : <Eye className="h-5 w-5" />}
                    </button>
                  </div>
                </div>
              </div>

              {error && (
                <div className="rounded-lg bg-red-50 border border-red-200 p-4 animate-in slide-in-from-top-2 duration-200">
                  <div className="flex">
                    <div className="flex-shrink-0">
                      <svg className="h-5 w-5 text-red-400" viewBox="0 0 20 20" fill="currentColor">
                        <path fillRule="evenodd" d="M10 18a8 8 0 100-16 8 8 0 000 16zM8.707 7.293a1 1 0 00-1.414 1.414L8.586 10l-1.293 1.293a1 1 0 101.414 1.414L10 11.414l1.293 1.293a1 1 0 001.414-1.414L11.414 10l1.293-1.293a1 1 0 00-1.414-1.414L10 8.586 8.707 7.293z" clipRule="evenodd" />
                      </svg>
                    </div>
                    <div className="ml-3">
                      <h3 className="text-sm font-medium text-red-800">
                        {isLogin ? 'Login Failed' : 'Signup Failed'}
                      </h3>
                      <div className="mt-2 text-sm text-red-700">
                        <p>{error}</p>
                      </div>
                    </div>
                  </div>
                </div>
              )}

              <div>
                <button
                  type="submit"
                  disabled={loading}
                  className={cn(
                    "group relative w-full flex justify-center py-2.5 sm:py-3 px-4 border border-transparent text-sm font-medium rounded-lg text-white bg-gradient-to-r from-blue-600 to-indigo-600 hover:from-blue-700 hover:to-indigo-700 focus:outline-none focus:ring-2 focus:ring-offset-2 focus:ring-blue-500 transition-all duration-200 shadow-lg",
                    loading && "opacity-50 cursor-not-allowed"
                  )}
                >
                  {loading ? (
                    <div className="flex items-center">
                      <div className="animate-spin rounded-full h-4 w-4 border-2 border-white border-t-transparent mr-2"></div>
                      Processing...
                    </div>
                  ) : (
                    isLogin ? 'Sign in' : 'Sign up'
                  )}
                </button>
              </div>
            </form>
          </div>
        </div>
      </div>
      
      {/* Footer */}
      <Footer />
    </div>
  );
}
