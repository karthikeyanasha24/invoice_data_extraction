'use client';

import React, { createContext, useContext, useState, useEffect, ReactNode } from 'react';
import { authApi } from '@/lib/api';
import { User } from '@/types';

interface AuthContextType {
  user: User | null;
  isAuthenticated: boolean;
  loading: boolean;
  login: (email: string, password: string) => Promise<boolean>;
  signup: (email: string, username: string, password: string) => Promise<boolean>;
  logout: () => void;
  handleAuthError: () => void;
  clearAuthData: () => void;
}

const AuthContext = createContext<AuthContextType | undefined>(undefined);

export const AuthProvider = ({ children }: { children: ReactNode }) => {
  const [user, setUser] = useState<User | null>(null);
  const [isAuthenticated, setIsAuthenticated] = useState(false);
  const [loading, setLoading] = useState(true);

  const clearAuthData = () => {
    console.log('🔐 AuthContext - Clearing all auth data');
    
    // Only access localStorage/sessionStorage on client side
    if (typeof window !== 'undefined') {
      // Clear all auth-related data from localStorage
      const authKeys = [
        'access_token',
        'refresh_token', 
        'user_data',
        'auth_state',
        'token_expiry',
        'last_login',
        'remember_me'
      ];
      
      authKeys.forEach(key => {
        localStorage.removeItem(key);
        sessionStorage.removeItem(key);
      });
      
      // Clear any cached API responses (if using a cache)
      if ('caches' in window) {
        caches.keys().then(cacheNames => {
          cacheNames.forEach(cacheName => {
            if (cacheName.includes('api') || cacheName.includes('auth')) {
              caches.delete(cacheName);
            }
          });
        });
      }
    }
    
    // Clear any axios interceptors or cached requests
    // This is handled by the API interceptor automatically
    
    // Reset state
    setUser(null);
    setIsAuthenticated(false);
    
    console.log('🔐 AuthContext - All auth data cleared');
  };

  useEffect(() => {
    const checkAuth = async () => {
      // Only run on client side
      if (typeof window === 'undefined') {
        setLoading(false);
        return;
      }
      
      console.log('🔐 AuthContext - Checking authentication...');
      
      const token = localStorage.getItem('access_token');
      console.log('🔐 AuthContext - Token found:', !!token);

      if (token) {
        try {
          const cached = localStorage.getItem('user_data');
          if (cached) {
            const parsed = JSON.parse(cached);
            if (parsed?.email || parsed?.username) {
              setUser(parsed);
              setIsAuthenticated(true);
              setLoading(false);
            }
          }
        } catch {
          /* ignore corrupt cache */
        }
        try {
          console.log('🔐 AuthContext - Fetching user data...');
          const userData = await authApi.fetchUser();
          console.log('🔐 AuthContext - User data received:', { username: userData.username, email: userData.email });
          setUser(userData);
          setIsAuthenticated(true);
          try {
            localStorage.setItem('user_data', JSON.stringify(userData));
          } catch {
            /* ignore quota */
          }
        } catch (error: any) {
          // Only clear session on explicit 401 (token actually invalid/expired).
          // Network errors or server restarts should NOT log the user out — the
          // token is still valid and will work once the server is back up.
          const is401 =
            error?.response?.status === 401 ||
            (error?.message || '').toLowerCase().includes('session expired');
          const isNetworkError = !error?.response && (error?.message || '').toLowerCase().includes('network');

          if (is401) {
            console.error('🔐 AuthContext - Token invalid/expired, clearing session:', error?.message);
            clearAuthData();
          } else if (isNetworkError) {
            // Server temporarily unreachable — preserve token so session restores on reconnect
            console.warn('🔐 AuthContext - Network error during auth check; keeping token for reconnect:', error?.message);
            setUser(null);
            setIsAuthenticated(false);
            // Do NOT call clearAuthData() — keep the token in localStorage
          } else {
            // Other server error (5xx etc.) — keep token, don't log out
            console.warn('🔐 AuthContext - Server error during auth check; preserving session:', error?.message);
            setUser(null);
            setIsAuthenticated(false);
          }
        }
      } else {
        console.log('🔐 AuthContext - No token found, user not authenticated');
        setUser(null);
        setIsAuthenticated(false);
      }
      
      setLoading(false);
    };

    checkAuth();
  }, []);

  const login = async (email: string, password: string): Promise<boolean> => {
    console.log('🔐 AuthContext - Login attempt:', { email });
    try {
      // Clear any existing auth data before login
      clearAuthData();
      
      const response = await authApi.login({ email, password });
      console.log('🔐 AuthContext - Login successful, storing token');
      
      // Only access localStorage on client side
      if (typeof window !== 'undefined') {
        localStorage.setItem('access_token', response.access_token);
        if (response.user) {
          localStorage.setItem('user_data', JSON.stringify(response.user));
        }
      }
      
      setUser(response.user);
      setIsAuthenticated(true);
      return true;
    } catch (error: any) {
      console.error('🔐 AuthContext - Login failed:', {
        message: error.message,
        status: error.response?.status,
        data: error.response?.data
      });
      // Ensure auth data is cleared on failed login
      clearAuthData();
      // Re-throw the error so the component can handle it
      throw error;
    }
  };

  const signup = async (email: string, username: string, password: string): Promise<boolean> => {
    console.log('🔐 AuthContext - Signup attempt:', { email, username });
    try {
      // Clear any existing auth data before signup
      clearAuthData();
      
      const response = await authApi.signup({ email, username, password });
      console.log('🔐 AuthContext - Signup successful, storing token');
      
      // Only access localStorage on client side
      if (typeof window !== 'undefined') {
        localStorage.setItem('access_token', response.access_token);
        if (response.user) {
          localStorage.setItem('user_data', JSON.stringify(response.user));
        }
      }
      
      setUser(response.user);
      setIsAuthenticated(true);
      return true;
    } catch (error: any) {
      console.error('🔐 AuthContext - Signup failed:', error.message);
      // Ensure auth data is cleared on failed signup
      clearAuthData();
      // Re-throw the error so the component can handle it
      throw error;
    }
  };

  const logout = () => {
    console.log('🔐 AuthContext - Logout initiated');
    clearAuthData();
    console.log('🔐 AuthContext - Logout completed');
  };

  const handleAuthError = () => {
    console.log('🔐 AuthContext - Authentication error detected, logging out');
    clearAuthData();
    // Redirect to login page
    if (typeof window !== 'undefined') {
      window.location.href = '/';
    }
  };

  const value = {
    user,
    isAuthenticated,
    loading,
    login,
    signup,
    logout,
    handleAuthError,
    clearAuthData,
  };

  return (
    <AuthContext.Provider value={value}>
      {children}
    </AuthContext.Provider>
  );
};

export const useAuth = () => {
  const context = useContext(AuthContext);
  if (context === undefined) {
    throw new Error('useAuth must be used within an AuthProvider');
  }
  return context;
};
