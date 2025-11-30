import axios from 'axios';
import { AuthResponse, LoginRequest, SignupRequest, User, FileUploadResponse, Invoice } from '@/types';

const API_BASE_URL = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000';

export const api = axios.create({
  baseURL: API_BASE_URL,
  headers: {
    'Content-Type': 'application/json',
  },
});

// Add request interceptor to include auth token and log requests
api.interceptors.request.use(
  (config) => {
    if (typeof window !== 'undefined') {
      const token = localStorage.getItem('access_token');
      if (token) {
        config.headers.Authorization = `Bearer ${token}`;
      }
    }
    
    // Log request details
    console.group(`🚀 API Request: ${config.method?.toUpperCase()} ${config.url}`);
    console.log('Headers:', config.headers);
    console.log('Data:', config.data);
    console.log('Params:', config.params);
    console.log('Base URL:', config.baseURL);
    console.log('Full URL:', `${config.baseURL}${config.url}`);
    console.groupEnd();
    
    return config;
  },
  (error) => {
    console.error('❌ Request interceptor error:', error);
    return Promise.reject(error);
  }
);

// Add response interceptor for better error handling and logging
api.interceptors.response.use(
  (response) => {
    // Log successful responses
    console.group(`✅ API Response: ${response.config.method?.toUpperCase()} ${response.config.url}`);
    console.log('Status:', response.status);
    console.log('Headers:', response.headers);
    console.log('Data:', response.data);
    console.groupEnd();
    
    return response;
  },
  (error) => {
    // Log error responses
    console.group(`❌ API Error: ${error.config?.method?.toUpperCase()} ${error.config?.url}`);
    console.log('Status:', error.response?.status);
    console.log('Status Text:', error.response?.statusText);
    console.log('Headers:', error.response?.headers);
    console.log('Error Data:', error.response?.data);
    console.log('Error Message:', error.message);
    console.log('Error Code:', error.code);
    console.log('Error Config:', error.config);
    console.log('Error Request:', error.request);
    console.log('Full Error Object:', error);
    console.log('Full Error:', error);
    console.groupEnd();
    
    if (error.response?.status === 401) {
      // Clear invalid token and all auth data
      if (typeof window !== 'undefined') {
        // Clear all auth-related data
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
        
        console.log('🔐 API - 401 detected, clearing all auth data and redirecting to login');
        // Redirect to login page
        window.location.href = '/';
      }
    }
    return Promise.reject(error);
  }
);

// Auth API
export const authApi = {
  login: async (data: LoginRequest): Promise<AuthResponse> => {
    console.log('🔐 Auth API - Login attempt:', { email: data.email, passwordLength: data.password.length });
    try {
      const response = await api.post('/api/v1/user/auth/login', data);
      console.log('🔐 Auth API - Login success:', { user: response.data.user?.username, tokenLength: response.data.access_token?.length });
      return response.data;
    } catch (error: any) {
      console.error('🔐 Auth API - Login failed:', {
        status: error.response?.status,
        data: error.response?.data,
        message: error.message,
        fullError: error
      });
      
      if (error.response?.status === 401) {
        throw new Error('Invalid email or password. Please check your credentials and try again.');
      } else if (error.response?.status === 422) {
        throw new Error('Please check your email format and try again.');
      } else if (error.response?.status >= 500) {
        throw new Error('Server error. Please try again later.');
      } else if (!error.response) {
        throw new Error('Network error. Please check your connection and try again.');
      } else {
        // Extract specific error message from response if available
        const errorMessage = error.response?.data?.detail || 
                           error.response?.data?.message || 
                           error.message || 
                           'Login failed. Please try again.';
        throw new Error(errorMessage);
      }
    }
  },

  signup: async (data: SignupRequest): Promise<AuthResponse> => {
    console.log('🔐 Auth API - Signup attempt:', { email: data.email, username: data.username, passwordLength: data.password.length });
    try {
      const response = await api.post('/api/v1/user/auth/create-user', data);
      console.log('🔐 Auth API - Signup success:', { user: response.data.user?.username, tokenLength: response.data.access_token?.length });
      return response.data;
    } catch (error: any) {
      console.error('🔐 Auth API - Signup failed:', error.response?.data || error.message);
      if (error.response?.status === 400) {
        throw new Error('User already exists or invalid data. Please try with different credentials.');
      } else if (error.response?.status === 422) {
        throw new Error('Please check your email format and password requirements.');
      } else if (error.response?.status >= 500) {
        throw new Error('Server error. Please try again later.');
      } else if (!error.response) {
        throw new Error('Network error. Please check your connection and try again.');
      } else {
        throw new Error('Signup failed. Please try again.');
      }
    }
  },

  fetchUser: async (): Promise<User> => {
    console.log('🔐 Auth API - Fetch user attempt');
    try {
      const response = await api.get('/api/v1/user/auth/fetch_user');
      console.log('🔐 Auth API - Fetch user success:', { user: response.data?.username, email: response.data?.email });
      return response.data;
    } catch (error: any) {
      console.error('🔐 Auth API - Fetch user failed:', error.response?.data || error.message);
      if (error.response?.status === 401) {
        throw new Error('Session expired. Please log in again.');
      } else if (!error.response) {
        throw new Error('Network error. Please check your connection.');
      } else {
        throw new Error('Failed to fetch user data.');
      }
    }
  },
};

