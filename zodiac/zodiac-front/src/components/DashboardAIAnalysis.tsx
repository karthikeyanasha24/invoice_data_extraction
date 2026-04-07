'use client';

import { useState, useRef, useEffect } from 'react';
import { dashboardApi } from '@/lib/api';
import {
  Sparkles, Send, ArrowDownToLine, ArrowUpFromLine, TrendingUp,
  GitBranch, RefreshCw, Mic, MicOff,
  Activity, BarChart3, Clock, Zap, AlertTriangle, CheckCircle2,
  ArrowUpRight, ArrowDownRight, Minus, CalendarRange, Eye,
  FlaskConical, TrendingDown, DollarSign,
  MessageCircle, Database, Table2, TableProperties, ChevronRight, Bot, User as UserIcon,
} from 'lucide-react';
import AIChartRenderer from './ai/AIChartRenderer';
import { useVoiceRecording } from '../hooks/useVoiceRecording';
import { useAuth } from '@/contexts/AuthContext';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';

/* ─── Constants ──────────────────────────────────────────────── */

const DEFAULT_DAYS = 30;

/** Always set when schema-chat returns thread_id (even if user-specific key not ready yet). */
const SCHEMA_CHAT_THREAD_PENDING_LS = 'zodiac_schema_chat_thread_pending';

function readSchemaChatThreadIdFromStorage(userKey: string | null): string | null {
  if (typeof window === 'undefined') return null;
  if (userKey) {
    const v = localStorage.getItem(userKey);
    if (v?.startsWith('sch_')) return v;
  }
  const p = localStorage.getItem(SCHEMA_CHAT_THREAD_PENDING_LS);
  return p?.startsWith('sch_') ? p : null;
}

function writeSchemaChatThreadIdToStorage(userKey: string | null, threadId: string) {
  if (typeof window === 'undefined' || !threadId.startsWith('sch_')) return;
  localStorage.setItem(SCHEMA_CHAT_THREAD_PENDING_LS, threadId);
  if (userKey) localStorage.setItem(userKey, threadId);
}

function clearSchemaChatThreadFromStorage(userKey: string | null) {
  if (typeof window === 'undefined') return;
  localStorage.removeItem(SCHEMA_CHAT_THREAD_PENDING_LS);
  if (userKey) localStorage.removeItem(userKey);
}

const AI_CONTEXT_KEYS = [
  'stats', 'failed_summary', 'top_customers',
  'inbound_summary', 'business_summary', 'process_flow',
];

const REALTIME_PROMPTS = [
  { label: 'Failed invoices', query: 'Summarize failed invoices and main failure reasons' },
  { label: 'Inbound SAT', query: 'Summarize inbound SAT documents: merges, sent to SAP vs pending, and top suppliers' },
  { label: 'Top customers', query: 'Show top customers with currency and number of invoices (outbound process)' },
  { label: 'Outbound flow', query: 'Show the outbound process flow and current document counts at each step' },
  { label: 'EDI status', query: 'Which EDI invoices failed vs succeeded for each customer? Show counts and error summary.' },
  { label: 'Conversion rate', query: 'What is the invoice conversion success rate, and which step has the most failures?' },
  { label: 'Open orders', query: 'Show open purchase requisitions (EBAN) and purchase orders that are still pending' },
  { label: 'Delivery status', query: 'Show recent delivery header and item status for current shipments from LIKP and LIPS tables' },
];

const HISTORICAL_PROMPTS = [
  { label: 'Profit margin', query: 'Show profit margin by product for all products in the database' },
  { label: 'Revenue trend', query: 'Summarize revenue by customer and by country with trend analysis' },
  { label: 'Revenue by country', query: 'Show total revenue grouped by country with invoice count and average order value' },
  { label: 'Flow deviation', query: 'How does my current document flow deviate from the standard process?' },
  { label: 'Period forecast', query: 'Based on historical patterns, forecast next period revenue and invoice volume' },
  { label: 'Anomaly detection', query: 'Identify any anomalies or unusual patterns in the historical data' },
  { label: 'Top materials', query: 'Show top materials by revenue using billing documents (VBRK joined with vbrp and MARA)' },
  { label: 'Period compare', query: 'Compare revenue and invoice volume between two different historical periods' },
];

/* ─── Domain query examples (adaptive, natural-language) ─── */
// These cover every table domain in the database.
// The AI pipeline classifies each question, picks a route, runs SQL,
// and generates dynamic charts/tables — nothing is hardcoded per question.
const DOMAIN_QUERY_EXAMPLES: { category: string; icon: string; questions: string[] }[] = [
  {
    category: 'Invoices & Billing',
    icon: '🧾',
    questions: [
      'Show invoices for the top customer in the last 30 days',
      'What is the total billed amount for this month?',
      'List invoices that are open or overdue',
      'Which invoices were corrected or re-validated recently?',
      'Compare v1 vs v2 invoice data for recent documents',
    ],
  },
  {
    category: 'Deliveries & Logistics',
    icon: '🚚',
    questions: [
      'Show delivery headers and items (LIKP, LIPS) for recent sales orders',
      'What is the delivery status for the most recent shipments?',
      'Show picking and packing lines for current open deliveries',
      'Which deliveries are blocked or have exceptions?',
    ],
  },
  {
    category: 'Sales Orders',
    icon: '📋',
    questions: [
      'Show sales order headers and line items (VBAK, VBAP) for recent orders',
      'Which orders are not fully delivered?',
      'Show schedule lines (VBEP) with delivery dates for open orders',
      'What pricing conditions (KONV) apply to the latest orders?',
    ],
  },
  {
    category: 'Purchasing',
    icon: '🛒',
    questions: [
      'Show purchase orders and lines (EKKO, EKPO) for the top vendor',
      'What purchase requisitions (EBAN) are still open?',
      'List goods receipt vs invoice data (RBKP, RSEG) for recent POs',
      'Show vendor info records (EINA, EINE) and purchasing org data',
    ],
  },
  {
    category: 'Master Data',
    icon: '🗂️',
    questions: [
      'Give me customer master and sales org data (KNA1, KNVV) for top customers',
      'What payment terms and bank details do we have for our top customer?',
      'Show material master data (MARA, MARC, MARD) and current stock levels',
      'List vendor company code and purchasing org data (LFA1, LFB1, LFM1)',
    ],
  },
  {
    category: 'Finance / GL',
    icon: '💰',
    questions: [
      'Show general ledger actual line items (FAGLFLEXA) for the current period',
      'What accounting documents (BKPF, BSEG) were posted this month?',
      'Show customer open items and cleared items (BSAD)',
      'Show CO document line items (COEP) for production orders',
    ],
  },
  {
    category: 'Costing & CO-PA',
    icon: '📊',
    questions: [
      'Show cost estimate items (CKIS) and costing run results (CKHS)',
      'What are the cost components for the top product (KEPH, KEKO)?',
      'Show CO-PA actual line items and compare with plan',
      'Show material ledger prices and period data (CKMLPR, CKMLPP)',
    ],
  },
  {
    category: 'Zodiac / EDI',
    icon: '⚡',
    questions: [
      'Which EDI invoices failed vs succeeded for each customer?',
      'Show converted invoices and their business field details',
      'What is in the AI query memory and training data for this workflow?',
      'Show SAT canonical merged documents and supplier mappings',
    ],
  },
  {
    category: 'Cross-cutting',
    icon: '🔗',
    questions: [
      'Summarize everything we know about a recent order: header, lines, delivery, billing',
      'Find duplicate or near-duplicate documents using SAT duplicate checks',
      'Show canonical supplier and customer mappings from SAT tables',
      'Give a full picture of the top customer: orders, deliveries, invoices, and payments',
    ],
  },
];

