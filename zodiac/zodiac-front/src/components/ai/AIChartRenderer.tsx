'use client';

import { useMemo, useState } from 'react';
import {
  BarChart, Bar, LineChart, Line, PieChart, Pie, AreaChart, Area,
  XAxis, YAxis, CartesianGrid, Tooltip, Legend, ResponsiveContainer,
  Cell, LabelList,
} from 'recharts';
import {
  Download, Calendar, TrendingUp,
  BarChart3, LineChart as LineIcon, PieChart as PieIcon,
  Table as TableIcon, AreaChart as AreaIcon,
} from 'lucide-react';

/* ─────────────────────────────────────────────────────────────────
   TYPES
───────────────────────────────────────────────────────────────── */
type ChartData = {
  chart_type: string;
  title: string;
  description?: string;
  data: any[];
  x_key?: string;
  y_keys?: string[];
  name_key?: string;
  value_key?: string;
  colors?: string[];
  show_legend?: boolean;
  show_grid?: boolean;
  stacked?: boolean;
  period_info?: string;
  currency?: string;
};

/* ─────────────────────────────────────────────────────────────────
   COLOR PALETTE  (solid, vivid – no SVG gradients)
───────────────────────────────────────────────────────────────── */
const PALETTE = [
  '#6366f1', // indigo
  '#f59e0b', // amber
  '#10b981', // emerald
  '#ef4444', // rose-red
  '#3b82f6', // blue
  '#a855f7', // purple
  '#f97316', // orange
  '#06b6d4', // cyan
  '#ec4899', // pink
  '#14b8a6', // teal
  '#eab308', // yellow
  '#84cc16', // lime
  '#8b5cf6', // violet
  '#f43f5e', // crimson
  '#0ea5e9', // sky
  '#22c55e', // green
];

/* ─────────────────────────────────────────────────────────────────
   NUMBER HELPERS
───────────────────────────────────────────────────────────────── */
/** Locale for currency + grouped numerals (standard grouping, per-row SAP currency). */
const NUM_LOCALE = 'en-US';

const CCY_SYMBOL: Record<string, string> = {
  USD: '$', EUR: '€', GBP: '£', INR: '₹', JPY: '¥', CNY: '¥',
  KRW: '₩', AUD: 'A$', CAD: 'CA$', SGD: 'S$', HKD: 'HK$',
  BRL: 'R$', MXN: 'MX$', ZAR: 'R ', TRY: '₺',
  DEM: 'DEM ', PTE: 'PTE ', CHF: 'CHF ',
};

/**
 * Format money using ISO currency when possible (WAERS/WAERK on each row), not Cr/L abbreviations.
 */
function fmtMoney(v: number, ccy?: string): string {
  if (!Number.isFinite(v)) return '—';
  const code = (ccy || '').trim().toUpperCase();
  if (code && /^[A-Z]{3}$/.test(code)) {
    try {
      return new Intl.NumberFormat(NUM_LOCALE, {
        style: 'currency',
        currency: code,
        minimumFractionDigits: 0,
        maximumFractionDigits: 2,
      }).format(v);
    } catch {
      /* obsolete or unknown ISO code — fall through */
    }
  }
  const sym = code ? (CCY_SYMBOL[code] ?? `${code} `) : '';
  const n = v.toLocaleString(NUM_LOCALE, { minimumFractionDigits: 0, maximumFractionDigits: 2 });
  return sym ? `${sym}${n}` : n;
}

function fmtAxis(v: number, isMoney: boolean, ccy?: string): string {
  if (isMoney) return fmtMoney(v, ccy);
  const abs = Math.abs(v);
  if (abs >= 1e9) return (v / 1e9).toFixed(1) + 'B';
  if (abs >= 1e6) return (v / 1e6).toFixed(1) + 'M';
  if (abs >= 1e3) return (v / 1e3).toFixed(1) + 'K';
  return String(Number.isInteger(v) ? v : v.toFixed(2));
}

/** SAP-style column is a percentage / ratio (do NOT plot on same axis as money without dual axis). */
function isPercentCol(k: string): boolean {
  const lk = k.toLowerCase();
  if (/qty|quantity|count|invoice_count|^cnt|^rn$|rank|row_number|sortorder/.test(lk)) return false;
  return (
    /percent|pct|marginpercent|margin_pct|_pct|profitmarginpercent|profit.?margin.?%/i.test(k) ||
    (/\bmargin\b/.test(lk) && /percent|pct|ratio/.test(lk)) ||
    /\bratio\b/.test(lk)
  );
}