// File upload API
export const fileApi = {
  uploadFile: async (file: File): Promise<{ 
    success: boolean; 
    data?: FileUploadResponse; 
    error?: string; 
    isProcessingError?: boolean;
    errorDetails?: any[];
    errorSummary?: any;
    suggestedActions?: string[];
    fileContentPreview?: string;
    warnings?: string[];
  }> => {
    console.log('📁 File API - Upload attempt:', { 
      fileName: file.name, 
      fileSize: file.size, 
      fileType: file.type,
      lastModified: new Date(file.lastModified).toISOString(),
      apiBaseUrl: API_BASE_URL,
      hasToken: typeof window !== 'undefined' ? !!localStorage.getItem('access_token') : 'N/A'
    });
    
    try {
      const formData = new FormData();
      formData.append('file', file);
      
      console.log('📁 File API - Making request to:', `${API_BASE_URL}/api/v1/invoices/process`);
      console.log('📁 File API - FormData contents:', {
        fileName: file.name,
        fileSize: file.size,
        fileType: file.type,
        hasFile: formData.has('file')
      });
      
      // Check if we have authentication token
      const token = typeof window !== 'undefined' ? localStorage.getItem('access_token') : null;
      console.log('📁 File API - Auth token present:', !!token);
      
      let response;
      try {
        console.log('📁 File API - About to make axios request...');
        response = await api.post('/api/v1/invoices/process', formData, {
          headers: {
            'Content-Type': 'multipart/form-data',
          },
        });
        console.log('📁 File API - Axios request completed successfully');
      } catch (axiosError: any) {
        console.error('📁 File API - Axios request failed:', axiosError);
        console.error('📁 File API - Axios error type:', typeof axiosError);
        console.error('📁 File API - Axios error constructor:', axiosError?.constructor?.name);
        
        // Handle 400 Bad Request - should only be for actual upload failures now
        if (axiosError.response?.status === 400) {
          console.log('📁 File API - Handling 400 Bad Request (should be upload failure only)');
          const errorData = axiosError.response.data;
          
          // 400 should only occur for actual upload failures (file_upload_pass: false)
          console.log('📁 File API - File upload failed');
          let errorMessage = 'File upload failed.';
          if (errorData.file_upload_message) {
            errorMessage = `File upload failed: ${errorData.file_upload_message}`;
          }
          
          // Include enhanced error information if available
          const enhancedError = {
            success: false,
            error: errorMessage,
            data: errorData,
            errorDetails: errorData.processing_steps || [],
            errorSummary: errorData.error_summary || null,
            suggestedActions: errorData.suggested_actions || []
          };
          
          console.log('📁 File API - Enhanced error response:', enhancedError);
          return enhancedError;
        }
        
        // For other errors, re-throw them
        throw axiosError;
      }
      
      console.log('📁 File API - Upload response:', { 
        responseData: response.data,
        responseStatus: response.status,
        responseDataType: typeof response.data
      });
      
      // Handle success case (201 Created or 202 Accepted for async processing)
      if (response.status === 201 || response.status === 202) {
        // Parse response data if it's a string (backend returns JSONResponse with json.dumps)
        let parsedData = response.data;
        if (typeof response.data === 'string') {
          try {
            parsedData = JSON.parse(response.data);
            console.log('📁 File API - Parsed response data:', parsedData);
          } catch (e) {
            console.error('📁 File API - Failed to parse response data:', e);
            parsedData = response.data;
          }
        }
        
        if (response.status === 202) {
          console.log('📁 File API - Invoice processing started (202 Accepted), tracking_id returned for real-time status');
          console.log('📁 File API - Parsed data:', parsedData);
          console.log('📁 File API - Tracking ID from response:', parsedData?.tracking_id);
        } else {
          console.log('📁 File API - Invoice processing completed successfully (201 Created)');
        }
        return { 
          success: true, 
          data: parsedData,
          status: response.status, // Include status code for frontend handling
          warnings: parsedData.warnings || []
        };
      } else if (response.status === 200) {
        // Handle 200 OK responses - could be processing failure or unexpected success
        console.log('📁 File API - Received 200 OK response:', response.data);
        const responseData = response.data;
        
        // Check if this is a processing failure (file upload succeeded but processing failed)
        if (responseData && responseData.file_upload_pass === true && responseData.invoice_operation_success === false) {
          console.log('📁 File API - Processing failure detected in 200 OK response');
          return { 
            success: false, 
            error: 'Processing failed', 
            data: responseData,
            isProcessingError: true, // Flag to indicate this is a processing error, not upload error
            errorDetails: responseData.processing_steps || [],
            errorSummary: responseData.error_summary || null,
            suggestedActions: responseData.suggested_actions || [],
            fileContentPreview: responseData.file_content_preview || null,
            warnings: responseData.warnings || []
          };
        } else {
          // Unexpected 200 response - treat as success
          console.log('📁 File API - Unexpected 200 OK response, treating as success');
          return { 
            success: true, 
            data: responseData,
            warnings: responseData.warnings || []
          };
        }
      } else {
        // Handle unexpected success status codes
        console.log('📁 File API - Unexpected success status code:', response.status);
        return { 
          success: true, 
          data: response.data,
          warnings: response.data.warnings || []
        };
      }
    } catch (error: any) {
      // First, let's log the raw error to understand what we're dealing with
      console.log('📁 File API - Raw error object:', error);
      console.log('📁 File API - Error constructor:', error?.constructor?.name);
      console.log('📁 File API - Error is Error instance:', error instanceof Error);
      
      // Try to extract meaningful information from the error
      let errorInfo: any = {};
      
      try {
        errorInfo = {
          error: error.response?.data || error.message || 'Unknown error',
          status: error.response?.status,
          fileName: file.name,
          fullError: error,
          responseHeaders: error.response?.headers,
          requestUrl: error.config?.url,
          requestMethod: error.config?.method,
          errorType: typeof error,
          errorKeys: Object.keys(error || {}),
          errorString: String(error),
          errorStack: error.stack,
          errorName: error.name,
          errorCode: error.code,
          errorCause: error.cause,
          isAxiosError: error.isAxiosError,
          axiosErrorCode: error.code,
          axiosErrorMessage: error.message,
          axiosResponse: error.response,
          axiosRequest: error.request
        };
      } catch (extractionError) {
        console.error('📁 File API - Error extracting error info:', extractionError);
        errorInfo = {
          rawError: error,
          extractionError: extractionError,
          fileName: file.name
        };
      }
      
      console.error('📁 File API - Upload failed:', errorInfo);
      
      let errorMessage = 'Upload failed. Please try again.';
      
      // Handle manually thrown errors (like unexpected status codes)
      if (error.message && error.message.includes('Unexpected response status')) {
        errorMessage = error.message;
      }
      // Handle specific zodiac-api error responses
      else if (error.response?.data?.detail) {
        const detail = error.response.data.detail;
        console.log('📁 File API - Processing error detail:', detail);
        
        if (typeof detail === 'object') {
          // Check for specific error messages in the detail object
          if (detail.file_upload_message) {
            errorMessage = `File upload failed: ${detail.file_upload_message}`;
          } else if (detail.xml_convert_message) {
            errorMessage = `XML validation failed: ${detail.xml_convert_message}`;
          } else if (detail.edi_convert_message) {
            errorMessage = `EDI conversion failed: ${detail.edi_convert_message}`;
          } else {
            // Try to extract any meaningful error message from the detail object
            const messages = Object.values(detail).filter(val => typeof val === 'string' && val.length > 0);
            if (messages.length > 0) {
              errorMessage = `Processing failed: ${messages[0]}`;
            }
          }
        } else if (typeof detail === 'string') {
          errorMessage = `Upload failed: ${detail}`;
        }
      } else if (error.response?.status === 400) {
        // This should not happen anymore since we handle 400 in the axios try-catch above
        console.log('📁 File API - Unexpected 400 error in catch block:', error.response.data);
        errorMessage = 'Invalid request. Please check your file and try again.';
      } else if (error.response?.status === 401) {
        errorMessage = 'Session expired. Please log in again to upload files.';
      } else if (error.response?.status === 403) {
        errorMessage = 'Access denied. You do not have permission to upload files.';
      } else if (error.response?.status === 404) {
        errorMessage = 'Upload endpoint not found. Please contact support.';
      } else if (error.response?.status === 413) {
        errorMessage = 'File too large. Please choose a smaller file.';
      } else if (error.response?.status === 415) {
        errorMessage = 'Unsupported file type. Please upload XML files only.';
      } else if (error.response?.status === 422) {
        errorMessage = 'Invalid file format. Please check your file and try again.';
      } else if (error.response?.status === 429) {
        errorMessage = 'Too many requests. Please wait a moment and try again.';
      } else if (error.response?.status >= 500) {
        errorMessage = 'Server error during upload. Please try again later.';
      } else if (!error.response) {
        errorMessage = 'Network error. Please check your connection and try again.';
      } else {
        // Handle any other status codes (including unexpected 201 responses)
        errorMessage = `Upload failed (${error.response.status}). Please try again.`;
      }
      
      return { success: false, error: errorMessage };
    }
  },

  getFiles: async (): Promise<Invoice[]> => {
    console.log('📁 File API - Get files attempt');
    try {
      console.log('📁 File API - Making API calls to success and failed endpoints...');
      
      // Get both successful and failed invoices
      const [successResponse, failedResponse] = await Promise.all([
        api.get('/api/v1/invoices/success'),
        api.get('/api/v1/invoices/failed')
      ]);
      
      console.log('📁 File API - API responses received:', {
        successStatus: successResponse.status,
        failedStatus: failedResponse.status,
        successData: successResponse.data,
        failedData: failedResponse.data
      });
      
      const successfulInvoices = successResponse.data || [];
      const failedInvoices = failedResponse.data || [];
      
      console.log('📁 File API - Raw API responses:', {
        successful: successfulInvoices,
        failed: failedInvoices
      });
      
      // Combine and format the invoices to match Invoice interface
      // Use blob URLs when available, fall back to local paths
      const allInvoices = [
        ...successfulInvoices.map((invoice: any) => {
          const xmlPath = invoice.blob_xml_path || invoice.xml_path;
          const ediPath = invoice.blob_edi_path || invoice.edi_path;
          
          console.log('📁 File API - Success invoice path resolution:', {
            id: invoice.id,
            blob_xml_path: invoice.blob_xml_path,
            xml_path: invoice.xml_path,
            final_xml_path: xmlPath,
            use_blob_storage: invoice.use_blob_storage
          });
          
          return {
            id: invoice.id,
            filename: xmlPath ? xmlPath.split('/').pop() : `${invoice.tracking_id}_invoice.xml`,
            status: 'successful',
            accepted: 1,
            rejected: 0,
            customerName:invoice.customer_name,
            invoice_id:invoice.invoice_id,
            formate: invoice.target_file_format?.toUpperCase() || 'X12',
            export: false,
            uploaded_at: invoice.uploaded_at,
            tracking_id: invoice.tracking_id,
            xml_validation_pass: invoice.xml_validation_pass,
            xml_convert_message: invoice.xml_convert_message,
            edi_convert_pass: invoice.edi_convert_pass,
            edi_convert_message: invoice.edi_convert_message,
            xml_path: xmlPath,
            edi_path: ediPath,
            blob_xml_path: invoice.blob_xml_path,
            blob_edi_path: invoice.blob_edi_path,
            use_blob_storage: invoice.use_blob_storage,
            external_status: invoice?.external_status,
            external_message: invoice?.external_message,
            target_file_format: invoice.target_file_format,
          };
        }),
        ...failedInvoices.map((invoice: any) => {
          const xmlPath = invoice.blob_xml_path || invoice.xml_path;
          const ediPath = invoice.blob_edi_path || invoice.edi_path;
          
          console.log('📁 File API - Failed invoice path resolution:', {
            id: invoice.id,
            blob_xml_path: invoice.blob_xml_path,
            xml_path: invoice.xml_path,
            final_xml_path: xmlPath,
            use_blob_storage: invoice.use_blob_storage
          });
          
          return {
            id: invoice.id,
            filename: xmlPath ? xmlPath.split('/').pop() : `${invoice.tracking_id}_invoice.xml`,
            status: 'failed',
            accepted: 0,
            rejected: 1,
            customerName: 'N/A',
            formate: invoice.target_file_format?.toUpperCase() || 'X12',
            export: false,
            uploaded_at: invoice.uploaded_at,
            tracking_id: invoice.tracking_id,
            xml_validation_pass: invoice.xml_validation_pass,
            xml_convert_message: invoice.xml_convert_message,
            edi_convert_pass: invoice.edi_convert_pass,
            edi_convert_message: invoice.edi_convert_message,
            xml_path: xmlPath,
            edi_path: ediPath,
            blob_xml_path: invoice.blob_xml_path,
            blob_edi_path: invoice.blob_edi_path,
            use_blob_storage: invoice.use_blob_storage,
            xml_content: invoice.xml_content,
            edi_content: invoice.edi_content,
            processing_steps_error: invoice.processing_steps_error
          };
        })
      ];
      
      console.log('📁 File API - Get files success:', { 
        successfulCount: successfulInvoices.length,
        failedCount: failedInvoices.length,
        totalCount: allInvoices.length
      });
      
      return allInvoices;
    } catch (error: any) {
      console.error('📁 File API - Get files failed:', {
        error: error,
        message: error.message,
        response: error.response?.data,
        status: error.response?.status,
        stack: error.stack,
        config: error.config,
        request: error.request,
        code: error.code,
        errno: error.errno,
        syscall: error.syscall,
        hostname: error.hostname
      });
      
      // Handle different types of errors
      if (error.response?.status === 401) {
        console.log('📁 File API - Authentication error, redirecting to login');
        throw new Error('Session expired. Please log in again.');
      } else if (error.response?.status === 403) {
        console.log('📁 File API - Forbidden error, user may not be authenticated');
        throw new Error('Access denied. Please log in again.');
      } else if (!error.response) {
        console.log('📁 File API - Network error, backend may be down');
        throw new Error('Network error. Please check your connection and ensure the backend server is running.');
      } else if (error.response?.status >= 500) {
        console.log('📁 File API - Server error');
        throw new Error('Server error. Please try again later.');
      } else {
        console.log('📁 File API - Unknown error');
        throw new Error('Failed to load files. Please try again.');
      }
    }
  },

  getFileById: async (id: number): Promise<Invoice> => {
    console.log('📁 File API - Get file by ID attempt:', { fileId: id });
    try {
      // Get all files first, then find the specific one
      const allFiles = await fileApi.getFiles();
      const file = allFiles.find((f: Invoice) => f.id === id);
      
      if (!file) {
        console.error('📁 File API - File not found:', { fileId: id, availableFiles: allFiles.map((f: Invoice) => f.id) });
        throw new Error('File not found');
      }
      
      console.log('📁 File API - Get file by ID success:', { fileId: id, file });
      return file;
    } catch (error: any) {
      console.error('📁 File API - Get file by ID failed:', error.response?.data || error.message);
      if (error.response?.status === 401) {
        throw new Error('Session expired. Please log in again.');
      } else if (!error.response) {
        throw new Error('Network error. Please check your connection.');
      } else {
        throw new Error('Failed to load file details.');
      }
    }
  },

  deleteFile: async (id: number): Promise<{ success: boolean; error?: string }> => {
    console.log('📁 File API - Delete file attempt:', { fileId: id });
    try {
      const response = await api.delete(`/api/v1/invoices/${id}`);
      
      console.log('📁 File API - Delete file success:', { 
        fileId: id,
        responseStatus: response.status
      });
      
      return { success: true };
    } catch (error: any) {
      console.error('📁 File API - Delete file failed:', {
        error: error.response?.data || error.message,
        status: error.response?.status,
        fileId: id
      });
      
      let errorMessage = 'Delete failed. Please try again.';
      
      if (error.response?.status === 401) {
        errorMessage = 'Session expired. Please log in again.';
      } else if (error.response?.status === 403) {
        errorMessage = 'Access denied. You do not have permission to delete this file.';
      } else if (error.response?.status === 404) {
        errorMessage = 'File not found. It may have already been deleted.';
      } else if (error.response?.status >= 500) {
        errorMessage = 'Server error during deletion. Please try again later.';
      } else if (!error.response) {
        errorMessage = 'Network error. Please check your connection and try again.';
      }
      
      return { success: false, error: errorMessage };
    }
  },

  restoreFile: async (id: number): Promise<{ success: boolean; error?: string }> => {
    console.log('📁 File API - Restore file attempt:', { fileId: id });
    try {
      const response = await api.post(`/api/v1/invoices/${id}/restore`);
      
      console.log('📁 File API - Restore file success:', { 
        fileId: id,
        responseStatus: response.status
      });
      
      return { success: true };
    } catch (error: any) {
      console.error('📁 File API - Restore file failed:', {
        error: error.response?.data || error.message,
        status: error.response?.status,
        fileId: id
      });
      
      let errorMessage = 'Restore failed. Please try again.';
      
      if (error.response?.status === 401) {
        errorMessage = 'Session expired. Please log in again.';
      } else if (error.response?.status === 403) {
        errorMessage = 'Access denied. You do not have permission to restore this file.';
      } else if (error.response?.status === 404) {
        errorMessage = 'File not found in recycle bin.';
      } else if (error.response?.status >= 500) {
        errorMessage = 'Server error during restore. Please try again later.';
      } else if (!error.response) {
        errorMessage = 'Network error. Please check your connection and try again.';
      }
      
      return { success: false, error: errorMessage };
    }
  },

  getDeletedFiles: async (): Promise<Invoice[]> => {
    console.log('📁 File API - Get deleted files attempt');
    try {
      const response = await api.get('/api/v1/invoices/deleted');
      const deletedInvoices = response.data || [];
      
      // Format the deleted invoices
      const formattedInvoices = deletedInvoices.map((invoice: any) => ({
        id: invoice.id,
        filename: invoice.xml_path ? invoice.xml_path.split('/').pop() : 'Unknown',
        status: 'deleted',
        customerName: 'Unknown',
        formate: 'XML',
        export: 'EDI',
        uploaded_at: invoice.uploaded_at,
        tracking_id: invoice.tracking_id,
        deleted_at: invoice.deleted_at
      }));
      
      console.log('📁 File API - Get deleted files success:', { 
        deletedCount: formattedInvoices.length
      });
      
      return formattedInvoices;
    } catch (error: any) {
      console.log('📁 File API - Get deleted files endpoint not available, returning empty array');
      
      // If the endpoint doesn't exist (404) or server error (500), return empty array
      if (error.response?.status === 404 || error.response?.status >= 500) {
        return [];
      }
      
      // For authentication errors, still throw the error
      if (error.response?.status === 401) {
        throw new Error('Session expired. Please log in again.');
      }
      
      // For other errors, return empty array gracefully
      console.warn('📁 File API - Get deleted files failed, returning empty array:', error.response?.data || error.message);
      return [];
    }
  },

  getFailedInvoiceByTrackingId: async (trackingId: string): Promise<any> => {
    console.log('📁 File API - Get failed invoice by tracking ID attempt:', trackingId);
    try {
      const response = await api.get(`/api/v1/invoices/failed/${trackingId}`);
      
      console.log('📁 File API - Get failed invoice by tracking ID success:', { 
        trackingId,
        responseData: response.data
      });
      
      console.log('🔍 API Response - processing_steps_error:', response.data.processing_steps_error);
      console.log('🔍 API Response - All keys:', Object.keys(response.data));
      console.log('🔍 API Response - XML content length:', response.data.xml_content?.length || 0);
      console.log('🔍 API Response - EDI content length:', response.data.edi_content?.length || 0);
      console.log('🔍 API Response - Full response:', JSON.stringify(response.data, null, 2));
      
      return response.data;
    } catch (error: any) {
      console.error('📁 File API - Get failed invoice by tracking ID failed:', {
        error: error.response?.data || error.message,
        status: error.response?.status,
        trackingId,
        fullError: error,
        url: `/api/v1/invoices/failed/${trackingId}`,
        method: 'GET'
      });
      
      if (error.response?.status === 401) {
        throw new Error('Session expired. Please log in again.');
      } else if (error.response?.status === 404) {
        throw new Error('Failed invoice not found.');
      } else if (error.response?.status >= 500) {
        throw new Error('Server error. Please try again later.');
      } else if (!error.response) {
        throw new Error('Network error. Please check your connection and try again.');
      } else {
        throw new Error('Failed to load invoice details. Please try again.');
      }
    }
  },

  getInvoiceCounts: async (): Promise<{
    successful: number;
    failed: number;
    deleted: number;
    total: number;
    processing: number;
  }> => {
    console.log('📊 File API - Get invoice counts attempt');
    try {
      const response = await api.get('/api/v1/invoices/counts');
      
      console.log('📊 File API - Get invoice counts success:', { 
        responseData: response.data
      });
      
      return response.data;
    } catch (error: any) {
      console.error('📊 File API - Get invoice counts failed:', {
        error: error.response?.data || error.message,
        status: error.response?.status,
        fullError: error
      });
      
      if (error.response?.status === 401) {
        throw new Error('Session expired. Please log in again.');
      } else if (error.response?.status >= 500) {
        throw new Error('Server error. Please try again later.');
      } else if (!error.response) {
        throw new Error('Network error. Please check your connection and try again.');
      } else {
        throw new Error('Failed to load invoice counts. Please try again.');
      }
    }
  },

  // API Key Management
  getApiKey: async (): Promise<{
    has_key: boolean;
    is_active?: boolean;
    api_user_identifier?: string;
    created_at?: string;
    updated_at?: string;
    allow_list?: string[];
    message: string;
  }> => {
    console.log('🔑 API Key - Get API key attempt');
    try {
      const response = await api.get('/api/v1/invoices/api-key');
      
      console.log('🔑 API Key - Get API key success:', { 
        responseData: response.data
      });
      
      return response.data;
    } catch (error: any) {
      console.error('🔑 API Key - Get API key failed:', {
        error: error.response?.data || error.message,
        status: error.response?.status,
        fullError: error
      });
      
      if (error.response?.status === 401) {
        throw new Error('Session expired. Please log in again.');
      } else if (error.response?.status === 403) {
        throw new Error('API access is not allowed for this user.');
      } else if (error.response?.status >= 500) {
        throw new Error('Server error. Please try again later.');
      } else if (!error.response) {
        throw new Error('Network error. Please check your connection and try again.');
      } else {
        throw new Error('Failed to get API key information. Please try again.');
      }
    }
  },

  generateApiKey: async (): Promise<{
    success: boolean;
    api_key: string;
    api_user_identifier: string;
    created_at: string;
    message: string;
  }> => {
    console.log('🔑 API Key - Generate API key attempt');
    try {
      const response = await api.post('/api/v1/invoices/api-key/generate');
      
      console.log('🔑 API Key - Generate API key success:', { 
        responseData: response.data
      });
      
      return response.data;
    } catch (error: any) {
      console.error('🔑 API Key - Generate API key failed:', {
        error: error.response?.data || error.message,
        status: error.response?.status,
        fullError: error
      });
      
      if (error.response?.status === 401) {
        throw new Error('Session expired. Please log in again.');
      } else if (error.response?.status === 403) {
        throw new Error('API access is not allowed for this user.');
      } else if (error.response?.status >= 500) {
        throw new Error('Server error. Please try again later.');
      } else if (!error.response) {
        throw new Error('Network error. Please check your connection and try again.');
      } else {
        throw new Error('Failed to generate API key. Please try again.');
      }
    }
  },

  regenerateApiKey: async (): Promise<{
    success: boolean;
    api_key: string;
    api_user_identifier: string;
    updated_at: string;
    message: string;
  }> => {
    console.log('🔑 API Key - Regenerate API key attempt');
    try {
      const response = await api.post('/api/v1/invoices/api-key/regenerate');
      
      console.log('🔑 API Key - Regenerate API key success:', { 
        responseData: response.data
      });
      
      return response.data;
    } catch (error: any) {
      console.error('🔑 API Key - Regenerate API key failed:', {
        error: error.response?.data || error.message,
        status: error.response?.status,
        fullError: error
      });
      
      if (error.response?.status === 401) {
        throw new Error('Session expired. Please log in again.');
      } else if (error.response?.status === 403) {
        throw new Error('API access is not allowed for this user.');
      } else if (error.response?.status >= 500) {
        throw new Error('Server error. Please try again later.');
      } else if (!error.response) {
        throw new Error('Network error. Please check your connection and try again.');
      } else {
        throw new Error('Failed to regenerate API key. Please try again.');
      }
    }
  },

  suspendApiKey: async (): Promise<{
    success: boolean;
    deactivated_at: string;
    message: string;
  }> => {
    console.log('🔑 API Key - Suspend API key attempt');
    try {
      const response = await api.post('/api/v1/invoices/api-key/suspend');
      
      console.log('🔑 API Key - Suspend API key success:', { 
        responseData: response.data
      });
      
      return response.data;
    } catch (error: any) {
      console.error('🔑 API Key - Suspend API key failed:', {
        error: error.response?.data || error.message,
        status: error.response?.status,
        fullError: error
      });
      
      if (error.response?.status === 401) {
        throw new Error('Session expired. Please log in again.');
      } else if (error.response?.status === 404) {
        throw new Error('No API key found to suspend.');
      } else if (error.response?.status >= 500) {
        throw new Error('Server error. Please try again later.');
      } else if (!error.response) {
        throw new Error('Network error. Please check your connection and try again.');
      } else {
        throw new Error('Failed to suspend API key. Please try again.');
      }
    }
  },

  activateApiKey: async (): Promise<{
    success: boolean;
    updated_at: string;
    message: string;
  }> => {
    console.log('🔑 API Key - Activate API key attempt');
    try {
      const response = await api.post('/api/v1/invoices/api-key/activate');
      
      console.log('🔑 API Key - Activate API key success:', { 
        responseData: response.data
      });
      
      return response.data;
    } catch (error: any) {
      console.error('🔑 API Key - Activate API key failed:', {
        error: error.response?.data || error.message,
        status: error.response?.status,
        fullError: error
      });
      
      if (error.response?.status === 401) {
        throw new Error('Session expired. Please log in again.');
      } else if (error.response?.status === 404) {
        throw new Error('No API key found to activate.');
      } else if (error.response?.status >= 500) {
        throw new Error('Server error. Please try again later.');
      } else if (!error.response) {
        throw new Error('Network error. Please check your connection and try again.');
      } else {
        throw new Error('Failed to activate API key. Please try again.');
      }
    }
  },

  updateApiKeyAllowList: async (allowList: string[]): Promise<{
    success: boolean;
    allow_list: string[];
    updated_at: string;
    message: string;
  }> => {
    console.log('🔑 API Key - Update allow list attempt:', allowList);
    try {
      const response = await api.post('/api/v1/invoices/api-key/allow-list', allowList);
      
      console.log('🔑 API Key - Update allow list success:', { 
        responseData: response.data
      });
      
      return response.data;
    } catch (error: any) {
      console.error('🔑 API Key - Update allow list failed:', {
        error: error.response?.data || error.message,
        status: error.response?.status,
        fullError: error
      });
      
      if (error.response?.status === 401) {
        throw new Error('Session expired. Please log in again.');
      } else if (error.response?.status === 404) {
        throw new Error('No API key found to update.');
      } else if (error.response?.status === 400) {
        throw new Error('Invalid IP address format provided.');
      } else if (error.response?.status >= 500) {
        throw new Error('Server error. Please try again later.');
      } else if (!error.response) {
        throw new Error('Network error. Please check your connection and try again.');
      } else {
        throw new Error('Failed to update API key allow list. Please try again.');
      }
    }
  },

  getProcessingStatus: async (trackingId: string): Promise<any> => {
    console.log('📊 File API - Get processing status:', trackingId);
    try {
      const response = await api.get(`/api/v1/invoices/status/${trackingId}`);
      
      console.log('📊 File API - Processing status response:', response.data);
      
      return response.data;
    } catch (error: any) {
      console.error('📊 File API - Get processing status failed:', {
        error: error.response?.data || error.message,
        status: error.response?.status,
        trackingId
      });
      
      if (error.response?.status === 401) {
        throw new Error('Session expired. Please log in again.');
      } else if (error.response?.status === 404) {
        throw new Error('Processing status not found');
      } else if (error.response?.status >= 500) {
        throw new Error('Server error. Please try again later.');
      } else if (!error.response) {
        throw new Error('Network error. Please check your connection and try again.');
      } else {
        throw new Error(error.response?.data?.detail || 'Failed to fetch processing status');
      }
    }
  },
};

