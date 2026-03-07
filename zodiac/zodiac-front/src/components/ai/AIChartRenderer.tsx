'use client';

import { BarChart, Bar, LineChart, Line, PieChart, Pie, AreaChart, Area, XAxis, YAxis, CartesianGrid, Tooltip, Legend, ResponsiveContainer, Cell } from 'recharts';
import { Download, Maximize2 } from 'lucide-react';

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

  const downloadChart = (chartTitle: string) => {
    // TODO: Implement SVG export
    console.log('Download chart:', chartTitle);
  };

  const renderChart = (chart: ChartData, index: number) => {
    const colors = chart.colors || ['#3b82f6', '#6366f1', '#10b981', '#f59e0b', '#ef4444'];
    
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
        if (!chart.x_key || !chart.y_keys || chart.y_keys.length === 0) {
          console.error('📊 Bar chart missing required keys:', { x_key: chart.x_key, y_keys: chart.y_keys });
          return <div className="text-sm text-red-500">Chart configuration error: missing x_key or y_keys</div>;
        }
        return (
          <ResponsiveContainer width="100%" height={400}>
            <BarChart data={chart.data}>
              {chart.show_grid && <CartesianGrid strokeDasharray="3 3" stroke="#e2e8f0" />}
              <XAxis dataKey={chart.x_key} stroke="#64748b" style={{ fontSize: '12px' }} />
              <YAxis stroke="#64748b" style={{ fontSize: '12px' }} />
              <Tooltip
                contentStyle={{
                  backgroundColor: '#FFFFFF',
                  border: '1px solid #cbd5e1',
                  borderRadius: '12px',
                  fontSize: '12px',
                  boxShadow: '0 4px 12px rgba(0,0,0,0.1)',
                }}
              />
              {chart.show_legend && <Legend wrapperStyle={{ fontSize: '12px' }} />}
              {chart.y_keys.map((key, idx) => (
                <Bar
                  key={key}
                  dataKey={key}
                  fill={colors[idx % colors.length]}
                  radius={[4, 4, 0, 0]}
                />
              ))}
            </BarChart>
          </ResponsiveContainer>
        );

      case 'line':
        if (!chart.x_key || !chart.y_keys || chart.y_keys.length === 0) {
          console.error('📊 Line chart missing required keys:', { x_key: chart.x_key, y_keys: chart.y_keys });
          return <div className="text-sm text-red-500">Chart configuration error: missing x_key or y_keys</div>;
        }
        return (
          <ResponsiveContainer width="100%" height={400}>
            <LineChart data={chart.data}>
              {chart.show_grid && <CartesianGrid strokeDasharray="3 3" stroke="#e2e8f0" />}
              <XAxis dataKey={chart.x_key} stroke="#64748b" style={{ fontSize: '12px' }} />
              <YAxis stroke="#64748b" style={{ fontSize: '12px' }} />
              <Tooltip
                contentStyle={{
                  backgroundColor: '#FFFFFF',
                  border: '1px solid #cbd5e1',
                  borderRadius: '12px',
                  fontSize: '12px',
                  boxShadow: '0 4px 12px rgba(0,0,0,0.1)',
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
        return (
          <ResponsiveContainer width="100%" height={400}>
            <AreaChart data={chart.data}>
              {chart.show_grid && <CartesianGrid strokeDasharray="3 3" stroke="#e2e8f0" />}
              <XAxis dataKey={chart.x_key} stroke="#64748b" style={{ fontSize: '12px' }} />
              <YAxis stroke="#64748b" style={{ fontSize: '12px' }} />
              <Tooltip
                contentStyle={{
                  backgroundColor: '#FFFFFF',
                  border: '1px solid #cbd5e1',
                  borderRadius: '12px',
                  fontSize: '12px',
                  boxShadow: '0 4px 12px rgba(0,0,0,0.1)',
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
        
        // Validate pie chart data has required keys
        if (chart.data.length > 0 && !(nameKey in chart.data[0] && valueKey in chart.data[0])) {
          console.error('📊 Pie chart data missing required keys:', { 
            nameKey, 
            valueKey, 
            availableKeys: Object.keys(chart.data[0]) 
          });
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
              />
              {chart.show_legend && <Legend wrapperStyle={{ fontSize: '12px' }} />}
            </PieChart>
          </ResponsiveContainer>
        );

      case 'table':
        if (!chart.data[0]) {
          return <div className="text-sm text-slate-500">No data available for table</div>;
        }
        return (
          <div className="overflow-x-auto rounded-lg border border-slate-200">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-slate-200 bg-gradient-to-r from-slate-50 to-slate-100">
                  {Object.keys(chart.data[0]).map((key) => (
                    <th key={key} className="px-3 py-2 text-left font-semibold text-slate-700 text-xs uppercase tracking-wide">
                      {key.replace(/_/g, ' ')}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {chart.data.map((row, idx) => (
                  <tr key={idx} className="border-b border-slate-100 hover:bg-slate-50 transition-colors">
                    {Object.values(row).map((value: any, cellIdx) => (
                      <td key={cellIdx} className="px-3 py-2 text-slate-900 text-sm">
                        {value === null || value === undefined 
                          ? '-' 
                          : typeof value === 'number' 
                            ? value.toLocaleString() 
                            : String(value)}
                      </td>
                    ))}
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
      {charts.map((chart, index) => {
        try {
          return (
            <div key={index} className="rounded-xl border border-slate-200 bg-white shadow-sm overflow-hidden">
              <div className="px-4 py-3 border-b border-slate-200 bg-gradient-to-r from-slate-50 to-slate-100 flex items-center justify-between">
                <div>
                  <h4 className="text-sm font-semibold text-slate-900">{chart.title || 'Untitled Chart'}</h4>
                  {chart.description && (
                    <p className="text-xs text-slate-600 mt-0.5">{chart.description}</p>
                  )}
                </div>
                <div className="flex items-center gap-2">
                  <button
                    type="button"
                    onClick={() => downloadChart(chart.title)}
                    className="p-1.5 rounded-md text-slate-500 hover:bg-slate-200 hover:text-slate-700 transition-colors"
                    title="Download chart"
                    aria-label="Download chart"
                  >
                    <Download className="h-4 w-4" />
                  </button>
                  <button
                    type="button"
                    className="p-1.5 rounded-md text-slate-500 hover:bg-slate-200 hover:text-slate-700 transition-colors"
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
