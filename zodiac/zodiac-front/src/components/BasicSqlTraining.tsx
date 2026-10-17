'use client';

import { useCallback, useEffect, useMemo, useState } from 'react';
import { Check, ChevronDown, ChevronRight, Copy, Database, Loader2, Play, RefreshCw, Save, Search, X } from 'lucide-react';
import { dashboardApi } from '@/lib/api';

type TrainingSource = 'business' | 'application';
type SchemaColumn = { name: string; type: string; description?: string; primary_key: boolean; foreign_key: boolean };
type SchemaTable = { table: string; description?: { description?: string; domain?: string; grain?: string; important_columns?: string }; columns: SchemaColumn[]; relationships: { columns: string[]; references_table?: string; references_columns: string[] }[] };
type Example = { id: string; source: TrainingSource; question: string; sql: string; dialect: string; revision: number; validation_status: string; updated_at: string; schema: { tables?: Record<string, { columns: { col: string; type: string }[] }>; relationships?: Record<string, { columns: string[]; references_table?: string; references_columns: string[] }[]> } };
type FilterOperator = 'include_value' | 'include_range' | 'exclude_value' | 'exclude_range' | 'greater_than' | 'less_than';
type TrainingFilter = { id: string; table: string; column: string; operator: FilterOperator; value: string; upper: string };
type PreviewResult = { sql?: string; rows: Record<string, unknown>[]; columns: string[]; row_count: number; limit?: number; applied_filters?: number };