/* ─── SAP Tables catalogue ────────────────────────────────── */
const SAP_TABLES: { name: string; desc: string; category: string }[] = [
  // ── Sales & Billing ──────────────────────────────────────────
  { name: 'VBRK',                      desc: 'Billing Document Header',              category: 'Sales' },
  { name: 'vbrp',                      desc: 'Billing Document Items',               category: 'Sales' },
  { name: 'VBAK',                      desc: 'Sales Order Header',                   category: 'Sales' },
  { name: 'VBAP',                      desc: 'Sales Order Items',                    category: 'Sales' },
  { name: 'VBEP',                      desc: 'Sales Order Schedule Lines',           category: 'Sales' },
  { name: 'VBFA',                      desc: 'Document Flow (Sales)',                category: 'Sales' },
  { name: 'KONV',                      desc: 'Pricing Conditions',                   category: 'Sales' },
  { name: 'MVKE',                      desc: 'Material Sales Data',                  category: 'Sales' },
  // ── Delivery & Logistics ─────────────────────────────────────
  { name: 'LIKP',                      desc: 'Delivery Header',                      category: 'Logistics' },
  { name: 'LIPS',                      desc: 'Delivery Items',                       category: 'Logistics' },
  { name: 'LSEG',                      desc: 'Delivery Segment',                     category: 'Logistics' },
  // ── Customer ─────────────────────────────────────────────────
  { name: 'KNA1',                      desc: 'Customer Master General',              category: 'Customer' },
  { name: 'KNVV',                      desc: 'Customer Sales Data',                  category: 'Customer' },
  { name: 'KNVP',                      desc: 'Customer Partner Functions',           category: 'Customer' },
  { name: 'KNBK',                      desc: 'Customer Bank Data',                   category: 'Customer' },
  // ── Vendor ───────────────────────────────────────────────────
  { name: 'LFA1',                      desc: 'Vendor Master General',                category: 'Vendor' },
  { name: 'LFB1',                      desc: 'Vendor Company Data',                  category: 'Vendor' },
  { name: 'LFM1',                      desc: 'Vendor Purchasing Data',               category: 'Vendor' },
  // ── Purchasing ───────────────────────────────────────────────
  { name: 'EKKO',                      desc: 'Purchase Order Header',                category: 'Purchasing' },
  { name: 'EKPO',                      desc: 'Purchase Order Items',                 category: 'Purchasing' },
  { name: 'EBAN',                      desc: 'Purchase Requisition',                 category: 'Purchasing' },
  { name: 'EINA',                      desc: 'Purchasing Info Record General',       category: 'Purchasing' },
  { name: 'EINE',                      desc: 'Purchasing Info Record Org Data',      category: 'Purchasing' },
  { name: 'RBKP',                      desc: 'Invoice Receipt Header (MM-IV)',       category: 'Purchasing' },
  { name: 'RSEG',                      desc: 'Invoice Receipt Line Items',           category: 'Purchasing' },
  { name: 'RESB',                      desc: 'Reservation / Dependent Requirements', category: 'Purchasing' },
  // ── Material ─────────────────────────────────────────────────
  { name: 'MAKT',                      desc: 'Material Descriptions',                category: 'Material' },
  { name: 'MARA',                      desc: 'Material Master General',              category: 'Material' },
  { name: 'MARC',                      desc: 'Material Plant Data',                  category: 'Material' },
  { name: 'MARD',                      desc: 'Storage Location Stock',               category: 'Material' },
  { name: 'MARM',                      desc: 'Material Units of Measure',            category: 'Material' },
  { name: 'MBEW',                      desc: 'Material Valuation',                   category: 'Material' },
  { name: 'MBEWH',                     desc: 'Material Valuation History',           category: 'Material' },
  { name: 'MCHB',                      desc: 'Batch Stocks',                         category: 'Material' },
  { name: 'MEAN',                      desc: 'International Article Numbers (EAN)',  category: 'Material' },
  { name: 'MKPF',                      desc: 'Material Document Header',             category: 'Material' },
  { name: 'MLAN',                      desc: 'Tax Classification for Material',      category: 'Material' },
  { name: 'MSLB',                      desc: 'Special Stocks at Vendor',             category: 'Material' },
  { name: 'STKO',                      desc: 'BOM Header',                           category: 'Material' },
  { name: 'STPO',                      desc: 'BOM Items',                            category: 'Material' },
  { name: 'CABN',                      desc: 'Characteristic Definition',            category: 'Material' },
  { name: 'AUSP',                      desc: 'Characteristic Values',                category: 'Material' },
  { name: 'KLAH',                      desc: 'Class Header',                         category: 'Material' },
  // ── Finance (FI) ────────────────────────────────────────────
  { name: 'BKPF',                      desc: 'Accounting Document Header',           category: 'Finance' },
  { name: 'BSEG',                      desc: 'Accounting Document Segment',          category: 'Finance' },
  { name: 'BSAD',                      desc: 'Customer Open Item (cleared)',         category: 'Finance' },
  { name: 'FAGLFLEXA',                 desc: 'General Ledger Actual Line Items',     category: 'Finance' },
  { name: 'DFKKOP',                    desc: 'FI-CA Document Item',                  category: 'Finance' },
  { name: 'T016T',                     desc: 'Credit Control Area Texts',            category: 'Finance' },
  // ── Controlling (CO) ─────────────────────────────────────────
  { name: 'COEP',                      desc: 'CO Document Line Items (actual)',      category: 'Controlling' },
  { name: 'COSP',                      desc: 'Cost Totals – External Postings',      category: 'Controlling' },
  { name: 'COSS',                      desc: 'Cost Totals – Internal Postings',      category: 'Controlling' },
  { name: 'CEPC',                      desc: 'Profit Center Master Data',            category: 'Controlling' },
  { name: 'CSKS',                      desc: 'Cost Center Master Data',              category: 'Controlling' },
  { name: 'CSKT',                      desc: 'Cost Center Texts',                    category: 'Controlling' },
  { name: 'CRHD',                      desc: 'Work Center / Resource Header',        category: 'Controlling' },
  { name: 'AUFK',                      desc: 'Order Master Data',                    category: 'Controlling' },
  { name: 'AFKO',                      desc: 'Production Order Header',              category: 'Controlling' },
  { name: 'AFPO',                      desc: 'Production Order Item',                category: 'Controlling' },
  // ── Costing (CO-PC) ──────────────────────────────────────────
  { name: 'CKIS',                      desc: 'Cost Estimate Items',                  category: 'Costing' },
  { name: 'CKHS',                      desc: 'Costing Run Header',                   category: 'Costing' },
  { name: 'CKIT',                      desc: 'Costing Item Detail',                  category: 'Costing' },
  { name: 'KEKO',                      desc: 'Product Costing Header',               category: 'Costing' },
  { name: 'KEPH',                      desc: 'Cost Components for Cost Estimate',    category: 'Costing' },
  { name: 'CKMLCR',                    desc: 'Material Ledger: Currency & Qty',      category: 'Costing' },
  { name: 'CKMLHD',                    desc: 'Material Ledger: Header',              category: 'Costing' },
  { name: 'CKMLPP',                    desc: 'Material Ledger: Period Data',         category: 'Costing' },
  { name: 'CKMLPR',                    desc: 'Material Ledger: Prices',              category: 'Costing' },
  { name: 'TCKH1',                     desc: 'Cost Element Hierarchy',               category: 'Costing' },
  { name: 'TCKH2',                     desc: 'Cost Element Hierarchy Nodes',         category: 'Costing' },
  // ── CO-PA (Profitability Analysis) ───────────────────────────
  { name: 'CE1BGIS',                   desc: 'CO-PA Actuals – BGIS',                 category: 'CO-PA' },
  { name: 'CE1IDEA',                   desc: 'CO-PA Actuals – IDEA',                 category: 'CO-PA' },
  { name: 'CE1INT1',                   desc: 'CO-PA Actuals – INT1',                 category: 'CO-PA' },
  { name: 'CE1PR22',                   desc: 'CO-PA Actuals – PR22',                 category: 'CO-PA' },
  { name: 'CE1R300',                   desc: 'CO-PA Actuals – R300',                 category: 'CO-PA' },
  { name: 'CE1S_AL',                   desc: 'CO-PA Actuals – S_AL',                 category: 'CO-PA' },
  { name: 'CE1S_CP',                   desc: 'CO-PA Actuals – S_CP',                 category: 'CO-PA' },
  { name: 'CE1S_GO',                   desc: 'CO-PA Actuals – S_GO',                 category: 'CO-PA' },
  { name: 'CE2BGIS',                   desc: 'CO-PA Plan – BGIS',                    category: 'CO-PA' },
  { name: 'CE2IDEA',                   desc: 'CO-PA Plan – IDEA',                    category: 'CO-PA' },
  { name: 'CE2S_AL',                   desc: 'CO-PA Plan – S_AL',                    category: 'CO-PA' },
  { name: 'CE2S_CP',                   desc: 'CO-PA Plan – S_CP',                    category: 'CO-PA' },
  { name: 'CS2S_GO',                   desc: 'CO-PA Segment – S_GO',                 category: 'CO-PA' },
  // ── Zodiac App ───────────────────────────────────────────────
  { name: 'ai_analysis_memory',        desc: 'AI Analysis Conversation Memory',      category: 'Zodiac' },
  { name: 'ai_query_embeddings',       desc: 'AI Query Vector Embeddings',           category: 'Zodiac' },
  { name: 'ai_query_memory',           desc: 'User-Approved Q→SQL Pairs',            category: 'Zodiac' },
  { name: 'ai_training_data',          desc: 'AI Training Examples',                 category: 'Zodiac' },
  { name: 'converted_invoices',        desc: 'Successfully Converted Invoices',      category: 'Zodiac' },
  { name: 'correction_cache',          desc: 'AI Correction Rule Cache',             category: 'Zodiac' },
  { name: 'customers',                 desc: 'Zodiac Customer Accounts',             category: 'Zodiac' },
  { name: 'invoice_business_data',     desc: 'Invoice Business Metadata',            category: 'Zodiac' },
  { name: 'invoice_v2_business_data',  desc: 'Invoice V2 Business Data',             category: 'Zodiac' },
  { name: 'invoice_v2_correction_cache', desc: 'Invoice V2 Correction Cache',        category: 'Zodiac' },
  { name: 'invoice_v2_documents',      desc: 'Invoice V2 Documents',                 category: 'Zodiac' },
  { name: 'invoice_v2_validated',      desc: 'Invoice V2 Validated Records',         category: 'Zodiac' },
  { name: 'v2_correction_cache',       desc: 'V2 Correction Cache',                  category: 'Zodiac' },
  { name: 'v2_invoice_documents',      desc: 'V2 Invoice Documents',                 category: 'Zodiac' },
  { name: 'v2_validated_invoices',     desc: 'V2 Validated Invoices',                category: 'Zodiac' },
  { name: 'zodiac_customers',          desc: 'Zodiac Customer Records',              category: 'Zodiac' },
  { name: 'zodiac_invoice_failed_edi', desc: 'Failed EDI Invoices',                  category: 'Zodiac' },
  { name: 'zodiac_invoice_success_edi', desc: 'Successful EDI Invoices',             category: 'Zodiac' },
  { name: 'zodiac_users',              desc: 'Zodiac User Accounts',                 category: 'Zodiac' },
  // ── SAT / Certificates ───────────────────────────────────────
  { name: 'sat_canonical_merged',      desc: 'SAT Canonical Merged Documents',       category: 'SAT' },
  { name: 'sat_company_mappings',      desc: 'SAT Company Mappings',                 category: 'SAT' },
  { name: 'sat_documents',             desc: 'SAT Documents',                        category: 'SAT' },
  { name: 'sat_duplicate_checks',      desc: 'SAT Duplicate Detection Log',          category: 'SAT' },
  { name: 'sat_processing_logs',       desc: 'SAT Processing Logs',                  category: 'SAT' },
  { name: 'sat_sap_account_mapping',   desc: 'SAT ↔ SAP Account Mapping',           category: 'SAT' },
  { name: 'sat_simple_merged',         desc: 'SAT Simple Merged Records',            category: 'SAT' },
  { name: 'sat_supplier_account_mapping', desc: 'SAT Supplier Account Mapping',      category: 'SAT' },
  { name: 'certificate_renewal_requests', desc: 'Certificate Renewal Requests',      category: 'SAT' },
  { name: 'certificate_revocation_list', desc: 'Certificate Revocation List',        category: 'SAT' },
  { name: 'customer_certificates',     desc: 'Customer Digital Certificates',        category: 'SAT' },
  { name: 'customer_delivery_settings', desc: 'Customer Delivery Settings',          category: 'SAT' },
  { name: 'customer_receiver_rfc',     desc: 'Customer Receiver RFC Mappings',       category: 'SAT' },
  { name: 'customer_tokens',           desc: 'Customer Auth Tokens',                 category: 'SAT' },
  { name: 'supplier_tokens',           desc: 'Supplier Auth Tokens',                 category: 'SAT' },
  { name: 'user_customers',            desc: 'User ↔ Customer Relationships',        category: 'SAT' },
];

const CHAT_STARTER_PROMPTS = [
  { label: 'VBRK & vbrp', query: 'Explain the relationship between VBRK and vbrp tables and what data they contain' },
  { label: 'Key joins', query: 'What are the most important table joins in this SAP schema for sales analysis?' },
  { label: 'Revenue fields', query: 'Which fields and tables should I use to calculate total revenue or net sales?' },
  { label: 'Customer lookup', query: 'How do I look up a customer name and sales org data for a billing document?' },
  { label: 'Profit margin', query: 'Walk me through how to build a profit margin query using CKIS and vbrp' },
  { label: 'Delivery joins', query: 'How do LIKP, LIPS, and VBFA relate to each other for delivery tracking?' },
  { label: 'PO to invoice', query: 'Explain the full purchasing flow from EKKO/EKPO through RBKP/RSEG to financial posting' },
  { label: 'Material stock', query: 'Which tables (MARA, MARC, MARD) should I use to get material stock by plant and storage location?' },
  { label: 'Vendor master', query: 'How is vendor master data structured across LFA1, LFB1, and LFM1?' },
  { label: 'CO-PA analysis', query: 'How do CE1* and CE2* CO-PA tables work and what can I analyse from them?' },
  { label: 'Year 2000 data', query: 'How should I filter data for the year 2000? The gjahr field seems unreliable.' },
  { label: 'EDI tables', query: 'Explain zodiac_invoice_failed_edi and zodiac_invoice_success_edi — what columns exist and how are they used?' },
];

/* ─── Types ───────────────────────────────────────────────────── */

type AiAnalysisMeta = {
  validation?: SqlValidationMeta;
  proposed_validation?: SqlValidationMeta;
  query_origin?: string;
  suggestion_source?: string;
  action?: string; reason?: string; sql?: string;
  rows_preview?: Record<string, unknown>[];
  compare?: unknown; charts?: any[]; multiModel?: any;
  /** Server-side intent + result-shape summary (adaptive pipeline) */
  adaptive_context?: {
    intent?: Record<string, unknown>;
    validation?: Record<string, unknown>;
    query_profile?: { kind?: string; tags?: string[]; explicit_tables?: string[]; flags?: Record<string, boolean> };
    result_shape?: Record<string, unknown>;
  };
  charts_blocked_reason?: string;
  time_scope?: string;
  date_range?: { min_date: string; max_date: string };
  period_info?: string;
  needs_approval?: boolean;
  proposed_sql?: string;
  performance?: {
    action_decision_ms?: number;
    pattern_matching_ms?: number;
    cache_lookup_ms?: number;
    sql_execution_ms?: number;
    summarization_ms?: number;
    chart_generation_ms?: number;
    total_ms?: number;
    used_pattern?: boolean;
    used_cache?: boolean;
    row_count?: number;
    chart_count?: number;
    sql_path_reason?: string;
  };
};

type SqlValidationMeta = {
  errors?: string[];
  warnings?: string[];
  tables?: string[];
  columns?: string[];
  date_normalizations?: string[];
  aggregate_functions?: string[];
};

type Message = {
  role: 'user' | 'assistant';
  content: string;
  meta?: AiAnalysisMeta;
  section?: 'realtime' | 'historical';
  ts?: number;
};

type OutboundData = {
  summary?: { documents_received: number; validated_success: number; validated_failed: number; converted_success: number; converted_failed: number; converted_pending: number };
  top_customers?: { customer_id: string; customer_name: string; currency: string; count: number }[];
  funnel?: { documents_received: number; validated_success: number; validated_failed: number; converted_success: number; converted_failed: number; converted_pending: number };
};

type InboundData = {
  summary?: { total_documents: number; merges_total: number; merges_sent_to_sap: number; merges_pending: number };
  top_suppliers?: { supplier_rfc: string; supplier_name: string; count: number; total_amount: number }[];
};

type BusinessData = {
  revenue_by_customer?: { customer_id: string; customer_name: string; invoice_count: number; total_revenue: number }[];
  revenue_by_country?: { country: string; country_name?: string; invoice_count: number; total_revenue: number }[];
  trend?: { current_period_revenue: number; previous_period_revenue: number; revenue_change_pct: number };
};

/* ─── Tiny helpers ────────────────────────────────────────────── */

function fmt(n: number | string | undefined) {
  return Number(n ?? 0).toLocaleString();
}

