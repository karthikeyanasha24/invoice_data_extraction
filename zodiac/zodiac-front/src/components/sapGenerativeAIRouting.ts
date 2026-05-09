/**
 * Client-side routing hints for the Generative AI panels (Realtime / Historical).
 * Prepends structured context to user_query so the backend orchestrator can pick
 * better tables/joins — similar in spirit to a LangGraph "schema classify" node,
 * without bundling megabyte JSON exports.
 */

export type GenerativeRoutingId =
  | 'billing_sales'
  | 'sales_orders'
  | 'delivery'
  | 'product_master'
  | 'customer_vendor'
  | 'purchasing'
  | 'finance'
  | 'costing'
  | 'copapa'
  | 'zodiac_sat';

export type GenerativeRoutingFocus = GenerativeRoutingId | 'auto';

type Preset = {
  id: GenerativeRoutingId;
  label: string;
  keywords: RegExp[];
  /** Primary SAP tables — names as used in prompts / typical SQL */
  tables: { name: string; role: string; columns: string[] }[];
  notes: string[];
};

function norm(s: string) {
  return s.toLowerCase();
}

/** Curated presets: transaction vs master, join hints, Andy-style billing/product rules */
const ROUTING_PRESETS: Preset[] = [
  {
    id: 'billing_sales',
    label: 'Billing & revenue',
    keywords: [
      /\binvoice\b/i,
      /\bbilling\b/i,
      /\bnetwr\b/i,
      /\bvb(?:rk|rp)\b/i,
      /\bgi ?revenue\b/i,
      /\bsales value\b/i,
      /\bfaktur/i,
      /\bnegative sales\b/i,
      /\bmargin\b/i,
      /\bprofit\b/i,
    ],
    tables: [
      {
        name: 'VBRK',
        role: 'transaction_header',
        columns: ['VBELN', 'FKDAT', 'FKART', 'WAERK', 'KUNRG', 'NETWR', 'MWSBK', 'BTGEW'],
      },
      {
        name: 'vbrp',
        role: 'transaction_item',
        columns: ['VBELN', 'POSNR', 'MATNR', 'ARKTX', 'FKIMG', 'NETWR', 'WAERK', 'WERKS', 'AUBEL'],
      },
      {
        name: 'MARA',
        role: 'master_material',
        columns: ['MATNR', 'MATKL', 'MTART', 'MEINS', 'BRGEW'],
      },
      {
        name: 'MAKT',
        role: 'master_text',
        columns: ['MATNR', 'MAKTX'],
      },
      {
        name: 'MEAN',
        role: 'master_ean',
        columns: ['MATNR', 'EAN11', 'EANTP'],
      },
      {
        name: 'MVKE',
        role: 'master_sales_org_mat',
        columns: ['MATNR', 'VKORG', 'VTWEG', 'SPART'],
      },
      {
        name: 'MARC',
        role: 'master_plant_mat',
        columns: ['MATNR', 'WERKS', 'EKGRP'],
      },
    ],
    notes: [
      'Document-level billed amount → VBRK.NETWR (header); line breakdown / products → vbrp (join VBRK.VBELN = vbrp.VBELN).',
      'Product drill-down: vbrp.MATNR → MARA → MAKT (text); extend with MEAN, MVKE, MARC only when/detail requires.',
      'When reporting monetary totals always include currency (WAERK) and differentiate abbreviated scale vs exact formatted values.',
      'Avoid T016T and unrelated Industry joins unless the user explicitly asks for credit-control area texts or similar.',
    ],
  },
  {
    id: 'sales_orders',
    label: 'Sales orders',
    keywords: [
      /\bsales order\b/i,
      /\bvbak\b/i,
      /\bvbap\b/i,
      /\bvbep\b/i,
      /\baufnr\b/i,
      /\bvbfa\b/i,
      /\border line\b/i,
    ],
    tables: [
      { name: 'VBAK', role: 'transaction_header', columns: ['VBELN', 'AUART', 'VKORG', 'KUNNR', 'ERDAT', 'NETWR'] },
      { name: 'VBAP', role: 'transaction_item', columns: ['VBELN', 'POSNR', 'MATNR', 'KWMENG', 'NETWR'] },
      { name: 'VBEP', role: 'schedule', columns: ['VBELN', 'POSNR', 'ETENR', 'EDATU', 'WMENG'] },
      { name: 'KONV', role: 'pricing', columns: ['KNUMV', 'KPOSN', 'KSCHL', 'KBETR', 'WAERS'] },
    ],
    notes: [
      'VBAK/VBAP are transactional; join to product master via MATNR only when breakdown by material/description is requested.',
    ],
  },
  {
    id: 'delivery',
    label: 'Delivery & logistics',
    keywords: [
      /\bdelivery\b/i,
      /\blikp\b/i,
      /\blips\b/i,
      /\bshipment\b/i,
      /\btransfer order\b/i,
    ],
    tables: [
      { name: 'LIKP', role: 'transaction_header', columns: ['VBELN', 'VSTEL', 'KUNNR', 'WADAT', 'LFART'] },
      { name: 'LIPS', role: 'transaction_item', columns: ['VBELN', 'POSNR', 'MATNR', 'LFIMG', 'WERKS', 'LGORT'] },
    ],
    notes: ['Link Deliveries ↔ Sales/Billing via document flow VBFA or VBELN where business rules allow.', 'Use LIKP/LIPS for logistics status, VBRK/vbrp for billed revenue.'],
  },
  {
    id: 'product_master',
    label: 'Materials & BOM',
    keywords: [
      /\bmaterial\b/i,
      /\bmara\b/i,
      /\bmakt\b/i,
      /\bmbom\b/i,
      /\bstko\b/i,
      /\bstpo\b/i,
      /\beats?\b/i,
      /\bmaterial master\b/i,
    ],
    tables: [
      { name: 'MARA', role: 'master', columns: ['MATNR', 'MATKL', 'MTART', 'MEINS'] },
      { name: 'MAKT', role: 'master_text', columns: ['MATNR', 'SPRAS', 'MAKTX'] },
      { name: 'MARC', role: 'master_plant', columns: ['MATNR', 'WERKS', 'DISPO', 'BESKZ'] },
      { name: 'MARD', role: 'master_stock_loc', columns: ['MATNR', 'WERKS', 'LGORT', 'LABST'] },
    ],
    notes: ['Master-data tables augment transactions; aggregate sales from vbrp/VBAK, not from MARA alone.'],
  },
  {
    id: 'customer_vendor',
    label: 'Customer / vendor master',
    keywords: [
      /\bcustomer\b/i,
      /\bkna1\b/i,
      /\bknvv\b/i,
      /\bvendor\b/i,
      /\blfa1\b/i,
      /\blfb1\b/i,
      /\bpayer\b/i,
      /\bsold-?to\b/i,
    ],
    tables: [
      { name: 'KNA1', role: 'master_customer', columns: ['KUNNR', 'NAME1', 'ORT01', 'LAND1'] },
      { name: 'KNVV', role: 'master_cust_sales', columns: ['KUNNR', 'VKORG', 'VTWEG', 'SPART', 'KDGRP'] },
      { name: 'LFA1', role: 'master_vendor', columns: ['LIFNR', 'NAME1', 'LAND1'] },
      { name: 'LFB1', role: 'master_vend_company', columns: ['LIFNR', 'BUKRS', 'AKONT'] },
    ],
    notes: ['Join transactional tables (VBAK/KUNNR, VBRK/KUNRG, etc.) to KNA1/KNVV for names and attributes.'],
  },
  {
    id: 'purchasing',
    label: 'Purchasing & MM invoices',
    keywords: [
      /\bpurchase order\b/i,
      /\bekko\b/i,
      /\bekpo\b/i,
      /\binvoice receipt\b/i,
      /\brbkp\b/i,
      /\brseg\b/i,
      /\biban\b/i,
      /\bmm-?iv\b/i,
    ],
    tables: [
      { name: 'EKKO', role: 'po_header', columns: ['EBELN', 'BUKRS', 'LIFNR', 'BEDAT', 'WAERS'] },
      { name: 'EKPO', role: 'po_item', columns: ['EBELN', 'EBELP', 'MATNR', 'MENGE', 'NETWR'] },
      { name: 'RBKP', role: 'mm_iv_header', columns: ['BELNR', 'GJAHR', 'BLDAT', 'RMWWR', 'WAERS'] },
      { name: 'RSEG', role: 'mm_iv_item', columns: ['BELNR', 'GJAHR', 'BUZEI', 'EBELN', 'EBELP', 'WRBTR'] },
    ],
    notes: ['Separate MM invoice (RBKP/RSEG) flows from SD billing (VBRK/vbrp).'],
  },
  {
    id: 'finance',
    label: 'FI / accounting',
    keywords: [
      /\bgl\b/i,
      /\bledger\b/i,
      /\bbf\.?bss\b|\bbkpf\b/i,
      /\bbseg\b/i,
      /\bopen items\b/i,
      /\bbsad\b/i,
      /\bposting\b/i,
    ],
    tables: [
      { name: 'BKPF', role: 'fi_header', columns: ['BUKRS', 'BELNR', 'GJAHR', 'BLDAT'] },
      { name: 'BSEG', role: 'fi_item', columns: ['BUKRS', 'BELNR', 'GJAHR', 'BUZEI', 'KOART', 'DMBTR', 'WRBTR'] },
      { name: 'BSAD', role: 'ar_open', columns: ['KUNNR', 'BELNR', 'GJAHR', 'DMBTR', 'WAERS'] },
    ],
    notes: ['Do not substitute FI aggregates for billing net values when question is invoice/revenue wording.'],
  },
  {
    id: 'costing',
    label: 'Costing / production',
    keywords: [
      /\bcost(?:ing)? estimate\b/i,
      /\bcost component\b/i,
      /\bakko\b|\baufk\b|\bafko\b|\bafpo\b/i,
      /\bckis\b|\bckko\b|\bkeph\b|\bkeko\b/i,
      /\bproduction order\b/i,
    ],
    tables: [
      { name: 'CKIS', role: 'cost_item', columns: ['KALNR', 'KKZMA', 'KSTAR', 'MENGE', 'CASTH'] },
      { name: 'KEKO', role: 'product_cost_hdr', columns: ['KALNR', 'MATNR', 'WERKS', 'BSTNK'] },
      { name: 'KEPH', role: 'cost_component', columns: ['KALNR', 'VERSN', 'KALKA', 'KADKY'] },
      { name: 'AUFK', role: 'order_master', columns: ['AUFNR', 'AUTYP', 'AUART'] },
      { name: 'AFPO', role: 'order_item', columns: ['AUFNR', 'POSNR', 'MATNR', 'PSOBS'] },
    ],
    notes: ['Costing complements SD line data; profitability may combine vbrp with CKIS/KERK paths depending on data availability.'],
  },
  {
    id: 'copapa',
    label: 'CO-PA',
    keywords: [/\bcopa\b/i, /\bprofitability segment\b/i, /\bce1\b/i, /\bce2\b/i],
    tables: [
      { name: 'CE1*', role: 'copa_actuals', columns: ['see table variant'] },
      { name: 'CE2*', role: 'copa_plan', columns: ['see table variant'] },
    ],
    notes: ['CE1*/CE2* tables are client-specific profitability structures; qualify with correct table suffix for installation.'],
  },
  {
    id: 'zodiac_sat',
    label: 'Zodiac / EDI / SAT',
    keywords: [
      /\bzodiac\b/i,
      /\bedi\b/i,
      /\bsat[_ ]/i,
      /\bconverted invoice\b/i,
      /\bai_analysis_memory\b/i,
      /\bai_query_memory\b/i,
    ],
    tables: [],
    notes: ['App tables vs SAP: operational queries resolve to Postgres Zodiac tables, not replicated in SAP validators.'],
  },
];

