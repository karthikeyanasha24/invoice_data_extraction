/** Guided query-scope builder for Basic SQL Training (not invoices-only). */

export type RestrictionMode = 'all' | 'specific' | 'by_entity';
export type PeriodMode = 'year' | 'year_range' | 'all_years' | 'none';
export type FilterOperator = 'include_value' | 'include_range' | 'exclude_value' | 'exclude_range' | 'greater_than' | 'less_than';
export type RestrictionFilter = {
  table: string;
  column: string;
  operator: FilterOperator;
  value: string;
  upper: string;
};

export type RestrictionProfile = {
  id: 'billing' | 'sales_order' | 'customer' | 'purchasing' | 'generic';
  label: string;
  primaryTable: string;
  documentField?: string;
  entityField?: string;
  entityLabel: string;
  dateField?: string;
  amountField?: string;
  modes: { id: RestrictionMode; label: string }[];
};

const FACT_TABLES = new Set([
  'vbrk', 'vbrp', 'vbak', 'vbap', 'likp', 'lips', 'ekko', 'ekpo', 'bkpf', 'bseg', 'acdoca',
]);

const PROFILES: Omit<RestrictionProfile, 'primaryTable'>[] = [
  {
    id: 'billing',
    label: 'Billing / invoices',
    documentField: 'vbeln',
    entityField: 'kunag',
    entityLabel: 'customer',
    dateField: 'fkdat',
    amountField: 'netwr',
    modes: [
      { id: 'all', label: 'All billing documents' },
      { id: 'specific', label: 'Specific invoice number' },
      { id: 'by_entity', label: 'By customer' },
    ],
  },
  {
    id: 'sales_order',
    label: 'Sales orders',
    documentField: 'vbeln',
    entityField: 'kunnr',
    entityLabel: 'customer',
    dateField: 'audat',
    amountField: 'netwr',
    modes: [
      { id: 'all', label: 'All sales orders' },
      { id: 'specific', label: 'Specific sales order' },
      { id: 'by_entity', label: 'By customer' },
    ],
  },
  {
    id: 'purchasing',
    label: 'Purchasing',
    documentField: 'ebeln',
    entityField: 'lifnr',
    entityLabel: 'vendor',
    dateField: 'bedat',
    amountField: 'netwr',
    modes: [
      { id: 'all', label: 'All purchase orders' },
      { id: 'specific', label: 'Specific purchase order' },
      { id: 'by_entity', label: 'By vendor' },
    ],
  },
  {
    id: 'customer',
    label: 'Customers',
    documentField: 'kunnr',
    entityField: 'land1',
    entityLabel: 'country',
    modes: [
      { id: 'all', label: 'All customers' },
      { id: 'specific', label: 'Specific customer number' },
      { id: 'by_entity', label: 'By country' },
    ],
  },
];

function pickTable(selected: string[], candidates: string[]): string | undefined {
  const lower = new Map(selected.map(name => [name.toLowerCase(), name]));
  for (const candidate of candidates) {
    const match = lower.get(candidate);
    if (match) return match;
  }
  return undefined;
}

export function detectRestrictionProfile(selectedTables: string[]): RestrictionProfile {
  const selected = selectedTables.filter(Boolean);
  const billing = pickTable(selected, ['vbrk', 'vbrp']);
  if (billing) {
    const primary = pickTable(selected, ['vbrk']) || billing;
    return { ...PROFILES[0], primaryTable: primary };
  }
  const sales = pickTable(selected, ['vbak', 'vbap']);
  if (sales) {
    const primary = pickTable(selected, ['vbak']) || sales;
    return { ...PROFILES[1], primaryTable: primary };
  }
  const purchasing = pickTable(selected, ['ekko', 'ekpo']);
  if (purchasing) {
    const primary = pickTable(selected, ['ekko']) || purchasing;
    return { ...PROFILES[2], primaryTable: primary };
  }
  const customer = pickTable(selected, ['kna1', 'knvv']);
  if (customer) {
    const primary = pickTable(selected, ['kna1']) || customer;
    return { ...PROFILES[3], primaryTable: primary };
  }
  const primary = selected[0] || 'selected_table';
  return {
    id: 'generic',
    label: 'Selected tables',
    primaryTable: primary,
    documentField: undefined,
    entityField: undefined,
    entityLabel: 'key value',
    dateField: undefined,
    amountField: undefined,
    modes: [
      { id: 'all', label: 'All rows (must set a year or confirm all years)' },
      { id: 'specific', label: 'Specific document / key' },
      { id: 'by_entity', label: 'By related entity value' },
    ],
  };
}