function isMoneycol(k: string): boolean {
  const lk = k.toLowerCase();
  if (isPercentCol(k)) return false;
  if (/qty|quantity|count|invoice_count|^cnt/.test(lk)) return false;
  return /\b(sales|revenue|amount|total|value|price|cost|profit|spend|balance|netwr|rmwwr|kwert|fkwrt|wert|betrag)\b/.test(lk);
}

/** Exclude window-function noise from chart series */
function isChartMeasureKey(k: string): boolean {
  const lk = k.toLowerCase();
  return !/^rn$|^row_num|sortorder|sort_key|rank_num/.test(lk);
}

function splitMeasureKeys(keys: string[]): { money: string[]; percent: string[]; other: string[] } {
  const money: string[] = [];
  const percent: string[] = [];
  const other: string[] = [];
  for (const k of keys) {
    if (!isChartMeasureKey(k)) continue;
    if (isPercentCol(k)) percent.push(k);
    else if (isMoneycol(k)) money.push(k);
    else other.push(k);
  }
  return { money, percent, other };
}

/** Full presentation: thousands separators + decimals (same locale as currency). */
function fmtNumberPlain(v: number, maxFrac = 2): string {
  if (!Number.isFinite(v)) return '—';
  return v.toLocaleString(NUM_LOCALE, {
    minimumFractionDigits: 0,
    maximumFractionDigits: maxFrac,
  });
}

function fmtCell(key: string, v: number, rowCcy?: string): string {
  if (isPercentCol(key)) return `${fmtNumberPlain(v, 2)}%`;
  if (isMoneycol(key)) return fmtMoney(v, rowCcy);
  return fmtNumberPlain(v, 4);
}

function getCcy(row: any): string | undefined {
  const k = Object.keys(row || {}).find(x => /^(currency|waerk|waers|rtcur|hwaer)$/i.test(x));
  return k ? String(row[k]) : undefined;
}

function domCcy(data: any[]): string | undefined {
  const cnt: Record<string, number> = {};
  for (const r of data) { const c = getCcy(r); if (c) cnt[c] = (cnt[c] || 0) + 1; }
  const e = Object.entries(cnt).sort((a, b) => b[1] - a[1]);
  return e[0]?.[0];
}

function multiCcy(data: any[]): boolean {
  const s = new Set(data.map(getCcy).filter(Boolean));
  return s.size > 1;
}

/* ─────────────────────────────────────────────────────────────────
   COLUMN DETECTION
───────────────────────────────────────────────────────────────── */
/** Returns true for numeric IDs, sort keys, SAP key fields —
 *  these should be treated as LABELS, not measures */
function isDimension(col: string, sampleVal: any): boolean {
  const lk = col.toLowerCase();
  // Explicit SAP ID / key columns
  if (/^(mandt|vbeln|kunnr|lifnr|matnr|werks|bukrs|vkorg|vtweg|spart|belnr|posnr|ebelp|ebeln|fkdat|budat|gjahr|pernr|aubel|knumv)$/.test(lk)) return true;
  // Generic pattern: ends in _id, _code, _no, _key; or IS "id", "code", "no"
  if (/(_id|_code|_no|_key|_num|id$|code$|no$|num$|sno$|ref$|seq$)/.test(lk)) return true;
  // High-cardinality unique integer strings look like IDs
  if (typeof sampleVal === 'string' && /^\d{5,}$/.test(sampleVal.trim())) return true;
  return false;
}

function isDateCol(col: string, sampleVal: any): boolean {
  const lk = col.toLowerCase();
  if (/date|month|period|year|quarter|week/.test(lk)) return true;
  const s = String(sampleVal ?? '').trim();
  return /^\d{4}-\d{2}(-\d{2})?$/.test(s) || /^\d{4}$/.test(s);
}

function isNumericVal(v: any): boolean {
  if (v === null || v === undefined || v === '') return false;
  return !isNaN(Number(v));
}

/** Split columns into {dims, measures} for a data row */
function splitCols(firstRow: any): { dims: string[]; measures: string[] } {
  const dims: string[] = [];
  const measures: string[] = [];
  for (const [col, val] of Object.entries(firstRow)) {
    if (isDimension(col, val) || isDateCol(col, val) || !isNumericVal(val)) {
      dims.push(col);
    } else {
      measures.push(col);
    }
  }
  return { dims, measures };
}