function TrendBadge({ pct }: { pct: number }) {
  if (pct > 0) return (
    <span className="inline-flex items-center gap-0.5 text-xs font-mono font-semibold text-emerald-600">
      <ArrowUpRight className="h-3 w-3" />+{pct}%
    </span>
  );
  if (pct < 0) return (
    <span className="inline-flex items-center gap-0.5 text-xs font-mono font-semibold text-red-500">
      <ArrowDownRight className="h-3 w-3" />{pct}%
    </span>
  );
  return (
    <span className="inline-flex items-center gap-0.5 text-xs font-mono text-slate-400">
      <Minus className="h-3 w-3" />0%
    </span>
  );
}

function SkeletonRow() {
  return (
    <div className="flex gap-3 py-2 animate-pulse">
      <div className="h-3 bg-slate-100 rounded flex-1" />
      <div className="h-3 bg-slate-100 rounded w-16" />
      <div className="h-3 bg-slate-100 rounded w-12" />
    </div>
  );
}

function LivePulse() {
  return (
    <span className="relative flex h-2 w-2">
      <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-blue-400 opacity-75" />
      <span className="relative inline-flex rounded-full h-2 w-2 bg-blue-500" />
    </span>
  );
}

function ValidationNotes({ validation }: { validation?: SqlValidationMeta }) {
  if (!validation) return null;
  const errors = validation.errors ?? [];
  const warnings = validation.warnings ?? [];
  const notes = validation.date_normalizations ?? [];
  if (!errors.length && !warnings.length && !notes.length) return null;

  return (
    <div className="rounded-md border border-amber-200 bg-amber-50 px-2.5 py-2 text-[11px] text-amber-900 space-y-1">
      {errors.map((error, idx) => (
        <div key={`error-${idx}`}>Blocked: {error}</div>
      ))}
      {warnings.map((warning, idx) => (
        <div key={`warning-${idx}`}>Warning: {warning}</div>
      ))}
      {notes.map((note, idx) => (
        <div key={`note-${idx}`}>Normalized: {note}</div>
      ))}
    </div>
  );
}

/* ─── Stat Card ──────────────────────────────────────────────── */

function StatCard({
  label, value, sub, accent = false,
}: { label: string; value: string | number; sub?: React.ReactNode; accent?: boolean }) {
  return (
    <div className={`rounded-xl border px-4 py-3.5 flex flex-col gap-1.5 ${accent ? 'bg-gradient-to-br from-blue-600 to-indigo-700 border-blue-600 text-white shadow-lg' : 'bg-white border-slate-200'}`}>
      <span className={`text-[10px] font-mono uppercase tracking-widest ${accent ? 'text-blue-100' : 'text-slate-500'}`}>{label}</span>
      <span className={`text-2xl font-mono font-bold tabular-nums leading-none ${accent ? 'text-white' : 'text-slate-900'}`}>{fmt(value)}</span>
      {sub && <div className="text-xs mt-0.5">{sub}</div>}
    </div>
  );
}

/* ─── Funnel Step ────────────────────────────────────────────── */

function FunnelStep({ step, label, count, total, warn = false }: {
  step: number; label: string; count: number; total: number; warn?: boolean;
}) {
  const pct = total > 0 ? Math.round((count / total) * 100) : 0;
  return (
    <div className="flex items-center gap-2.5">
      <span className="w-4 h-4 rounded-full bg-slate-100 flex items-center justify-center text-[9px] font-mono font-bold text-slate-600 flex-shrink-0">
        {step}
      </span>
      <div className="flex-1 min-w-0">
        <div className="flex items-center justify-between mb-0.5">
          <span className="text-xs text-slate-600 truncate">{label}</span>
          <span className={`text-xs font-mono font-bold ml-2 ${warn ? 'text-red-500' : 'text-slate-800'}`}>{fmt(count)}</span>
        </div>
        <div className="h-1 bg-slate-100 rounded-full overflow-hidden">
          <div
            className={`h-full rounded-full transition-all duration-700 ${warn ? 'bg-red-400' : 'bg-gradient-to-r from-blue-600 to-indigo-700'}`}
            style={{ width: `${pct}%` }}
          />
        </div>
      </div>
      <span className="text-[10px] font-mono text-slate-400 w-7 text-right flex-shrink-0">{pct}%</span>
    </div>
  );
}

/* ─── Domain Explorer ────────────────────────────────────────── */
// Collapsible panel shown in the AI chat empty state.
// Organises natural-language examples by domain so users discover
// what they can ask without being limited to pre-set chips.

function DomainExplorer({ onSelect }: { onSelect: (q: string) => void }) {
  const [openCategory, setOpenCategory] = useState<string | null>(null);

  return (
    <div className="mt-3 rounded-xl border border-slate-200 bg-white overflow-hidden">
      <div className="px-3 py-2 border-b border-slate-100 flex items-center gap-2 bg-gradient-to-r from-blue-50 to-indigo-50">
        <Sparkles className="h-3.5 w-3.5 text-blue-500" />
        <span className="text-[11px] font-semibold text-slate-700">What can you ask?</span>
        <span className="ml-auto text-[10px] text-slate-400 italic">Click any question to run it</span>
      </div>
      <div className="divide-y divide-slate-100">
        {DOMAIN_QUERY_EXAMPLES.map((domain) => (
          <div key={domain.category}>
            <button
              type="button"
              onClick={() => setOpenCategory(openCategory === domain.category ? null : domain.category)}
              className="w-full flex items-center gap-2 px-3 py-2 hover:bg-slate-50 transition-colors text-left"
            >
              <span className="text-sm leading-none">{domain.icon}</span>
              <span className="text-[11px] font-medium text-slate-700 flex-1">{domain.category}</span>
              <span className="text-[10px] text-slate-400">{domain.questions.length} examples</span>
              <ChevronRight
                className={`h-3 w-3 text-slate-400 transition-transform ${openCategory === domain.category ? 'rotate-90' : ''}`}
              />
            </button>
            {openCategory === domain.category && (
              <div className="bg-slate-50 px-3 pb-2 space-y-1">
                {domain.questions.map((q, qi) => (
                  <button
                    key={qi}
                    type="button"
                    onClick={() => { onSelect(q); setOpenCategory(null); }}
                    className="w-full text-left text-[11px] text-slate-600 hover:text-blue-700 hover:bg-blue-50 rounded-lg px-2.5 py-1.5 transition-all flex items-start gap-2 group"
                  >
                    <span className="text-blue-400 group-hover:text-blue-600 flex-shrink-0 mt-0.5">›</span>
                    <span>{q}</span>
                  </button>
                ))}
              </div>
            )}
          </div>
        ))}
      </div>
    </div>
  );
}

/* ─── Chat Panel ─────────────────────────────────────────────── */

const PROGRESS_STEPS = [
  { icon: '🔍', label: 'Analyzing your question...', color: 'text-blue-500' },
  { icon: '📋', label: 'Loading schema & context...', color: 'text-purple-500' },
  { icon: '⚙️', label: 'Generating SQL query...', color: 'text-orange-500' },
  { icon: '▶️', label: 'Running query on database...', color: 'text-green-500' },
  { icon: '✍️', label: 'Composing your answer...', color: 'text-indigo-500' },
];

const FOLLOWUP_PROGRESS_STEPS = [
  { icon: '🧠', label: 'Analyzing previous result…', color: 'text-indigo-600' },
  { icon: '✍️', label: 'Composing your answer…', color: 'text-slate-600' },
];

function formatCellValue(v: unknown): string {
  if (v === null || v === undefined) return '—';
  if (typeof v === 'object') return JSON.stringify(v);
  return String(v);
}