export function selectedHasFactTable(selectedTables: string[]): boolean {
  return selectedTables.some(table => FACT_TABLES.has(table.toLowerCase()));
}

function yearBounds(year: string): { start: string; endExclusive: string } | null {
  if (!/^(19|20)\d{2}$/.test(year)) return null;
  const next = String(Number(year) + 1);
  return { start: `${year}0101`, endExclusive: `${next}0101` };
}

export type RestrictionDraft = {
  mode: RestrictionMode;
  period: PeriodMode;
  year: string;
  yearTo: string;
  specificValue: string;
  entityValue: string;
  client: string;
  allowUnrestricted: boolean;
  documentFieldOverride?: string;
  entityFieldOverride?: string;
  dateFieldOverride?: string;
};

export function validateRestrictionDraft(
  profile: RestrictionProfile,
  draft: RestrictionDraft,
): string | null {
  const documentField = draft.documentFieldOverride || profile.documentField;
  const entityField = draft.entityFieldOverride || profile.entityField;
  if (draft.mode === 'specific') {
    if (!documentField) return 'Choose a document/key field for a specific-value restriction.';
    if (!draft.specificValue.trim()) return `Enter the ${profile.modes.find(mode => mode.id === 'specific')?.label.toLowerCase() || 'specific value'}.`;
  }
  if (draft.mode === 'by_entity') {
    if (!entityField) return `Choose a ${profile.entityLabel} field.`;
    if (!draft.entityValue.trim()) return `Enter a ${profile.entityLabel} value.`;
  }
  if (draft.mode === 'all') {
    if (draft.period === 'none' && !draft.allowUnrestricted) {
      return 'Pick a calendar year, a year range, or confirm “all years / unrestricted”. Wildcard scans are blocked.';
    }
    if (draft.period === 'year' && !yearBounds(draft.year.trim())) {
      return 'Enter a valid four-digit calendar year (for example 2000).';
    }
    if (draft.period === 'year_range') {
      if (!yearBounds(draft.year.trim()) || !yearBounds(draft.yearTo.trim())) {
        return 'Enter a valid from/to calendar year range.';
      }
      if (Number(draft.year) > Number(draft.yearTo)) {
        return 'The from year must not be after the to year.';
      }
    }
  } else if (draft.period === 'year' && draft.year.trim() && !yearBounds(draft.year.trim())) {
    return 'Enter a valid four-digit calendar year, or clear it.';
  } else if (draft.period === 'year_range') {
    if (!yearBounds(draft.year.trim()) || !yearBounds(draft.yearTo.trim())) {
      return 'Enter a valid from/to calendar year range, or switch period mode.';
    }
    if (Number(draft.year) > Number(draft.yearTo)) {
      return 'The from year must not be after the to year.';
    }
  }
  return null;
}

export function buildRestrictionFilters(
  profile: RestrictionProfile,
  draft: RestrictionDraft,
): RestrictionFilter[] {
  const filters: RestrictionFilter[] = [];
  const table = profile.primaryTable;
  const documentField = draft.documentFieldOverride || profile.documentField;
  const entityField = draft.entityFieldOverride || profile.entityField;
  const dateField = draft.dateFieldOverride || profile.dateField;

  if (draft.client.trim()) {
    filters.push({
      table,
      column: 'mandt',
      operator: 'include_value',
      value: draft.client.trim(),
      upper: '',
    });
  }
  if (draft.mode === 'specific' && documentField && draft.specificValue.trim()) {
    filters.push({
      table,
      column: documentField,
      operator: 'include_value',
      value: draft.specificValue.trim(),
      upper: '',
    });
  }
  if (draft.mode === 'by_entity' && entityField && draft.entityValue.trim()) {
    filters.push({
      table,
      column: entityField,
      operator: 'include_value',
      value: draft.entityValue.trim(),
      upper: '',
    });
  }
  if (dateField && (draft.period === 'year' || draft.period === 'year_range')) {
    const from = yearBounds(draft.year.trim());
    const to = draft.period === 'year_range' ? yearBounds(draft.yearTo.trim()) : from;
    if (from && to) {
      const endYear = draft.period === 'year_range' ? draft.yearTo.trim() : draft.year.trim();
      const endExclusive = yearBounds(endYear)?.endExclusive;
      if (endExclusive) {
        // Training filters use inclusive BETWEEN; map half-open year range to last day of end year.
        filters.push({
          table,
          column: dateField,
          operator: 'include_range',
          value: `${from.start.slice(0, 4)}-01-01`,
          upper: `${endYear}-12-31`,
        });
      }
    }
  }
  return filters;
}

