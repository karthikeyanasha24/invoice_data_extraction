export interface User {
  id: number;
  email: string;
  username: string;
  is_active: boolean;
  is_verified: boolean;
  is_admin: boolean;
  created_at: string;
  updated_at: string;
}

export interface AuthResponse {
  access_token: string;
  token_type: string;
  user: User;
}

export interface LoginRequest {
  email: string;
  password: string;
}

export interface SignupRequest {
  email: string;
  username: string;
  password: string;
}

export interface ErrorDetail {
  step: string; // e.g., "XML_VALIDATION", "EDI_CONVERSION", "EDI_FORMAT_VALIDATION"
  error_type: string; // e.g., "VALIDATION_ERROR", "FORMAT_ERROR", "DATA_TYPE_ERROR"
  field_name?: string; // Specific field that failed
  error_message: string;
  expected_format?: string;
  actual_value?: string;
  suggestions?: string[];
}

// New comprehensive error information structure matching API
export interface DetailedErrorInfo {
  error_code: string; // e.g., "E2003", "E4010"
  error_category: string; // e.g., "XML_VALIDATION", "EDI_FORMAT_VALIDATION"
  error_message: string; // Technical error message
  severity: string; // "CRITICAL", "ERROR", "WARNING"
  user_message: string; // User-friendly message
  technical_details: string; // Detailed technical explanation
  suggested_actions?: string[];
  file_name?: string;
  timestamp?: number;
  additional_context?: Record<string, any>;
  documentation_links?: string[];
  is_recoverable?: boolean;
  estimated_fix_time?: string;
}

export interface StepStatus {
  file_upload_pass?: boolean;
  file_upload_message?: string;
  xml_validation_pass?: boolean;
  xml_convert_message?: string;
  edi_convert_pass?: boolean;
  edi_convert_message?: string;
}

export interface ProcessingStepResult {
  step_name?: string;
  step_number?: number;
  success?: boolean;
  duration_seconds?: number;
  message?: string;
  status?: StepStatus; // Step-specific status fields
  error_details?: DetailedErrorInfo[]; // Complete error information with all details
  // API response fields (when step itself is an error)
  user_message?: string;
  error_context?: Record<string, any>;
  is_recoverable?: boolean;
  related_errors?: any[];
  suggested_actions?: string[];
  technical_details?: string;
  estimated_fix_time?: string;
  documentation_links?: string[];
}

export interface FileUploadResponse {
  invoice_operation_success: boolean;
  file_upload_pass: boolean;
  file_upload_message?: string;
  xml_validation_pass: boolean;
  xml_convert_message?: string;
  edi_convert_pass: boolean;
  edi_convert_message?: string;
  tracking_id?: string;
  
  // Enhanced error information
  processing_steps?: ProcessingStepResult[];
  error_summary?: {
    total_errors: number;
    failed_step: string;
    error_categories: string[];
    suggested_actions: string[];
  };
  file_content_preview?: string; // First 500 chars of XML file
  suggested_actions?: string[];
  warnings?: string[]; // XML validation warnings
}

export interface InvoiceProcessingResponse {
  tracking_id?: string;
  processing_steps?: ProcessingStepResult[];
}

export interface Invoice {
  id: number | string; // Allow both number and string for generated IDs
  filename: string;
  customerId?: string;
  customerName?: string;
  supplier_id?: string;
  supplier_name?: string;
  invoice_id?: string;
  status?: string;
  accepted: number;
  rejected: number;
  aktId?: string;
  formate?: string;
  destinationCountry?: string;
  export?: boolean;
  country?: string;
  // Error details for failed invoices
  xml_validation_pass?: boolean;
  xml_convert_message?: string;
  edi_convert_pass?: boolean;
  edi_convert_message?: string;
  tracking_id?: string;
  uploaded_at?: string;
  deleted_at?: string;
  warnings?: string[]; // XML validation warnings
  processing_steps?: ProcessingStepResult[]; // Detailed processing step results
  processing_steps_error?: ErrorDetail[]; // Stored detailed error information
  // File paths and storage information
  xml_path?: string;
  edi_path?: string;
  blob_xml_path?: string;
  blob_edi_path?: string;
  use_blob_storage?: boolean;
  xml_content?: string;
  edi_content?: string;
  external_status?: string;
  external_message?: string;
  target_file_format?: string;
}