export function inferGenerativeRoutingId(question: string, manual: GenerativeRoutingFocus): GenerativeRoutingId {
  if (manual !== 'auto') return manual;

  const q = norm(question);
  let best: GenerativeRoutingId = 'billing_sales';
  let bestScore = -1;

  for (const p of ROUTING_PRESETS) {
    let score = 0;
    for (const rx of p.keywords) {
      if (rx.test(q)) score += 1;
    }
    if (score > bestScore) {
      bestScore = score;
      best = p.id;
    }
  }
  return bestScore > 0 ? best : 'billing_sales';
}

function presetById(id: GenerativeRoutingId): Preset {
  const p = ROUTING_PRESETS.find((x) => x.id === id);
  return p ?? ROUTING_PRESETS[0];
}

function yamlishTables(tables: Preset['tables']) {
  if (!tables.length) return '  (no static table list — infer from catalog)';
  return tables
    .map((t) => {
      const cols = t.columns.join(', ');
      return `  - ${t.name}: { role: ${t.role}, columns: [${cols}] }`;
    })
    .join('\n');
}

/**
 * Visible user text stays unchanged in the UI; this string is sent as `message`
 * so the orchestrator sees routing + catalogue hints without altering chat history UX.
 */
export function buildAugmentedGenerativeQuestion(
  userText: string,
  opts: {
    queryMode: 'new' | 'follow_up';
    section: 'realtime' | 'historical';
    routingFocus: GenerativeRoutingFocus;
  },
): string {
  const id = inferGenerativeRoutingId(userText, opts.routingFocus);
  const preset = presetById(id);

  const head =
    `[ZODIAC_GENERATIVE_CLIENT_ROUTING v=1]` +
    `\nanalysis_panel: ${opts.section}` +
    `\nquery_mode: ${opts.queryMode}` +
    `\nrouting_bucket: ${preset.label} (${preset.id})` +
    `\nmaster_vs_transaction: Transaction tables carry facts (amounts, dates, quantities); ` +
    `master tables provide attributes (material text, customer name). Prefer correct grain: header totals vs item lines.` +
    `\ntable_hints:\n${yamlishTables(preset.tables)}` +
    `\nguidelines:\n${preset.notes.map((n) => `  - ${n}`).join('\n')}` +
    `\ncontinuous_analysis: ${opts.queryMode === 'follow_up' ? `If drill-down / deeper analysis, reuse prior constraints (years, currencies, customers, doc subsets) unless the question widens scope.` : 'fresh topic — establish filters only from question.'}` +
    `\n[/ZODIAC_GENERATIVE_CLIENT_ROUTING]`;

  return `${head}\n\nUser question:\n${userText.trim()}`;
}

export const GENERATIVE_ROUTING_OPTIONS: { id: GenerativeRoutingFocus; short: string }[] = [
  { id: 'auto', short: 'Auto' },
  { id: 'billing_sales', short: 'Billing' },
  { id: 'sales_orders', short: 'Orders' },
  { id: 'delivery', short: 'Delivery' },
  { id: 'product_master', short: 'Materials' },
  { id: 'customer_vendor', short: 'BP master' },
  { id: 'purchasing', short: 'MM / PO' },
  { id: 'finance', short: 'FI' },
  { id: 'costing', short: 'Costing' },
  { id: 'copapa', short: 'CO-PA' },
  { id: 'zodiac_sat', short: 'Zodiac' },
];