function DataPreviewTable({ rows, maxHeight = 280 }: { rows: Record<string, unknown>[]; maxHeight?: number }) {
  if (!rows?.length) return null;
  const keys = Array.from(
    rows.reduce((acc, row) => {
      Object.keys(row || {}).forEach((k) => acc.add(k));
      return acc;
    }, new Set<string>()),
  );
  return (
    <div
      className="mt-2 rounded-lg border border-slate-200 bg-white overflow-auto"
      style={{ maxHeight }}
    >
      <table className="w-full text-[10px] font-mono border-collapse">
        <thead className="sticky top-0 bg-slate-100 border-b border-slate-200">
          <tr>
            {keys.map((k) => (
              <th key={k} className="text-left px-2 py-1.5 text-slate-600 font-semibold whitespace-nowrap">
                {k}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((row, ri) => (
            <tr key={ri} className="border-b border-slate-50 hover:bg-slate-50/80">
              {keys.map((k) => (
                <td key={k} className="px-2 py-1 text-slate-800 align-top break-all max-w-[14rem]">
                  {formatCellValue(row[k])}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
      <p className="text-[9px] text-slate-400 px-2 py-1 border-t border-slate-100 bg-slate-50">
        Showing {rows.length} row{rows.length === 1 ? '' : 's'} (server preview)
      </p>
    </div>
  );
}

function ChatPanel({
  section,
  messages,
  loading,
  loadingStep = 0,
  loadingElapsed = 0,
  prompts,
  onSend,
  placeholder,
  useContext,
  setUseContext,
  queryMode = 'new',
  setQueryMode,
  timeScope,
  setTimeScope,
  fullWidth = false,
}: {
  section: 'realtime' | 'historical';
  messages: Message[];
  loading: boolean;
  loadingStep?: number;
  loadingElapsed?: number;
  prompts: { label: string; query: string }[];
  onSend: (text: string) => void;
  placeholder: string;
  useContext: boolean;
  setUseContext: (v: boolean) => void;
  queryMode?: 'new' | 'follow_up';
  setQueryMode?: (m: 'new' | 'follow_up') => void;
  timeScope: 'current' | 'historical' | 'both';
  setTimeScope: (s: 'current' | 'historical' | 'both') => void;
  fullWidth?: boolean;
}) {
  const [input, setInput] = useState('');
  const bottomRef = useRef<HTMLDivElement>(null);

  const {
    isListening, transcript, isSupported: isVoiceSupported,
    error: voiceError, startListening, stopListening, resetTranscript,
  } = useVoiceRecording();

  useEffect(() => { if (transcript) setInput(transcript); }, [transcript]);
  useEffect(() => { bottomRef.current?.scrollIntoView({ behavior: 'smooth' }); }, [messages]);

  const toggleVoice = () => {
    if (isListening) { stopListening(); } else { resetTranscript(); startListening(); }
  };

  const submit = (text?: string) => {
    const msg = (text ?? input).trim();
    if (!msg || loading) return;
    if (!text) setInput('');
    onSend(msg);
  };

  const messagesWithCharts = messages.filter(
    (m) => m.role === 'assistant' && m.meta?.charts && m.meta.charts.length > 0,
  );
  const hasCharts = messagesWithCharts.length > 0;
  const chartPanelBreakpoint = fullWidth ? 'md' : 'lg';
  const effectiveSteps = queryMode === 'follow_up' ? FOLLOWUP_PROGRESS_STEPS : PROGRESS_STEPS;
  const effectiveStepIdx = queryMode === 'follow_up'
    ? (loadingElapsed < 2 ? 0 : 1)
    : loadingStep;

  return (
    <div className="flex flex-col h-full">
      <div className="px-3 py-2 border-b border-slate-100 flex flex-wrap gap-1.5">
        {prompts.map((p) => (
          <button
            key={p.label}
            type="button"
            onClick={() => submit(p.query)}
            className="inline-flex items-center gap-1 px-2.5 py-1 rounded-full border border-slate-200 bg-white text-[11px] font-medium text-slate-600 hover:border-slate-400 hover:text-slate-900 transition-all"
          >
            <Sparkles className="h-3 w-3 text-slate-400" />
            {p.label}
          </button>
        ))}
      </div>

      <div className="flex-1 overflow-hidden min-h-0 flex gap-0">
        <div className={`flex flex-col overflow-hidden ${hasCharts ? `w-full ${chartPanelBreakpoint === 'md' ? 'md:w-[45%]' : 'lg:w-[45%]'}` : 'w-full'}`}>
          <div className="flex-1 overflow-y-auto px-3 py-3 space-y-3">
            {messages.length === 0 ? (
              <div className="w-full py-3 select-none">
                <div className="flex flex-col items-center text-center mb-3">
                  <div className="w-10 h-10 rounded-2xl bg-slate-100 flex items-center justify-center mb-2">
                    {section === 'realtime'
                      ? <Activity className="h-4 w-4 text-slate-400" />
                      : <BarChart3 className="h-4 w-4 text-slate-400" />}
                  </div>
                  <p className="text-sm font-medium text-slate-500 mb-0.5">
                    {section === 'realtime' ? 'Real-time Intelligence' : 'Historical Analysis'}
                  </p>
                  <p className="text-xs text-slate-400 max-w-md">
                    Ask in plain English. The server generates safe SQL, runs it on the database, and returns rows plus an optional summary and charts — the same adaptive NL→SQL→results flow. Use <strong className="text-slate-600">Follow-up</strong> to analyse the last result without a new query (server thread).
                  </p>
                </div>
                <DomainExplorer onSelect={(q) => submit(q)} />
              </div>
            ) : (
              messages.map((m, i) => (
                <div key={i} className={`flex flex-col gap-0.5 ${m.role === 'user' ? 'items-end' : 'items-start'}`}>
                  <span className="text-[10px] font-mono text-slate-400 px-1">
                    {m.role === 'user' ? 'YOU' : 'AI'}{m.ts ? ` · ${new Date(m.ts).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}` : ''}
                  </span>
                  <div className={`max-w-[92%] rounded-2xl px-3.5 py-2.5 text-sm leading-relaxed break-words ${
                    m.role === 'user'
                      ? 'bg-gradient-to-br from-blue-600 to-indigo-700 text-white rounded-tr-sm shadow-md'
                      : 'bg-slate-50 border border-slate-200 text-slate-800 rounded-tl-sm'
                  }`}>
                    {m.role === 'user' ? (
                      <div className="whitespace-pre-wrap">{m.content}</div>
                    ) : (
                      <div className="prose prose-sm max-w-none
                        prose-headings:mt-3 prose-headings:mb-2 prose-headings:font-semibold prose-headings:text-slate-900
                        prose-h3:text-base prose-h4:text-sm
                        prose-p:my-1.5 prose-p:text-slate-700
                        prose-strong:text-slate-900 prose-strong:font-bold prose-strong:bg-yellow-100 prose-strong:px-1 prose-strong:rounded
                        prose-ul:my-2 prose-ul:ml-4 prose-li:my-0.5 prose-li:text-slate-700
                        prose-ol:my-2 prose-ol:ml-4
                        prose-code:text-xs prose-code:bg-slate-100 prose-code:px-1 prose-code:py-0.5 prose-code:rounded prose-code:text-blue-700
                        prose-pre:bg-slate-800 prose-pre:text-slate-100 prose-pre:rounded-lg prose-pre:p-3
                        prose-blockquote:border-l-4 prose-blockquote:border-blue-500 prose-blockquote:pl-4 prose-blockquote:italic prose-blockquote:text-slate-600
                        prose-table:text-xs
                      ">
                        <ReactMarkdown>{m.content}</ReactMarkdown>
                      </div>
                    )}
                  </div>
                  {m.role === 'assistant' && m.meta?.rows_preview && m.meta.rows_preview.length > 0 && (
                    <div className="max-w-[92%] w-full">
                      <DataPreviewTable rows={m.meta.rows_preview as Record<string, unknown>[]} />
                    </div>
                  )}
                  {m.role === 'assistant' && m.meta && (
                    <div className="max-w-[92%] mt-1 text-[10px] font-mono text-slate-400 px-1 space-y-0.5">
                      {m.meta.period_info && (
                        <div className="inline-flex items-center gap-1 bg-blue-50 border border-blue-200 text-blue-700 px-2 py-1 rounded-md mb-1">
                          <CalendarRange className="h-3 w-3" />
                          <span className="font-semibold">{m.meta.period_info}</span>
                          {m.meta.date_range && (
                            <span className="text-blue-600">
                              ({m.meta.date_range.min_date} to {m.meta.date_range.max_date})
                            </span>
                          )}
                        </div>
                      )}
                      <div>
                        {m.meta.action && <span>Action: {m.meta.action}</span>}
                        {m.meta.reason && <span> • Reason: {m.meta.reason}</span>}
                        {m.meta.adaptive_context?.query_profile?.kind && (
                          <span> • Intent: {String(m.meta.adaptive_context.query_profile.kind)}</span>
                        )}
                        {m.meta.sql && <span> • SQL executed</span>}
                        {m.meta.rows_preview && <span> • {m.meta.rows_preview.length} preview rows</span>}
                        {m.meta.charts && <span> • {m.meta.charts.length} chart(s)</span>}
                      </div>
                      {m.meta.sql && (
                        <details className="mt-0.5">
                          <summary className="cursor-pointer text-[10px] text-blue-600 underline">
                            View generated SQL
                          </summary>
                          <pre className="mt-1 max-h-40 overflow-auto text-[10px] bg-slate-900 text-slate-50 rounded p-2 whitespace-pre-wrap">
                            {m.meta.sql}
                          </pre>
                        </details>
                      )}
                      <ValidationNotes validation={m.meta.validation} />
                      {m.meta.charts_blocked_reason && (
                        <div className="text-xs text-amber-700 bg-amber-50 border border-amber-200 px-2 py-1 rounded-md">
                          Charts suppressed: {m.meta.charts_blocked_reason}
                        </div>
                      )}
                      {m.meta.performance && (
                        <div className="text-slate-500">
                          ⏱ {(m.meta.performance.total_ms || 0) / 1000}s
                          {m.meta.performance.used_pattern && <span className="text-green-600"> • pattern-matched</span>}
                          {m.meta.performance.used_cache && <span className="text-blue-600"> • cached</span>}
                          {m.meta.performance.sql_execution_ms != null && (
                            <span> • sql: {m.meta.performance.sql_execution_ms}ms</span>
                          )}
                        </div>
                      )}
                    </div>
                  )}
                  {m.role === 'assistant' && m.meta?.charts && m.meta.charts.length > 0 && (
                    <div className={`${chartPanelBreakpoint === 'md' ? 'md:hidden' : 'lg:hidden'} w-full mt-2 max-w-[92%]`}>
                      <AIChartRenderer charts={m.meta.charts} />
                    </div>
                  )}
                </div>
              ))
            )}
            {loading && (
              <div className="flex flex-col gap-2 my-1">
                <div className="rounded-xl border border-blue-100 bg-gradient-to-br from-blue-50 to-indigo-50 p-3 shadow-sm">
                  <div className="flex items-center justify-between mb-2">
                    <span className="text-[10px] font-bold uppercase tracking-widest text-blue-600">AI Processing</span>
                    <span className="text-[10px] font-mono text-slate-500 bg-white px-2 py-0.5 rounded-full border border-slate-200">
                      {loadingElapsed.toFixed(1)}s
                    </span>
                  </div>
                  <div className="flex flex-col gap-1">
                    {effectiveSteps.map((step, si) => {
                      const isDone = si < effectiveStepIdx;
                      const isActive = si === effectiveStepIdx;
                      return (
                        <div key={si} className={`flex items-center gap-2 text-xs transition-all duration-300 ${
                          isDone ? 'opacity-40' : isActive ? 'opacity-100' : 'opacity-20'
                        }`}>
                          <span className="text-base leading-none">{isDone ? '✅' : step.icon}</span>
                          <span className={`font-medium ${isActive ? step.color : 'text-slate-500'}`}>
                            {step.label}
                          </span>
                          {isActive && (
                            <span className="ml-auto flex gap-0.5">
                              {[0, 1, 2].map((j) => (
                                <span key={j} className="w-1 h-1 rounded-full bg-blue-400 animate-bounce"
                                  style={{ animationDelay: `${j * 150}ms` }} />
                              ))}
                            </span>
                          )}
                        </div>
                      );
                    })}
                  </div>
                  <div className="mt-2 h-1 w-full bg-blue-100 rounded-full overflow-hidden">
                    <div
                      className="h-full bg-gradient-to-r from-blue-400 to-indigo-500 rounded-full transition-all duration-500"
                      style={{ width: `${Math.min(100, ((effectiveStepIdx + 1) / effectiveSteps.length) * 100)}%` }}
                    />
                  </div>
                  <p className="text-[10px] text-slate-400 mt-1.5 italic">
                    {queryMode === 'follow_up'
                      ? 'Follow-ups analyze the last result — no new database query.'
                      : 'Complex queries may take 30–90s. Results appear when ready.'}
                  </p>
                </div>
              </div>
            )}
            <div ref={bottomRef} />
          </div>
        </div>

        {hasCharts && (
          <div className={`${chartPanelBreakpoint === 'md' ? 'hidden md:flex' : 'hidden lg:flex'} flex-col w-[55%] border-l border-slate-100 bg-gradient-to-br from-slate-50 to-white overflow-hidden`}>
            <div className="px-4 py-2.5 border-b border-slate-100 flex items-center gap-2 flex-shrink-0 bg-white/90 backdrop-blur-sm sticky top-0 z-10">
              <BarChart3 className="h-4 w-4 text-blue-600" />
              <div className="flex-1 min-w-0">
                <h3 className="text-sm font-semibold text-slate-900">Visualizations</h3>
                <p className="text-[10px] text-slate-400 leading-tight">Charts from your query results</p>
              </div>
              <span className="text-[10px] font-mono text-slate-400 flex-shrink-0">{messagesWithCharts.length} chart{messagesWithCharts.length > 1 ? 's' : ''}</span>
            </div>
            <div className="flex-1 overflow-y-auto p-4 space-y-6">
              {messagesWithCharts.map((m, idx) => (
                <div key={idx} className="space-y-2">
                  {messagesWithCharts.length > 1 && (
                    <div className="text-[10px] font-mono text-slate-400 uppercase tracking-widest px-1">
                      Query {messages.indexOf(m)} {m.ts ? `· ${new Date(m.ts).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}` : ''}
                    </div>
                  )}
                  {m.meta?.charts && <AIChartRenderer charts={m.meta.charts} />}
                </div>
              ))}
            </div>
          </div>
        )}
      </div>

      {voiceError && (
        <div className="mx-3 mb-1 rounded-lg bg-amber-50 border border-amber-200 px-3 py-1.5 text-xs text-amber-700">
          {voiceError}
        </div>
      )}
      {isListening && (
        <div className="mx-3 mb-1 rounded-lg bg-blue-50 border border-blue-100 px-3 py-1.5 text-xs text-blue-700 flex items-center gap-2">
          <div className="flex gap-0.5">
            {[0, 1, 2].map((i) => (
              <span key={i} className="w-0.5 h-3 bg-blue-500 rounded-full animate-pulse"
                style={{ animationDelay: `${i * 120}ms` }} />
            ))}
          </div>
          Listening…
        </div>
      )}

      <div className="px-3 pt-2 pb-2 border-t border-slate-100">
        <div className="flex items-center gap-2 mb-1.5 flex-wrap">
          {setQueryMode && (
            <div className="flex items-center gap-0.5 bg-slate-100 rounded-full p-0.5 text-[11px] font-medium select-none">
              <button
                type="button"
                onClick={() => setQueryMode('new')}
                title="Run a fresh SQL query on the database"
                className={`px-2.5 py-0.5 rounded-full transition-all ${
                  queryMode === 'new'
                    ? 'bg-white text-slate-800 shadow-sm'
                    : 'text-slate-400 hover:text-slate-600'
                }`}
              >
                New question
              </button>
              <button
                type="button"
                onClick={() => setQueryMode('follow_up')}
                title="Analyse the previous result set — no new SQL (server thread)"
                className={`px-2.5 py-0.5 rounded-full transition-all ${
                  queryMode === 'follow_up'
                    ? 'bg-white text-indigo-700 shadow-sm'
                    : 'text-slate-400 hover:text-slate-600'
                }`}
              >
                Follow-up
              </button>
            </div>
          )}
          <label className="flex items-center gap-1.5 cursor-pointer select-none">
            <input type="checkbox" checked={useContext} onChange={(e) => setUseContext(e.target.checked)}
              className="rounded border-slate-300 text-slate-800 focus:ring-slate-500 w-3 h-3" />
            <span className="text-[11px] text-slate-500 font-medium">Dashboard context</span>
          </label>
          <div className="flex items-center gap-1 ml-auto">
            <span className="text-[10px] text-slate-400">Scope</span>
            <select
              value={timeScope}
              onChange={(e) => setTimeScope(e.target.value as 'current' | 'historical' | 'both')}
              className="text-[10px] font-mono border border-slate-200 rounded-lg px-1.5 py-0.5 bg-white text-slate-700"
            >
              <option value="current">Current</option>
              <option value="historical">Historical</option>
              <option value="both">Both</option>
            </select>
          </div>
        </div>
        {queryMode === 'follow_up' && (
          <div className="flex items-center gap-1.5 mb-1.5 px-2.5 py-1 bg-indigo-50 border border-indigo-100 rounded-lg text-[11px] text-indigo-600">
            <svg className="w-3 h-3 flex-shrink-0" fill="currentColor" viewBox="0 0 20 20">
              <path fillRule="evenodd" d="M18 10c0 4.418-3.582 8-8 8S2 14.418 2 10 5.582 2 10 2s8 3.582 8 8zm-8-3a1 1 0 100 2 1 1 0 000-2zm-1 4a1 1 0 012 0v3a1 1 0 01-2 0v-3z" clipRule="evenodd" />
            </svg>
            <span>
              <strong>Follow-up</strong> — answers from the last query in this session (server-side thread). For new data, switch to <button type="button" className="underline font-semibold" onClick={() => setQueryMode?.('new')}>New question</button>.
            </span>
          </div>
        )}
        <div className="flex gap-1.5">
          <input
            type="text"
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={(e) => { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); submit(); } }}
            placeholder={placeholder}
            className="flex-1 min-w-0 rounded-xl border border-slate-200 text-sm py-2 px-3 text-slate-900 placeholder:text-slate-400 bg-white focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-transparent disabled:opacity-60 transition-shadow"
            disabled={loading}
          />
          {isVoiceSupported && (
            <button
              type="button"
              onClick={toggleVoice}
              disabled={loading}
              className={`flex-shrink-0 w-9 h-9 rounded-xl flex items-center justify-center transition-all ${
                isListening ? 'bg-red-500 text-white animate-pulse' : 'bg-slate-100 hover:bg-slate-200 text-slate-600'
              }`}
            >
              {isListening ? <MicOff className="h-3.5 w-3.5" /> : <Mic className="h-3.5 w-3.5" />}
            </button>
          )}
          <button
            type="button"
            onClick={() => submit()}
            disabled={loading || !input.trim()}
            className="flex-shrink-0 h-9 px-3.5 bg-gradient-to-r from-blue-600 to-indigo-700 text-white rounded-xl hover:from-blue-700 hover:to-indigo-800 disabled:opacity-40 disabled:cursor-not-allowed transition-all flex items-center gap-1.5 text-sm font-medium shadow-sm"
          >
            {loading
              ? <div className="h-3.5 w-3.5 border-2 border-white border-t-transparent rounded-full animate-spin" />
              : <Send className="h-3.5 w-3.5" />}
            <span className="hidden sm:inline text-xs">Send</span>
          </button>
        </div>
      </div>
    </div>
  );
}
/* ─── ChatGPT Free-Chat Panel ─────────────────────────────── */

type ChatMessage = { role: 'user' | 'assistant'; content: string; ts: number };

type SapTableRow = (typeof SAP_TABLES)[number];

/** Case-insensitive lookup for API schema (table name keys vary). */
function buildSchemaColumnLookup(
  schema: Record<string, { columns?: string[] }>,
): Map<string, string[]> {
  const m = new Map<string, string[]>();
  for (const [table, info] of Object.entries(schema)) {
    const cols = info?.columns ?? [];
    if (!cols.length) continue;
    for (const k of new Set([table, table.toLowerCase(), table.toUpperCase()])) {
      if (!m.has(k)) m.set(k, cols);
    }
  }
  return m;
}

function lookupTableColumns(map: Map<string, string[]>, tableName: string): string[] | undefined {
  return (
    map.get(tableName) ||
    map.get(tableName.toLowerCase()) ||
    map.get(tableName.toUpperCase())
  );
}

function ChatGPTPanel({
  messages,
  loading,
  onSend,
  onNewChat,
}: {
  messages: ChatMessage[];
  loading: boolean;
  onSend: (text: string) => void;
  onNewChat?: () => void;
}) {
  const [input, setInput] = useState('');
  const [selectedCategory, setSelectedCategory] = useState<string | null>(null);
  const [selectedTable, setSelectedTable] = useState<SapTableRow | null>(null);
  const [columnLookup, setColumnLookup] = useState<Map<string, string[]>>(() => new Map());
  const [schemaLoadState, setSchemaLoadState] = useState<'idle' | 'loading' | 'done' | 'error'>('idle');
  const bottomRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    let cancelled = false;
    setSchemaLoadState('loading');
    dashboardApi
      .getAIAnalysisSchema()
      .then((res) => {
        if (cancelled) return;
        setColumnLookup(buildSchemaColumnLookup(res.schema || {}));
        setSchemaLoadState('done');
      })
      .catch(() => {
        if (!cancelled) setSchemaLoadState('error');
      });
    return () => {
      cancelled = true;
    };
  }, []);

  useEffect(() => { bottomRef.current?.scrollIntoView({ behavior: 'smooth' }); }, [messages]);

  const submit = (text?: string) => {
    const msg = (text ?? input).trim();
    if (!msg || loading) return;
    if (!text) setInput('');
    onSend(msg);
  };

  const categories = Array.from(new Set(SAP_TABLES.map((t) => t.category)));
  const filteredTables = selectedCategory
    ? SAP_TABLES.filter((t) => t.category === selectedCategory)
    : SAP_TABLES;

  const selectedCols = selectedTable ? lookupTableColumns(columnLookup, selectedTable.name) : undefined;

  const askAboutTable = (tbl: SapTableRow) => {
    submit(
      `Tell me about the ${tbl.name} table (${tbl.desc}) — key columns, relationships to other tables, and example queries I can run.`,
    );
  };

  return (
    <div className="flex gap-3 flex-1 min-h-0 h-full max-h-full">
      {/* Left: Table browser — height-bounded; table list + columns each scroll */}
      <div className="hidden md:flex flex-col w-[13.5rem] lg:w-60 flex-shrink-0 rounded-2xl border border-slate-200 bg-white min-h-0 min-w-0 max-h-full overflow-hidden">
        <div className="px-3 pt-3 pb-2 border-b border-slate-100 flex items-center gap-2 flex-shrink-0">
          <Database className="h-3.5 w-3.5 text-blue-600 flex-shrink-0" />
          <span className="text-xs font-semibold text-slate-900 truncate">SAP Tables</span>
        </div>

        {/* Category filter — scroll if many chips */}
        <div className="px-2 pt-2 max-h-[4.5rem] overflow-y-auto overscroll-y-contain flex-shrink-0 border-b border-slate-50">
          <div className="flex flex-wrap gap-1">
            <button
              type="button"
              onClick={() => setSelectedCategory(null)}
              className={`text-[10px] px-2 py-0.5 rounded-full border transition-all ${!selectedCategory ? 'bg-blue-600 text-white border-blue-600' : 'border-slate-200 text-slate-600 hover:border-blue-400'}`}
            >
              All
            </button>
            {categories.map((cat) => (
              <button
                key={cat}
                type="button"
                onClick={() => setSelectedCategory(selectedCategory === cat ? null : cat)}
                className={`text-[10px] px-2 py-0.5 rounded-full border transition-all ${selectedCategory === cat ? 'bg-blue-600 text-white border-blue-600' : 'border-slate-200 text-slate-600 hover:border-blue-400'}`}
              >
                {cat}
              </button>
            ))}
          </div>
        </div>

        {/* Table list */}
        <div className="flex-[3] min-h-[6rem] min-w-0 overflow-y-auto overscroll-y-contain p-2 space-y-0.5 border-b border-slate-100">
          {filteredTables.map((tbl) => (
            <button
              key={tbl.name}
              type="button"
              onClick={() => setSelectedTable(tbl)}
              disabled={loading}
              className={`w-full text-left rounded-lg px-2 py-1.5 border transition-all group disabled:opacity-50 ${
                selectedTable?.name === tbl.name
                  ? 'bg-blue-50 border-blue-300 ring-1 ring-blue-200'
                  : 'border-transparent hover:bg-blue-50/80 hover:border-blue-200'
              }`}
            >
              <div className="flex items-center gap-1.5">
                <Table2 className="h-3 w-3 text-slate-400 flex-shrink-0 group-hover:text-blue-500 transition-colors" />
                <span className="text-[11px] font-mono font-semibold text-slate-800 group-hover:text-blue-700">{tbl.name}</span>
              </div>
              <p className="text-[10px] text-slate-500 ml-4 leading-tight mt-0.5">{tbl.desc}</p>
            </button>
          ))}
        </div>

        {/* Selected table: columns from /ai-analysis/schema */}
        <div className="flex-[2] min-h-[5rem] min-w-0 flex flex-col bg-slate-50/80">
          <div className="px-2 py-1.5 border-b border-slate-100 flex items-center gap-1 flex-shrink-0">
            <TableProperties className="h-3 w-3 text-slate-500 flex-shrink-0" />
            <span className="text-[10px] font-semibold text-slate-700 truncate">
              {selectedTable ? selectedTable.name : 'Columns'}
            </span>
          </div>
          <div className="flex-1 min-h-0 overflow-y-auto overscroll-y-contain px-2 py-1.5">
            {!selectedTable && (
              <p className="text-[10px] text-slate-500 leading-snug">Select a table to list columns from the connected schema.</p>
            )}
            {selectedTable && schemaLoadState === 'loading' && (
              <p className="text-[10px] text-slate-500">Loading schema…</p>
            )}
            {selectedTable && schemaLoadState === 'error' && (
              <p className="text-[10px] text-amber-700">Could not load schema. Try again or use Ask AI.</p>
            )}
            {selectedTable && schemaLoadState === 'done' && !selectedCols?.length && (
              <p className="text-[10px] text-slate-500 leading-snug">
                No columns in the live schema mapping for <span className="font-mono text-slate-700">{selectedTable.name}</span>. Use Ask AI for typical SAP fields.
              </p>
            )}
            {selectedTable && selectedCols && selectedCols.length > 0 && (
              <ul className="space-y-0.5">
                {selectedCols.map((col) => (
                  <li key={col} className="text-[10px] font-mono text-slate-800 leading-tight break-all">
                    {col}
                  </li>
                ))}
              </ul>
            )}
          </div>
          {selectedTable && (
            <div className="p-2 border-t border-slate-100 flex-shrink-0">
              <button
                type="button"
                onClick={() => askAboutTable(selectedTable)}
                disabled={loading}
                className="w-full text-[10px] font-medium py-1.5 rounded-lg bg-blue-600 text-white hover:bg-blue-700 disabled:opacity-40"
              >
                Ask AI about this table
              </button>
            </div>
          )}
        </div>
      </div>

      {/* Right: Chat area */}
      <div className="flex-1 min-w-0 min-h-0 flex flex-col rounded-2xl border border-slate-200 bg-white overflow-hidden max-h-full">
        {/* Header */}
        <div className="px-4 pt-3 pb-2.5 border-b border-slate-100 flex items-center gap-2 flex-shrink-0 justify-between">
          <div className="flex items-center gap-2 min-w-0">
            <div className="w-6 h-6 rounded-lg bg-gradient-to-br from-emerald-500 to-teal-600 flex items-center justify-center flex-shrink-0">
              <Bot className="h-3.5 w-3.5 text-white" />
            </div>
            <div className="min-w-0">
              <h2 className="text-xs font-semibold text-slate-900">Chat with ChatGPT</h2>
              <p className="text-[10px] text-slate-500 truncate">
                Ask about tables, schema, or logic — chat is saved and restores after reload
              </p>
            </div>
          </div>
          {onNewChat && (
            <button
              type="button"
              onClick={onNewChat}
              disabled={loading}
              className="flex-shrink-0 text-[10px] font-medium px-2.5 py-1 rounded-lg border border-slate-200 text-slate-600 hover:bg-slate-50 hover:border-slate-300 disabled:opacity-40"
            >
              New chat
            </button>
          )}
        </div>

        {/* Messages */}
        <div className="flex-1 min-h-0 overflow-y-auto overscroll-y-contain p-4 space-y-3">
          {messages.length === 0 && (
            <div className="space-y-4">
              <div className="text-center py-4">
                <div className="w-12 h-12 rounded-2xl bg-gradient-to-br from-emerald-500 to-teal-600 flex items-center justify-center mx-auto mb-3 shadow-lg">
                  <MessageCircle className="h-6 w-6 text-white" />
                </div>
                <h3 className="text-sm font-semibold text-slate-900 mb-1">Chat with your data</h3>
                <p className="text-xs text-slate-500 max-w-xs mx-auto">
                  Ask about table structures, query logic, business rules, or run live SQL analysis — across invoices, logistics, purchasing, finance, master data, and more.
                </p>
              </div>
              <div className="grid grid-cols-1 sm:grid-cols-2 gap-2">
                {CHAT_STARTER_PROMPTS.map((p) => (
                  <button
                    key={p.label}
                    onClick={() => submit(p.query)}
                    disabled={loading}
                    className="text-left rounded-xl border border-slate-200 bg-slate-50 hover:bg-gradient-to-br hover:from-blue-600 hover:to-indigo-700 hover:border-blue-600 hover:text-white text-slate-700 px-3 py-2.5 transition-all group disabled:opacity-50 hover:shadow-md"
                  >
                    <div className="flex items-center gap-1.5 mb-0.5">
                      <ChevronRight className="h-3 w-3 text-blue-500 group-hover:text-white flex-shrink-0" />
                      <span className="text-xs font-semibold">{p.label}</span>
                    </div>
                    <p className="text-[10px] text-slate-500 group-hover:text-blue-100 leading-tight ml-4">{p.query}</p>
                  </button>
                ))}
              </div>
              <DomainExplorer onSelect={(q) => submit(q)} />
            </div>
          )}

          {messages.map((m, i) => (
            <div key={i} className={`flex gap-2.5 ${m.role === 'user' ? 'justify-end' : 'justify-start'}`}>
              {m.role === 'assistant' && (
                <div className="w-6 h-6 rounded-lg bg-gradient-to-br from-emerald-500 to-teal-600 flex items-center justify-center flex-shrink-0 mt-0.5 shadow-sm">
                  <Bot className="h-3.5 w-3.5 text-white" />
                </div>
              )}
              <div className={`max-w-[80%] rounded-2xl px-3.5 py-2.5 text-sm leading-relaxed ${
                m.role === 'user'
                  ? 'bg-gradient-to-br from-blue-600 to-indigo-700 text-white rounded-br-sm'
                  : 'bg-slate-50 border border-slate-200 text-slate-800 rounded-bl-sm'
              }`}>
                {m.role === 'assistant' ? (
                  <div className="prose prose-sm max-w-none prose-pre:bg-slate-900 prose-pre:text-slate-50 prose-code:text-blue-700 prose-code:bg-blue-50 prose-code:px-1 prose-code:rounded text-xs">
                    <ReactMarkdown remarkPlugins={[remarkGfm]}>{m.content}</ReactMarkdown>
                  </div>
                ) : (
                  <span className="text-xs">{m.content}</span>
                )}
              </div>
              {m.role === 'user' && (
                <div className="w-6 h-6 rounded-lg bg-gradient-to-br from-blue-600 to-indigo-700 flex items-center justify-center flex-shrink-0 mt-0.5 shadow-sm">
                  <UserIcon className="h-3.5 w-3.5 text-white" />
                </div>
              )}
            </div>
          ))}

          {loading && (
            <div className="flex gap-2.5 justify-start">
              <div className="w-6 h-6 rounded-lg bg-gradient-to-br from-emerald-500 to-teal-600 flex items-center justify-center flex-shrink-0 shadow-sm">
                <Bot className="h-3.5 w-3.5 text-white" />
              </div>
              <div className="bg-slate-50 border border-slate-200 rounded-2xl rounded-bl-sm px-4 py-3 flex items-center gap-1.5">
                <div className="flex gap-1">
                  {[0, 1, 2].map((i) => (
                    <div key={i} className="w-1.5 h-1.5 rounded-full bg-slate-400 animate-bounce" style={{ animationDelay: `${i * 0.15}s` }} />
                  ))}
                </div>
                <span className="text-xs text-slate-500 ml-1">Thinking…</span>
              </div>
            </div>
          )}

          <div ref={bottomRef} />
        </div>

        {/* Input */}
        <div className="px-3 py-3 border-t border-slate-100 flex gap-2 flex-shrink-0">
          <input
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={(e) => { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); submit(); } }}
            placeholder="Ask about tables, schema, data, or business logic…"
            className="flex-1 min-w-0 rounded-xl border border-slate-200 text-sm py-2 px-3 text-slate-900 placeholder:text-slate-400 bg-white focus:outline-none focus:ring-2 focus:ring-emerald-500 focus:border-transparent disabled:opacity-60 transition-shadow"
            disabled={loading}
          />
          <button
            type="button"
            onClick={() => submit()}
            disabled={loading || !input.trim()}
            className="flex-shrink-0 h-9 px-3.5 bg-gradient-to-r from-emerald-500 to-teal-600 text-white rounded-xl hover:from-emerald-600 hover:to-teal-700 disabled:opacity-40 disabled:cursor-not-allowed transition-all flex items-center gap-1.5 text-sm font-medium shadow-sm"
          >
            {loading
              ? <div className="h-3.5 w-3.5 border-2 border-white border-t-transparent rounded-full animate-spin" />
              : <Send className="h-3.5 w-3.5" />}
            <span className="hidden sm:inline text-xs">Send</span>
          </button>
        </div>
      </div>
    </div>
  );
}

/* ═══════════════════════════════════════════════════════════════
   MAIN COMPONENT
══════════════════════════════════════════════════════════════ */

export default function DashboardAIAnalysis() {
  const { user } = useAuth();
  const [activeSection, setActiveSection] = useState<'realtime' | 'historical' | 'chat'>('realtime');
  const [days, setDays] = useState(DEFAULT_DAYS);
  const [historicalDays, setHistoricalDays] = useState(90);

  const [realtimeMessages, setRealtimeMessages] = useState<Message[]>([]);
  const [historicalMessages, setHistoricalMessages] = useState<Message[]>([]);
  const [chatMessages, setChatMessages] = useState<ChatMessage[]>([]);
  const [chatLoading, setChatLoading] = useState(false);
  const chatHistoryRef = useRef<{ role: string; content: string }[]>([]);
  /** Persisted schema-chat thread (server); restored from DB + localStorage on reload */
  const schemaChatThreadIdRef = useRef<string | null>(null);
  /** Which thread_id we already hydrated into UI (reset on effect cleanup for Strict Mode). */
  const schemaChatHydratedTidRef = useRef<string | null>(null);
  /** Blocks duplicate POSTs before React re-renders with chatLoading (double-click / Enter churn). */
  const schemaChatSendInFlightRef = useRef(false);

  // "New question" vs "Follow-up" mode
  // follow_up: answer from this thread's context (like ChatGPT follow-ups) — no new SQL
  // new: full SQL generation pipeline (default, always safe)
  const [queryMode, setQueryMode] = useState<'new' | 'follow_up'>('new');
  // Thread ID: stable per page load so all turns share a thread for follow-up context
  const threadIdRef = useRef<string>(
    `t_${Date.now()}_${Math.random().toString(36).slice(2, 8)}`
  );

  const schemaChatStorageKey = user ? `zodiac_schema_chat_thread_u${user.id}` : null;

  useEffect(() => {
    const saved = readSchemaChatThreadIdFromStorage(schemaChatStorageKey);
    if (saved) schemaChatThreadIdRef.current = saved;
  }, [schemaChatStorageKey]);

  /* Copy pending thread id to per-user key once auth is ready */
  useEffect(() => {
    if (!user?.id || typeof window === 'undefined') return;
    const uk = `zodiac_schema_chat_thread_u${user.id}`;
    const pending = localStorage.getItem(SCHEMA_CHAT_THREAD_PENDING_LS);
    if (!pending?.startsWith('sch_')) return;
    const existing = localStorage.getItem(uk);
    if (!existing?.startsWith('sch_')) {
      localStorage.setItem(uk, pending);
    }
  }, [user?.id]);

  useEffect(() => {
    if (activeSection !== 'chat' || !user || !schemaChatStorageKey) {
      return;
    }
    const tid =
      schemaChatThreadIdRef.current || readSchemaChatThreadIdFromStorage(schemaChatStorageKey);
    if (!tid?.startsWith('sch_')) {
      return;
    }
    if (chatMessages.length > 0) {
      return;
    }
    if (schemaChatHydratedTidRef.current === tid) {
      return;
    }
    schemaChatHydratedTidRef.current = tid;
    schemaChatThreadIdRef.current = tid;
    let cancelled = false;
    (async () => {
      try {
        const { messages } = await dashboardApi.getAISchemaChatHistory(tid);
        if (cancelled) return;
        if (!messages?.length) {
          clearSchemaChatThreadFromStorage(schemaChatStorageKey);
          schemaChatThreadIdRef.current = null;
          schemaChatHydratedTidRef.current = null;
          return;
        }
        const base = Date.now();
        setChatMessages(
          messages.map((m, i) => ({
            role: m.role as 'user' | 'assistant',
            content: m.content,
            ts: base - (messages.length - i) * 1000,
          })),
        );
        chatHistoryRef.current = messages.map((m) => ({ role: m.role, content: m.content }));
      } catch {
        schemaChatHydratedTidRef.current = null;
      }
    })();
    return () => {
      cancelled = true;
      schemaChatHydratedTidRef.current = null;
    };
  }, [activeSection, user, schemaChatStorageKey, chatMessages.length]);

  const startNewSchemaChat = () => {
    clearSchemaChatThreadFromStorage(schemaChatStorageKey);
    schemaChatThreadIdRef.current = null;
    schemaChatHydratedTidRef.current = null;
    chatHistoryRef.current = [];
    setChatMessages([]);
  };

  const [realtimeLoading, setRealtimeLoading] = useState(false);
  const [historicalLoading, setHistoricalLoading] = useState(false);

  // Progress tracking for loading state
  const [loadingElapsed, setLoadingElapsed] = useState(0);
  const [loadingStep, setLoadingStep] = useState(0);

  const [useContext, setUseContext] = useState(true);

  const [outboundData, setOutboundData] = useState<OutboundData | null>(null);
  const [inboundData, setInboundData] = useState<InboundData | null>(null);
  const [businessData, setBusinessData] = useState<BusinessData | null>(null);
  const [dataLoading, setDataLoading] = useState(true);

  const [error, setError] = useState<string | null>(null);
  const [timeScope, setTimeScope] = useState<'current' | 'historical' | 'both'>('current');

  /* ── Data fetch ─────────────────────────────────────────── */

  const fetchData = async (d: number) => {
    setDataLoading(true);
    try {
      const [outbound, inbound, business] = await Promise.all([
        dashboardApi.getV2Outbound(d),
        dashboardApi.getV2Inbound(d),
        dashboardApi.getV2Business(d),
      ]);
      setOutboundData(outbound || null);
      setInboundData(inbound || null);
      setBusinessData(business || null);
    } catch { /* silently fail */ }
    finally { setDataLoading(false); }
  };

  useEffect(() => { fetchData(days); }, [days]);

  // Timer effect for progress tracking
  const isAnyLoading = realtimeLoading || historicalLoading;
  useEffect(() => {
    if (isAnyLoading) {
      const start = Date.now();
      setLoadingElapsed(0);
      setLoadingStep(0);
      const interval = setInterval(() => {
        const elapsed = (Date.now() - start) / 1000;
        setLoadingElapsed(elapsed);
        if (elapsed < 4) setLoadingStep(0);
        else if (elapsed < 10) setLoadingStep(1);
        else if (elapsed < 22) setLoadingStep(2);
        else if (elapsed < 50) setLoadingStep(3);
        else setLoadingStep(4);
      }, 300);
      return () => clearInterval(interval);
    } else {
      setLoadingElapsed(0);
      setLoadingStep(0);
    }
  }, [isAnyLoading]);

  /* ── Send helpers ───────────────────────────────────────── */

  const sendMessage = async (section: 'realtime' | 'historical', text: string) => {
    const isRT = section === 'realtime';
    const setLoading = isRT ? setRealtimeLoading : setHistoricalLoading;
    const setMsgs = isRT ? setRealtimeMessages : setHistoricalMessages;
    const currentMsgs = isRT ? realtimeMessages : historicalMessages;
    const d = isRT ? days : historicalDays;

    setError(null);
    setMsgs((prev) => [...prev, { role: 'user', content: text, section, ts: Date.now() }]);
    setLoading(true);

    try {
      const lastAssistant = currentMsgs.slice().reverse().find((m) => m.role === 'assistant' && m.meta?.sql);
      const res = await dashboardApi.postAdaptiveQuery({
        question: text,
        tableHint: null,
        contextData: queryMode === 'follow_up' ? {
          previousQuestion: currentMsgs.slice().reverse().find((m) => m.role === 'user')?.content,
          previousSQL: lastAssistant?.meta?.sql,
          data: (lastAssistant?.meta?.rows_preview as any[]) || [],
        } : null,
      });

      // Reference-style follow-up response (no SQL)
      if (res?.type === 'analysis' && typeof res?.answer === 'string') {
        setMsgs((prev) => [...prev, {
          role: 'assistant',
          content: res.answer,
          meta: { action: 'follow_up', reason: 'contextData_analysis' },
          section,
          ts: Date.now(),
        }]);
        return;
      }

      // New query response
      if (res?.sql && queryMode === 'new') {
        setQueryMode('follow_up');
      }

      const reply = (res?.summary ?? res?.answer ?? '') || 'No response received.';
      const meta: AiAnalysisMeta = {
        action: queryMode === 'follow_up' ? 'follow_up' : 'new',
        reason: res?.retried ? 'auto_retry' : undefined,
        sql: res?.sql,
        rows_preview: Array.isArray(res?.data) ? res.data : undefined,
        charts: res?.charts,
      };

      const hasMeta = Boolean(
        meta.action || meta.sql || meta.validation || (meta.rows_preview?.length)
        || (meta.charts?.length) || meta.period_info || meta.adaptive_context,
      );
      setMsgs((prev) => [...prev, {
        role: 'assistant', content: reply,
        meta: hasMeta ? meta : undefined, section, ts: Date.now(),
      }]);
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : 'Failed to get AI response.';
      setError(msg);
      setMsgs((prev) => [...prev, { role: 'assistant', content: `Error: ${msg}`, section, ts: Date.now() }]);
    } finally {
      setLoading(false);
    }
  };

  /* ── Free chat with ChatGPT ──────────────────────────────── */
  const sendChatMessage = async (text: string) => {
    const trimmed = text.trim();
    if (!trimmed || schemaChatSendInFlightRef.current) return;
    schemaChatSendInFlightRef.current = true;
    setChatLoading(true);

    const tid =
      schemaChatThreadIdRef.current ||
      readSchemaChatThreadIdFromStorage(schemaChatStorageKey);

    try {
      // After refresh, localStorage still has sch_* but chatHistoryRef may be empty until
      // the hydrate effect finishes — prefetch so the POST always includes prior turns.
      if (chatHistoryRef.current.length === 0 && tid?.startsWith('sch_')) {
        try {
          const { messages: hist } = await dashboardApi.getAISchemaChatHistory(tid);
          if (hist?.length) {
            chatHistoryRef.current = hist.map((m) => ({ role: m.role, content: m.content }));
            schemaChatThreadIdRef.current = tid;
          }
        } catch {
          /* history optional; POST still uses server DB merge */
        }
      }

      const userMsg: ChatMessage = { role: 'user', content: trimmed, ts: Date.now() };
      setChatMessages((prev) => {
        if (prev.length === 0 && chatHistoryRef.current.length > 0) {
          const base = Date.now() - (chatHistoryRef.current.length + 1) * 1000;
          const priorUi: ChatMessage[] = chatHistoryRef.current.map((m, i) => ({
            role: m.role as 'user' | 'assistant',
            content: m.content,
            ts: base + i * 1000,
          }));
          return [...priorUi, userMsg];
        }
        return [...prev, userMsg];
      });

      // Build updated history including the new user message
      const history = [...chatHistoryRef.current, { role: 'user', content: trimmed }];

      // Use the dedicated schema-chat endpoint so every turn — including follow-up
      // questions like "is that right?", "what did I ask?", "where should we focus?" —
      // is answered from full conversation context without triggering SQL generation.
      const res = await dashboardApi.postAISchemaChat(
        trimmed,
        chatHistoryRef.current,
        tid ?? undefined,
      );
      const reply = res?.reply ?? 'No response received.';
      if (res?.thread_id) {
        schemaChatThreadIdRef.current = res.thread_id;
        writeSchemaChatThreadIdToStorage(schemaChatStorageKey, res.thread_id);
      }
      const assistantMsg: ChatMessage = { role: 'assistant', content: reply, ts: Date.now() };
      setChatMessages((prev) => [...prev, assistantMsg]);
      // Save full history (user + assistant) for next turn's context
      chatHistoryRef.current = [...history, { role: 'assistant', content: reply }];
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : 'Chat error. Please try again.';
      setChatMessages((prev) => [...prev, { role: 'assistant', content: `⚠️ ${msg}`, ts: Date.now() }]);
    } finally {
      schemaChatSendInFlightRef.current = false;
      setChatLoading(false);
    }
  };

  /* ── Derived stats ───────────────────────────────────────── */

  const f = outboundData?.funnel;
  const successRate = f && f.documents_received > 0
    ? Math.round((f.converted_success / f.documents_received) * 100) : null;
  const failRate = f && f.documents_received > 0
    ? Math.round(((f.validated_failed + f.converted_failed) / f.documents_received) * 100) : null;

  /* ══════════════════════════════════════════════════════════
     RENDER
  ════════════════════════════════════════════════════════════ */

  return (
    <div className="w-full -m-4 sm:-m-6 min-h-screen bg-gray-50 font-sans flex flex-col">
      <style>{`
        @import url('https://fonts.googleapis.com/css2?family=DM+Sans:ital,wght@0,300;0,400;0,500;0,600;1,400&family=IBM+Plex+Mono:wght@400;500;600;700&display=swap');
        body { font-family: 'DM Sans', sans-serif; }
        .font-mono, [class*="font-mono"] { font-family: 'IBM Plex Mono', monospace !important; }
        .tab-pill { transition: background 0.2s, color 0.2s, box-shadow 0.2s; }
        .tab-pill.active {
          background: linear-gradient(135deg, #3b82f6 0%, #6366f1 100%);
          color: #ffffff;
          box-shadow: 0 2px 8px rgba(59, 130, 246, 0.3);
        }
        .tab-pill:not(.active):hover { background: rgba(241, 245, 249, 0.8); }
        .fade-in { animation: fadeUp 0.3s ease both; }
        @keyframes fadeUp { from { opacity:0; transform: translateY(6px); } to { opacity:1; transform: none; } }
      `}</style>

      {/* ── Header ── */}
      <header className="sticky top-0 z-20 bg-white border-b border-slate-200 shadow-sm flex-shrink-0">
        <div className="w-full px-4 md:px-6 lg:px-8 h-14 flex items-center justify-between gap-4">
          <div className="flex items-center gap-3">
            <div className="flex items-center gap-2">
              <div className="w-7 h-7 rounded-lg bg-gradient-to-br from-blue-600 to-indigo-700 flex items-center justify-center shadow-md">
                <Zap className="h-3.5 w-3.5 text-white" />
              </div>
              <span className="font-mono text-sm font-bold text-slate-900 hidden sm:inline">Intelligence</span>
            </div>
            <div className="flex items-center gap-0.5 bg-slate-200 rounded-full p-0.5">
              {[
                { key: 'realtime', label: 'Real-time', icon: Activity },
                { key: 'historical', label: 'Historical', icon: BarChart3 },
                { key: 'chat', label: 'Chat', icon: MessageCircle },
              ].map(({ key, label, icon: Icon }) => (
                <button
                  key={key}
                  type="button"
                  onClick={() => setActiveSection(key as 'realtime' | 'historical' | 'chat')}
                  className={`tab-pill flex items-center gap-1.5 px-3 py-1.5 rounded-full text-xs font-medium ${activeSection === key ? 'active' : 'text-slate-600'}`}
                >
                  <Icon className="h-3 w-3" />
                  {label}
                </button>
              ))}
            </div>
          </div>

          <div className="flex items-center gap-2">
            <div className="flex items-center gap-1 text-xs text-slate-500">
              <Clock className="h-3 w-3" />
              <select
                value={activeSection === 'realtime' ? days : historicalDays}
                onChange={(e) => {
                  const v = Number(e.target.value);
                  activeSection === 'realtime' ? setDays(v) : setHistoricalDays(v);
                }}
                className="bg-transparent font-mono text-xs text-slate-700 focus:outline-none cursor-pointer"
              >
                {activeSection === 'realtime'
                  ? [7, 30, 90].map((d) => <option key={d} value={d}>{d}d</option>)
                  : [90, 180, 365].map((d) => <option key={d} value={d}>{d}d</option>)}
              </select>
            </div>
            <button
              type="button"
              onClick={() => fetchData(days)}
              disabled={dataLoading}
              className="w-8 h-8 rounded-lg bg-white border border-slate-200 flex items-center justify-center text-slate-500 hover:text-slate-800 hover:border-slate-400 transition-all disabled:opacity-50"
            >
              <RefreshCw className={`h-3.5 w-3.5 ${dataLoading ? 'animate-spin' : ''}`} />
            </button>
          </div>
        </div>
      </header>

      {/* ── Main content ── */}
      <main
        className={`flex-1 w-full px-4 md:px-6 lg:px-8 py-4 min-h-0 ${
          activeSection === 'chat' ? 'flex flex-col overflow-hidden' : 'overflow-y-auto'
        }`}
      >

        {/* ═══════════════════════════
            REAL-TIME SECTION
        ═══════════════════════════ */}
        {activeSection === 'realtime' && (
          <div className="fade-in flex flex-col gap-4">

            {/* Section title + KPIs */}
            <div className="flex-shrink-0 space-y-3">
              <div className="flex items-center gap-3">
                <LivePulse />
                <h1 className="text-sm font-semibold text-slate-900">Real-time Monitor</h1>
                <span className="text-xs font-mono text-slate-400">Last {days} days</span>
              </div>

              {/* KPI row */}
              <div className="grid grid-cols-2 md:grid-cols-4 gap-2.5">
                {dataLoading ? (
                  Array(4).fill(0).map((_, i) => (
                    <div key={i} className="rounded-xl border border-slate-200 bg-white p-4 animate-pulse h-16" />
                  ))
                ) : (
                  <>
                    <StatCard accent label="Docs received" value={f?.documents_received ?? 0} />
                    <StatCard label="Validated OK" value={f?.validated_success ?? 0}
                      sub={f?.validated_failed ? <span className="text-red-500 font-mono font-semibold">{f.validated_failed} failed</span> : <CheckCircle2 className="h-3 w-3 text-emerald-500" />} />
                    <StatCard label="Converted OK" value={f?.converted_success ?? 0}
                      sub={f?.converted_pending ? <span className="text-amber-500 font-mono font-semibold">{f.converted_pending} pending</span> : undefined} />
                    <StatCard label="Success rate" value={successRate !== null ? `${successRate}%` : '—'}
                      sub={failRate !== null && failRate > 0 ? <span className="text-red-500 font-mono font-semibold">{failRate}% fail</span> : undefined} />
                  </>
                )}
              </div>
            </div>

            {/* Data panels row: Inbound + Outbound side by side */}
            <div className="grid grid-cols-1 md:grid-cols-2 gap-3">

              {/* Inbound SAT */}
              <div className="rounded-2xl border border-slate-200 bg-white overflow-hidden flex flex-col">
                <div className="px-4 pt-3 pb-2.5 border-b border-slate-100 flex items-center justify-between flex-shrink-0">
                  <div className="flex items-center gap-2">
                    <ArrowUpFromLine className="h-3.5 w-3.5 text-slate-500" />
                    <h2 className="text-xs font-semibold text-slate-900">Inbound (SAT)</h2>
                  </div>
                  <LivePulse />
                </div>
                <div className="p-3 space-y-3 overflow-y-auto max-h-72 md:max-h-80">
                  {dataLoading ? (
                    <>{Array(3).fill(0).map((_, i) => <SkeletonRow key={i} />)}</>
                  ) : inboundData?.summary ? (
                    <>
                      <div className="grid grid-cols-3 gap-1.5 text-center">
                        {[
                          { v: inboundData.summary.total_documents, l: 'Total' },
                          { v: inboundData.summary.merges_sent_to_sap, l: 'In SAP' },
                          { v: inboundData.summary.merges_pending, l: 'Pending' },
                        ].map(({ v, l }) => (
                          <div key={l} className="rounded-lg bg-slate-50 py-2">
                            <div className="font-mono font-bold text-base text-slate-900 leading-none">{fmt(v)}</div>
                            <div className="text-[9px] text-slate-500 font-mono uppercase tracking-wide mt-0.5">{l}</div>
                          </div>
                        ))}
                      </div>
                      {inboundData.top_suppliers?.slice(0, 8).map((s, i) => (
                        <div key={i} className="flex items-center justify-between py-1.5 border-b border-slate-50 last:border-0">
                          <span className="text-xs text-slate-700 truncate flex-1 mr-3">{s.supplier_name || s.supplier_rfc}</span>
                          <span className="font-mono text-xs font-semibold text-slate-900 flex-shrink-0">{fmt(s.count)}</span>
                        </div>
                      ))}
                    </>
                  ) : (
                    <p className="text-xs text-slate-400 py-4 text-center">No inbound data</p>
                  )}
                </div>
              </div>

              {/* Outbound funnel */}
              <div className="rounded-2xl border border-slate-200 bg-white overflow-hidden flex flex-col">
                <div className="px-4 pt-3 pb-2.5 border-b border-slate-100 flex items-center justify-between flex-shrink-0">
                  <div className="flex items-center gap-2">
                    <ArrowDownToLine className="h-3.5 w-3.5 text-slate-500" />
                    <h2 className="text-xs font-semibold text-slate-900">Outbound Funnel</h2>
                  </div>
                  <GitBranch className="h-3.5 w-3.5 text-slate-400" />
                </div>
                <div className="p-3 space-y-2.5 overflow-y-auto max-h-72 md:max-h-80">
                  {dataLoading ? (
                    <>{Array(5).fill(0).map((_, i) => <SkeletonRow key={i} />)}</>
                  ) : f ? (
                    <>
                      <div className="space-y-2">
                        <FunnelStep step={1} label="Received" count={f.documents_received} total={f.documents_received} />
                        <FunnelStep step={2} label="Validated ✓" count={f.validated_success} total={f.documents_received} />
                        <FunnelStep step={3} label="Validation ✗" count={f.validated_failed} total={f.documents_received} warn />
                        <FunnelStep step={4} label="Converted ✓" count={f.converted_success} total={f.documents_received} />
                        <FunnelStep step={5} label="Converted ✗" count={f.converted_failed} total={f.documents_received} warn />
                        <FunnelStep step={6} label="Pending" count={f.converted_pending} total={f.documents_received} />
                      </div>
                      {outboundData?.top_customers?.length ? (
                        <div className="pt-2 border-t border-slate-100">
                          <div className="text-[9px] font-mono uppercase tracking-widest text-slate-400 mb-1.5">Top customers</div>
                          {outboundData.top_customers.slice(0, 5).map((c, i) => (
                            <div key={i} className="flex items-center justify-between py-1.5 border-b border-slate-50 last:border-0">
                              <span className="text-xs text-slate-700 truncate flex-1 mr-2">{c.customer_name || c.customer_id}</span>
                              <span className="font-mono text-[10px] text-slate-400 mr-2 flex-shrink-0">{c.currency}</span>
                              <span className="font-mono text-xs font-semibold text-slate-900 flex-shrink-0">{c.count}</span>
                            </div>
                          ))}
                        </div>
                      ) : null}
                    </>
                  ) : (
                    <p className="text-xs text-slate-400 py-4 text-center">No outbound data</p>
                  )}
                </div>
              </div>
            </div>

            {/* AI Chat — full width below data panels */}
            <div className="rounded-2xl border border-slate-200 bg-white overflow-hidden flex flex-col" style={{ minHeight: '420px' }}>
              <div className="px-4 pt-3 pb-2.5 border-b border-slate-100 flex items-center gap-2 flex-shrink-0">
                <Sparkles className="h-3.5 w-3.5 text-blue-600" />
                <h2 className="text-xs font-semibold text-slate-900">AI Analysis</h2>
                <LivePulse />
                <span className="ml-auto text-[10px] font-mono text-slate-400 bg-slate-100 rounded-full px-2 py-0.5">Real-time</span>
              </div>
              <div className="flex-1 min-h-0 overflow-hidden flex flex-col">
                <ChatPanel
                  section="realtime"
                  messages={realtimeMessages}
                  loading={realtimeLoading}
                  loadingStep={realtimeLoading ? loadingStep : 0}
                  loadingElapsed={realtimeLoading ? loadingElapsed : 0}
                  prompts={REALTIME_PROMPTS}
                  onSend={(t) => void sendMessage('realtime', t)}
                  placeholder="e.g. Show failed invoices by customer, or list open purchase orders…"
                  useContext={useContext}
                  setUseContext={setUseContext}
                  queryMode={queryMode}
                  setQueryMode={setQueryMode}
                  timeScope={timeScope}
                  setTimeScope={setTimeScope}
                  fullWidth
                />
              </div>
            </div>

            {error && (
              <div className="rounded-xl bg-red-50 border border-red-200 px-4 py-2.5 text-sm text-red-700">
                {error}
              </div>
            )}
          </div>
        )}

        {/* ═══════════════════════════
            HISTORICAL SECTION
        ═══════════════════════════ */}
        {activeSection === 'historical' && (
          <div className="fade-in h-full flex flex-col gap-4">

            {/* Title + Revenue cards */}
            <div className="flex-shrink-0 space-y-3">
              <div className="flex items-center gap-3">
                <CalendarRange className="h-4 w-4 text-slate-600" />
                <h1 className="text-sm font-semibold text-slate-900">Historical Analysis &amp; Forecasting</h1>
                <span className="text-xs font-mono text-slate-400">Last {historicalDays} days</span>
              </div>

              <div className="grid grid-cols-1 sm:grid-cols-3 gap-2.5">
                {dataLoading ? (
                  Array(3).fill(0).map((_, i) => (
                    <div key={i} className="rounded-xl border border-slate-200 bg-white p-4 animate-pulse h-16" />
                  ))
                ) : (
                  <>
                    <StatCard accent label="Current period revenue"
                      value={businessData?.trend?.current_period_revenue ?? 0}
                      sub={businessData?.trend && <TrendBadge pct={businessData.trend.revenue_change_pct} />}
                    />
                    <StatCard label="Previous period"
                      value={businessData?.trend?.previous_period_revenue ?? 0}
                    />
                    <StatCard label="Revenue change"
                      value={businessData?.trend ? `${businessData.trend.revenue_change_pct >= 0 ? '+' : ''}${businessData.trend.revenue_change_pct}%` : '—'}
                      sub={
                        businessData?.trend
                          ? businessData.trend.revenue_change_pct >= 0
                            ? <span className="text-emerald-600 font-mono">↑ Positive trend</span>
                            : <span className="text-red-500 font-mono">↓ Declining</span>
                          : undefined
                      }
                    />
                  </>
                )}
              </div>
            </div>

            {/* 3-col layout: revenue by customer | revenue by country | AI chat (2x) */}
            <div className="flex-1 min-h-0 grid grid-cols-1 lg:grid-cols-[1fr_1fr_2fr] gap-3 overflow-hidden">

              {/* Revenue by customer */}
              <div className="rounded-2xl border border-slate-200 bg-white overflow-hidden flex flex-col min-h-0">
                <div className="px-4 pt-3 pb-2.5 border-b border-slate-100 flex items-center gap-2 flex-shrink-0">
                  <TrendingUp className="h-3.5 w-3.5 text-slate-500" />
                  <h2 className="text-xs font-semibold text-slate-900">By Customer</h2>
                </div>
                <div className="p-3 flex-1 overflow-y-auto">
                  {dataLoading ? (
                    <>{Array(6).fill(0).map((_, i) => <SkeletonRow key={i} />)}</>
                  ) : businessData?.revenue_by_customer?.length ? (
                    <div className="space-y-2">
                      {businessData.revenue_by_customer.slice(0, 10).map((c, i) => {
                        const max = businessData.revenue_by_customer![0].total_revenue;
                        const pct = max > 0 ? Math.round((c.total_revenue / max) * 100) : 0;
                        return (
                          <div key={i}>
                            <div className="flex items-center justify-between mb-0.5">
                              <span className="text-xs text-slate-700 truncate flex-1 mr-3">{c.customer_name || c.customer_id}</span>
                              <span className="font-mono text-xs font-semibold text-slate-900 flex-shrink-0">{fmt(c.total_revenue)}</span>
                            </div>
                            <div className="h-1 bg-slate-100 rounded-full overflow-hidden">
                              <div className="h-full bg-gradient-to-r from-blue-600 to-indigo-700 rounded-full transition-all duration-700"
                                style={{ width: `${pct}%` }} />
                            </div>
                          </div>
                        );
                      })}
                    </div>
                  ) : (
                    <p className="text-xs text-slate-400 py-6 text-center">No revenue data</p>
                  )}
                </div>
              </div>

              {/* Revenue by country */}
              <div className="rounded-2xl border border-slate-200 bg-white overflow-hidden flex flex-col min-h-0">
                <div className="px-4 pt-3 pb-2.5 border-b border-slate-100 flex items-center gap-2 flex-shrink-0">
                  <Eye className="h-3.5 w-3.5 text-slate-500" />
                  <h2 className="text-xs font-semibold text-slate-900">By Country</h2>
                </div>
                <div className="p-3 flex-1 overflow-y-auto">
                  {dataLoading ? (
                    <>{Array(5).fill(0).map((_, i) => <SkeletonRow key={i} />)}</>
                  ) : businessData?.revenue_by_country?.length ? (
                    <div className="space-y-2">
                      {businessData.revenue_by_country.slice(0, 10).map((c, i) => {
                        const max = businessData.revenue_by_country![0].total_revenue;
                        const pct = max > 0 ? Math.round((c.total_revenue / max) * 100) : 0;
                        return (
                          <div key={i}>
                            <div className="flex items-center justify-between mb-0.5">
                              <span className="text-xs text-slate-700 truncate flex-1 mr-2">{c.country_name || c.country}</span>
                              <div className="flex items-center gap-2 flex-shrink-0">
                                <span className="font-mono text-[10px] text-slate-400">{c.invoice_count}</span>
                                <span className="font-mono text-xs font-semibold text-slate-900">{fmt(c.total_revenue)}</span>
                              </div>
                            </div>
                            <div className="h-1 bg-slate-100 rounded-full overflow-hidden">
                              <div className="h-full bg-gradient-to-r from-blue-500 to-indigo-600 rounded-full transition-all duration-700"
                                style={{ width: `${pct}%` }} />
                            </div>
                          </div>
                        );
                      })}
                    </div>
                  ) : (
                    <p className="text-xs text-slate-400 py-6 text-center">No country data</p>
                  )}
                </div>
              </div>

              {/* AI Trend Analysis */}
              <div className="rounded-2xl border border-slate-200 bg-white overflow-hidden flex flex-col min-h-0">
                <div className="px-4 pt-3 pb-2.5 border-b border-slate-100 flex items-center gap-2 flex-shrink-0">
                  <FlaskConical className="h-3.5 w-3.5 text-slate-500" />
                  <h2 className="text-xs font-semibold text-slate-900">AI Trend Analysis &amp; Forecasting</h2>
                  <span className="ml-auto text-[10px] font-mono text-slate-400 bg-slate-100 rounded-full px-2 py-0.5">Historical</span>
                </div>

                {/* Quick action tiles */}
                <div className="px-3 pt-2.5 pb-0 grid grid-cols-2 md:grid-cols-5 gap-2 flex-shrink-0">
                  {[
                    { label: 'Profit margin', query: 'Show profit margin by product for all products in the database', icon: DollarSign },
                    { label: 'Forecast', query: 'Based on historical patterns, forecast next period revenue and invoice volume', icon: TrendingUp },
                    { label: 'Compare periods', query: 'Compare current period performance to the previous period with key insights', icon: BarChart3 },
                    { label: 'Anomalies', query: 'Identify any anomalies or unusual patterns in the historical data', icon: AlertTriangle },
                    { label: 'Growth drivers', query: 'What are the main drivers of revenue growth or decline in the historical data?', icon: TrendingDown },
                  ].map(({ label, query, icon: Icon }) => (
                    <button
                      key={label}
                      type="button"
                      onClick={() => sendMessage('historical', query)}
                      disabled={historicalLoading}
                      className="rounded-xl border border-slate-200 bg-slate-50 hover:bg-gradient-to-br hover:from-blue-600 hover:to-indigo-700 hover:border-blue-600 hover:text-white text-slate-700 px-2 py-2 text-left transition-all group disabled:opacity-50 hover:shadow-md flex items-center gap-1.5"
                    >
                      <Icon className="h-3 w-3 flex-shrink-0 group-hover:text-white transition-colors" />
                      <span className="text-[11px] font-medium leading-tight">{label}</span>
                    </button>
                  ))}
                </div>

                <div className="flex-1 min-h-0 overflow-hidden flex flex-col mt-1">
                  <ChatPanel
                    section="historical"
                    messages={historicalMessages}
                    loading={historicalLoading}
                    loadingStep={historicalLoading ? loadingStep : 0}
                    loadingElapsed={historicalLoading ? loadingElapsed : 0}
                    prompts={HISTORICAL_PROMPTS}
                    onSend={(t) => void sendMessage('historical', t)}
                    placeholder="e.g. Compare periods, forecast revenue, or analyze historical SAP billing data…"
                    useContext={useContext}
                    setUseContext={setUseContext}
                    queryMode={queryMode}
                    setQueryMode={setQueryMode}
                    timeScope={timeScope}
                    setTimeScope={setTimeScope}
                  />
                </div>
              </div>
            </div>

            {error && (
              <div className="rounded-xl bg-red-50 border border-red-200 px-4 py-2.5 text-sm text-red-700">
                {error}
              </div>
            )}
          </div>
        )}

        {activeSection === 'chat' && (
          <div className="fade-in flex flex-col flex-1 min-h-0 gap-4 max-h-[calc(100dvh-7rem)] h-[calc(100dvh-7rem)]">
            <ChatGPTPanel
              messages={chatMessages}
              loading={chatLoading}
              onSend={sendChatMessage}
              onNewChat={startNewSchemaChat}
            />
          </div>
        )}

      </main>
    </div>
  );
}