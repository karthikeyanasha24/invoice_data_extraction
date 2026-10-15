'use client';

import { useCallback, useEffect, useMemo, useState } from 'react';
import { Check, ChevronDown, ChevronRight, Copy, Database, Loader2, Play, RefreshCw, Save, Search } from 'lucide-react';
import { dashboardApi } from '@/lib/api';

type TrainingSource = 'business' | 'application';
type SchemaColumn = { name: string; type: string; description?: string; primary_key: boolean; foreign_key: boolean };
type SchemaTable = { table: string; description?: Record<string, string>; columns: SchemaColumn[]; relationships: { columns: string[]; references_table?: string; references_columns: string[] }[] };
type Example = { id: string; source: TrainingSource; question: string; sql: string; dialect: string; revision: number; validation_status: string; updated_at: string; schema: { tables?: Record<string, { columns: { col: string; type: string }[] }>; relationships?: Record<string, { columns: string[]; references_table?: string; references_columns: string[] }[]> } };

export default function BasicSqlTraining({ initialQuestion = '' }: { initialQuestion?: string }) {
  const [source, setSource] = useState<TrainingSource>('business');
  const [tables, setTables] = useState<SchemaTable[]>([]);
  const [schemaSource, setSchemaSource] = useState('');
  const [selected, setSelected] = useState<Record<string, string[]>>({});
  const [expanded, setExpanded] = useState<Record<string, boolean>>({});
  const [filter, setFilter] = useState('');
  const [question, setQuestion] = useState(initialQuestion);
  const [sql, setSql] = useState('');
  const [loadingSchema, setLoadingSchema] = useState(false);
  const [running, setRunning] = useState(false);
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  const [run, setRun] = useState<{ run_id?: string; sql: string; rows: Record<string, unknown>[]; columns: string[]; row_count: number; llm_calls: 0 } | null>(null);
  const [examples, setExamples] = useState<Example[]>([]);
  const [exampleFilter, setExampleFilter] = useState('');
  const [saving, setSaving] = useState(false);

  const loadSchema = useCallback(async (nextSource: TrainingSource = source) => {
    setLoadingSchema(true); setError(''); setRun(null);
    try {
      const result = await dashboardApi.getBasicTrainingSchema(nextSource);
      setTables(result.tables || []); setSchemaSource(result.schema_source || '');
      const all = Object.fromEntries((result.tables || []).map(table => [table.table, table.columns.map(column => column.name)]));
      setSelected(all); setExpanded(Object.fromEntries((result.tables || []).map(table => [table.table, true])));
    } catch (cause) {
      setTables([]); setSelected({}); setError(cause instanceof Error ? cause.message : 'Could not load the database schema.');
    } finally { setLoadingSchema(false); }
  }, [source]);

  const loadExamples = useCallback(async (q: string) => {
    try { const result = await dashboardApi.getBasicTrainingExamples(q); setExamples(result.examples || []); }
    catch (cause) { setError(cause instanceof Error ? cause.message : 'Could not load saved SQL examples.'); }
  }, []);

  useEffect(() => { void loadSchema(source); }, [loadSchema, source]);
  useEffect(() => { void loadExamples(''); }, [loadExamples]);
  useEffect(() => { if (initialQuestion.trim()) setQuestion(initialQuestion.trim()); }, [initialQuestion]);

  const filteredTables = useMemo(() => {
    const needle = filter.trim().toLowerCase();
    return tables.filter(table => !needle || table.table.toLowerCase().includes(needle) || table.columns.some(column => column.name.toLowerCase().includes(needle)));
  }, [filter, tables]);
  const selectedSchema = useMemo(() => Object.fromEntries(Object.entries(selected).filter(([, columns]) => columns.length)), [selected]);
  const selectedCount = Object.values(selectedSchema).reduce((sum, columns) => sum + columns.length, 0);
  const exactCandidate = useMemo(() => {
    const normalized = question.trim().toLocaleLowerCase().replace(/\s+/g, ' ');
    return normalized ? examples.find(example => example.question.trim().toLocaleLowerCase().replace(/\s+/g, ' ') === normalized) : undefined;
  }, [examples, question]);

  const toggleColumn = (table: string, column: string) => setSelected(current => {
    const values = current[table] || [];
    const next = values.includes(column) ? values.filter(value => value !== column) : [...values, column];
    return { ...current, [table]: next };
  });
  const toggleTable = (table: SchemaTable, checked: boolean) => setSelected(current => ({
    ...current, [table.table]: checked ? table.columns.map(column => column.name) : [],
  }));

  const schemaContext = () => JSON.stringify({ source, dialect: 'PostgreSQL', tables: tables.filter(table => selectedSchema[table.table]).map(table => ({
    name: table.table, description: table.description, columns: table.columns.filter(column => selectedSchema[table.table].includes(column.name)), relationships: table.relationships,
  })) }, null, 2);
  const copySchema = async () => {
    try { await navigator.clipboard.writeText(schemaContext()); setNotice('Selected schema copied.'); setTimeout(() => setNotice(''), 2500); }
    catch { setError('Clipboard access failed.'); }
  };
  const copyPrompt = async () => {
    const prompt = `Write one read-only PostgreSQL SELECT query for this business question. Use only this selected schema. Do not invent columns or tables. Return SQL only; do not execute it.\n\nQuestion: ${question || '[describe the question]'}\n\nSchema:\n${schemaContext()}`;
    try { await navigator.clipboard.writeText(prompt); setNotice('Question and selected schema copied. Paste into your chosen assistant, then review the SQL before running it here.'); setTimeout(() => setNotice(''), 5000); }
    catch { setError('Clipboard access failed.'); }
  };

  const execute = async () => {
    setError(''); setNotice(''); setRun(null);
    if (!question.trim()) { setError('Write the business question this SQL is intended to answer.'); return; }
    if (!sql.trim()) { setError('Enter or paste a SQL query.'); return; }
    if (!selectedCount) { setError('Select at least one table and column in the schema explorer.'); return; }
    setRunning(true);
    try {
      const result = await dashboardApi.executeBasicTrainingSql({ source, question: question.trim(), sql, selected_schema: selectedSchema });
      if (result.status !== 'executed') { setError(result.error || 'The SQL could not be executed.'); return; }
      setSql(result.sql || sql); setRun(result); setNotice(`${result.row_count} row${result.row_count === 1 ? '' : 's'} returned · 0 model calls.`);
    } catch (cause) { setError(cause instanceof Error ? cause.message : 'Query execution failed.'); }
    finally { setRunning(false); }
  };

  const saveExample = async () => {
    if (!run?.run_id) return;
    setSaving(true); setError('');
    try { const result = await dashboardApi.saveBasicTrainingExample(run.run_id, question.trim()); setNotice(`Saved as revision ${result.revision}. Basic SQL Training library updated.`); await loadExamples(''); }
    catch (cause) { setError(cause instanceof Error ? cause.message : 'Could not save this example.'); }
    finally { setSaving(false); }
  };

  const loadExample = (example: Example) => {
    setQuestion(example.question); setSql(example.sql); setRun(null); setError('');
    setSource(example.source);
    const restored = Object.fromEntries(Object.entries(example.schema?.tables || {}).map(([table, details]) => [table, details.columns.map(column => column.col).filter(Boolean)]));
    setSelected(restored); setNotice(`Loaded saved example, revision ${example.revision}. Run it to validate against current data.`);
  };

  const editExample = async (example: Example) => {
    const nextSql = window.prompt('Edit SQL. This saves a new revision and marks it as needing validation.', example.sql);
    if (nextSql == null || nextSql.trim() === example.sql) return;
    try { await dashboardApi.editBasicTrainingExample(example.id, nextSql); setNotice('New SQL revision saved; run the example to validate it.'); await loadExamples(exampleFilter); }
    catch (cause) { setError(cause instanceof Error ? cause.message : 'Could not update saved SQL.'); }
  };

  return <div className="h-full overflow-y-auto bg-slate-50 px-3 py-4 sm:px-6" style={{ scrollbarWidth: 'thin' }}>
    <div className="mx-auto max-w-7xl space-y-4">
      <section className="rounded-2xl border border-indigo-100 bg-white p-4 sm:p-5 shadow-sm">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div><h3 className="flex items-center gap-2 text-base font-semibold text-slate-900"><Database className="h-5 w-5 text-indigo-600"/>Basic SQL Training</h3>
            <p className="mt-1 max-w-3xl text-sm text-slate-600">Explore the live schema, write or paste SQL, run it with read-only validation, then save successful wording and SQL for reuse. This workflow makes <strong>0 AI/model calls</strong>; it does not train model weights.</p></div>
          <div className="flex items-center gap-2"><label className="sr-only" htmlFor="training-source">Database</label><select id="training-source" value={source} onChange={event => setSource(event.target.value as TrainingSource)} className="rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm"><option value="business">Business database</option><option value="application">Application database</option></select>
            <button type="button" onClick={() => void loadSchema()} disabled={loadingSchema} className="inline-flex items-center gap-2 rounded-lg border px-3 py-2 text-sm hover:bg-slate-50 disabled:opacity-50"><RefreshCw className={`h-4 w-4 ${loadingSchema ? 'animate-spin' : ''}`}/>Refresh</button></div>
        </div>
        <p className="mt-2 text-xs text-slate-500">SQL dialect: PostgreSQL · Schema: {schemaSource || (loadingSchema ? 'loading…' : 'unavailable')} · Selected: {Object.keys(selectedSchema).length} tables, {selectedCount} columns</p>
      </section>

      {error && <div role="alert" className="rounded-xl border border-red-200 bg-red-50 p-3 text-sm text-red-800">{error}</div>}
      {notice && <div role="status" className="rounded-xl border border-emerald-200 bg-emerald-50 p-3 text-sm text-emerald-800">{notice}</div>}

      <div className="grid gap-4 xl:grid-cols-[minmax(18rem,0.8fr)_minmax(0,1.5fr)]">
        <section className="min-w-0 rounded-2xl border bg-white p-4 shadow-sm">
          <div className="flex items-center justify-between gap-2"><h4 className="font-semibold text-slate-900">Schema explorer</h4><div className="flex gap-2"><button type="button" onClick={() => setSelected(Object.fromEntries(tables.map(table => [table.table, table.columns.map(column => column.name)])))} className="text-xs text-indigo-700 hover:underline">Select all</button><button type="button" onClick={() => setSelected({})} className="text-xs text-slate-500 hover:underline">Clear</button></div></div>
          <label className="relative mt-3 block"><Search className="absolute left-3 top-2.5 h-4 w-4 text-slate-400"/><input value={filter} onChange={event => setFilter(event.target.value)} placeholder="Find table or column" className="w-full rounded-lg border py-2 pl-9 pr-3 text-sm"/></label>
          <div className="mt-3 max-h-[28rem] space-y-2 overflow-y-auto pr-1">
            {loadingSchema && <div className="flex items-center gap-2 p-4 text-sm text-slate-500"><Loader2 className="h-4 w-4 animate-spin"/>Loading live schema…</div>}
            {!loadingSchema && filteredTables.map(table => { const checked = selected[table.table] || []; const allChecked = table.columns.length > 0 && checked.length === table.columns.length; const isOpen = expanded[table.table] ?? false;
              return <div key={table.table} className="rounded-xl border border-slate-200">
                <div className="flex items-center gap-2 px-3 py-2"><input aria-label={`Select all columns in ${table.table}`} type="checkbox" checked={allChecked} onChange={event => toggleTable(table, event.target.checked)}/><button type="button" onClick={() => setExpanded(current => ({ ...current, [table.table]: !isOpen }))} className="flex min-w-0 flex-1 items-center gap-2 text-left text-sm font-medium text-slate-800">{isOpen ? <ChevronDown className="h-4 w-4"/> : <ChevronRight className="h-4 w-4"/>}<span className="truncate">{table.table}</span><span className="text-xs font-normal text-slate-400">{checked.length}/{table.columns.length}</span></button></div>
                {isOpen && <div className="border-t bg-slate-50 px-3 py-2">{table.columns.map(column => <label key={column.name} title={column.description || undefined} className="flex items-center gap-2 py-1 text-xs text-slate-700"><input type="checkbox" checked={checked.includes(column.name)} onChange={() => toggleColumn(table.table, column.name)}/><span className="min-w-0 truncate font-medium">{column.name}</span><span className="truncate text-slate-400">{column.type}</span>{column.primary_key && <span className="rounded bg-amber-100 px-1 text-amber-800">PK</span>}{column.foreign_key && <span className="rounded bg-sky-100 px-1 text-sky-800">FK</span>}{column.description && <span className="hidden truncate text-slate-500 2xl:inline">· {column.description}</span>}</label>)}
                  {table.relationships.map((relationship, index) => <p key={index} className="mt-1 text-[11px] text-sky-800">{relationship.columns.join(', ')} → {relationship.references_table}.{relationship.references_columns.join(', ')}</p>)}</div>}
              </div>;
            })}
            {!loadingSchema && filteredTables.length === 0 && <p className="p-4 text-sm text-slate-500">No visible tables. Refresh the connected database catalog or check access.</p>}
          </div>
          <div className="mt-3 flex flex-wrap gap-2"><button type="button" onClick={() => void copySchema()} disabled={!selectedCount} className="inline-flex items-center gap-1.5 rounded-lg border px-3 py-2 text-xs disabled:opacity-40"><Copy className="h-3.5 w-3.5"/>Copy selected schema</button><button type="button" onClick={() => void copyPrompt()} disabled={!selectedCount} className="inline-flex items-center gap-1.5 rounded-lg border px-3 py-2 text-xs disabled:opacity-40"><Copy className="h-3.5 w-3.5"/>Copy prompt for external AI</button></div>
          <details className="mt-3"><summary className="cursor-pointer text-xs font-medium text-slate-700">Preview selected schema ({Object.keys(selectedSchema).length} tables)</summary><pre className="mt-2 max-h-56 overflow-auto rounded-lg bg-slate-50 p-3 text-[11px] leading-4 text-slate-700">{schemaContext()}</pre></details>
          <p className="mt-2 text-[11px] leading-4 text-slate-500">External AI is optional and separate. Nothing is sent automatically. Review any SQL before running it.</p>
        </section>

        <div className="space-y-4">
          <section className="rounded-2xl border bg-white p-4 shadow-sm">
            <h4 className="font-semibold text-slate-900">Write and run a query</h4>
            <label className="mt-3 block text-xs font-medium text-slate-600">Business question to save<input value={question} onChange={event => setQuestion(event.target.value)} maxLength={4000} placeholder="e.g. Show the top 10 customers by billed sales in 2001" className="mt-1 w-full rounded-lg border px-3 py-2 text-sm"/></label>
            {exactCandidate && <div className="mt-2 flex flex-wrap items-center justify-between gap-2 rounded-lg border border-indigo-200 bg-indigo-50 p-3 text-xs text-indigo-900"><span>A matching saved question is available, revision {exactCandidate.revision}. This exact wording match is a candidate; run it to validate current data.</span><button type="button" onClick={() => loadExample(exactCandidate)} className="rounded-md border border-indigo-300 bg-white px-3 py-1.5 font-medium">Load candidate SQL</button></div>}
            <label className="mt-3 block text-xs font-medium text-slate-600">Read-only SQL<textarea value={sql} onChange={event => setSql(event.target.value)} maxLength={24000} rows={10} spellCheck={false} placeholder={'SELECT customer_id, SUM(net_value) AS billed_sales\nFROM billing_documents\nGROUP BY customer_id\nORDER BY billed_sales DESC\nLIMIT 10;'} className="mt-1 w-full rounded-xl border bg-slate-950 p-3 font-mono text-xs leading-5 text-slate-100 placeholder:text-slate-500"/></label>
            <div className="mt-3 flex flex-wrap items-center gap-2"><button type="button" onClick={() => void execute()} disabled={running || loadingSchema} className="inline-flex items-center gap-2 rounded-lg bg-indigo-700 px-4 py-2 text-sm font-medium text-white hover:bg-indigo-800 disabled:opacity-50">{running ? <Loader2 className="h-4 w-4 animate-spin"/> : <Play className="h-4 w-4"/>}{running ? 'Running read-only query…' : 'Run SQL'}</button>{run?.run_id && <button type="button" onClick={() => void saveExample()} disabled={saving} className="inline-flex items-center gap-2 rounded-lg border border-emerald-300 bg-emerald-50 px-4 py-2 text-sm font-medium text-emerald-800 disabled:opacity-50">{saving ? <Loader2 className="h-4 w-4 animate-spin"/> : <Save className="h-4 w-4"/>}Save checked example</button>}<span className="text-xs text-slate-500">SELECT/WITH only · database scope and selected schema enforced · no model call</span></div>
          </section>

          {run && <section className="rounded-2xl border bg-white p-4 shadow-sm"><div className="flex flex-wrap items-center justify-between gap-2"><div><h4 className="font-semibold text-slate-900">Query results</h4><p className="text-xs text-slate-500">{run.row_count} rows · 0 model calls</p></div><span className="inline-flex items-center gap-1 rounded-full bg-emerald-50 px-2.5 py-1 text-xs text-emerald-800"><Check className="h-3.5 w-3.5"/>Executed</span></div>
            <div className="mt-3 max-h-96 overflow-auto rounded-lg border"><table className="min-w-full text-left text-xs"><thead className="sticky top-0 bg-slate-100"><tr>{run.columns.map(column => <th key={column} className="whitespace-nowrap px-3 py-2 font-semibold text-slate-700">{column}</th>)}</tr></thead><tbody>{run.rows.map((row, index) => <tr key={index} className="border-t">{run.columns.map(column => <td key={column} className="max-w-xs whitespace-nowrap px-3 py-2 text-slate-700">{row[column] == null ? '—' : String(row[column])}</td>)}</tr>)}</tbody></table>{run.rows.length === 0 && <p className="p-4 text-sm text-slate-500">Query ran successfully and returned no rows.</p>}</div>
            <details className="mt-3"><summary className="cursor-pointer text-xs text-slate-600">Executed SQL</summary><pre className="mt-2 overflow-auto rounded-lg bg-slate-950 p-3 text-xs text-slate-100">{run.sql}</pre></details>
          </section>}
        </div>
      </div>

      <section className="rounded-2xl border bg-white p-4 shadow-sm"><div className="flex flex-wrap items-center justify-between gap-3"><div><h4 className="font-semibold text-slate-900">Saved SQL examples</h4><p className="mt-1 text-xs text-slate-500">Saved wording and SQL are isolated to your accessible workspace. Load and rerun to check current figures.</p></div><div className="flex gap-2"><input value={exampleFilter} onChange={event => setExampleFilter(event.target.value)} onKeyDown={event => { if (event.key === 'Enter') void loadExamples(exampleFilter); }} placeholder="Search saved wording or SQL" className="w-56 rounded-lg border px-3 py-2 text-xs"/><button type="button" onClick={() => void loadExamples(exampleFilter)} className="rounded-lg border px-3 py-2 text-xs">Search</button></div></div>
        <div className="mt-3 divide-y">{examples.map(example => <div key={example.id} className="flex flex-wrap items-center justify-between gap-3 py-3"><div className="min-w-0"><p className="truncate text-sm font-medium text-slate-800">{example.question}</p><p className="mt-1 text-xs text-slate-500">Revision {example.revision} · {example.dialect} · {example.validation_status} · {new Date(example.updated_at).toLocaleString()}</p><code className="mt-1 block max-w-3xl truncate text-[11px] text-slate-500">{example.sql}</code></div><div className="flex shrink-0 gap-2"><button type="button" onClick={() => loadExample(example)} className="rounded-lg border px-3 py-2 text-xs">Load to editor</button><button type="button" onClick={() => void editExample(example)} className="rounded-lg border px-3 py-2 text-xs">Edit SQL</button></div></div>)}{examples.length === 0 && <p className="py-6 text-center text-sm text-slate-500">No saved examples yet. Run a query successfully, then save it here.</p>}</div>
      </section>
    </div>
  </div>;
}
