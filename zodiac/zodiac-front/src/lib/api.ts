import axios from 'axios';
import { AuthResponse, LoginRequest, SignupRequest, User, FileUploadResponse, Invoice } from '@/types';

function trimTrailingSlash(url: string): string {
    return url.replace(/\/$/, '');
}

/**
 * Axios baseURL: server-side and explicit NEXT_PUBLIC hit the backend directly.
 * Browser without NEXT_PUBLIC uses same-origin URLs; next.config rewrites proxy /api/v1 → FastAPI (avoids localhost:8000 / wrong-process 404s in dev).
 */
function resolveAxiosBaseURL(): string | undefined {
    const pub = process.env.NEXT_PUBLIC_API_URL?.trim();
    if (typeof window === 'undefined') {
        const internal = process.env.INTERNAL_API_URL?.trim();
        return trimTrailingSlash(internal || pub || 'http://127.0.0.1:8000');
    }
    if (pub) return trimTrailingSlash(pub);
    return undefined;
}

/** Full origin for download links and logging (browser + no NEXT_PUBLIC → current page origin). */
export function getPublicApiBase(): string {
    const pub = process.env.NEXT_PUBLIC_API_URL?.trim();
    if (typeof window === 'undefined') {
        return trimTrailingSlash(
            process.env.INTERNAL_API_URL?.trim() || pub || 'http://127.0.0.1:8000'
        );
    }
    if (pub) return trimTrailingSlash(pub);
    return trimTrailingSlash(window.location.origin);
}

