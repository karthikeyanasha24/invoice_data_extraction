'use client';
import { useEffect, useRef, useState } from 'react';
import { dashboardApi } from '@/lib/api';
import { analystDecimal } from '@/lib/analystNumbers';
import { analystChartCsv } from '@/lib/analystChartLayout';

export default function AnalystDrilldown({reference, rows, selectedRow}: {reference: any; rows: any[]; selectedRow?: number | null}) {
  const [rowIndex, setRowIndex] = useState<number | null>(null);
  const [measure, setMeasure] = useState(reference.measures?.[0] || '');
  const [result, setResult] = useState<any>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const generation = useRef(0);
  useEffect(() => { setRowIndex(selectedRow ?? null); setResult(null); setError(''); generation.current++; setBusy(false); }, [selectedRow, reference.id]);
  const load = async (next = false) => {
    if (rowIndex == null) return;
    const current = ++generation.current;
    setBusy(true); setError('');
    try {
      const data = await dashboardApi.getAnalystDocuments(reference.id, {row_index: rowIndex, measure, page_size: 50,
        ...(next ? {after: result.next_cursor, snapshot_id: result.snapshot_id} : {})});
      if (current === generation.current) setResult(data);
    } catch (e: any) { if (current === generation.current) setError(e?.response?.data?.detail || e.message || 'Could not reconcile these documents.'); }
    finally { if (current === generation.current) setBusy(false); }
  };
  const reset = () => { generation.current++; setBusy(false); setResult(null); setError(''); };
  const exportPage = () => {
    const blob = new Blob([analystChartCsv(result.data)], {type:'text/csv;charset=utf-8;'});
    const url = URL.createObjectURL(blob); const anchor = document.createElement('a');
    anchor.href=url; anchor.download='contributing-billing-documents-current-page.csv'; anchor.click(); URL.revokeObjectURL(url);
  };
  if (!reference.measures?.length) return null;
  return <details open className="mb-4 rounded-xl border border-emerald-200 bg-emerald-50/30 p-4 min-w-0">
    <summary className="cursor-pointer text-sm font-medium text-emerald-900">Billing documents · reconcile a displayed total</summary>
    <p className="mt-3 text-xs text-slate-600">Choose the exact row and amount. This uses the original query filters and no AI tokens. Result captured {reference.created_at ? new Date(reference.created_at).toLocaleString() : ''}.</p>
    <div className="flex flex-wrap gap-2 my-3">
      <select aria-label="Aggregate row to inspect" className="min-w-0 max-w-full rounded border p-2 text-sm" value={rowIndex ?? ''} onChange={e => {reset();setRowIndex(e.target.value === '' ? null : Number(e.target.value));}}>
        <option value="">Select a result row</option>{rows.map((row,i) => <option value={i} key={i}>{i+1}. {Object.entries(row).map(([k,v]) => `${k.replaceAll('_',' ')}: ${v ?? 'not available'}`).join(' · ')}</option>)}
      </select>
      <select aria-label="Amount to reconcile" className="rounded border p-2 text-sm" value={measure} onChange={e => {reset();setMeasure(e.target.value);}}>{reference.measures.map((name:string) => <option key={name}>{name}</option>)}</select>
      <button type="button" className="rounded bg-emerald-700 px-3 py-2 text-sm text-white disabled:opacity-50" disabled={busy || rowIndex == null} onClick={() => load()}>{busy ? 'Checking documents…' : 'Show billing documents'}</button>
    </div>
    {error && <p role="alert" className="text-sm text-red-700">{error}</p>}
    {result && <div className="space-y-3">
      <p role="status" className={`text-sm font-medium ${result.reconciliation.matched ? 'text-emerald-800' : 'text-red-800'}`}>{result.reconciliation.matched ? 'Total reconciled' : 'Totals differ — this is not a reconciled answer'} · Original {analystDecimal(result.reconciliation.original_total)} · Documents {analystDecimal(result.reconciliation.document_total)} · Difference {analystDecimal(result.reconciliation.difference)} · {result.totalCount} documents</p>
      <p className="text-xs text-slate-600">{result.reconciliation.note}</p>
      <div className="max-w-full overflow-x-auto"><table className="w-full text-sm"><thead><tr>{['Client','Billing document','Currency','Billed net value'].map(h => <th key={h} className="p-2 text-left">{h}</th>)}</tr></thead><tbody>{result.data.map((row:any,i:number) => <tr key={i} className="border-t"><td className="p-2">{row.sap_client}</td><td className="p-2 font-mono">{row.billing_document}</td><td className="p-2">{row.currency}</td><td className="p-2 tabular-nums">{analystDecimal(row.billed_sales)}</td></tr>)}</tbody></table></div>
      <div className="flex flex-wrap gap-3 text-sm"><button type="button" disabled={busy || !result.has_more} onClick={() => load(true)} className="rounded border px-3 py-2 disabled:opacity-40">Next documents</button><button type="button" onClick={exportPage} className="rounded border px-3 py-2">Export current page CSV</button></div>
      <details><summary className="cursor-pointer text-xs text-slate-600">Reconciliation SQL</summary><pre className="mt-2 max-h-64 overflow-auto whitespace-pre-wrap text-xs">{result.sql}</pre></details>
    </div>}
  </details>;
}