/* ─────────────────────────────────────────────────────────────────
   KEY RESOLUTION
───────────────────────────────────────────────────────────────── */
function resolveKeys(chart: ChartData): { xKey: string; yKeys: string[] } {
  if (chart.data.length === 0) return { xKey: '', yKeys: [] };
  const first = chart.data[0];
  const { dims, measures } = splitCols(first);
  const allKeys = Object.keys(first);

  let xKey = chart.x_key || chart.name_key || dims[0] || allKeys[0];
  const usableMeasures = measures.filter(isChartMeasureKey);
  let yKeys = chart.y_keys?.length ? chart.y_keys.filter(isChartMeasureKey)
    : chart.value_key ? [chart.value_key]
    : usableMeasures.length ? usableMeasures.slice(0, 6)
    : allKeys.filter(k => k !== xKey && isChartMeasureKey(k)).slice(0, 6);

  return { xKey: xKey || allKeys[0], yKeys };
}

/* ─────────────────────────────────────────────────────────────────
   CHART-TYPE ICON MAP
───────────────────────────────────────────────────────────────── */
const T_ICON: Record<string, React.ReactNode> = {
  bar:   <BarChart3 className="h-3 w-3" />,
  line:  <LineIcon  className="h-3 w-3" />,
  area:  <AreaIcon  className="h-3 w-3" />,
  pie:   <PieIcon   className="h-3 w-3" />,
  table: <TableIcon className="h-3 w-3" />,
};
const T_LABEL: Record<string, string> = {
  bar: 'Bar', line: 'Line', area: 'Area', pie: 'Pie',
  table: 'Table', bar_horizontal: 'H-Bar', stacked_bar: 'Stack',
};

/* ─────────────────────────────────────────────────────────────────
   TOOLTIP
───────────────────────────────────────────────────────────────── */
const TOOLTIP_STYLE: React.CSSProperties = {
  backgroundColor: '#1e293b',   // dark slate — high contrast
  border: 'none',
  borderRadius: '10px',
  fontSize: '12px',
  fontWeight: 600,
  color: '#f8fafc',
  boxShadow: '0 12px 28px rgba(0,0,0,0.35)',
  padding: '10px 14px',
};
const TOOLTIP_CURSOR = { fill: 'rgba(99,102,241,0.08)' };