export interface FailedInvoiceDetails {
  id: number;
  tracking_id: string;
  user_id: number;
  uploaded_at: string;
  xml_path: string;
  xml_validation_pass: boolean;
  xml_convert_message?: string;
  xml_content?: string;
  edi_path?: string;
  edi_convert_pass: boolean;
  edi_convert_message?: string;
  edi_content?: string;
  
  // Enhanced error information
  processing_steps?: ProcessingStepResult[];
  processing_steps_error?: ErrorDetail[]; // Stored detailed error information
  error_summary?: {
    total_errors: number;
    failed_step: string;
    error_categories: string[];
    suggested_actions: string[];
  };
  file_content_preview?: string;
  suggested_actions?: string[];
  warnings?: string[]; // XML validation warnings
  // File paths and storage information
  
  blob_xml_path?: string;
  blob_edi_path?: string;
  use_blob_storage?: boolean;
}

export interface LLMMessage {
  id: string;
  role: 'user' | 'assistant';
  content: string;
  timestamp: Date;
}

export interface LLMConversation {
  id: string;
  invoiceId: string;
  messages: LLMMessage[];
  createdAt: Date;
  updatedAt: Date;
}

export interface ApiKeyInfo {
  has_key: boolean;
  is_active?: boolean;
  api_user_identifier?: string;
  created_at?: string;
  updated_at?: string;
  allow_list?: string[];
  message: string;
}

export interface ApiKeyResponse {
  success: boolean;
  api_key: string;
  api_user_identifier: string;
  created_at?: string;
  updated_at?: string;
  message: string;
}

// === VERSION CONTROL TYPES ===
export interface DiffLine {
  line_number: number;
  original_text: string;
  fixed_text: string;
  change_type: 'added' | 'removed' | 'modified' | 'unchanged';
  is_modified: boolean;
}

export interface VersionComparison {
  file_type: string;
  original_content: string;
  fixed_content: string;
  diffs: DiffLine[];
  total_lines: number;
  modified_line_count: number;
  is_ai_corrected: boolean;
  correction_method?: string;
}

export interface FileEditorRequest {
  tracking_id: string;
  file_type: string;
  content: string;
  is_success_invoice: boolean;
}

export interface FileEditorResponse {
  status: string;
  message: string;
  tracking_id: string;
  file_type: string;
  content_length: number;
  line_count: number;
}

// Dashboard Types
export interface DashboardOverview {
  total: number;
  successful: number;
  failed: number;
  success_rate: number;
}

export interface TimelineDataPoint {
  date: string;
  successful: number;
  failed: number;
  total: number;
}

export interface FormatDistribution {
  format: string;
  count: number;
}

export interface CustomerDistribution {
  customer: string;
  successful: number;
  failed: number;
  total: number;
}

export interface RequestTypeDistribution {
  type: string;
  count: number;
}

export interface RecentActivity {
  id: number;
  tracking_id: string;
  status: string;
  format: string;
  uploaded_at: string;
  request_type: string;
}

export interface DashboardStatistics {
  overview: DashboardOverview;
  timeline: TimelineDataPoint[];
  format_distribution: FormatDistribution[];
  customer_distribution: CustomerDistribution[];
  request_type_distribution: RequestTypeDistribution[];
  recent_activity: RecentActivity[];
  date_range: {
    start: string;
    end: string;
    days: number;
  };
}

export interface ErrorPattern {
  code: string;
  count: number;
  percentage: number;
}

export interface AIInsights {
  summary: string;
  insights: string[];
  recommendations: string[];
  root_causes?: string[];
  error_patterns: ErrorPattern[];
  total_failed: number;
  analyzed_at: string;
}