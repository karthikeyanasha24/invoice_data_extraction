// Debug utility for frontend logging
export const debugLog = (category: string, message: string, data?: any) => {
  const isDebugMode = process.env.NODE_ENV === 'development' || localStorage.getItem('debug') === 'true';
  
  if (isDebugMode) {
    console.log(`[${category}] ${message}`, data || '');
  }
};

export const debugError = (category: string, message: string, error?: any) => {
  const isDebugMode = process.env.NODE_ENV === 'development' || localStorage.getItem('debug') === 'true';
  
  if (isDebugMode) {
    console.error(`[${category}] ${message}`, error || '');
  }
};

export const debugWarn = (category: string, message: string, data?: any) => {
  const isDebugMode = process.env.NODE_ENV === 'development' || localStorage.getItem('debug') === 'true';
  
  if (isDebugMode) {
    console.warn(`[${category}] ${message}`, data || '');
  }
};

// Enable debug mode in production by running: localStorage.setItem('debug', 'true')
// Disable debug mode by running: localStorage.removeItem('debug')