const API_BASE_URL = resolveAxiosBaseURL();

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

        // 401 on login/signup is "wrong credentials" / validation — not an expired session. Do not redirect.
        const reqPath = String(error.config?.url || '');
        const isAuthCredentialRequest =
            reqPath.includes('/user/auth/login') || reqPath.includes('/user/auth/create-user');

        if (error.response?.status === 401 && !isAuthCredentialRequest) {
            if (typeof window !== 'undefined') {
                const authKeys = [
                    'access_token',
                    'refresh_token',
                    'user_data',
                    'auth_state',
                    'token_expiry',
                    'last_login',
                    'remember_me',
                ];

                authKeys.forEach((key) => {
                    localStorage.removeItem(key);
                    sessionStorage.removeItem(key);
                });

                console.log('🔐 API - 401 (session invalid), clearing auth and redirecting to login');
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
            // Avoid logging raw AxiosError in one object — Next dev overlay often shows `{}` (non-serializable).
            const st = error.response?.status;
            const detail = error.response?.data?.detail;
            const baseLabel = API_BASE_URL ?? getPublicApiBase();
            console.error(
                `🔐 Auth API - Login failed: status=${st ?? 'none'} code=${error.code ?? 'n/a'} message=${error.message} baseURL=${baseLabel}`
            );
            if (detail !== undefined) console.error('🔐 Auth API - Login detail:', detail);

            if (error.response?.status === 401) {
                throw new Error('Invalid email or password. Please check your credentials and try again.');
            } else if (error.response?.status === 404) {
                throw new Error(
                    'Login API returned Not Found. Use same-origin API (leave NEXT_PUBLIC unset locally) or set NEXT_PUBLIC_API_URL to your running backend; ensure the API is on port 8000.'
                );
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

// Customer users API (admin only)
export interface CustomerUserResponse {
    id: number;
    email: string;
    username: string;
    is_customer_user: boolean;
    customer_ids: string[];
}
export const customerUsersApi = {
    list: async (): Promise<CustomerUserResponse[]> => {
        const response = await api.get('/api/v1/customer-users');
        return response.data;
    },
    create: async (data: { email: string; username: string; password: string }): Promise<CustomerUserResponse> => {
        try {
            const response = await api.post('/api/v1/customer-users', data);
            return response.data;
        } catch (error: any) {
            const detail = error.response?.data?.detail;
            let msg = 'Failed to create customer user.';
            if (typeof detail === 'string') msg = detail;
            else if (Array.isArray(detail) && detail.length)
                msg = detail.map((d: { msg?: string; message?: string }) => d.msg || d.message).filter(Boolean).join(' ') || msg;
            throw new Error(msg);
        }
    },
    getMyCustomers: async (): Promise<string[]> => {
        const response = await api.get('/api/v1/customer-users/me/customers');
        return response.data;
    },
    getCustomers: async (userId: number): Promise<string[]> => {
        const response = await api.get(`/api/v1/customer-users/${userId}/customers`);
        return response.data;
    },
    assignCustomers: async (userId: number, customerIds: string[]): Promise<CustomerUserResponse> => {
        const response = await api.put(`/api/v1/customer-users/${userId}/customers`, { customer_ids: customerIds });
        return response.data;
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
            apiBaseUrl: API_BASE_URL ?? getPublicApiBase(),
            hasToken: typeof window !== 'undefined' ? !!localStorage.getItem('access_token') : 'N/A'
        });

        try {
            const formData = new FormData();
            formData.append('file', file);

            console.log('📁 File API - Making request to:', `${API_BASE_URL ?? getPublicApiBase()}/api/v1/invoices/process`);
            console.log('📁 File API - FormData contents:', {
                fileName: file.name,
                fileSize: file.size,
                fileType: file.type,
                hasFile: formData.has('file')
            });

            // Check if we have authentication token
            const token = typeof window !== 'undefined' ? localStorage.getItem('access_token') : null;
            console.log('📁 File API - Auth token present:', !!token);

            // All files are processed as XML input
            // Output format (EDIFACT, X12, etc.) is determined by customer configuration
            const endpoint = '/api/v1/invoices/process';

            console.log('📁 File API - Processing XML file:', {
                fileName: file.name,
                endpoint
            });

            let response;
            try {
                console.log(`📁 File API - About to make axios request to ${endpoint}...`);
                response = await api.post(endpoint, formData, {
                    headers: {
                        'Content-Type': 'multipart/form-data',
                    },
                });
                console.log('📁 File API - Axios request completed successfully');
            } catch (axiosError: any) {
                console.error('📁 File API - Axios request failed:', axiosError);
                console.error('📁 File API - Axios error type:', typeof axiosError);
                console.error('📁 File API - Axios error constructor:', axiosError?.constructor?.name);

                // Handle 400 Bad Request - can be duplicate, validation, or upload failures
                if (axiosError.response?.status === 400) {
                    console.log('📁 File API - Handling 400 Bad Request');
                    const errorData = axiosError.response.data;
                    console.log('📁 File API - Error data:', errorData);

                    // Check if this is a duplicate invoice error (new structured format)
                    if (errorData.detail && typeof errorData.detail === 'object') {
                        if (errorData.detail.error === 'Duplicate invoice detected') {
                            console.log('📁 File API - Duplicate invoice detected!');
                            const detail = errorData.detail;
                            return {
                                success: false,
                                error: detail.message || `Invoice #${detail.invoice_number} has already been uploaded.`,
                                isDuplicate: true,
                                invoiceNumber: detail.invoice_number,
                                existingInvoiceId: detail.existing_invoice_id,
                                data: errorData
                            };
                        }
                        
                        // Check if this is invoice number extraction failure
                        if (errorData.detail.error === 'Invoice number extraction failed') {
                            console.log('📁 File API - Invoice number extraction failed');
                            const detail = errorData.detail;
                            return {
                                success: false,
                                error: detail.message || 'Could not extract invoice number from XML file.',
                                isExtractionError: true,
                                supportedFormats: detail.supported_formats || [],
                                data: errorData
                            };
                        }
                        
                        // Generic structured error
                        if (errorData.detail.message) {
                            return {
                                success: false,
                                error: errorData.detail.message,
                                data: errorData
                            };
                        }
                    }

                    // Legacy: Handle old format (file_upload_pass: false) or simple string detail
                    let errorMessage = 'File upload failed.';
                    if (errorData.file_upload_message) {
                        errorMessage = `File upload failed: ${errorData.file_upload_message}`;
                    } else if (errorData.detail && typeof errorData.detail === 'string') {
                        errorMessage = errorData.detail;
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

            // Get both successful and failed invoices with pagination
            // Fetch first 50 of each for faster initial load
            const [successResponse, failedResponse] = await Promise.all([
                api.get('/api/v1/invoices/success', { params: { skip: 0, limit: 50 } }),
                api.get('/api/v1/invoices/failed', { params: { skip: 0, limit: 50 } })
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
                        use_blob_storage: invoice.use_blob_storage,
                        customerId: invoice.customerId,
                        customerName: invoice.customerName,
                        formate: invoice.formate
                    });

                    return {
                        id: invoice.id,
                        filename: xmlPath ? xmlPath.split('/').pop() : `${invoice.tracking_id}_invoice.xml`,
                        status: 'successful',
                        accepted: 1,
                        rejected: 0,
                        customerId: invoice.customerId || invoice.invoice_id,
                        customerName: invoice.customerName || invoice.customer_name,
                        invoice_id: invoice.invoice_id,
                        formate: invoice.formate?.toUpperCase() || invoice.target_file_format?.toUpperCase() || 'X12',
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
                        request_type: invoice.request_type || 'web', // Add request_type for source tracking
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
                        use_blob_storage: invoice.use_blob_storage,
                        customerId: invoice.customerId,
                        customerName: invoice.customerName,
                        formate: invoice.formate
                    });

                    return {
                        id: invoice.id,
                        filename: xmlPath ? xmlPath.split('/').pop() : `${invoice.tracking_id}_invoice.xml`,
                        status: 'failed',
                        accepted: 0,
                        rejected: 1,
                        customerId: invoice.customerId || invoice.invoice_id,
                        customerName: invoice.customerName || invoice.customer_name || 'N/A',
                        invoice_id: invoice.invoice_id,
                        formate: invoice.formate?.toUpperCase() || invoice.target_file_format?.toUpperCase() || 'X12',
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
                        processing_steps_error: invoice.processing_steps_error,
                        request_type: invoice.request_type || 'web', // Add request_type for source tracking
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
            // Fetch first 50 deleted invoices for faster load
            const response = await api.get('/api/v1/invoices/deleted', { params: { skip: 0, limit: 50 } });
            const deletedInvoices = response.data || [];

            // Format the deleted invoices
            const formattedInvoices = deletedInvoices.map((invoice: any) => ({
                id: invoice.id,
                filename: invoice.filename || (invoice.xml_path ? invoice.xml_path.split('/').pop() : 'Unknown'),
                status: invoice.status || 'deleted',
                customerId: invoice.customerId || invoice.invoice_id,
                customerName: invoice.customerName || invoice.customer_name || 'Unknown',
                formate: invoice.formate?.toUpperCase() || invoice.target_file_format?.toUpperCase() || 'X12',
                export: false,
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

    getReceiverRfcs: async (customerId: string): Promise<string[]> => {
        const response = await api.get(`/api/v1/customers/${encodeURIComponent(customerId)}/receiver-rfcs`);
        return response.data;
    },
    setReceiverRfcs: async (customerId: string, receiverRfcs: string[]): Promise<string[]> => {
        const response = await api.put(`/api/v1/customers/${encodeURIComponent(customerId)}/receiver-rfcs`, { receiver_rfcs: receiverRfcs });
        return response.data;
    },

    getDeliverySettings: async (customerId: string): Promise<any> => {
        const response = await api.get(`/api/v1/customers/${encodeURIComponent(customerId)}/delivery-settings`);
        return response.data;
    },
    updateDeliverySettings: async (customerId: string, body: {
        delivery_method?: string;
        host: string;
        port?: number;
        username: string;
        remote_path?: string;
        auth_type: 'key' | 'password';
        private_key?: string;
        password?: string;
        key_passphrase?: string;
        use_test_env?: boolean;
    }): Promise<any> => {
        const response = await api.put(`/api/v1/customers/${encodeURIComponent(customerId)}/delivery-settings`, body);
        return response.data;
    },
    testDeliveryConnection: async (customerId: string): Promise<{ success: boolean; message: string }> => {
        const response = await api.post(`/api/v1/customers/${encodeURIComponent(customerId)}/delivery-settings/test`);
        return response.data;
    },

    generateCustomerToken: async (customerId: string, options?: { expires_in_days?: number; notes?: string }): Promise<{ success: boolean; token: string; customer_id: string; expires_at: string | null; message: string }> => {
        const response = await api.post(`/api/v1/customers/${encodeURIComponent(customerId)}/token/generate`, options || {});
        return response.data;
    },
    getCustomerTokenInfo: async (customerId: string): Promise<{ has_token: boolean; last_used_at?: string; expires_at?: string; is_active?: boolean }> => {
        const response = await api.get(`/api/v1/customers/${encodeURIComponent(customerId)}/token`);
        return response.data;
    },
    revokeCustomerToken: async (customerId: string): Promise<{ success: boolean; message: string }> => {
        const response = await api.delete(`/api/v1/customers/${encodeURIComponent(customerId)}/token`);
        return response.data;
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

// Certificate API
export const certificateApi = {
    issueCertificate: async (data: {
        customer_id: string;
        organization?: string;
        organizational_unit?: string;
        country?: string;
        email?: string;
        validity_days?: number;
        notes?: string;
    }): Promise<any> => {
        const response = await api.post('/api/v1/certificates/issue', data);
        return response.data;
    },

    listCertificates: async (
        customerId?: string,
        statusFilter?: string,
        skip: number = 0,
        limit: number = 100
    ): Promise<any> => {
        const params = new URLSearchParams();
        if (customerId) params.append('customer_id', customerId);
        if (statusFilter) params.append('status_filter', statusFilter);
        params.append('skip', skip.toString());
        params.append('limit', limit.toString());

        const response = await api.get(`/api/v1/certificates?${params}`);
        return response.data;
    },

    getCertificate: async (certificateId: number): Promise<any> => {
        const response = await api.get(`/api/v1/certificates/${certificateId}`);
        return response.data;
    },

    getCustomerActiveCertificate: async (customerId: string): Promise<any> => {
        try {
            const response = await api.get(`/api/v1/certificates/customer/${encodeURIComponent(customerId)}/active`);
            return response.data;
        } catch (error: any) {
            if (error.response?.status === 404) {
                return null;
            }
            throw error;
        }
    },

    renewCertificate: async (certificateId: number, data: {
        validity_days?: number;
        notes?: string;
    }): Promise<any> => {
        const response = await api.post(`/api/v1/certificates/${certificateId}/renew`, data);
        return response.data;
    },

    revokeCertificate: async (certificateId: number, reason?: string): Promise<any> => {
        const response = await api.post(`/api/v1/certificates/${certificateId}/revoke`, { reason });
        return response.data;
    },

    downloadCertificatePEM: async (certificateId: number, includePrivateKey: boolean = false): Promise<any> => {
        const params = includePrivateKey ? '?include_private_key=true' : '';
        const response = await api.get(`/api/v1/certificates/${certificateId}/download-pem${params}`);
        return response.data;
    },

    downloadCertificateCRT: async (certificateId: number): Promise<{ blob: Blob; filename: string }> => {
        const response = await api.get(`/api/v1/certificates/${certificateId}/download-crt`, {
            responseType: 'blob',
        });

        const contentDisposition = response.headers['content-disposition'] || '';
        const filenameMatch = contentDisposition.match(/filename="?([^"]+)"?/);
        const filename = filenameMatch ? filenameMatch[1] : `certificate-${certificateId}.crt`;

        return {
            blob: response.data,
            filename,
        };
    },

    downloadCertificateP12: async (certificateId: number): Promise<{ blob: Blob; password: string; filename: string }> => {
        const response = await api.get(`/api/v1/certificates/${certificateId}/download-p12`, {
            responseType: 'blob',
        });

        const password = response.headers['x-p12-password'] || '';
        const contentDisposition = response.headers['content-disposition'] || '';
        const filenameMatch = contentDisposition.match(/filename="?([^"]+)"?/);
        const filename = filenameMatch ? filenameMatch[1] : `certificate-${certificateId}.p12`;

        return {
            blob: response.data,
            password,
            filename,
        };
    },

    createRenewalRequest: async (certificateId: number, notes?: string): Promise<any> => {
        const response = await api.post('/api/v1/certificates/renewal-requests', {
            certificate_id: certificateId,
            notes,
        });
        return response.data;
    },

    listRenewalRequests: async (
        statusFilter?: string,
        customerId?: string,
        skip: number = 0,
        limit: number = 100
    ): Promise<any> => {
        const params = new URLSearchParams();
        if (statusFilter) params.append('status_filter', statusFilter);
        if (customerId) params.append('customer_id', customerId);
        params.append('skip', skip.toString());
        params.append('limit', limit.toString());

        const response = await api.get(`/api/v1/certificates/renewal-requests?${params}`);
        return response.data;
    },

    processRenewalRequest: async (requestId: number, data: {
        approved: boolean;
        validity_days?: number;
        notes?: string;
        rejection_reason?: string;
    }): Promise<any> => {
        const response = await api.post(`/api/v1/certificates/renewal-requests/${requestId}/process`, data);
        return response.data;
    },

    getCertificateHealth: async (): Promise<any> => {
        const response = await api.get('/api/v1/certificates/health/summary');
        return response.data;
    },

    updateCertificateStatuses: async (): Promise<any> => {
        const response = await api.post('/api/v1/certificates/maintenance/update-statuses');
        return response.data;
    },
};

// Dashboard API
export const dashboardApi = {
    // Get dashboard statistics (overview, timeline, distributions)
    getStatistics: async (days: number = 30) => {
        try {
            const response = await api.get(`/api/v1/dashboard/statistics?days=${days}`);
            return response.data;
        } catch (error: any) {
            console.error('Failed to fetch dashboard statistics:', error);
            if (error.response?.status === 401) {
                throw new Error('Session expired. Please log in again.');
            }
            throw new Error(error.response?.data?.detail || 'Failed to load dashboard statistics.');
        }
    },

    // Get AI-powered insights for failed invoices
    getAIInsights: async () => {
        try {
            const response = await api.get('/api/v1/dashboard/ai-insights');
            return response.data;
        } catch (error: any) {
            console.error('Failed to fetch AI insights:', error);
            if (error.response?.status === 401) {
                throw new Error('Session expired. Please log in again.');
            }
            throw new Error(error.response?.data?.detail || 'Failed to load AI insights.');
        }
    },

    // Get auto-fix details by fix type
    getAutoFixDetails: async (fixType: string) => {
        try {
            const response = await api.get(`/api/v1/dashboard/auto-fix-details?fix_type=${encodeURIComponent(fixType)}`);
            return response.data;
        } catch (error: any) {
            console.error('Failed to fetch auto-fix details:', error);
            if (error.response?.status === 401) {
                throw new Error('Session expired. Please log in again.');
            }
            throw new Error(error.response?.data?.detail || 'Failed to load auto-fix details.');
        }
    },

    // Get operations statistics
    getOperations: async (days: number = 30) => {
        try {
            const response = await api.get(`/api/v1/dashboard/operations?days=${days}`);
            return response.data;
        } catch (error: any) {
            console.error('Failed to fetch operations data:', error);
            if (error.response?.status === 401) {
                throw new Error('Session expired. Please log in again.');
            }
            throw new Error(error.response?.data?.detail || 'Failed to load operations data.');
        }
    },

    // Get business analytics
    getBusiness: async (days: number = 30) => {
        try {
            const response = await api.get(`/api/v1/dashboard/business?days=${days}`);
            return response.data;
        } catch (error: any) {
            console.error('Failed to fetch business analytics:', error);
            if (error.response?.status === 401) {
                throw new Error('Session expired. Please log in again.');
            }
            throw new Error(error.response?.data?.detail || 'Failed to load business analytics.');
        }
    },

    // Get industry intelligence
    getIndustryIntelligence: async (days: number = 30) => {
        try {
            const response = await api.get(`/api/v1/dashboard/industry-intelligence?days=${days}`);
            return response.data;
        } catch (error: any) {
            console.error('Failed to fetch industry intelligence:', error);
            if (error.response?.status === 401) {
                throw new Error('Session expired. Please log in again.');
            }
            throw new Error(error.response?.data?.detail || 'Failed to load industry intelligence.');
        }
    },
    
    backfillInvoiceV2BI: async () => {
        try {
            const response = await api.post('/api/v1/dashboard/backfill-invoice-v2-bi');
            return response.data;
        } catch (error: any) {
            console.error('Failed to backfill Invoice V2 BI:', error);
            throw new Error(error.response?.data?.detail || 'Failed to backfill Invoice V2 business intelligence.');
        }
    },
    getDashboardDataStats: async () => {
        const response = await api.get('/api/v1/dashboard/dashboard-data-stats');
        return response.data;
    },
    
    getRevenueAnalysis: async (days: number = 90) => {
        try {
            const response = await api.get(`/api/v1/dashboard/revenue-analysis?days=${days}`);
            return response.data;
        } catch (error: any) {
            console.error('Failed to fetch revenue analysis:', error);
            throw new Error(error.response?.data?.detail || 'Failed to load revenue analysis.');
        }
    },
    
    getProductDemand: async (days: number = 90) => {
        try {
            const response = await api.get(`/api/v1/dashboard/product-demand?days=${days}`);
            return response.data;
        } catch (error: any) {
            console.error('Failed to fetch product demand:', error);
            throw new Error(error.response?.data?.detail || 'Failed to load product demand analysis.');
        }
    },

    getV2Inbound: async (days: number = 30) => {
        const response = await api.get(`/api/v1/dashboard/v2/inbound?days=${days}`);
        return response.data;
    },
    getV2Outbound: async (days: number = 30) => {
        const response = await api.get(`/api/v1/dashboard/v2/outbound?days=${days}`);
        return response.data;
    },
    getV2FailedInvoicesAnalysis: async (days: number = 30, demo?: boolean) => {
        let url = `/api/v1/dashboard/v2/failed-invoices-analysis?days=${days}`;
        if (demo) url += '&demo=1';
        const response = await api.get(url);
        return response.data;
    },
    getV2FailedInvoicesAiInsights: async (days: number = 30, demo?: boolean) => {
        let url = `/api/v1/dashboard/v2/failed-invoices-ai-insights?days=${days}`;
        if (demo) url += '&demo=1';
        const response = await api.get(url);
        return response.data;
    },
    getV2Business: async (days: number = 90, currency?: string | null) => {
        let url = `/api/v1/dashboard/v2/business?days=${days}`;
        if (currency && currency !== '') {
            url += `&currency=${encodeURIComponent(currency)}`;
        }
        const response = await api.get(url);
        return response.data;
    },
    getSAPHistorical: async () => {
        const response = await api.get('/api/v1/dashboard/v2/sap-historical');
        return response.data;
    },
    getV2CustomerComparison: async (days: number = 90, currency?: string | null) => {
        let url = `/api/v1/dashboard/v2/customer-comparison?days=${days}`;
        if (currency && currency !== '') {
            url += `&currency=${encodeURIComponent(currency)}`;
        }
        const response = await api.get(url);
        return response.data;
    },
    postCustomerComparisonChat: async (message: string, customerA: object, customerB: object, conversationHistory: { role: string; content: string }[] = []) => {
        const response = await api.post('/api/v1/dashboard/v2/customer-comparison-chat', {
            message,
            customer_a: customerA,
            customer_b: customerB,
            conversation_history: conversationHistory,
        });
        return response.data;
    },
    postAIAnalysisChat: async (
        message: string,
        conversationHistory: { role: string; content: string }[] = [],
        contextKeys: string[] = [],
        days: number = 30,
        timeScope?: 'current' | 'historical' | 'both'
    ) => {
        try {
            const response = await api.post('/api/v1/dashboard/ai-analysis/chat', {
                message,
                conversation_history: conversationHistory,
                context_keys: contextKeys,
                time_scope: timeScope || 'current',
                days: Math.max(1, Math.min(365, days)),
            });
            return response.data;
        } catch (error: any) {
            console.error('AI analysis chat failed:', error);
            if (error.response?.status === 401) {
                throw new Error('Session expired. Please log in again.');
            }
            throw new Error(error.response?.data?.detail || 'Failed to get AI analysis response.');
        }
    },

    postAIAnalysisMultiModel: async (
        message: string,
        contextKeys: string[] = [],
        days: number = 30,
        timeScope?: 'current' | 'historical' | 'both'
    ) => {
        try {
            const response = await api.post('/api/v1/dashboard/ai-analysis-multi-model', null, {
                params: {
                    message,
                    context_keys: contextKeys,
                    days: Math.max(1, Math.min(365, days)),
                    time_scope: timeScope || 'current',
                },
            });
            return response.data;
        } catch (error: any) {
            console.error('Multi-model AI analysis failed:', error);
            if (error.response?.status === 401) {
                throw new Error('Session expired. Please log in again.');
            }
            if (error.response?.status === 400) {
                throw new Error(error.response?.data?.detail || 'Multi-model mode is not enabled.');
            }
            throw new Error(error.response?.data?.detail || 'Failed to get multi-model AI response.');
        }
    },

    postAIAnalysisApproveQuery: async (
        question: string,
        proposedSql: string,
        timeScope: 'current' | 'historical' | 'both' = 'both',
        approvalSource: 'chatgpt' | 'manual' | 'assistant_sql' = 'chatgpt'
    ) => {
        try {
            const response = await api.post('/api/v1/dashboard/ai-analysis/approve-query', {
                question,
                proposed_sql: proposedSql,
                time_scope: timeScope,
                approval_source: approvalSource,
            });
            return response.data;
        } catch (error: any) {
            console.error('AI approve query failed:', error);
            const detail = error.response?.data?.detail;
            const msg = typeof detail === 'string' ? detail
                : Array.isArray(detail) ? detail.map((d: any) => d?.msg ?? d).join('; ')
                : 'Failed to approve and run query.';
            throw new Error(msg);
        }
    },

    postAIAnalysisStoreQuery: async (
        question: string,
        sqlQuery: string,
        timeScope: 'current' | 'historical' | 'both' = 'both',
        approvalSource: 'assistant_sql' | 'manual' = 'assistant_sql'
    ) => {
        try {
            const response = await api.post('/api/v1/dashboard/ai-analysis/store-query', {
                question,
                sql_query: sqlQuery,
                time_scope: timeScope,
                approval_source: approvalSource,
            });
            return response.data;
        } catch (error: any) {
            console.error('AI store query failed:', error);
            throw new Error(error.response?.data?.detail || 'Failed to store query.');
        }
    },

    getAIAnalysisSchema: async (): Promise<{
        schema: Record<string, { columns: string[]; description: string; source: string }>;
        table_count: number;
    }> => {
        try {
            const response = await api.get('/api/v1/dashboard/ai-analysis/schema');
            return response.data;
        } catch (error: any) {
            console.error('Schema fetch failed:', error);
            return { schema: {}, table_count: 0 };
        }
    },

    postAIAnalysisSuggestSql: async (
        question: string,
        timeScope: 'current' | 'historical' | 'both' = 'both',
        instructions?: string
    ) => {
        try {
            const response = await api.post('/api/v1/dashboard/ai-analysis/suggest-sql', {
                question,
                time_scope: timeScope,
                instructions: instructions ?? '',
            });
            return response.data;
        } catch (error: any) {
            console.error('AI suggest SQL failed:', error);
            throw new Error(error.response?.data?.detail || 'Failed to get SQL suggestion.');
        }
    },

    postAIAnalysisRejectQuery: async (
        question: string,
        rejectedSql: string,
        timeScope: 'current' | 'historical' | 'both' = 'both',
        attemptSource: 'chatgpt' | 'manual' | 'assistant_sql' = 'assistant_sql',
        feedbackReason: string = 'rejected_by_user'
    ) => {
        try {
            const response = await api.post('/api/v1/dashboard/ai-analysis/reject-query', {
                question,
                rejected_sql: rejectedSql,
                time_scope: timeScope,
                attempt_source: attemptSource,
                feedback_reason: feedbackReason,
            });
            return response.data;
        } catch (error: any) {
            console.error('AI reject query failed:', error);
            throw new Error(error.response?.data?.detail || 'Failed to record rejected SQL.');
        }
    },
};

// Admin API
export const adminApi = {
    runBackfill: async () => {
        try {
            const response = await api.post('/api/v1/admin/backfill-business-intelligence');
            return response.data;
        } catch (error: any) {
            console.error('Failed to run backfill:', error);
            if (error.response?.status === 401) {
                throw new Error('Session expired. Please log in again.');
            }
            throw new Error(error.response?.data?.detail || 'Failed to start backfill process.');
        }
    },
    
    getBackfillStatus: async () => {
        try {
            const response = await api.get('/api/v1/admin/backfill-status');
            return response.data;
        } catch (error: any) {
            console.error('Failed to get backfill status:', error);
            if (error.response?.status === 401) {
                throw new Error('Session expired. Please log in again.');
            }
            throw new Error(error.response?.data?.detail || 'Failed to get backfill status.');
        }
    },
};

// SAT Documents API
export const satApi = {
    // Intake a CFDI document
    intake: async (xmlContent: string) => {
        try {
            const response = await api.post('/api/v1/sat/intake', {
                xml_content: xmlContent
            });
            return response.data;
        } catch (error: any) {
            console.error('Failed to intake CFDI:', error);
            throw new Error(error.response?.data?.detail || 'Failed to process CFDI document.');
        }
    },

    // List SAT documents
    list: async (
        fiscal_year?: number,
        fiscal_period?: number,
        doc_type?: string,
        status?: string,
        skip: number = 0,
        limit: number = 100
    ) => {
        try {
            const params: any = { skip, limit };
            if (fiscal_year) params.fiscal_year = fiscal_year;
            if (fiscal_period) params.fiscal_period = fiscal_period;
            if (doc_type) params.doc_type = doc_type;
            if (status) params.status_filter = status;

            const response = await api.get('/api/v1/sat/documents', { params });
            return response.data;
        } catch (error: any) {
            console.error('Failed to list SAT documents:', error);
            throw new Error(error.response?.data?.detail || 'Failed to fetch SAT documents.');
        }
    },

    listDocumentsForCustomerUser: async (params?: {
        fiscal_year?: number;
        fiscal_period?: number;
        doc_type?: string;
        status_filter?: string;
        skip?: number;
        limit?: number;
    }) => {
        const response = await api.get('/api/v1/sat/documents/for-customer-user', { params: params || {} });
        return response.data;
    },

    // Get a specific document
    getDocument: async (documentId: string) => {
        try {
            const response = await api.get(`/api/v1/sat/documents/${documentId}`);
            return response.data;
        } catch (error: any) {
            console.error('Failed to get SAT document:', error);
            throw new Error(error.response?.data?.detail || 'Failed to fetch document.');
        }
    },

    // Get document XML
    getDocumentXml: async (documentId: string) => {
        try {
            const response = await api.get(`/api/v1/sat/documents/${documentId}/xml`, {
                responseType: 'blob'
            });
            return response.data;
        } catch (error: any) {
            console.error('Failed to get document XML:', error);
            throw new Error(error.response?.data?.detail || 'Failed to fetch XML.');
        }
    },

    // Upload multiple files (admin upload)
    uploadFiles: async (files: FileList) => {
        try {
            const formData = new FormData();
            for (let i = 0; i < files.length; i++) {
                formData.append('files', files[i]);
            }

            const response = await api.post('/api/v1/sat/upload-files', formData, {
                headers: {
                    'Content-Type': 'multipart/form-data',
                },
            });
            return response.data;
        } catch (error: any) {
            console.error('Failed to upload files:', error);
            throw new Error(error.response?.data?.detail || 'Failed to upload files.');
        }
    },

    // Delete a document
    deleteDocument: async (documentId: string) => {
        try {
            const response = await api.delete(`/api/v1/sat/documents/${documentId}`);
            return response.data;
        } catch (error: any) {
            console.error('Failed to delete SAT document:', error);
            throw new Error(error.response?.data?.detail || 'Failed to delete document.');
        }
    },
};

// SAT Simple Merge API
export const satSimpleMergeApi = {
    // Merge documents and save to database
    merge: async (params: {
        fiscal_year: number;
        fiscal_period: number;
        supplier_rfc: string;
    }) => {
        try {
            const response = await api.post('/api/v1/sat/simple-merge/merge', params);
            return response.data;
        } catch (error: any) {
            console.error('Failed to merge documents:', error);
            throw new Error(error.response?.data?.detail || 'Failed to merge documents.');
        }
    },

    // List simple merged documents
    list: async (
        fiscal_year?: number,
        fiscal_period?: number,
        skip: number = 0,
        limit: number = 100
    ) => {
        try {
            const params: any = { skip, limit };
            if (fiscal_year) params.fiscal_year = fiscal_year;
            if (fiscal_period) params.fiscal_period = fiscal_period;

            const response = await api.get('/api/v1/sat/simple-merge/', { params });
            return response.data;
        } catch (error: any) {
            console.error('Failed to fetch simple merged documents:', error);
            throw new Error(error.response?.data?.detail || 'Failed to fetch simple merged documents.');
        }
    },

    // Get simple merged document by ID
    get: async (mergedId: string) => {
        try {
            const response = await api.get(`/api/v1/sat/simple-merge/${mergedId}`);
            return response.data;
        } catch (error: any) {
            console.error('Failed to get simple merged document:', error);
            throw new Error(error.response?.data?.detail || 'Failed to fetch merged document.');
        }
    },

    // Download merged XML
    download: async (mergedId: string): Promise<Blob> => {
        try {
            const response = await api.get(`/api/v1/sat/simple-merge/${mergedId}/download`, {
                responseType: 'blob'
            });
            return response.data;
        } catch (error: any) {
            console.error('Failed to download merged XML:', error);
            throw new Error(error.response?.data?.detail || 'Failed to download XML.');
        }
    },

    // Preview SAP JSON
    previewSapJson: async (mergedId: string) => {
        try {
            const response = await api.get(`/api/v1/sat/simple-merge/${mergedId}/preview-sap-json`);
            return response.data;
        } catch (error: any) {
            console.error('Failed to preview SAP JSON:', error);
            throw new Error(error.response?.data?.detail || 'Failed to generate SAP JSON preview.');
        }
    },

    // Fetch CSRF token from SAP
    fetchCsrfToken: async (mergedId: string) => {
        try {
            const response = await api.post(`/api/v1/sat/simple-merge/${mergedId}/fetch-csrf-token`);
            return response.data;
        } catch (error: any) {
            console.error('Failed to fetch CSRF token:', error);
            throw new Error(error.response?.data?.detail || 'Failed to fetch CSRF token from SAP.');
        }
    },

    // Send to SAP with CSRF token
    sendToSAP: async (mergedId: string, csrfToken: string) => {
        try {
            const response = await api.post(`/api/v1/sat/simple-merge/${mergedId}/send-to-sap`, {
                csrf_token: csrfToken
            });
            return response.data;
        } catch (error: any) {
            console.error('Failed to send to SAP:', error);
            throw new Error(error.response?.data?.detail || 'Failed to send to SAP.');
        }
    },

    // Delete simple merged document
    delete: async (mergedId: string) => {
        try {
            const response = await api.delete(`/api/v1/sat/simple-merge/${mergedId}`);
            return response.data;
        } catch (error: any) {
            console.error('Failed to delete merged document:', error);
            throw new Error(error.response?.data?.detail || 'Failed to delete merged document.');
        }
    },

    // Check merge requirements for RFC group
    checkMergeRequirements: async (
        supplier_rfc: string,
        fiscal_year: number,
        fiscal_period: number
    ) => {
        try {
            const response = await api.get(
                `/api/v1/sat/simple-merge/check-merge-requirements/${supplier_rfc}`,
                { params: { fiscal_year, fiscal_period } }
            );
            return response.data;
        } catch (error: any) {
            console.error('Failed to check merge requirements:', error);
            throw new Error(error.response?.data?.detail || 'Failed to check requirements.');
        }
    },
};

// SAT Canonical Merged API
export const satCanonicalApi = {
    // Merge documents
    merge: async (params: {
        company_code: string;
        fiscal_year: number;
        fiscal_period: number;
    }) => {
        try {
            const response = await api.post('/api/v1/sat/canonical/merge', params);
            return response.data;
        } catch (error: any) {
            console.error('Failed to merge documents:', error);
            throw new Error(error.response?.data?.detail || 'Failed to merge to canonical format.');
        }
    },

    // List canonical documents
    list: async (
        fiscal_year?: number,
        fiscal_period?: number,
        skip: number = 0,
        limit: number = 100
    ) => {
        try {
            const params: any = { skip, limit };
            if (fiscal_year) params.fiscal_year = fiscal_year;
            if (fiscal_period) params.fiscal_period = fiscal_period;

            const response = await api.get('/api/v1/sat/canonical', { params });
            return response.data;
        } catch (error: any) {
            console.error('Failed to fetch canonical documents:', error);
            throw new Error(error.response?.data?.detail || 'Failed to fetch canonical documents.');
        }
    },

    // Get canonical document by ID
    get: async (canonicalId: string) => {
        try {
            const response = await api.get(`/api/v1/sat/canonical/${canonicalId}`);
            return response.data;
        } catch (error: any) {
            console.error('Failed to get canonical document:', error);
            throw new Error(error.response?.data?.detail || 'Failed to fetch canonical document.');
        }
    },

    // Preview SAP JSON
    preview: async (canonicalId: string) => {
        try {
            const response = await api.get(`/api/v1/sat/canonical/${canonicalId}/preview-sap-json`);
            return response.data;
        } catch (error: any) {
            console.error('Failed to get preview:', error);
            throw new Error(error.response?.data?.detail || 'Failed to generate preview.');
        }
    },

    // Send to SAP
    sendToSAP: async (canonicalId: string) => {
        try {
            const response = await api.post(`/api/v1/sat/canonical/${canonicalId}/send-to-sap`);
            return response.data;
        } catch (error: any) {
            console.error('Failed to send to SAP:', error);
            throw new Error(error.response?.data?.detail || 'Failed to send to SAP.');
        }
    },

    // Send all documents to SAP (both canonical and simple merge)
    sendAllToSAP: async (params: { fiscal_year: number; fiscal_period: number }) => {
        try {
            const response = await api.post('/api/v1/sat/send-all-to-sap', params);
            return response.data;
        } catch (error: any) {
            console.error('Failed to send all to SAP:', error);
            throw new Error(error.response?.data?.detail || 'Failed to send all documents to SAP.');
        }
    },

    // Download canonical merged XML
    downloadXml: async (canonicalId: string): Promise<Blob> => {
        try {
            const response = await api.get(`/api/v1/sat/canonical/${canonicalId}/download-xml`, {
                responseType: 'blob'
            });
            return response.data;
        } catch (error: any) {
            console.error('Failed to download canonical XML:', error);
            throw new Error(error.response?.data?.detail || 'Failed to download XML.');
        }
    },
};

// Supplier Tokens API
export const supplierTokensApi = {
    // Generate new supplier token
    generate: async (data: { supplier_rfc: string; supplier_name: string; expires_in_days?: number; notes?: string }) => {
        try {
            const response = await api.post('/api/v1/supplier-tokens/generate', data);
            return response.data;
        } catch (error: any) {
            console.error('Failed to generate supplier token:', error);
            throw new Error(error.response?.data?.detail || 'Failed to generate supplier token.');
        }
    },

    // List all supplier tokens
    list: async (skip: number = 0, limit: number = 100, active_only: boolean = false) => {
        try {
            const response = await api.get('/api/v1/supplier-tokens/list', {
                params: { skip, limit, active_only }
            });
            return response.data;
        } catch (error: any) {
            console.error('Failed to fetch supplier tokens:', error);
            throw new Error(error.response?.data?.detail || 'Failed to fetch supplier tokens.');
        }
    },

    // Revoke token
    revoke: async (tokenId: number) => {
        try {
            const response = await api.delete(`/api/v1/supplier-tokens/${tokenId}`);
            return response.data;
        } catch (error: any) {
            console.error('Failed to revoke supplier token:', error);
            throw new Error(error.response?.data?.detail || 'Failed to revoke supplier token.');
        }
    },

    // Refresh token
    refresh: async (tokenId: number) => {
        try {
            const response = await api.post(`/api/v1/supplier-tokens/${tokenId}/refresh`);
            return response.data;
        } catch (error: any) {
            console.error('Failed to refresh supplier token:', error);
            throw new Error(error.response?.data?.detail || 'Failed to refresh supplier token.');
        }
    },

    // Get stats
    getStats: async () => {
        try {
            const response = await api.get('/api/v1/supplier-tokens/stats');
            return response.data;
        } catch (error: any) {
            console.error('Failed to get supplier token stats:', error);
            throw new Error(error.response?.data?.detail || 'Failed to get statistics.');
        }
    },
};

// SAT Supplier Mapping API
export const satSupplierMappingApi = {
    // Upload Excel mapping
    uploadExcel: async (file: File) => {
        try {
            const formData = new FormData();
            formData.append('file', file);

            const response = await api.post('/api/v1/sat/supplier-mapping/upload-excel', formData, {
                headers: {
                    'Content-Type': 'multipart/form-data',
                },
            });
            return response.data;
        } catch (error: any) {
            console.error('Failed to upload Excel:', error);
            throw new Error(error.response?.data?.detail || 'Failed to upload Excel file.');
        }
    },

    // List mappings
    list: async (active_only: boolean = false, skip: number = 0, limit: number = 100) => {
        try {
            const response = await api.get('/api/v1/sat/supplier-mapping/list', {
                params: { active_only, skip, limit }
            });
            return response.data;
        } catch (error: any) {
            console.error('Failed to list mappings:', error);
            throw new Error(error.response?.data?.detail || 'Failed to fetch mappings.');
        }
    },

    // Lookup mapping
    lookup: async (supplierRfc: string) => {
        try {
            const response = await api.get(`/api/v1/sat/supplier-mapping/lookup/${supplierRfc}`);
            return response.data;
        } catch (error: any) {
            console.error('Failed to lookup mapping:', error);
            throw new Error(error.response?.data?.detail || 'Failed to lookup mapping.');
        }
    },

    // Delete mapping
    delete: async (mappingId: number) => {
        try {
            const response = await api.delete(`/api/v1/sat/supplier-mapping/${mappingId}`);
            return response.data;
        } catch (error: any) {
            console.error('Failed to delete mapping:', error);
            throw new Error(error.response?.data?.detail || 'Failed to delete mapping.');
        }
    },

    // Get stats
    getStats: async () => {
        try {
            const response = await api.get('/api/v1/sat/supplier-mapping/stats/summary');
            return response.data;
        } catch (error: any) {
            console.error('Failed to get stats:', error);
            throw new Error(error.response?.data?.detail || 'Failed to fetch stats.');
        }
    },
};

// Invoices V2 API
export const invoicesV2Api = {
    // Documents endpoints
    uploadManual: async (formData: FormData) => {
        try {
            const response = await api.post('/api/v1/invoices-v2/upload', formData, {
                headers: { 'Content-Type': 'multipart/form-data' }
            });
            return response.data;
        } catch (error: any) {
            console.error('Failed to upload invoice:', error);
            throw new Error(error.response?.data?.detail || 'Failed to upload invoice.');
        }
    },

    getDocuments: async (source?: string, status?: string, includeDeleted: boolean = false) => {
        try {
            const response = await api.get('/api/v1/invoices-v2/documents', {
                params: { source, validation_status: status, include_deleted: includeDeleted }
            });
            return response;
        } catch (error: any) {
            console.error('Failed to get documents:', error);
            throw new Error(error.response?.data?.detail || 'Failed to fetch documents.');
        }
    },

    getDocumentsForCustomerUser: async (params?: { skip?: number; limit?: number }) => {
        const response = await api.get('/api/v1/invoices-v2/documents/for-customer-user', { params: params || {} });
        return response.data;
    },

    deleteDocument: async (documentId: number) => {
        try {
            const response = await api.delete(`/api/v1/invoices-v2/documents/${documentId}`);
            return response.data;
        } catch (error: any) {
            console.error('Failed to delete document:', error);
            throw new Error(error.response?.data?.detail || 'Failed to delete document.');
        }
    },

    getDocumentInfo: async (documentId: number) => {
        try {
            const response = await api.get(`/api/v1/invoices-v2/documents/${documentId}/info`);
            return response.data;
        } catch (error: any) {
            console.error('Failed to get document info:', error);
            throw new Error(error.response?.data?.detail || 'Failed to get document info.');
        }
    },

    downloadDocument: async (documentId: number, filename: string) => {
        try {
            const response = await api.get(`/api/v1/invoices-v2/documents/${documentId}/download`, {
                responseType: 'blob'
            });
            
            // Check if response is actually an error (JSON blob)
            if (response.data.type === 'application/json') {
                // Read the JSON error from blob
                const text = await response.data.text();
                const errorData = JSON.parse(text);
                throw new Error(errorData.detail || 'Failed to download document');
            }
            
            // Create a download link
            const url = window.URL.createObjectURL(new Blob([response.data]));
            const link = document.createElement('a');
            link.href = url;
            link.setAttribute('download', filename);
            document.body.appendChild(link);
            link.click();
            link.remove();
            window.URL.revokeObjectURL(url);
        } catch (error: any) {
            console.error('Failed to download document:', error);
            // Try to extract error detail from blob if available
            if (error.response?.data instanceof Blob) {
                try {
                    const text = await error.response.data.text();
                    const errorData = JSON.parse(text);
                    throw new Error(errorData.detail || 'Failed to download document.');
                } catch (e) {
                    throw new Error('Failed to download document.');
                }
            }
            throw new Error(error.message || error.response?.data?.detail || 'Failed to download document.');
        }
    },

    // Validation endpoints
    getUnvalidated: async () => {
        try {
            const response = await api.get('/api/v1/invoices-v2/unvalidated');
            return response.data;
        } catch (error: any) {
            console.error('Failed to get unvalidated invoices:', error);
            throw new Error(error.response?.data?.detail || 'Failed to fetch unvalidated invoices.');
        }
    },

    getUnvalidatedForCustomerUser: async () => {
        try {
            const response = await api.get('/api/v1/invoices-v2/unvalidated/for-customer-user');
            return response.data;
        } catch (error: any) {
            console.error('Failed to get unvalidated invoices for customer user:', error);
            throw new Error(error.response?.data?.detail || 'Failed to fetch unvalidated invoices.');
        }
    },

    validateInvoices: async (documentIds: number[]) => {
        try {
            const response = await api.post('/api/v1/invoices-v2/validate', { document_ids: documentIds });
            return response.data;
        } catch (error: any) {
            console.error('Failed to validate invoices:', error);
            throw new Error(error.response?.data?.detail || 'Failed to validate invoices.');
        }
    },

    getValidationProgress: async (documentIds: number[]) => {
        try {
            const idsStr = documentIds.join(',');
            const response = await api.get('/api/v1/invoices-v2/validation-progress', {
                params: { document_ids: idsStr }
            });
            return response.data;
        } catch (error: any) {
            console.error('Failed to get validation progress:', error);
            throw new Error(error.response?.data?.detail || 'Failed to get validation progress.');
        }
    },

    // Validated invoices endpoints
    getValidated: async (statusFilter?: string, excludeConverted?: boolean) => {
        try {
            const response = await api.get('/api/v1/invoices-v2/validated', {
                params: { 
                    status_filter: statusFilter,
                    exclude_converted: excludeConverted
                }
            });
            return response.data;
        } catch (error: any) {
            console.error('Failed to get validated invoices:', error);
            throw new Error(error.response?.data?.detail || 'Failed to fetch validated invoices.');
        }
    },

    getValidatedForCustomerUser: async (params?: { status_filter?: string; skip?: number; limit?: number }) => {
        const response = await api.get('/api/v1/invoices-v2/for-customer-user', { params: params || {} });
        return response.data;
    },

    getValidatedDetails: async (validatedId: number) => {
        try {
            const response = await api.get(`/api/v1/invoices-v2/validated/${validatedId}`);
            return response.data;
        } catch (error: any) {
            console.error('Failed to get validated invoice details:', error);
            throw new Error(error.response?.data?.detail || 'Failed to fetch invoice details.');
        }
    },

    manualFix: async (validatedId: number, corrections: Record<string, any>) => {
        try {
            console.log('📝 Sending corrections to backend:', corrections);
            const response = await api.put(`/api/v1/invoices-v2/validated/${validatedId}/manual-fix`, {
                corrections
            });
            console.log('✅ Backend response:', response.data);
            return response.data;
        } catch (error: any) {
            console.error('Failed to apply manual fix:', error);
            throw new Error(error.response?.data?.detail || 'Failed to apply manual fix.');
        }
    },

    // Simple update for successful invoices (no validation, just direct update)
    updateSuccessfulInvoice: async (validatedId: number, updates: Record<string, any>) => {
        try {
            console.log('💾 Updating successful invoice:', validatedId, updates);
            const response = await api.put(`/api/v1/invoices-v2/validated/${validatedId}/update-successful`, updates);
            console.log('✅ Update response:', response.data);
            return response.data;
        } catch (error: any) {
            console.error('Failed to update successful invoice:', error);
            throw new Error(error.response?.data?.detail || 'Failed to update invoice.');
        }
    },

    aiFix: async (validatedId: number) => {
        try {
            const response = await api.post(`/api/v1/invoices-v2/validated/${validatedId}/ai-fix`);
            return response.data;
        } catch (error: any) {
            console.error('Failed to apply AI fix:', error);
            throw new Error(error.response?.data?.detail || 'Failed to apply AI fix.');
        }
    },

    reprocessInvoice: async (validatedId: number) => {
        try {
            const response = await api.post(`/api/v1/invoices-v2/validated/${validatedId}/reprocess`);
            return response.data;
        } catch (error: any) {
            console.error('Failed to reprocess invoice:', error);
            throw new Error(error.response?.data?.detail || 'Failed to reprocess invoice.');
        }
    },
};

/**
 * Converted Invoices API (V2 Conversion System)
 */
export const convertedInvoicesApi = {
    // Convert successful invoices to customer-specific formats
    convertInvoices: async (validatedInvoiceIds: number[]) => {
        try {
            const response = await api.post('/api/v1/converted-invoices/convert', {
                validated_invoice_ids: validatedInvoiceIds
            });
            return response.data;
        } catch (error: any) {
            console.error('Failed to convert invoices:', error);
            throw new Error(error.response?.data?.detail || 'Failed to convert invoices.');
        }
    },

    // Override validation mismatch and force conversion
    overrideValidation: async (validatedInvoiceId: number, updateCustomerFields: boolean = false) => {
        try {
            const response = await api.post(`/api/v1/converted-invoices/${validatedInvoiceId}/override`, {
                update_customer_fields: updateCustomerFields
            });
            return response.data;
        } catch (error: any) {
            console.error('Failed to override validation:', error);
            throw new Error(error.response?.data?.detail || 'Failed to override validation.');
        }
    },

    // List all converted invoices
    getConverted: async (skip: number = 0, limit: number = 100, statusFilter?: string) => {
        try {
            const params: any = { skip, limit };
            if (statusFilter) {
                params.status_filter = statusFilter;
            }
            const response = await api.get('/api/v1/converted-invoices/list', { params });
            return response.data;
        } catch (error: any) {
            console.error('Failed to get converted invoices:', error);
            throw new Error(error.response?.data?.detail || 'Failed to fetch converted invoices.');
        }
    },

    // List converted invoices for customer user (only assigned customer_ids)
    getConvertedForCustomerUser: async (skip: number = 0, limit: number = 100, statusFilter?: string) => {
        try {
            const params: any = { skip, limit };
            if (statusFilter) {
                params.status_filter = statusFilter;
            }
            const response = await api.get('/api/v1/converted-invoices/list/for-customer-user', { params });
            return response.data;
        } catch (error: any) {
            console.error('Failed to get converted invoices for customer user:', error);
            throw new Error(error.response?.data?.detail || 'Failed to fetch converted invoices.');
        }
    },

    // Download a converted invoice file
    downloadConverted: async (convertedId: number) => {
        try {
            const response = await api.get(`/api/v1/converted-invoices/${convertedId}/download`, {
                responseType: 'blob',
            });

            // Extract filename from Content-Disposition header
            const contentDisposition = response.headers['content-disposition'];
            let filename = `converted_invoice_${convertedId}.bin`;
            if (contentDisposition) {
                const filenameMatch = contentDisposition.match(/filename="?(.+?)"?$/);
                if (filenameMatch) {
                    filename = filenameMatch[1];
                }
            }

            // Create blob and download
            const blob = new Blob([response.data]);
            const url = window.URL.createObjectURL(blob);
            const link = document.createElement('a');
            link.href = url;
            link.download = filename;
            document.body.appendChild(link);
            link.click();
            document.body.removeChild(link);
            window.URL.revokeObjectURL(url);

            return { success: true, filename };
        } catch (error: any) {
            console.error('Failed to download converted invoice:', error);
            throw new Error(error.response?.data?.detail || 'Failed to download converted invoice.');
        }
    },

    // Get converted invoice info (debugging)
    getConvertedInfo: async (convertedId: number) => {
        try {
            const response = await api.get(`/api/v1/converted-invoices/${convertedId}/info`);
            return response.data;
        } catch (error: any) {
            console.error('Failed to get converted invoice info:', error);
            throw new Error(error.response?.data?.detail || 'Failed to get converted invoice info.');
        }
    },

    // Delete a converted invoice
    deleteConverted: async (convertedId: number) => {
        try {
            const response = await api.delete(`/api/v1/converted-invoices/${convertedId}`);
            return response.data;
        } catch (error: any) {
            console.error('Failed to delete converted invoice:', error);
            throw new Error(error.response?.data?.detail || 'Failed to delete converted invoice.');
        }
    },

    // Send converted file to customer SFTP (delivery settings must be configured)
    sendToCustomer: async (convertedId: number): Promise<{ success: boolean; message: string; remote_path?: string }> => {
        try {
            const response = await api.post(`/api/v1/converted-invoices/${convertedId}/send-to-customer`);
            return response.data;
        } catch (error: any) {
            const detail = error.response?.data?.detail;
            throw new Error(typeof detail === 'string' ? detail : 'Failed to send to customer.');
        }
    },
};

export default api;

