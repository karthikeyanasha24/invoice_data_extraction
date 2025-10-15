// Authentication error handler utility
export const handleAuthError = () => {
  console.log('🔐 Auth Error Handler - Session expired, redirecting to login');
  
  // Clear any stored authentication data
  if (typeof window !== 'undefined') {
    localStorage.removeItem('access_token');
    
    // Redirect to login page
    window.location.href = '/';
  }
};

// Check if an error is an authentication error
export const isAuthError = (error: any): boolean => {
  if (!error) return false;
  
  // Check error message
  const message = error.message || error.error || '';
  if (typeof message === 'string') {
    return message.includes('Session expired') || 
           message.includes('log in again') || 
           message.includes('Unauthorized') ||
           message.includes('Invalid token');
  }
  
  // Check status code
  if (error.response?.status === 401) {
    return true;
  }
  
  return false;
};

// Safe API call wrapper that handles auth errors
export const safeApiCall = async <T>(
  apiCall: () => Promise<T>,
  onAuthError?: () => void
): Promise<T | null> => {
  try {
    return await apiCall();
  } catch (error: any) {
    if (isAuthError(error)) {
      console.log('🔐 Safe API Call - Authentication error detected');
      if (onAuthError) {
        onAuthError();
      } else {
        handleAuthError();
      }
      return null;
    }
    throw error;
  }
};