// Customer API
export const customerApi = {
  getCustomers: async (skip: number = 0, limit: number = 100, search?: string): Promise<any> => {
    console.log('👥 Customer API - Fetching customers:', { skip, limit, search });
    try {
      const params = new URLSearchParams();
      params.append('skip', skip.toString());
      params.append('limit', limit.toString());
      if (search) {
        params.append('search', search);
      }
      
      const response = await api.get(`/api/v1/customers/?${params}`);
      
      console.log('👥 Customer API - Fetched customers:', response.data);
      return response.data;
    } catch (error: any) {
      console.error('👥 Customer API - Failed to fetch customers:', error.response?.data || error.message);
      
      if (error.response?.status === 401) {
        throw new Error('Session expired. Please log in again.');
      } else if (error.response?.status >= 500) {
        throw new Error('Server error. Please try again later.');
      } else if (!error.response) {
        throw new Error('Network error. Please check your connection.');
      } else {
        throw new Error('Failed to fetch customers.');
      }
    }
  },

  getCustomerById: async (customerId: string): Promise<any> => {
    console.log('👥 Customer API - Fetching customer:', customerId);
    try {
      const response = await api.get(`/api/v1/customers/${customerId}`);
      console.log('👥 Customer API - Fetched customer:', response.data);
      return response.data;
    } catch (error: any) {
      console.error('👥 Customer API - Failed to fetch customer:', error.response?.data || error.message);
      
      if (error.response?.status === 401) {
        throw new Error('Session expired. Please log in again.');
      } else if (error.response?.status === 404) {
        throw new Error('Customer not found.');
      } else if (error.response?.status >= 500) {
        throw new Error('Server error. Please try again later.');
      } else if (!error.response) {
        throw new Error('Network error. Please check your connection.');
      } else {
        throw new Error('Failed to fetch customer.');
      }
    }
  },

  createCustomer: async (data: any): Promise<any> => {
    console.log('👥 Customer API - Creating customer:', data);
    try {
      const response = await api.post('/api/v1/customers/', data);
      console.log('👥 Customer API - Customer created:', response.data);
      return response.data;
    } catch (error: any) {
      console.error('👥 Customer API - Failed to create customer:', error.response?.data || error.message);
      
      if (error.response?.status === 401) {
        throw new Error('Session expired. Please log in again.');
      } else if (error.response?.status === 409) {
        throw new Error('Customer with this ID already exists.');
      } else if (error.response?.status === 400) {
        throw new Error('Invalid customer data provided.');
      } else if (error.response?.status >= 500) {
        throw new Error('Server error. Please try again later.');
      } else if (!error.response) {
        throw new Error('Network error. Please check your connection.');
      } else {
        throw new Error(error.response?.data?.detail || 'Failed to create customer.');
      }
    }
  },

  updateCustomer: async (customerId: string, data: any): Promise<any> => {
    console.log('👥 Customer API - Updating customer:', { customerId, data });
    try {
      const response = await api.put(`/api/v1/customers/${customerId}`, data);
      console.log('👥 Customer API - Customer updated:', response.data);
      return response.data;
    } catch (error: any) {
      console.error('👥 Customer API - Failed to update customer:', error.response?.data || error.message);
      
      if (error.response?.status === 401) {
        throw new Error('Session expired. Please log in again.');
      } else if (error.response?.status === 404) {
        throw new Error('Customer not found.');
      } else if (error.response?.status === 409) {
        throw new Error('New customer ID already exists.');
      } else if (error.response?.status === 400) {
        throw new Error('Invalid customer data provided.');
      } else if (error.response?.status >= 500) {
        throw new Error('Server error. Please try again later.');
      } else if (!error.response) {
        throw new Error('Network error. Please check your connection.');
      } else {
        throw new Error(error.response?.data?.detail || 'Failed to update customer.');
      }
    }
  },

  deleteCustomer: async (customerId: string): Promise<any> => {
    console.log('👥 Customer API - Deleting customer:', customerId);
    try {
      const response = await api.delete(`/api/v1/customers/${customerId}`);
      console.log('👥 Customer API - Customer deleted:', response.data);
      return response.data;
    } catch (error: any) {
      console.error('👥 Customer API - Failed to delete customer:', error.response?.data || error.message);
      
      if (error.response?.status === 401) {
        throw new Error('Session expired. Please log in again.');
      } else if (error.response?.status === 404) {
        throw new Error('Customer not found.');
      } else if (error.response?.status >= 500) {
        throw new Error('Server error. Please try again later.');
      } else if (!error.response) {
        throw new Error('Network error. Please check your connection.');
      } else {
        throw new Error(error.response?.data?.detail || 'Failed to delete customer.');
      }
    }
  },

  getSupportedFormats: async (): Promise<any> => {
    console.log('👥 Customer API - Fetching supported formats');
    try {
      const response = await api.get('/api/v1/customers/formats/list');
      console.log('👥 Customer API - Supported formats:', response.data);
      return response.data;
    } catch (error: any) {
      console.error('👥 Customer API - Failed to fetch formats:', error.response?.data || error.message);
      
      // Return default formats if API fails
      return {
        supported_formats: ['edifact', 'x12', 'x12_embed', 'xml'],
        descriptions: {
          edifact: 'UN/EDIFACT electronic data interchange format',
          x12: 'ASC X12 EDI format',
          x12_embed: 'X12 embedded in another format',
          xml: 'XML format',
        },
      };
    }
  },

  bulkCreateCustomers: async (customers: any[]): Promise<any> => {
    console.log('👥 Customer API - Bulk creating customers:', { count: customers.length });
    try {
      const response = await api.post('/api/v1/customers/bulk/create', customers);
      console.log('👥 Customer API - Bulk create response:', response.data);
      return response.data;
    } catch (error: any) {
      console.error('👥 Customer API - Failed to bulk create:', error.response?.data || error.message);
      
      if (error.response?.status === 401) {
        throw new Error('Session expired. Please log in again.');
      } else if (error.response?.status === 400) {
        throw new Error('Invalid customer data provided.');
      } else if (error.response?.status >= 500) {
        throw new Error('Server error. Please try again later.');
      } else if (!error.response) {
        throw new Error('Network error. Please check your connection.');
      } else {
        throw new Error(error.response?.data?.detail || 'Failed to bulk create customers.');
      }
    }
  },
};

export default api;