export function buildSuggestedRestrictionSql(
  profile: RestrictionProfile,
  draft: RestrictionDraft,
  selectedColumns: string[],
): string {
  const alias = 'k';
  const table = profile.primaryTable;
  const documentField = draft.documentFieldOverride || profile.documentField;
  const entityField = draft.entityFieldOverride || profile.entityField;
  const dateField = draft.dateFieldOverride || profile.dateField;
  const amountField = profile.amountField;
  const preferred = [documentField, dateField, entityField, 'waerk', amountField, 'mandt']
    .filter((name): name is string => !!name);
  const columns = Array.from(new Set([
    ...preferred.filter(name => selectedColumns.map(item => item.toLowerCase()).includes(name.toLowerCase())
      || !selectedColumns.length),
    ...selectedColumns.slice(0, 8),
  ])).slice(0, 8);

  const selectList = columns.map(column => {
    if (amountField && column.toLowerCase() === amountField.toLowerCase()) {
      return `    CAST(NULLIF(TRIM(${alias}.${column}), '') AS NUMERIC) AS ${column}_value`;
    }
    if (dateField && column.toLowerCase() === dateField.toLowerCase()) {
      return `    ${alias}.${column} AS ${column}`;
    }
    if (documentField && column.toLowerCase() === documentField.toLowerCase()) {
      return `    ${alias}.${column} AS ${profile.id === 'billing' ? 'invoice_number' : column}`;
    }
    if (entityField && column.toLowerCase() === entityField.toLowerCase()) {
      return `    ${alias}.${column} AS ${profile.entityLabel.replace(/\s+/g, '_')}`;
    }
    return `    ${alias}.${column}`;
  }).join(',\n');

  const where: string[] = [];
  if (draft.client.trim()) {
    where.push(`  ${alias}.mandt = '${draft.client.trim().replace(/'/g, "''")}'`);
  }
  if (draft.mode === 'specific' && documentField && draft.specificValue.trim()) {
    where.push(`  ${alias}.${documentField} = '${draft.specificValue.trim().replace(/'/g, "''")}'`);
  }
  if (draft.mode === 'by_entity' && entityField && draft.entityValue.trim()) {
    where.push(`  ${alias}.${entityField} = '${draft.entityValue.trim().replace(/'/g, "''")}'`);
  }
  if (dateField && draft.period === 'year') {
    const bounds = yearBounds(draft.year.trim());
    if (bounds) {
      where.push(`  ${alias}.${dateField} >= '${bounds.start}'`);
      where.push(`  ${alias}.${dateField} < '${bounds.endExclusive}'`);
    }
  }
  if (dateField && draft.period === 'year_range') {
    const from = yearBounds(draft.year.trim());
    const to = yearBounds(draft.yearTo.trim());
    if (from && to) {
      where.push(`  ${alias}.${dateField} >= '${from.start}'`);
      where.push(`  ${alias}.${dateField} < '${to.endExclusive}'`);
    }
  }

  const order = dateField
    ? `ORDER BY ${alias}.${dateField} DESC${documentField ? `, ${alias}.${documentField} DESC` : ''}`
    : documentField
      ? `ORDER BY ${alias}.${documentField} DESC`
      : '';

  return [
    'SELECT',
    selectList || `    ${alias}.*`,
    `FROM ${table} ${alias}`,
    where.length ? `WHERE\n${where.join('\n  AND ')}` : '',
    order,
    'LIMIT 200;',
  ].filter(Boolean).join('\n');
}

export function restrictionQuestionHint(profile: RestrictionProfile, draft: RestrictionDraft): string {
  const bits: string[] = [];
  if (draft.mode === 'specific' && draft.specificValue.trim()) {
    bits.push(`${profile.modes.find(mode => mode.id === 'specific')?.label || 'specific key'} ${draft.specificValue.trim()}`);
  } else if (draft.mode === 'by_entity' && draft.entityValue.trim()) {
    bits.push(`${profile.entityLabel} ${draft.entityValue.trim()}`);
  } else {
    bits.push(profile.label.toLowerCase());
  }
  if (draft.period === 'year' && draft.year.trim()) bits.push(`for calendar year ${draft.year.trim()}`);
  if (draft.period === 'year_range' && draft.year.trim() && draft.yearTo.trim()) {
    bits.push(`between ${draft.year.trim()} and ${draft.yearTo.trim()}`);
  }
  if (draft.period === 'all_years' || draft.allowUnrestricted) bits.push('for all years');
  return `Show ${bits.join(' ')}`.replace(/\s+/g, ' ').trim();
}