export default function BasicSqlTraining({ initialQuestion = '' }: { initialQuestion?: string }) {
  const [source, setSource] = useState<TrainingSource>('business');
  const [tables, setTables] = useState<SchemaTable[]>([]);
  const [schemaSource, setSchemaSource] = useState('');
  const [selected, setSelected] = useState<Record<string, string[]>>({});
  const [expanded, setExpanded] = useState<Record<string, boolean>>({});
  const [filter, setFilter] = useState('');
  const [trainingFieldSearch, setTrainingFieldSearch] = useState('');
  const [question, setQuestion] = useState(initialQuestion);
  const [sql, setSql] = useState('');
  const [trainingFilters, setTrainingFilters] = useState<TrainingFilter[]>([]);
  const [activeTab, setActiveTab] = useState<'training' | 'data'>('training');
  const [previewTable, setPreviewTable] = useState('');
  const [previewColumns, setPreviewColumns] = useState<string[]>([]);
  const [previewFieldSearch, setPreviewFieldSearch] = useState('');
  const [previewFilters, setPreviewFilters] = useState<TrainingFilter[]>([]);
  const [previewResult, setPreviewResult] = useState<PreviewResult | null>(null);
  const [previewLoading, setPreviewLoading] = useState(false);
  const [loadingSchema, setLoadingSchema] = useState(false);
  const [running, setRunning] = useState(false);
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  const [run, setRun] = useState<{ run_id?: string; sql: string; rows: Record<string, unknown>[]; columns: string[]; row_count: number; llm_calls: 0 } | null>(null);
  const [examples, setExamples] = useState<Example[]>([]);
  const [exampleFilter, setExampleFilter] = useState('');
  const [saving, setSaving] = useState(false);

  const loadSchema = useCallback(async (nextSource: TrainingSource | 'auto') => {
    setLoadingSchema(true); setError(''); setRun(null); setPreviewFilters([]); setPreviewResult(null); setPreviewFieldSearch('');
    if (nextSource !== 'auto') setSource(nextSource);
    try {
      const result = await dashboardApi.getBasicTrainingSchema(nextSource);
      setSource(result.source as TrainingSource);
      setTables(result.tables || []); setSchemaSource(result.schema_source || '');
      setPreviewTable(result.tables?.[0]?.table || '');
      setPreviewColumns(result.tables?.[0]?.columns.slice(0, 12).map((column: SchemaColumn) => column.name) || []);
      setPreviewResult(null);
      // The live catalog can contain thousands of columns. Load it collapsed
      // and let the user select only the tables/columns needed for the query.
      setSelected({}); setExpanded({});
    } catch (cause) {
      setTables([]); setSelected({}); setError(cause instanceof Error ? cause.message : 'Could not load the database schema.');
    } finally { setLoadingSchema(false); }
  }, []);

  const loadExamples = useCallback(async (q: string) => {
    try { const result = await dashboardApi.getBasicTrainingExamples(q); setExamples(result.examples || []); }
    catch (cause) { setError(cause instanceof Error ? cause.message : 'Could not load saved SQL examples.'); }
  }, []);

  useEffect(() => { void loadSchema('auto'); }, [loadSchema]);
  useEffect(() => { void loadExamples(''); }, [loadExamples]);
  useEffect(() => { if (initialQuestion.trim()) setQuestion(initialQuestion.trim()); }, [initialQuestion]);

  const filteredTables = useMemo(() => {
    const needle = filter.trim().toLowerCase();
    return tables.filter(table => !needle || table.table.toLowerCase().includes(needle) || table.columns.some(column => column.name.toLowerCase().includes(needle)));
  }, [filter, tables]);
  const selectedSchema = useMemo(() => Object.fromEntries(Object.entries(selected).filter(([, columns]) => columns.length)), [selected]);
  const selectedTableNames = useMemo(() => Object.keys(selectedSchema), [selectedSchema]);
  const selectedCount = Object.values(selectedSchema).reduce((sum, columns) => sum + columns.length, 0);
  const availableFilterFields = tables.flatMap(table => (selectedSchema[table.table] || []).map(name => ({ table: table.table, name, type: table.columns.find(column => column.name === name)?.type || '' })));
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
  const currentPreviewTable = tables.find(table => table.table === previewTable);
  const togglePreviewColumn = (name: string) => setPreviewColumns(current => current.includes(name) ? current.filter(column => column !== name) : [...current, name]);
  const previewFilterFields = currentPreviewTable?.columns || [];
  const visiblePreviewFilterFields = previewFilterFields.filter(column => !previewFieldSearch.trim()
    || column.name.toLowerCase().includes(previewFieldSearch.trim().toLowerCase())
    || column.type.toLowerCase().includes(previewFieldSearch.trim().toLowerCase()));
  const addPreviewFilter = (column: string) => {
    setPreviewFilters(current => [...current, { id: crypto.randomUUID(), table: previewTable, column, operator: 'include_value', value: '', upper: '' }]);
    setPreviewResult(null); setError('');
  };
  const patchPreviewFilter = (id: string, patch: Partial<TrainingFilter>) => {
    setPreviewFilters(current => current.map(item => item.id === id ? { ...item, ...patch } : item));
    setPreviewResult(null); setError('');
  };
  const isDateColumn = (column?: SchemaColumn) => !!column && (/date|time/i.test(column.type) || /^(fkdat|fkdat_rl|erdat|aedat|budat|bldat|ftrms|gltrp|gstrp|gltrs|gstrs|gstri|getri|gltri|ftrmi|ftrmp|pdatv|sdatv|trmdt|valdt|kdatb|kdate|bedat|cpudt|audat|eindt|lfdat|prsdt|zfbdt|datuv|ersda|laeda|vdatu|prdat)$/i.test(column.name) || /(?:_date|_dt|date|dat|startd|endd)$/i.test(column.name));
  const isNumberColumn = (column?: SchemaColumn) => !!column && (/int|numeric|decimal|float|double|real/i.test(column.type) || /^(netwr|mwsbk|rmwwr|wavwr|fkwrt|wrbtr|dmbtr|salk3|stprs|verpr|peinh|netpr|mwsbp|kwmeng|fkimg|lfimg|menge|gamng|bmenge|vfmng|lmeng|brgew|ntgew|kzwi[1-6])$/i.test(column.name));
  const previewData = async () => {
    if (!previewTable || !previewColumns.length) { setError('Choose a table and at least one column to preview.'); return; }
    if (previewFilters.some(item => !item.value.trim() || ((item.operator === 'include_range' || item.operator === 'exclude_range') && !item.upper.trim()))) {
      setError('Complete or remove each filter condition before previewing the table.'); return;
    }
    setError(''); setPreviewLoading(true); setPreviewResult(null);
    try {
      const result = await dashboardApi.previewBasicTrainingTable({ source, table: previewTable, columns: previewColumns, limit: 50, filters: previewFilters.map(({ table, column, operator, value, upper }) => ({ table, column, operator, value, upper })) });
      if (result.status !== 'executed') { setError(result.error || 'Could not preview this table.'); return; }
      if (previewFilters.length && result.applied_filters !== previewFilters.length) {
        setError('The database service did not confirm that every filter was applied. Refresh the local API, then run this preview again. No unfiltered rows were shown.');
        return;
      }
      setPreviewResult(result); setNotice(`Previewed ${result.row_count} row${result.row_count === 1 ? '' : 's'} from ${previewTable} · 0 model calls.`);
    } catch (cause) { setError(cause instanceof Error ? cause.message : 'Could not preview this table.'); }
    finally { setPreviewLoading(false); }
  };
  const usePreviewInTraining = () => {
    if (!previewResult?.sql || !previewTable) return;
    setSql(previewResult.sql); setQuestion(`Preview selected columns from ${previewTable}`); setTrainingFilters([]); setRun(null);
    setSelected(current => ({ ...current, [previewTable]: [...new Set([...(current[previewTable] || []), ...previewColumns])] }));
    setActiveTab('training'); setNotice('Table and selected columns were added to SQL Training with a safe SELECT starter. Edit the question/SQL, run and check it, then save if correct.');
  };

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
      const result = await dashboardApi.executeBasicTrainingSql({ source, question: question.trim(), sql, selected_schema: selectedSchema, filters: trainingFilters.map(({ table, column, operator, value, upper }) => ({ table, column, operator, value, upper })) });
      if (result.status !== 'executed') { setError(result.error || 'The SQL could not be executed.'); return; }
      setSql(result.sql || sql); setTrainingFilters([]); setRun(result); setNotice(`${result.row_count} row${result.row_count === 1 ? '' : 's'} returned · 0 model calls. The applied filters are visible in Executed SQL and will be saved with this checked example.`);
    } catch (cause) { setError(cause instanceof Error ? cause.message : 'Query execution failed.'); }
    finally { setRunning(false); }
  };

  const saveExample = async () => {
    if (!run?.run_id) return;
    setSaving(true); setError('');
    try { const result = await dashboardApi.saveBasicTrainingExample(run.run_id, question.trim()); setNotice(`Saved as revision ${result.revision}. In AI Analyst → Basic, find this wording under Questions → Verified saved questions.`); window.dispatchEvent(new Event('basic-queries-saved')); await loadExamples(''); }
    catch (cause) { setError(cause instanceof Error ? cause.message : 'Could not save this example.'); }
    finally { setSaving(false); }
  };

  const loadExample = (example: Example) => {
    setQuestion(example.question); setSql(example.sql); setTrainingFilters([]); setRun(null); setError('');
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
          <div className="flex items-center gap-2"><label className="sr-only" htmlFor="training-source">Database</label><select id="training-source" value={source} onChange={event => void loadSchema(event.target.value as TrainingSource)} className="rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm"><option value="business">Business database</option><option value="application">Application database</option></select>
            <button type="button" onClick={() => void loadSchema(source)} disabled={loadingSchema} className="inline-flex items-center gap-2 rounded-lg border px-3 py-2 text-sm hover:bg-slate-50 disabled:opacity-50"><RefreshCw className={`h-4 w-4 ${loadingSchema ? 'animate-spin' : ''}`}/>Refresh</button></div>
        </div>
        <p className="mt-2 text-xs text-slate-500">SQL dialect: PostgreSQL · Schema: {schemaSource || (loadingSchema ? 'loading…' : 'unavailable')} · Selected: {Object.keys(selectedSchema).length} tables, {selectedCount} columns</p>
      </section>

      {error && <div role="alert" className="rounded-xl border border-red-200 bg-red-50 p-3 text-sm text-red-800">{error}</div>}
      {notice && <div role="status" className="rounded-xl border border-emerald-200 bg-emerald-50 p-3 text-sm text-emerald-800">{notice}</div>}

      <div role="tablist" aria-label="Basic SQL Training views" className="flex w-fit gap-1 rounded-xl border bg-white p-1 shadow-sm">
        <button type="button" role="tab" aria-selected={activeTab === 'training'} onClick={() => setActiveTab('training')} className={`rounded-lg px-4 py-2 text-sm font-medium ${activeTab === 'training' ? 'bg-indigo-700 text-white' : 'text-slate-600 hover:bg-slate-100'}`}>SQL Training</button>
        <button type="button" role="tab" aria-selected={activeTab === 'data'} onClick={() => setActiveTab('data')} className={`rounded-lg px-4 py-2 text-sm font-medium ${activeTab === 'data' ? 'bg-indigo-700 text-white' : 'text-slate-600 hover:bg-slate-100'}`}>SAP Data Browser</button>
      </div>

      {activeTab === 'training' ? <div className="grid gap-4 xl:grid-cols-[minmax(18rem,0.8fr)_minmax(0,1.5fr)]">
        <section className="min-w-0 rounded-2xl border bg-white p-4 shadow-sm">
          <div className="flex items-center justify-between gap-2"><h4 className="font-semibold text-slate-900">Schema explorer</h4><div className="flex gap-2"><button type="button" title="Select every table and column currently shown by the search" onClick={() => setSelected(current => ({ ...current, ...Object.fromEntries(filteredTables.map(table => [table.table, table.columns.map(column => column.name)])) }))} className="text-xs text-indigo-700 hover:underline">Select all matching ({filteredTables.length})</button><button type="button" onClick={() => setSelected({})} className="text-xs text-slate-500 hover:underline">Clear</button></div></div>
          <div className="mt-3 rounded-lg border border-indigo-200 bg-indigo-50 p-3" role="status">
            <div className="flex flex-wrap items-center justify-between gap-2"><p className="text-xs font-semibold text-indigo-950">Tables included in this SQL ({selectedTableNames.length})</p><p className="text-[11px] text-indigo-800">Select multiple tables for joins, such as VBRK + VBRP.</p></div>
            {selectedTableNames.length > 0 ? <div className="mt-2 flex flex-wrap gap-1.5">{selectedTableNames.map(tableName => <span key={tableName} className="inline-flex items-center gap-1 rounded-full border border-indigo-200 bg-white px-2 py-1 text-[11px] font-medium text-indigo-900">{tableName}<button type="button" aria-label={`Remove ${tableName} from selected tables`} onClick={() => setSelected(current => ({ ...current, [tableName]: [] }))} className="rounded-full p-0.5 text-indigo-600 hover:bg-indigo-100"><X className="h-3 w-3"/></button></span>)}</div> : <p className="mt-1 text-[11px] text-indigo-800">No tables selected yet. Search for each table and check it; searching for another table keeps your earlier selections.</p>}
          </div>
          <label className="relative mt-3 block"><Search className="absolute left-3 top-2.5 h-4 w-4 text-slate-400"/><input value={filter} onChange={event => setFilter(event.target.value)} placeholder="Search tables or columns" className="w-full rounded-lg border py-2 pl-9 pr-3 text-sm"/></label>
          <p className="mt-1 text-[11px] text-slate-500">Showing {filteredTables.length} of {tables.length} tables{filter.trim() ? ' matching your search' : ''}. Search for a table, check its box, then search for the next one. Earlier checked tables stay selected. “Select all matching” selects every column in every matching table.</p>
          <p className="mt-2 text-[11px] text-slate-500">For a join, add every table and the columns your SQL uses here, then write the JOIN conditions in SQL. The SAP Data Browser tab previews one table at a time.</p>
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
            <div className="mt-3 rounded-xl border border-slate-200 bg-slate-50 p-3">
              <div className="flex flex-wrap items-center justify-between gap-2"><div><h5 className="text-sm font-semibold text-slate-800">Selection filters (SAP style)</h5><p className="mt-0.5 text-xs text-slate-500">Add include or exclude values/ranges, or choose greater/less. Filters are added to your SQL before it runs.</p></div><button type="button" disabled={!availableFilterFields.length} onClick={() => { const first = availableFilterFields[0]; if (first) setTrainingFilters(current => [...current, { id: crypto.randomUUID(), table: first.table, column: first.name, operator: 'include_range', value: '', upper: '' }]); }} className="rounded-lg border bg-white px-3 py-1.5 text-xs font-medium disabled:opacity-40">Add filter</button></div>
              {trainingFilters.map(item => { const fields = availableFilterFields; const selectedField = fields.find(field => field.table === item.table && field.name === item.column); const visibleFields = fields.filter(field => field.table === item.table && (field.name === item.column || !trainingFieldSearch.trim() || field.name.toLowerCase().includes(trainingFieldSearch.trim().toLowerCase()))); const isRange = item.operator === 'include_range' || item.operator === 'exclude_range'; return <div key={item.id} className="mt-2 grid gap-2 rounded-lg border bg-white p-2 sm:grid-cols-2 xl:grid-cols-[minmax(8rem,1fr)_minmax(8rem,1fr)_minmax(10rem,1fr)_minmax(7rem,0.8fr)_minmax(7rem,0.8fr)_auto]">
                <select aria-label="Filter table" value={item.table} onChange={event => { const table = event.target.value; const first = fields.find(field => field.table === table); setTrainingFilters(current => current.map(filter => filter.id === item.id ? { ...filter, table, column: first?.name || '' } : filter)); }} className="rounded-md border px-2 py-1.5 text-xs">{[...new Set(fields.map(field => field.table))].map(table => <option key={table} value={table}>{table}</option>)}</select>
                <div className="min-w-0 space-y-1"><input aria-label="Find filter field" value={trainingFieldSearch} onChange={event => setTrainingFieldSearch(event.target.value)} placeholder="Find field, e.g. NETWR" className="w-full rounded-md border px-2 py-1.5 text-xs"/><select aria-label="Filter field" value={item.column} onChange={event => setTrainingFilters(current => current.map(filter => filter.id === item.id ? { ...filter, column: event.target.value } : filter))} className="w-full rounded-md border px-2 py-1.5 text-xs">{visibleFields.map(field => <option key={field.name} value={field.name}>{field.name} · {field.type}</option>)}{visibleFields.length === 1 && trainingFieldSearch.trim() && !visibleFields.some(field => field.name.toLowerCase().includes(trainingFieldSearch.trim().toLowerCase())) && <option value={item.column}>{item.column} · current</option>}</select></div>
                <select aria-label="Filter operation" value={item.operator} onChange={event => setTrainingFilters(current => current.map(filter => filter.id === item.id ? { ...filter, operator: event.target.value as FilterOperator } : filter))} className="rounded-md border px-2 py-1.5 text-xs"><option value="include_value">Include value</option><option value="include_range">Include range</option><option value="exclude_value">Exclude value</option><option value="exclude_range">Exclude range</option><option value="greater_than">Greater than</option><option value="less_than">Less than</option></select>
                <input aria-label="Filter value or lower limit" value={item.value} onChange={event => setTrainingFilters(current => current.map(filter => filter.id === item.id ? { ...filter, value: event.target.value } : filter))} placeholder={isRange ? 'From / lower limit' : selectedField?.type.toLowerCase().includes('date') ? 'DD.MM.YYYY' : 'Value'} className="min-w-0 rounded-md border px-2 py-1.5 text-xs"/>
                {isRange && <input aria-label="Filter upper limit" value={item.upper} onChange={event => setTrainingFilters(current => current.map(filter => filter.id === item.id ? { ...filter, upper: event.target.value } : filter))} placeholder="To / upper limit" className="min-w-0 rounded-md border px-2 py-1.5 text-xs"/>}
                <button type="button" onClick={() => setTrainingFilters(current => current.filter(filter => filter.id !== item.id))} className="rounded-md px-2 py-1 text-xs text-red-700 hover:bg-red-50">Remove</button>
              </div>; })}
              {trainingFilters.length === 0 && <p className="mt-2 text-xs text-slate-500">No extra filters. Use this when the SAP selection screen has date, value, customer, or billing-type criteria.</p>}
            </div>
            <label className="mt-3 block text-xs font-medium text-slate-600">Read-only SQL<textarea value={sql} onChange={event => setSql(event.target.value)} maxLength={24000} rows={10} spellCheck={false} placeholder={'SELECT customer_id, SUM(net_value) AS billed_sales\nFROM billing_documents\nGROUP BY customer_id\nORDER BY billed_sales DESC\nLIMIT 10;'} className="mt-1 w-full rounded-xl border bg-slate-950 p-3 font-mono text-xs leading-5 text-slate-100 placeholder:text-slate-500"/></label>
            <div className="mt-3 flex flex-wrap items-center gap-2"><button type="button" onClick={() => void execute()} disabled={running || loadingSchema} className="inline-flex items-center gap-2 rounded-lg bg-indigo-700 px-4 py-2 text-sm font-medium text-white hover:bg-indigo-800 disabled:opacity-50">{running ? <Loader2 className="h-4 w-4 animate-spin"/> : <Play className="h-4 w-4"/>}{running ? 'Running read-only query…' : 'Run SQL'}</button>{run?.run_id && <button type="button" onClick={() => void saveExample()} disabled={saving} className="inline-flex items-center gap-2 rounded-lg border border-emerald-300 bg-emerald-50 px-4 py-2 text-sm font-medium text-emerald-800 disabled:opacity-50">{saving ? <Loader2 className="h-4 w-4 animate-spin"/> : <Save className="h-4 w-4"/>}Save checked example</button>}<span className="text-xs text-slate-500">SELECT/WITH only · database scope and selected schema enforced · no model call</span></div>
          </section>

          {run && <section className="rounded-2xl border bg-white p-4 shadow-sm"><div className="flex flex-wrap items-center justify-between gap-2"><div><h4 className="font-semibold text-slate-900">Query results</h4><p className="text-xs text-slate-500">{run.row_count} rows · 0 model calls</p></div><span className="inline-flex items-center gap-1 rounded-full bg-emerald-50 px-2.5 py-1 text-xs text-emerald-800"><Check className="h-3.5 w-3.5"/>Executed</span></div>
            <div className="mt-3 max-h-96 overflow-auto rounded-lg border"><table className="min-w-full text-left text-xs"><thead className="sticky top-0 bg-slate-100"><tr>{run.columns.map(column => <th key={column} className="whitespace-nowrap px-3 py-2 font-semibold text-slate-700">{column}</th>)}</tr></thead><tbody>{run.rows.map((row, index) => <tr key={index} className="border-t">{run.columns.map(column => <td key={column} className="max-w-xs whitespace-nowrap px-3 py-2 text-slate-700">{row[column] == null ? '—' : String(row[column])}</td>)}</tr>)}</tbody></table>{run.rows.length === 0 && <p className="p-4 text-sm text-slate-500">Query ran successfully and returned no rows.</p>}</div>
            <details className="mt-3"><summary className="cursor-pointer text-xs text-slate-600">Executed SQL</summary><pre className="mt-2 overflow-auto rounded-lg bg-slate-950 p-3 text-xs text-slate-100">{run.sql}</pre></details>
          </section>}
        </div>
      </div> : <section className="grid gap-4 xl:grid-cols-[minmax(18rem,0.75fr)_minmax(0,1.5fr)]">
        <div className="rounded-2xl border bg-white p-4 shadow-sm">
          <h4 className="font-semibold text-slate-900">Choose SAP table and columns</h4>
          <p className="mt-1 text-xs text-slate-500">Live schema fields and types. Select columns to preview up to 50 read-only rows.</p>
          <label className="mt-3 block text-xs font-medium text-slate-600">Table<select value={previewTable} onChange={event => { const nextTable = tables.find(table => table.table === event.target.value); setPreviewTable(event.target.value); setPreviewColumns(nextTable?.columns.slice(0, 12).map(column => column.name) || []); setPreviewFilters([]); setPreviewFieldSearch(''); setPreviewResult(null); setError(''); }} className="mt-1 w-full rounded-lg border bg-white px-3 py-2 text-sm">{tables.map(table => <option key={table.table} value={table.table}>{table.table}{table.description?.description ? ` · ${table.description.description}` : ''}</option>)}</select></label>
          {currentPreviewTable && <><div className="mt-3 flex items-center justify-between"><h5 className="text-xs font-semibold text-slate-700">Columns ({currentPreviewTable.columns.length})</h5><div className="flex gap-2"><button type="button" onClick={() => setPreviewColumns(currentPreviewTable.columns.map(column => column.name).slice(0, 60))} className="text-xs text-indigo-700 hover:underline">Select up to 60</button><button type="button" onClick={() => setPreviewColumns([])} className="text-xs text-slate-500 hover:underline">Clear</button></div></div>
            <div className="mt-2 max-h-[30rem] overflow-y-auto rounded-lg border p-2">{currentPreviewTable.columns.map(column => <label key={column.name} className="flex items-center gap-2 border-b py-1.5 text-xs last:border-0"><input type="checkbox" checked={previewColumns.includes(column.name)} onChange={() => togglePreviewColumn(column.name)}/><span className="font-medium text-slate-800">{column.name}</span><span className="text-slate-400">{column.type}</span>{column.primary_key && <span className="rounded bg-amber-100 px-1 text-amber-800">PK</span>}{column.foreign_key && <span className="rounded bg-sky-100 px-1 text-sky-800">FK</span>}<span className="ml-auto truncate text-slate-400">{column.description}</span></label>)}</div>
            <p className="mt-2 text-[11px] text-slate-500">{previewColumns.length} selected · up to 60 columns per preview</p>
            <div className="mt-4 rounded-xl border border-indigo-100 bg-indigo-50/60 p-3">
              <div className="flex flex-wrap items-end justify-between gap-2"><div><h5 className="text-xs font-semibold text-slate-800">Selection filters for {previewTable}</h5><p className="mt-1 text-[11px] leading-4 text-slate-600">This table’s fields are listed below. Add a condition beside any field; date, numeric, and text values get the matching inputs.</p></div><span className="text-[11px] text-slate-500">{previewFilterFields.length} fields</span></div>
              <input aria-label="Search filter fields" value={previewFieldSearch} onChange={event => setPreviewFieldSearch(event.target.value)} placeholder="Find a filter field" className="mt-3 w-full rounded-md border bg-white px-3 py-2 text-xs"/>
              <div className="mt-2 max-h-[32rem] space-y-2 overflow-y-auto pr-1">{visiblePreviewFilterFields.map(field => {
                const fieldFilters = previewFilters.filter(item => item.column === field.name);
                const inputType = isDateColumn(field) ? 'date' : isNumberColumn(field) ? 'number' : 'text';
                const placeholder = isDateColumn(field) ? 'Choose date' : isNumberColumn(field) ? 'Enter amount' : 'Enter value';
                return <div key={field.name} className="rounded-lg border bg-white p-2">
                  <div className="flex flex-wrap items-center justify-between gap-2"><div><span className="text-xs font-semibold text-slate-800">{field.name}</span><span className="ml-2 text-[10px] text-slate-400">{field.type}</span></div><button type="button" onClick={() => addPreviewFilter(field.name)} className="rounded-md border px-2 py-1 text-[11px] font-medium text-indigo-700 hover:bg-indigo-50">Add condition</button></div>
                  {fieldFilters.map((item, index) => {
                    const isRange = item.operator === 'include_range' || item.operator === 'exclude_range';
                    return <div key={item.id} className="mt-2 grid gap-2 rounded-md bg-slate-50 p-2 sm:grid-cols-2">
                      <label className="text-[10px] font-medium text-slate-600">Condition {index + 1}<select aria-label={`Selection for ${field.name}`} value={item.operator} onChange={event => patchPreviewFilter(item.id, { operator: event.target.value as FilterOperator, upper: '' })} className="mt-1 w-full rounded-md border bg-white px-2 py-2 text-xs"><option value="include_value">Include single value</option><option value="include_range">Include range</option><option value="exclude_value">Exclude single value</option><option value="exclude_range">Exclude range</option><option value="greater_than">Greater than</option><option value="less_than">Less than</option></select></label>
                      <label className="text-[10px] font-medium text-slate-600">{isRange ? 'From / lower limit' : 'Value'}<input aria-label={`${field.name} value or lower limit`} type={inputType} step={inputType === 'number' ? 'any' : undefined} value={item.value} placeholder={placeholder} onInput={event => patchPreviewFilter(item.id, { value: event.currentTarget.value })} onChange={event => patchPreviewFilter(item.id, { value: event.currentTarget.value })} className="mt-1 w-full rounded-md border bg-white px-2 py-2 text-xs"/></label>
                      {isRange && <label className="text-[10px] font-medium text-slate-600">To / upper limit<input aria-label={`${field.name} upper limit`} type={inputType} step={inputType === 'number' ? 'any' : undefined} value={item.upper} placeholder={placeholder} onInput={event => patchPreviewFilter(item.id, { upper: event.currentTarget.value })} onChange={event => patchPreviewFilter(item.id, { upper: event.currentTarget.value })} className="mt-1 w-full rounded-md border bg-white px-2 py-2 text-xs"/></label>}
                      <button type="button" onClick={() => { setPreviewFilters(current => current.filter(filter => filter.id !== item.id)); setPreviewResult(null); setError(''); }} className="justify-self-start text-[10px] font-medium text-red-700 hover:underline">Remove condition</button>
                    </div>;
                  })}
                </div>;
              })}</div>
              {previewFilterFields.length > 0 && visiblePreviewFilterFields.length === 0 && <p className="mt-2 text-[11px] text-slate-500">No fields match that search.</p>}
              {previewFilters.length === 0 && <p className="mt-2 text-[11px] text-slate-500">No conditions yet. Choose a field above and add one or more SAP selection conditions.</p>}
            </div>
            <button type="button" onClick={() => void previewData()} disabled={previewLoading || !previewColumns.length} className="mt-3 inline-flex items-center gap-2 rounded-lg bg-indigo-700 px-4 py-2 text-sm font-medium text-white disabled:opacity-50">{previewLoading ? <Loader2 className="h-4 w-4 animate-spin"/> : <Search className="h-4 w-4"/>}{previewLoading ? 'Loading rows…' : 'Show table data'}</button>
          </>}
        </div>
        <div className="min-w-0 rounded-2xl border bg-white p-4 shadow-sm">
          <div className="flex flex-wrap items-center justify-between gap-2"><div><h4 className="font-semibold text-slate-900">{previewTable || 'Table'} data preview</h4><p className="mt-1 text-xs text-slate-500">Read-only preview · maximum 50 rows · 0 AI/model calls · nothing is saved until you train it.</p></div>{previewResult && <button type="button" onClick={usePreviewInTraining} className="rounded-lg border border-emerald-300 bg-emerald-50 px-3 py-2 text-xs font-medium text-emerald-800">Prefill SQL Training</button>}</div>
          {!previewResult && <div className="mt-4 rounded-lg border border-dashed p-8 text-center text-sm text-slate-500">Choose a table and columns, then select <strong>Show table data</strong>.</div>}
          {previewResult && <><p className="mt-3 text-xs text-slate-500">Showing {previewResult.row_count} row{previewResult.row_count === 1 ? '' : 's'} · query limit {previewResult.limit || 50}</p><div className="mt-2 max-h-[36rem] overflow-auto rounded-lg border"><table className="min-w-full text-left text-xs"><thead className="sticky top-0 bg-slate-100"><tr>{previewResult.columns.map(column => <th key={column} className="whitespace-nowrap px-3 py-2 font-semibold text-slate-700">{column}</th>)}</tr></thead><tbody>{previewResult.rows.map((row, index) => <tr key={index} className="border-t">{previewResult.columns.map(column => <td key={column} className="max-w-xs whitespace-nowrap px-3 py-2 text-slate-700">{row[column] == null ? '—' : String(row[column])}</td>)}</tr>)}</tbody></table>{previewResult.rows.length === 0 && <p className="p-4 text-sm text-slate-500">No rows found for the selected table.</p>}</div><details className="mt-3"><summary className="cursor-pointer text-xs text-slate-600">Preview SQL</summary><pre className="mt-2 overflow-auto rounded-lg bg-slate-950 p-3 text-xs text-slate-100">{previewResult.sql}</pre></details></>}
        </div>
      </section>}

      <section className="rounded-2xl border bg-white p-4 shadow-sm"><div className="flex flex-wrap items-center justify-between gap-3"><div><h4 className="font-semibold text-slate-900">Saved SQL examples</h4><p className="mt-1 text-xs text-slate-500">Saved wording and SQL are isolated to your accessible workspace. Load and rerun to check current figures.</p></div><div className="flex gap-2"><input value={exampleFilter} onChange={event => setExampleFilter(event.target.value)} onKeyDown={event => { if (event.key === 'Enter') void loadExamples(exampleFilter); }} placeholder="Search saved wording or SQL" className="w-56 rounded-lg border px-3 py-2 text-xs"/><button type="button" onClick={() => void loadExamples(exampleFilter)} className="rounded-lg border px-3 py-2 text-xs">Search</button></div></div>
        <div className="mt-3 divide-y">{examples.map(example => <div key={example.id} className="flex flex-wrap items-center justify-between gap-3 py-3"><div className="min-w-0"><p className="truncate text-sm font-medium text-slate-800">{example.question}</p><p className="mt-1 text-xs text-slate-500">Revision {example.revision} · {example.dialect} · {example.validation_status} · {new Date(example.updated_at).toLocaleString()}</p><code className="mt-1 block max-w-3xl truncate text-[11px] text-slate-500">{example.sql}</code></div><div className="flex shrink-0 gap-2"><button type="button" onClick={() => loadExample(example)} className="rounded-lg border px-3 py-2 text-xs">Load to editor</button><button type="button" onClick={() => void editExample(example)} className="rounded-lg border px-3 py-2 text-xs">Edit SQL</button></div></div>)}{examples.length === 0 && <p className="py-6 text-center text-sm text-slate-500">No saved examples yet. Run a query successfully, then save it here.</p>}</div>
      </section>
    </div>
  </div>;
}
