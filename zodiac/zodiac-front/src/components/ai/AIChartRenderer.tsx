'use client';

import { BarChart, Bar, LineChart, Line, PieChart, Pie, AreaChart, Area, XAxis, YAxis, CartesianGrid, Tooltip, Legend, ResponsiveContainer, Cell } from 'recharts';
import { Download, Maximize2, Calendar, TrendingUp } from 'lucide-react';

type ChartData = {
  chart_type: string;
  title: string;
  description: string;
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
};

interface AIChartRendererProps {
  charts: ChartData[];
}

export default function AIChartRenderer({ charts }: AIChartRendererProps) {
  if (!charts || charts.length === 0) {
    console.log('📊 AIChartRenderer: No charts provided');
    return null;
  }
  
  console.log('📊 AIChartRenderer: Rendering', charts.length, 'chart(s)');
  console.log('📊 Chart data:', charts);

  // Animation class for smooth entrance
  const fadeInClass = "opacity-0 animate-[fadeIn_0.5s_ease-in_forwards]";

  // Currency symbol map for SAP currency codes
  const CURRENCY_SYMBOLS: Record<string, string> = {
    USD: '$', EUR: '€', GBP: '£', KRW: '₩', JPY: '¥', CNY: '¥',
    INR: '₹', AUD: 'A$', CAD: 'CA$', CHF: 'CHF ', SEK: 'SEK ',
    NOK: 'NOK ', DKK: 'DKK ', BRL: 'R$', MXN: 'MX$', SGD: 'S$',
    HKD: 'HK$', NZD: 'NZ$', ZAR: 'R ', TRY: '₺', RUB: '₽',
    // Legacy SAP currencies
    DEM: 'DEM ', FRF: 'FRF ', PTE: 'PTE ', ITL: 'ITL ', ESP: 'ESP ',
    ATS: 'ATS ', BEF: 'BEF ', NLG: 'NLG ', GRD: 'GRD ', FIM: 'FIM ',
  };

  // Format a numeric value with the correct currency symbol
  // currencyCode: ISO 4217 code (e.g. "USD", "KRW") — uses $ only when actually USD
  const formatCurrency = (value: number, currencyCode?: string): string => {
    const code = (currencyCode || '').toUpperCase();
    const symbol = code ? (CURRENCY_SYMBOLS[code] ?? (code + ' ')) : '';
    const formatted = Math.abs(value) >= 1_000_000
      ? (value / 1_000_000).toFixed(2).replace(/\.?0+$/, '') + 'M'
      : Math.abs(value) >= 1_000
      ? Math.round(value).toLocaleString('en-US')
      : value.toFixed(2);
    return symbol ? `${symbol}${formatted}` : formatted;
  };

  // Check if a key/column likely represents currency/money
  const isCurrencyField = (key: string): boolean => {
    const lowerKey = key.toLowerCase();
    // Never treat quantity/count columns as currency
    if (lowerKey.includes('quantity') || lowerKey.includes('invoice_count') || lowerKey === 'count') return false;
    return lowerKey.includes('sales') ||
           lowerKey.includes('revenue') ||
           lowerKey.includes('amount') ||
           lowerKey.includes('total') ||
           lowerKey.includes('value') ||
           lowerKey.includes('price') ||
           lowerKey.includes('cost') ||
           lowerKey.includes('spend') ||
           lowerKey.includes('balance') ||
           lowerKey.includes('netwr') ||
           lowerKey.includes('rmwwr');
  };

  // Extract currency code from a chart data row (looks for a 'currency' or 'waerk'/'waers' column)
  const getCurrencyFromRow = (row: any): string | undefined => {
    if (!row) return undefined;
    const keys = Object.keys(row);
    const currKey = keys.find(k =>
      k.toLowerCase() === 'currency' ||
      k.toLowerCase() === 'waerk' ||
      k.toLowerCase() === 'waers' ||
      k.toLowerCase() === 'rtcur' ||
      k.toLowerCase() === 'hwaer'
    );
    return currKey ? String(row[currKey]) : undefined;
  };

  // Extract the dominant currency from all chart data rows
  const getDominantCurrency = (data: any[]): string | undefined => {
    if (!data || data.length === 0) return undefined;
    // Count occurrences of each currency code
    const counts: Record<string, number> = {};
    for (const row of data) {
      const c = getCurrencyFromRow(row);
      if (c) counts[c] = (counts[c] || 0) + 1;
    }
    if (Object.keys(counts).length === 0) return undefined;
    // Return the most common currency
    return Object.entries(counts).sort((a, b) => b[1] - a[1])[0][0];
  };

  /** When rows mix WAERK/waers, a single-symbol Y-axis is misleading — use plain numbers on axis. */
  const distinctCurrenciesInData = (data: any[]): string[] => {
    const s = new Set<string>();
    for (const row of data || []) {
      const c = getCurrencyFromRow(row);
      if (c) s.add(c);
    }
    return Array.from(s);
  };

  const downloadChart = (chartTitle: string) => {
    // TODO: Implement SVG export
    console.log('Download chart:', chartTitle);
  };

  const renderChart = (chart: ChartData, index: number) => {
    const colors = chart.colors || [
      '#3b82f6', '#10b981', '#f59e0b', '#ef4444', '#8b5cf6',
      '#06b6d4', '#f97316', '#ec4899', '#14b8a6', '#a855f7',
      '#eab308', '#6366f1', '#84cc16', '#f43f5e', '#0ea5e9',
    ];
    
    // Validate chart has data
    if (!chart.data || chart.data.length === 0) {
      console.warn(`📊 Chart ${index} has no data:`, chart);
      return (
        <div className="flex items-center justify-center h-40 text-sm text-slate-500">
          No data available for this chart
        </div>
      );
    }
    
    console.log(`📊 Rendering chart ${index}:`, {
      type: chart.chart_type,
      dataLength: chart.data.length,
      x_key: chart.x_key,
      y_keys: chart.y_keys,
      name_key: chart.name_key,
      value_key: chart.value_key,
    });

    switch (chart.chart_type) {
      case 'bar':
      case 'stacked_bar':
        if (!chart.x_key || !chart.y_keys || chart.y_keys.length === 0) {
          console.error('📊 Bar chart missing required keys:', { x_key: chart.x_key, y_keys: chart.y_keys });
          return <div className="text-sm text-red-500">Chart configuration error: missing x_key or y_keys</div>;
        }
        const barHasCurrency = chart.y_keys.some(k => isCurrencyField(k));
        const barCurrencies = distinctCurrenciesInData(chart.data);
        const mixedCurrencyAxis = barCurrencies.length > 1;
        const barCurrency = mixedCurrencyAxis ? undefined : getDominantCurrency(chart.data);
        const isStacked = chart.stacked || chart.chart_type === 'stacked_bar';
        return (
          <ResponsiveContainer width="100%" height={400}>
            <BarChart data={chart.data}>
              {chart.show_grid && <CartesianGrid strokeDasharray="3 3" stroke="#e2e8f0" opacity={0.3} />}
              <XAxis
                dataKey={chart.x_key}
                stroke="#64748b"
                style={{ fontSize: '11px', fontWeight: 500 }}
                tick={{ fill: '#475569' }}
              />
              <YAxis
                stroke="#64748b"
                style={{ fontSize: '11px', fontWeight: 500 }}
                tick={{ fill: '#475569' }}
                tickFormatter={
                  barHasCurrency
                    ? (v) =>
                        mixedCurrencyAxis
                          ? Number(v).toLocaleString(undefined, { maximumFractionDigits: 0 })
                          : formatCurrency(Number(v), barCurrency)
                    : undefined
                }
              />
              <Tooltip
                contentStyle={{
                  backgroundColor: '#FFFFFF',
                  border: '1px solid #cbd5e1',
                  borderRadius: '12px',
                  fontSize: '12px',
                  boxShadow: '0 8px 24px rgba(0,0,0,0.12)',
                  padding: '12px',
                }}
                formatter={(value: any, name: string, props: any) => {
                  const rowCurrency = getCurrencyFromRow(props?.payload) ?? barCurrency;
                  const formattedValue = isCurrencyField(name) ? formatCurrency(Number(value), rowCurrency) : Number(value).toLocaleString();
                  return [formattedValue, name.replace(/_/g, ' ')];
                }}
                cursor={{ fill: 'rgba(59, 130, 246, 0.1)' }}
              />
              {chart.show_legend && (
                <Legend 
                  wrapperStyle={{ fontSize: '11px', paddingTop: '16px' }}
                  iconType="circle"
                />
              )}
              {chart.y_keys.map((key, idx) => (
                <Bar
                  key={key}
                  dataKey={key}
                  fill={colors[idx % colors.length]}
                  radius={[4, 4, 0, 0]}
                  stackId={isStacked ? 'stack' : undefined}
                  animationDuration={800}
                  animationEasing="ease-out"
                >
                  {/* Color each bar individually on single-metric charts (ranking, distribution, breakdown).
                      Multi-series charts keep per-series coloring. */}
                  {chart.y_keys.length === 1 && chart.data.map((_: any, cellIdx: number) => (
                    <Cell key={`cell-${cellIdx}`} fill={colors[cellIdx % colors.length]} />
                  ))}
                </Bar>
              ))}
            </BarChart>
          </ResponsiveContainer>
        );

      case 'line':
        if (!chart.x_key || !chart.y_keys || chart.y_keys.length === 0) {
          console.error('📊 Line chart missing required keys:', { x_key: chart.x_key, y_keys: chart.y_keys });
          return <div className="text-sm text-red-500">Chart configuration error: missing x_key or y_keys</div>;
        }
        const lineHasCurrency = chart.y_keys.some(k => isCurrencyField(k));
        const lineCurrencies = distinctCurrenciesInData(chart.data);
        const lineMixedCurrencyAxis = lineCurrencies.length > 1;
        const lineCurrency = lineMixedCurrencyAxis ? undefined : getDominantCurrency(chart.data);
        return (
          <ResponsiveContainer width="100%" height={400}>
            <LineChart data={chart.data}>
              {chart.show_grid && <CartesianGrid strokeDasharray="3 3" stroke="#e2e8f0" />}
              <XAxis dataKey={chart.x_key} stroke="#64748b" style={{ fontSize: '12px' }} />
              <YAxis
                stroke="#64748b"
                style={{ fontSize: '12px' }}
                tickFormatter={
                  lineHasCurrency
                    ? (v) =>
                        lineMixedCurrencyAxis
                          ? Number(v).toLocaleString(undefined, { maximumFractionDigits: 0 })
                          : formatCurrency(Number(v), lineCurrency)
                    : undefined
                }
              />
              <Tooltip
                contentStyle={{
                  backgroundColor: '#FFFFFF',
                  border: '1px solid #cbd5e1',
                  borderRadius: '12px',
                  fontSize: '12px',
                  boxShadow: '0 4px 12px rgba(0,0,0,0.1)',
                }}
                formatter={(value: any, name: string, props: any) => {
                  const rowCurrency = getCurrencyFromRow(props?.payload) ?? lineCurrency;
                  const formattedValue = isCurrencyField(name)
                    ? formatCurrency(Number(value), rowCurrency)
                    : Number(value).toLocaleString();
                  return [formattedValue, name.replace(/_/g, ' ')];
                }}
              />
              {chart.show_legend && <Legend wrapperStyle={{ fontSize: '12px' }} />}
              {chart.y_keys.map((key, idx) => (
                <Line
                  key={key}
                  type="monotone"
                  dataKey={key}
                  stroke={colors[idx % colors.length]}
                  strokeWidth={2}
                  dot={{ fill: colors[idx % colors.length], r: 3 }}
                  activeDot={{ r: 5 }}
                />
              ))}
            </LineChart>
          </ResponsiveContainer>
        );

      case 'area':
        if (!chart.x_key || !chart.y_keys || chart.y_keys.length === 0) {
          console.error('📊 Area chart missing required keys:', { x_key: chart.x_key, y_keys: chart.y_keys });
          return <div className="text-sm text-red-500">Chart configuration error: missing x_key or y_keys</div>;
        }
        const areaHasCurrency = chart.y_keys.some(k => isCurrencyField(k));
        const areaCurrencies = distinctCurrenciesInData(chart.data);
        const areaMixedCurrencyAxis = areaCurrencies.length > 1;
        const areaCurrency = areaMixedCurrencyAxis ? undefined : getDominantCurrency(chart.data);
        return (
          <ResponsiveContainer width="100%" height={400}>
            <AreaChart data={chart.data}>
              {chart.show_grid && <CartesianGrid strokeDasharray="3 3" stroke="#e2e8f0" />}
              <XAxis dataKey={chart.x_key} stroke="#64748b" style={{ fontSize: '12px' }} />
              <YAxis
                stroke="#64748b"
                style={{ fontSize: '12px' }}
                tickFormatter={
                  areaHasCurrency
                    ? (v) =>
                        areaMixedCurrencyAxis
                          ? Number(v).toLocaleString(undefined, { maximumFractionDigits: 0 })
                          : formatCurrency(Number(v), areaCurrency)
                    : undefined
                }
              />
              <Tooltip
                contentStyle={{
                  backgroundColor: '#FFFFFF',
                  border: '1px solid #cbd5e1',
                  borderRadius: '12px',
                  fontSize: '12px',
                  boxShadow: '0 4px 12px rgba(0,0,0,0.1)',
                }}
                formatter={(value: any, name: string, props: any) => {
                  const rowCurrency = getCurrencyFromRow(props?.payload) ?? areaCurrency;
                  const formattedValue = isCurrencyField(name) ? formatCurrency(Number(value), rowCurrency) : Number(value).toLocaleString();
                  return [formattedValue, name.replace(/_/g, ' ')];
                }}
              />
              {chart.show_legend && <Legend wrapperStyle={{ fontSize: '12px' }} />}
              {chart.y_keys.map((key, idx) => (
                <Area
                  key={key}
                  type="monotone"
                  dataKey={key}
                  stroke={colors[idx % colors.length]}
                  fill={colors[idx % colors.length]}
                  fillOpacity={0.6}
                />
              ))}
            </AreaChart>
          </ResponsiveContainer>
        );

      case 'pie':
        const nameKey = chart.name_key || 'name';
        const valueKey = chart.value_key || 'value';
        
        console.log('📊 Pie chart config:', { nameKey, valueKey, dataLength: chart.data.length });
        if (chart.data.length > 0) {
          console.log('📊 First data item:', chart.data[0]);
          console.log('📊 Available keys:', Object.keys(chart.data[0]));
        }
        
        // Validate pie chart data has required keys
        if (chart.data.length > 0 && !(nameKey in chart.data[0] && valueKey in chart.data[0])) {
          console.error('📊 Pie chart data missing required keys:', { 
            nameKey, 
            valueKey, 
            availableKeys: Object.keys(chart.data[0]) 
          });
          
          // Try to auto-fix by finding matching keys
          const availableKeys = Object.keys(chart.data[0]);
          const autoNameKey = availableKeys.find(k => k.toLowerCase().includes('name') || k === 'name') || availableKeys[0];
          const autoValueKey = availableKeys.find(k => k.toLowerCase().includes('value') || k === 'value') || availableKeys[1];
          
          if (autoNameKey && autoValueKey) {
            console.log('🔧 Auto-fixing pie chart keys:', { autoNameKey, autoValueKey });
            return (
              <ResponsiveContainer width="100%" height={400}>
                <PieChart>
                  <Pie
                    data={chart.data}
                    dataKey={autoValueKey}
                    nameKey={autoNameKey}
                    cx="50%"
                    cy="50%"
                    outerRadius={100}
                    label={(entry) => entry[autoNameKey]}
                    labelLine={true}
                  >
                    {chart.data.map((entry, idx) => (
                      <Cell key={`cell-${idx}`} fill={colors[idx % colors.length]} />
                    ))}
                  </Pie>
                  <Tooltip
                    formatter={(value: any, _name: any, props: any) => {
                      const rowCurrency = getCurrencyFromRow(props?.payload);
                      return isCurrencyField(autoValueKey) ? formatCurrency(Number(value), rowCurrency) : Number(value).toLocaleString();
                    }}
                  />
                  {chart.show_legend && <Legend />}
                </PieChart>
              </ResponsiveContainer>
            );
          }
          
          return <div className="text-sm text-red-500">Chart configuration error: data missing name or value keys</div>;
        }
        
        return (
          <ResponsiveContainer width="100%" height={400}>
            <PieChart>
              <Pie
                data={chart.data}
                dataKey={valueKey}
                nameKey={nameKey}
                cx="50%"
                cy="50%"
                outerRadius={100}
                label={(entry) => entry[nameKey]}
                labelLine={true}
              >
                {chart.data.map((entry, idx) => (
                  <Cell key={`cell-${idx}`} fill={colors[idx % colors.length]} />
                ))}
              </Pie>
              <Tooltip
                contentStyle={{
                  backgroundColor: '#FFFFFF',
                  border: '1px solid #cbd5e1',
                  borderRadius: '12px',
                  fontSize: '12px',
                  boxShadow: '0 4px 12px rgba(0,0,0,0.1)',
                }}
                formatter={(value: any, _name: any, props: any) => {
                  const rowCurrency = getCurrencyFromRow(props?.payload);
                  return isCurrencyField(valueKey) ? formatCurrency(Number(value), rowCurrency) : Number(value).toLocaleString();
                }}
              />
              {chart.show_legend && <Legend wrapperStyle={{ fontSize: '12px' }} />}
            </PieChart>
          </ResponsiveContainer>
        );

      case 'table':
        if (!chart.data[0]) {
          return <div className="text-sm text-slate-500">No data available for table</div>;
        }
        const columnKeys = Object.keys(chart.data[0]);
        return (
          <div className="overflow-x-auto rounded-lg border border-slate-200">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-slate-200 bg-gradient-to-r from-slate-50 to-slate-100">
                  {columnKeys.map((key) => (
                    <th key={key} className="px-3 py-2 text-left font-semibold text-slate-700 text-xs uppercase tracking-wide">
                      {key.replace(/_/g, ' ')}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {chart.data.map((row, idx) => (
                  <tr key={idx} className="border-b border-slate-100 hover:bg-slate-50 transition-colors">
                    {columnKeys.map((key, cellIdx) => {
                      const value = row[key];
                      let displayValue = '-';

                      if (value !== null && value !== undefined) {
                        if (typeof value === 'number') {
                          if (isCurrencyField(key)) {
                            // Use the currency column from the SAME row, not a hardcoded USD
                            const rowCurrency = getCurrencyFromRow(row);
                            displayValue = formatCurrency(value, rowCurrency);
                          } else {
                            displayValue = value.toLocaleString();
                          }
                        } else {
                          displayValue = String(value);
                        }
                      }

                      return (
                        <td key={cellIdx} className="px-3 py-2 text-slate-900 text-sm">
                          {displayValue}
                        </td>
                      );
                    })}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        );

      default:
        return null;
    }
  };

  return (
    <div className="space-y-4">
      <style>{`
        @keyframes fadeIn {
          from { opacity: 0; transform: translateY(10px); }
          to { opacity: 1; transform: translateY(0); }
        }
        .chart-container {
          animation: fadeIn 0.5s ease-out forwards;
        }
        .chart-container:nth-child(1) { animation-delay: 0.1s; }
        .chart-container:nth-child(2) { animation-delay: 0.2s; }
        .chart-container:nth-child(3) { animation-delay: 0.3s; }
        .chart-container:nth-child(4) { animation-delay: 0.4s; }
      `}</style>
      {charts.map((chart, index) => {
        try {
          const chartTypeIcon = chart.chart_type === 'table' ? '📋' : chart.chart_type === 'pie' ? '🥧' : chart.chart_type === 'line' ? '📈' : chart.chart_type === 'area' || chart.chart_type === 'stacked_area' ? '📉' : '📊';
          const mixedCurr =
            chart.chart_type !== 'table' && distinctCurrenciesInData(chart.data).length > 1;

          return (
            <div 
              key={index} 
              className="chart-container rounded-xl border border-slate-200 bg-white shadow-md hover:shadow-xl transition-all duration-300 overflow-hidden opacity-0"
              style={{ animationDelay: `${index * 0.1}s` }}
            >
              <div className="px-4 py-3 border-b border-slate-200 bg-gradient-to-r from-blue-50 via-indigo-50 to-purple-50 flex items-center justify-between">
                <div className="flex-1">
                  <div className="flex items-center gap-2 mb-1">
                    <span className="text-lg">{chartTypeIcon}</span>
                    <h4 className="text-sm font-bold text-slate-900">{chart.title || 'Untitled Chart'}</h4>
                    {chart.period_info && (
                      <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-[10px] font-semibold bg-blue-100 text-blue-700 border border-blue-200">
                        <Calendar className="h-3 w-3" />
                        {chart.period_info}
                      </span>
                    )}
                    {chart.stacked && (
                      <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-[10px] font-semibold bg-purple-100 text-purple-700 border border-purple-200">
                        <TrendingUp className="h-3 w-3" />
                        Stacked
                      </span>
                    )}
                    {mixedCurr && (
                      <span
                        className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-[10px] font-semibold bg-amber-50 text-amber-900 border border-amber-200"
                        title="Values use more than one currency code — compare per row, not on a single money axis"
                      >
                        Mixed currencies
                      </span>
                    )}
                  </div>
                  {chart.description && (
                    <p className="text-xs text-slate-600 ml-7">{chart.description}</p>
                  )}
                </div>
                <div className="flex items-center gap-2">
                  <button
                    type="button"
                    onClick={() => downloadChart(chart.title)}
                    className="p-1.5 rounded-lg text-slate-500 hover:bg-white hover:text-blue-600 hover:shadow-sm transition-all"
                    title="Download chart"
                    aria-label="Download chart"
                  >
                    <Download className="h-4 w-4" />
                  </button>
                  <button
                    type="button"
                    className="p-1.5 rounded-lg text-slate-500 hover:bg-white hover:text-blue-600 hover:shadow-sm transition-all"
                    title="Fullscreen"
                    aria-label="Fullscreen"
                  >
                    <Maximize2 className="h-4 w-4" />
                  </button>
                </div>
              </div>
              <div className="p-5">{renderChart(chart, index)}</div>
            </div>
          );
        } catch (error) {
          console.error(`📊 Error rendering chart ${index}:`, error, chart);
          return (
            <div key={index} className="rounded-xl border border-red-200 bg-red-50 p-4">
              <p className="text-sm text-red-700 font-medium">Failed to render chart: {chart.title || 'Untitled'}</p>
              <p className="text-xs text-red-600 mt-1">Check console for details</p>
            </div>
          );
        }
      })}
    </div>
  );
}