/* ═════════════════════════════════════════════════════════════════
   MAIN COMPONENT
═════════════════════════════════════════════════════════════════ */
export default function AIChartRenderer({ charts }: { charts: ChartData[] }) {
  const [overrides, setOverrides] = useState<Record<number, string>>({});

  if (!charts?.length) return null;

  /* ── available toggle types per chart ─────────────────────── */
  const available = useMemo<Record<number, string[]>>(() => {
    const out: Record<number, string[]> = {};
    charts.forEach((chart, idx) => {
      if (!chart.data?.length) { out[idx] = [chart.chart_type || 'table']; return; }
      const first = chart.data[0];
      const { dims, measures } = splitCols(first);
      const hasDim = dims.length > 0;
      const hasMeasure = measures.length > 0;
      const types = new Set<string>([chart.chart_type || 'bar']);

      if (hasDim && hasMeasure && chart.data.length > 0) {
        types.add('bar');
        types.add('line');
        types.add('area');
        // Pie: sensible only for few categories with one measure
        if (chart.data.length <= 12 && measures.length === 1 && !isDateCol(dims[0], chart.data[0]?.[dims[0]])) {
          types.add('pie');
        }
        types.add('table');
      } else {
        types.add('table');
      }
      out[idx] = Array.from(types);
    });
    return out;
  }, [charts]);

  /* ═══ renderChart ══════════════════════════════════════════════ */
  const renderChart = (chart: ChartData, idx: number, activeType: string) => {
    if (!chart.data?.length) return (
      <p className="text-sm text-slate-400 italic text-center py-10">No data available</p>
    );

    const { xKey, yKeys } = resolveKeys(chart);
    const colors = chart.colors?.length ? chart.colors : PALETTE;
    const currency = chart.currency || domCcy(chart.data);
    const mixedC = multiCcy(chart.data);
    const { money: moneyKeys, percent: percentKeys, other: otherKeys } = splitMeasureKeys(yKeys);
    const leftAxisKeys = [...moneyKeys, ...otherKeys];
    /** Money amounts vs % share one canvas — must use two Y scales or bars look wrong */
    const useDualPercentAxis =
      percentKeys.length > 0 &&
      leftAxisKeys.length > 0 &&
      !(activeType === 'stacked_bar' || chart.stacked) &&
      activeType !== 'bar_horizontal';

    // sort time-series data
    const sorted = [...chart.data].sort((a, b) => {
      const va = String(a?.[xKey] ?? ''), vb = String(b?.[xKey] ?? '');
      if (/^\d{4}-/.test(va) && /^\d{4}-/.test(vb)) return va < vb ? -1 : va > vb ? 1 : 0;
      return 0;
    });

    const maxPercentVal = percentKeys.length
      ? Math.max(
          100,
          ...sorted.flatMap((r) => percentKeys.map((k) => Math.abs(Number(r[k]) || 0))),
        )
      : 100;

    const hasMoneyOnLeft = leftAxisKeys.some(isMoneycol);
    const leftAxisFmt = (v: number) =>
      hasMoneyOnLeft ? fmtAxis(v, true, mixedC ? undefined : currency) : fmtNumberPlain(v, 2);

    const singleAxisHasMoney = yKeys.some(isMoneycol);
    const axFmt = (v: number) =>
      percentKeys.length && !leftAxisKeys.length
        ? `${fmtNumberPlain(v, 2)}%`
        : fmtAxis(v, singleAxisHasMoney, mixedC ? undefined : currency);

    const tipFmt = (value: any, name?: string, props?: any) => {
      const key = String(name ?? '');
      const lbl = key.replace(/_/g, ' ');
      const rc = getCcy(props?.payload) ?? currency;
      return [fmtCell(key, Number(value), rc), lbl];
    };

    const grid = <CartesianGrid strokeDasharray="3 3" stroke="#334155" opacity={0.15} vertical={false} />;
    const xA = (
      <XAxis dataKey={xKey}
        tick={{ fill: '#64748b', fontSize: 11, fontWeight: 500 }}
        tickLine={false} axisLine={{ stroke: '#e2e8f0' }}
        interval="preserveStartEnd"
      />
    );
    const yA = (
      <YAxis
        tick={{ fill: '#64748b', fontSize: 11 }}
        tickLine={false} axisLine={false}
        tickFormatter={axFmt} width={72}
      />
    );
    const yLeft = (
      <YAxis
        yAxisId="left"
        orientation="left"
        tick={{ fill: '#64748b', fontSize: 11 }}
        tickLine={false}
        axisLine={false}
        tickFormatter={leftAxisFmt}
        width={80}
      />
    );
    const yRight = (
      <YAxis
        yAxisId="right"
        orientation="right"
        tick={{ fill: '#64748b', fontSize: 11 }}
        tickLine={false}
        axisLine={false}
        tickFormatter={(v) => `${fmtNumberPlain(v)}%`}
        domain={[0, Math.ceil(maxPercentVal * 1.08)]}
        width={46}
      />
    );
    const tip = (
      <Tooltip
        contentStyle={TOOLTIP_STYLE}
        labelStyle={{ color: '#94a3b8', fontWeight: 400, fontSize: '11px', marginBottom: '4px' }}
        itemStyle={{ color: '#f8fafc' }}
        formatter={tipFmt}
        cursor={TOOLTIP_CURSOR}
      />
    );

    /* ── BAR (vertical or horizontal) ──────────────────────── */
    if (activeType === 'bar' || activeType === 'stacked_bar' || activeType === 'bar_horizontal') {
      const isHoriz = activeType === 'bar_horizontal';
      const isStack = activeType === 'stacked_bar' || chart.stacked;
      const barH = isHoriz ? Math.max(280, sorted.length * 34 + 60) : 340;
      const dualVertical = useDualPercentAxis && !isHoriz;
      const seriesKeys = dualVertical ? [...leftAxisKeys, ...percentKeys] : yKeys;
      const legendCount = dualVertical ? seriesKeys.length : yKeys.length;

      return (
        <div>
          {dualVertical && (
            <p className="text-[10px] text-slate-500 mb-2 px-0.5">
              Left axis: amounts using each row currency code (WAERS/WAERK). Right axis: % values — separate scales so bars match the table.
            </p>
          )}
          <ResponsiveContainer width="100%" height={barH}>
          <BarChart
            data={sorted}
            layout={isHoriz ? 'vertical' : 'horizontal'}
            margin={{
              top: 20,
              right: isHoriz ? 60 : dualVertical ? 54 : 20,
              bottom: 10,
              left: 0,
            }}
          >
            {grid}
            {isHoriz ? (
              <>
                <XAxis type="number" tick={{ fill: '#64748b', fontSize: 11 }} tickLine={false}
                  axisLine={{ stroke: '#e2e8f0' }} tickFormatter={axFmt} />
                <YAxis type="category" dataKey={xKey}
                  tick={{ fill: '#475569', fontSize: 11, fontWeight: 500 }}
                  width={140} tickLine={false} axisLine={false} />
              </>
            ) : dualVertical ? (
              <>
                {xA}
                {yLeft}
                {yRight}
              </>
            ) : (
              <>
                {xA}
                {yA}
              </>
            )}
            {tip}
            {(chart.show_legend !== false && legendCount > 1) && (
              <Legend wrapperStyle={{ fontSize: '11px', paddingTop: '12px', color: '#64748b' }} iconType="circle" />
            )}
            {dualVertical ? (
              <>
                {leftAxisKeys.map((key, ki) => (
                  <Bar
                    key={key}
                    yAxisId="left"
                    dataKey={key}
                    fill={colors[ki % colors.length]}
                    radius={[4, 4, 0, 0]}
                    animationDuration={600}
                    maxBarSize={52}
                  >
                    {!isStack && (
                      <LabelList
                        dataKey={key}
                        position="top"
                        style={{ fontSize: '10px', fontWeight: 700, fill: '#374151' }}
                        formatter={(v: any) =>
                          fmtCell(key, Number(v), mixedC ? undefined : currency)}
                      />
                    )}
                  </Bar>
                ))}
                {percentKeys.map((key, ki) => (
                  <Bar
                    key={key}
                    yAxisId="right"
                    dataKey={key}
                    fill={colors[(leftAxisKeys.length + ki) % colors.length]}
                    radius={[4, 4, 0, 0]}
                    animationDuration={600}
                    maxBarSize={40}
                  >
                    {!isStack && (
                      <LabelList
                        dataKey={key}
                        position="top"
                        style={{ fontSize: '10px', fontWeight: 700, fill: '#7c3aed' }}
                        formatter={(v: any) => fmtCell(key, Number(v))}
                      />
                    )}
                  </Bar>
                ))}
              </>
            ) : (
              yKeys.map((key, ki) => (
                <Bar
                  key={key}
                  dataKey={key}
                  fill={colors[ki % colors.length]}
                  radius={isHoriz ? [0, 4, 4, 0] : [4, 4, 0, 0]}
                  stackId={isStack ? 'stack' : undefined}
                  animationDuration={600}
                  maxBarSize={isHoriz ? 22 : 52}
                >
                  {yKeys.length === 1 &&
                    sorted.map((_: any, ci: number) => (
                      <Cell key={ci} fill={colors[ci % colors.length]} />
                    ))}
                  {!isStack && (
                    <LabelList
                      dataKey={key}
                      position={isHoriz ? 'right' : 'top'}
                      style={{ fontSize: '10px', fontWeight: 700, fill: '#374151' }}
                      formatter={(v: any) =>
                        fmtCell(key, Number(v), mixedC ? undefined : currency)}
                    />
                  )}
                </Bar>
              ))
            )}
          </BarChart>
        </ResponsiveContainer>
        </div>
      );
    }

    /* ── LINE ───────────────────────────────────────────────── */
    if (activeType === 'line') {
      const dualLine = useDualPercentAxis;
      return (
        <ResponsiveContainer width="100%" height={340}>
          <LineChart data={sorted} margin={{ top: 20, right: dualLine ? 52 : 20, bottom: 10, left: 0 }}>
            {grid}
            {xA}
            {dualLine ? <>{yLeft}{yRight}</> : yA}
            {tip}
            {(chart.show_legend !== false && yKeys.length > 1) && (
              <Legend wrapperStyle={{ fontSize: '11px', paddingTop: '12px', color: '#64748b' }} iconType="circle" />
            )}
            {dualLine ? (
              <>
                {leftAxisKeys.map((key, ki) => (
                  <Line
                    key={key}
                    yAxisId="left"
                    type="monotone"
                    dataKey={key}
                    stroke={colors[ki % colors.length]}
                    strokeWidth={2.5}
                    dot={{ fill: colors[ki % colors.length], r: 4, stroke: '#fff', strokeWidth: 2 }}
                    activeDot={{ r: 7, stroke: '#fff', strokeWidth: 2 }}
                    animationDuration={700}
                  />
                ))}
                {percentKeys.map((key, ki) => (
                  <Line
                    key={key}
                    yAxisId="right"
                    type="monotone"
                    dataKey={key}
                    stroke={colors[(leftAxisKeys.length + ki) % colors.length]}
                    strokeWidth={2.5}
                    strokeDasharray="6 3"
                    dot={{ fill: colors[(leftAxisKeys.length + ki) % colors.length], r: 4, stroke: '#fff', strokeWidth: 2 }}
                    animationDuration={700}
                  />
                ))}
              </>
            ) : (
              yKeys.map((key, ki) => (
                <Line key={key} type="monotone" dataKey={key}
                  stroke={colors[ki % colors.length]}
                  strokeWidth={2.5}
                  dot={{ fill: colors[ki % colors.length], r: 4, stroke: '#fff', strokeWidth: 2 }}
                  activeDot={{ r: 7, stroke: '#fff', strokeWidth: 2 }}
                  animationDuration={700}
                />
              ))
            )}
          </LineChart>
        </ResponsiveContainer>
      );
    }

    /* ── AREA ───────────────────────────────────────────────── */
    if (activeType === 'area' || activeType === 'stacked_area') {
      const isStack = activeType === 'stacked_area';
      const dualArea = useDualPercentAxis && !isStack;
      return (
        <ResponsiveContainer width="100%" height={340}>
          <AreaChart data={sorted} margin={{ top: 20, right: dualArea ? 52 : 20, bottom: 10, left: 0 }}>
            {grid}
            {xA}
            {dualArea ? <>{yLeft}{yRight}</> : yA}
            {tip}
            {(chart.show_legend !== false && yKeys.length > 1) && (
              <Legend wrapperStyle={{ fontSize: '11px', paddingTop: '12px', color: '#64748b' }} iconType="circle" />
            )}
            {dualArea ? (
              <>
                {leftAxisKeys.map((key, ki) => (
                  <Area
                    key={key}
                    yAxisId="left"
                    type="monotone"
                    dataKey={key}
                    stroke={colors[ki % colors.length]}
                    fill={colors[ki % colors.length]}
                    fillOpacity={0.18}
                    strokeWidth={2.5}
                    dot={{ fill: colors[ki % colors.length], r: 3, stroke: '#fff', strokeWidth: 1.5 }}
                    animationDuration={700}
                  />
                ))}
                {percentKeys.map((key, ki) => (
                  <Area
                    key={key}
                    yAxisId="right"
                    type="monotone"
                    dataKey={key}
                    stroke={colors[(leftAxisKeys.length + ki) % colors.length]}
                    fill={colors[(leftAxisKeys.length + ki) % colors.length]}
                    fillOpacity={0.12}
                    strokeWidth={2}
                    strokeDasharray="5 4"
                    dot={{ fill: colors[(leftAxisKeys.length + ki) % colors.length], r: 3, stroke: '#fff', strokeWidth: 1.5 }}
                    animationDuration={700}
                  />
                ))}
              </>
            ) : (
              yKeys.map((key, ki) => (
                <Area key={key} type="monotone" dataKey={key}
                  stroke={colors[ki % colors.length]}
                  fill={colors[ki % colors.length]}
                  fillOpacity={0.18}
                  strokeWidth={2.5}
                  dot={{ fill: colors[ki % colors.length], r: 3, stroke: '#fff', strokeWidth: 1.5 }}
                  stackId={isStack ? 'stack' : undefined}
                  animationDuration={700}
                />
              ))
            )}
          </AreaChart>
        </ResponsiveContainer>
      );
    }

    /* ── PIE / DONUT ────────────────────────────────────────── */
    if (activeType === 'pie') {
      const nameKey = xKey;
      const valueKey = yKeys[0];
      if (!nameKey || !valueKey) return (
        <p className="text-sm text-red-500 p-4">Pie config error: missing dimension or measure</p>
      );

      const total = sorted.reduce((s, r) => s + Number(r[valueKey] ?? 0), 0);
      const pct = (v: number) => total ? ((v / total) * 100).toFixed(1) + '%' : '0%';

      return (
        <div className="flex flex-col items-center gap-3">
          <ResponsiveContainer width="100%" height={340}>
            <PieChart>
              <Pie
                data={sorted}
                dataKey={valueKey}
                nameKey={nameKey}
                cx="50%"
                cy="50%"
                innerRadius={72}
                outerRadius={128}
                paddingAngle={3}
                animationDuration={800}
                label={(props: {
                  cx?: number;
                  cy?: number;
                  midAngle?: number;
                  outerRadius?: number;
                  value?: number;
                  payload?: Record<string, unknown>;
                }) => {
                  const { cx, cy, midAngle, outerRadius, value } = props;
                  if (
                    cx == null ||
                    cy == null ||
                    midAngle == null ||
                    outerRadius == null ||
                    value == null
                  ) {
                    return null;
                  }
                  const RADIAN = Math.PI / 180;
                  const r = outerRadius + 32;
                  const x = cx + r * Math.cos(-midAngle * RADIAN);
                  const y = cy + r * Math.sin(-midAngle * RADIAN);
                  const p = (Number(value) / total) * 100;
                  if (p < 4 || !Number.isFinite(p)) return null;
                  return (
                    <text x={x} y={y} fill="#1e293b"
                      textAnchor={x > cx ? 'start' : 'end'}
                      dominantBaseline="central"
                      style={{ fontSize: '11px', fontWeight: 700 }}>
                      {p.toFixed(1)}%
                    </text>
                  );
                }}
                labelLine={false}
              >
                {sorted.map((_: any, i: number) => (
                  <Cell key={i} fill={colors[i % colors.length]} stroke="#fff" strokeWidth={2} />
                ))}
              </Pie>
              {/* Centre total */}
              <text x="50%" y="50%" textAnchor="middle" dominantBaseline="central">
                <tspan x="50%" dy="-0.4em" style={{ fontSize: '11px', fill: '#64748b', fontWeight: 500 }}>Total</tspan>
                <tspan x="50%" dy="1.4em" style={{ fontSize: '14px', fill: '#0f172a', fontWeight: 700 }}>
                  {fmtMoney(total, currency)}
                </tspan>
              </text>
              <Tooltip
                contentStyle={TOOLTIP_STYLE}
                labelStyle={{ color: '#94a3b8', fontSize: '11px' }}
                itemStyle={{ color: '#f8fafc' }}
                formatter={(v: any, _n: any, props: any) => {
                  const rc = getCcy(props?.payload) ?? currency;
                  return [`${fmtMoney(Number(v), rc)}  (${pct(Number(v))})`, String(props?.payload?.[nameKey] ?? '')];
                }}
              />
            </PieChart>
          </ResponsiveContainer>
          {/* Legend */}
          <div className="flex flex-wrap justify-center gap-x-5 gap-y-1.5 text-xs text-slate-600 px-4 pb-1 max-w-lg">
            {sorted.map((row: any, i: number) => (
              <div key={i} className="flex items-center gap-1.5 min-w-0">
                <span className="w-2.5 h-2.5 rounded-full flex-shrink-0"
                  style={{ backgroundColor: colors[i % colors.length] }} />
                <span className="font-medium truncate max-w-[100px]">{String(row[nameKey] ?? '')}</span>
                <span className="text-slate-400 tabular-nums">{pct(Number(row[valueKey] ?? 0))}</span>
              </div>
            ))}
          </div>
        </div>
      );
    }

    /* ── TABLE ──────────────────────────────────────────────── */
    const colKeys = Object.keys(chart.data[0] || {});
    return (
      <div className="overflow-x-auto rounded-xl border border-slate-200">
        <table className="w-full text-sm">
          <thead>
            <tr className="bg-gradient-to-r from-indigo-50 to-slate-50 border-b border-slate-200">
              {colKeys.map(k => (
                <th key={k} className="px-4 py-2.5 text-left text-xs font-bold text-slate-600 uppercase tracking-wider whitespace-nowrap">
                  {k.replace(/_/g, ' ')}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {chart.data.map((row: any, ri: number) => (
              <tr key={ri}
                className={`border-b border-slate-100 hover:bg-indigo-50/30 transition-colors ${ri % 2 === 1 ? 'bg-slate-50/40' : 'bg-white'}`}>
                {colKeys.map((k, ci) => {
                  const v = row[k];
                  const num = typeof v === 'number' || (typeof v === 'string' && v !== '' && !isNaN(Number(v)) && !isDimension(k, v));
                  const rc = getCcy(row) ?? currency;
                  const display = v == null ? '—'
                    : num ? (
                      <span
                        className={
                          isMoneycol(k)
                            ? 'font-bold text-emerald-700'
                            : isPercentCol(k)
                              ? 'font-semibold text-violet-700'
                              : 'text-slate-800'
                        }
                      >
                        {fmtCell(k, Number(v), rc)}
                      </span>
                    )
                    : String(v);
                  return (
                    <td key={ci} className={`px-4 py-2 text-slate-800 ${num ? 'text-right tabular-nums' : ''} ${ci === 0 ? 'font-semibold text-slate-900' : ''}`}>
                      {display}
                    </td>
                  );
                })}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    );
  };

  /* ═══ OUTER LAYOUT ═════════════════════════════════════════════ */
  return (
    <div className="space-y-5 mt-2">
      <style>{`
        @keyframes chartIn {
          from { opacity:0; transform:translateY(12px); }
          to   { opacity:1; transform:translateY(0); }
        }
        .chart-card { animation: chartIn 0.4s ease-out both; }
      `}</style>

      {charts.map((chart, idx) => {
        try {
          const activeType = overrides[idx] || chart.chart_type || 'bar';
          const typeList = available[idx] || [chart.chart_type];
          const mixedC = chart.chart_type !== 'table' && multiCcy(chart.data);

          const EMOJI: Record<string, string> = {
            bar: '📊', line: '📈', area: '📉', pie: '🍩',
            table: '📋', bar_horizontal: '📊', stacked_bar: '📊',
          };

          return (
            <div
              key={idx}
              className="chart-card rounded-2xl border border-slate-200 bg-white shadow-sm hover:shadow-md transition-shadow overflow-hidden"
              style={{ animationDelay: `${idx * 70}ms` }}
            >
              {/* ── Header ── */}
              <div className="px-5 py-3 border-b border-slate-100 bg-gradient-to-r from-indigo-50/70 via-white to-violet-50/50 flex items-center gap-3">
                <div className="flex-1 min-w-0">
                  <div className="flex flex-wrap items-center gap-2">
                    <span className="text-base leading-none">{EMOJI[activeType] ?? '📊'}</span>
                    <h4 className="text-sm font-bold text-slate-900 truncate">{chart.title || 'Results'}</h4>
                    {chart.period_info && (
                      <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-[10px] font-semibold bg-indigo-100 text-indigo-700 border border-indigo-200">
                        <Calendar className="h-2.5 w-2.5" />{chart.period_info}
                      </span>
                    )}
                    {chart.stacked && (
                      <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-[10px] font-semibold bg-violet-100 text-violet-700 border border-violet-200">
                        <TrendingUp className="h-2.5 w-2.5" />Stacked
                      </span>
                    )}
                    {mixedC && (
                      <span className="px-2 py-0.5 rounded-full text-[10px] font-semibold bg-amber-50 text-amber-800 border border-amber-200">
                        Multi-currency
                      </span>
                    )}
                  </div>
                  {chart.description && (
                    <p className="text-xs text-slate-400 mt-0.5 ml-6 truncate">{chart.description}</p>
                  )}
                </div>

                {/* ── Chart type toggle ── */}
                <div className="flex items-center gap-1.5 flex-shrink-0">
                  {typeList.length > 1 && (
                    <div className="flex items-center gap-0.5 rounded-lg border border-slate-200 bg-white p-0.5 shadow-sm">
                      {typeList.map(t => {
                        const isActive = activeType === t;
                        return (
                          <button
                            key={t}
                            type="button"
                            title={`Switch to ${T_LABEL[t] || t}`}
                            onClick={() => setOverrides(prev => ({ ...prev, [idx]: t }))}
                            className={`flex items-center gap-1 px-2 py-1 rounded-md text-[10px] font-bold transition-all duration-150 ${
                              isActive
                                ? 'bg-indigo-600 text-white shadow-sm scale-105'
                                : 'text-slate-500 hover:text-slate-900 hover:bg-slate-100'
                            }`}
                          >
                            {T_ICON[t] ?? null}
                            <span className="uppercase tracking-wide">{T_LABEL[t] || t}</span>
                          </button>
                        );
                      })}
                    </div>
                  )}
                  <button type="button" title="Download"
                    className="p-1.5 rounded-lg text-slate-400 hover:bg-slate-100 hover:text-slate-700 transition-colors">
                    <Download className="h-3.5 w-3.5" />
                  </button>
                </div>
              </div>

              {/* ── Chart body ── */}
              <div className="p-5 pb-4">{renderChart(chart, idx, activeType)}</div>

              {/* ── Footer ── */}
              {chart.data?.length > 0 && (
                <div className="px-5 py-1.5 border-t border-slate-100 bg-slate-50/60 text-[10px] text-slate-400 flex justify-between">
                  <span>{chart.data.length} row{chart.data.length !== 1 ? 's' : ''}</span>
                  {chart.chart_type && <span className="uppercase tracking-widest">{chart.chart_type}</span>}
                </div>
              )}
            </div>
          );
        } catch (e) {
          return (
            <div key={idx} className="rounded-2xl border border-red-200 bg-red-50 p-4">
              <p className="text-sm font-semibold text-red-700">Chart failed: {chart.title}</p>
            </div>
          );
        }
      })}
    </div>
  );
}
