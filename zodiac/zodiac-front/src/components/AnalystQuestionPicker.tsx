'use client';

import { useEffect, useId, useRef, useState } from 'react';
import { ChevronDown, Search, X } from 'lucide-react';
import { dashboardApi } from '@/lib/api';

export default function AnalystQuestionPicker({ predefined, disabled, onSelect }: {
  predefined: string[];
  disabled: boolean;
  onSelect: (question: string, verified: boolean) => void;
}) {
  const [open, setOpen] = useState(false);
  const [search, setSearch] = useState('');
  const [saved, setSaved] = useState<string[]>([]);
  const [databaseQuestions, setDatabaseQuestions] = useState<string[]>([]);
  const [patterns, setPatterns] = useState<string[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const [refresh, setRefresh] = useState(0);
  const panelId = useId();
  const root = useRef<HTMLDivElement>(null);
  const trigger = useRef<HTMLButtonElement>(null);
  const searchInput = useRef<HTMLInputElement>(null);

  useEffect(() => {
    if (!open) return;
    let active = true;
    setLoading(true);
    setError('');
    dashboardApi.getBasicQuestions().then(result => {
      if (active) {
        setSaved(result.questions);
        setDatabaseQuestions(result.database_questions || []);
        setPatterns(result.predefined_questions || []);
      }
    }).catch(() => {
        if (active) { setSaved([]); setDatabaseQuestions([]); setError('Could not load question suggestions.'); }
    }).finally(() => { if (active) setLoading(false); });
    return () => { active = false; };
  }, [open, refresh]);

  useEffect(() => {
    if (!open) return;
    searchInput.current?.focus();
    const outside = (event: PointerEvent) => {
      if (!root.current?.contains(event.target as Node)) setOpen(false);
    };
    const updated = () => setRefresh(value => value + 1);
    document.addEventListener('pointerdown', outside);
    window.addEventListener('basic-queries-saved', updated);
    return () => {
      document.removeEventListener('pointerdown', outside);
      window.removeEventListener('basic-queries-saved', updated);
    };
  }, [open]);

  const matches = (question: string) => question.toLocaleLowerCase().includes(search.trim().toLocaleLowerCase());
  const databaseSet = new Set(databaseQuestions.map(question => question.toLocaleLowerCase()));
  const allPredefined = [...new Set([...patterns, ...predefined])].filter(question => !databaseSet.has(question.toLocaleLowerCase()));
  const verifiedMatches = saved.filter(matches);
  const databaseMatches = databaseQuestions.filter(matches);
  const predefinedMatches = allPredefined.filter(matches);
  const choose = (question: string, verified: boolean) => {
    onSelect(question, verified);
    setOpen(false);
    setSearch('');
  };

  return (
    <div ref={root} className="relative shrink-0" onKeyDown={event => {
      if (event.key === 'Escape') { setOpen(false); trigger.current?.focus(); }
    }} onBlur={event => {
      if (!event.currentTarget.contains(event.relatedTarget)) setOpen(false);
    }}>
      <button ref={trigger} type="button" aria-expanded={open} aria-controls={panelId}
        onClick={() => setOpen(value => !value)}
        className="inline-flex min-h-10 items-center gap-1.5 rounded-xl border border-slate-200 bg-white px-3 text-xs font-medium text-slate-700 hover:bg-slate-50">
        Questions <ChevronDown className="h-3.5 w-3.5" />
      </button>
      {open && (
        <section id={panelId} aria-label="Question suggestions"
          className="absolute right-0 top-full z-50 mt-2 flex max-h-[min(70dvh,36rem)] w-[min(26rem,calc(100vw-2rem))] flex-col rounded-2xl border border-slate-200 bg-white text-left shadow-xl">
          <div className="border-b border-slate-100 p-4">
            <div className="flex items-center justify-between gap-2">
              <h3 className="text-sm font-semibold text-slate-900">Choose a question</h3>
              <button type="button" aria-label="Close question suggestions" onClick={() => { setOpen(false); trigger.current?.focus(); }}
                className="rounded-lg p-1.5 text-slate-500 hover:bg-slate-100"><X className="h-4 w-4" /></button>
            </div>
            <p className="mt-1 text-xs text-slate-500">Select a question to put it in your message, then send when ready.</p>
            <label className="mt-3 flex items-center gap-2 rounded-lg border border-slate-200 px-3 py-2">
              <Search className="h-4 w-4 shrink-0 text-slate-400" />
              <input ref={searchInput} aria-label="Search questions" value={search} onChange={event => setSearch(event.target.value)}
                placeholder="Search all questions…" className="min-w-0 flex-1 text-sm outline-none" />
            </label>
          </div>
          <div className="min-h-0 overflow-y-auto overscroll-contain p-2">
            <div className="px-2 pb-1 pt-2">
              <h4 className="text-xs font-semibold text-emerald-800">Verified saved questions{!loading && !error && ` (${saved.length})`}</h4>
              <p className="mt-1 text-[11px] text-slate-500">Saved for your account. Opens in Basic to reuse checked SQL.</p>
            </div>
            {loading && <p role="status" className="p-2 text-xs text-slate-500">Loading questions…</p>}
            {error && <div role="alert" className="flex items-center gap-2 p-2 text-xs text-red-700">{error}
              <button type="button" onClick={() => setRefresh(value => value + 1)} className="font-medium underline">Retry</button>
            </div>}
            {!loading && !error && !saved.length && <p className="p-2 text-xs text-slate-500">Use “Reuse it in Basic Model” on a checked answer to add it here.</p>}
            {!loading && !error && saved.length > 0 && !verifiedMatches.length && <p className="p-2 text-xs text-slate-500">No saved questions match your search.</p>}
            {!loading && !error && verifiedMatches.map(question => (
              <button key={question} type="button" disabled={disabled} onClick={() => choose(question, true)}
                className="block w-full rounded-lg px-3 py-2.5 text-left text-sm text-slate-700 hover:bg-emerald-50 focus-visible:bg-emerald-50 disabled:opacity-50">{question}</button>
            ))}
            <div className="mt-2 border-t border-slate-100 px-2 pb-1 pt-3">
              <h4 className="text-xs font-semibold text-emerald-800">Database-tested questions{!loading && !error && ` (${databaseQuestions.length})`}</h4>
              <p className="mt-1 text-[11px] text-slate-500">Read-only queries tested on the configured extract. Opens in Basic and reruns on current data with your access.</p>
            </div>
            {!loading && !error && !databaseMatches.length && <p className="p-2 text-xs text-slate-500">No database questions match your search.</p>}
            {databaseMatches.map(question => (
              <button key={question} type="button" disabled={disabled} onClick={() => choose(question, true)}
                className="block w-full rounded-lg px-3 py-2.5 text-left text-sm text-slate-700 hover:bg-emerald-50 focus-visible:bg-emerald-50 disabled:opacity-50">{question}</button>
            ))}
            <div className="mt-2 border-t border-slate-100 px-2 pb-1 pt-3">
              <h4 className="text-xs font-semibold text-slate-700">Predefined questions ({allPredefined.length})</h4>
              <p className="mt-1 text-[11px] text-slate-500">Examples to explore using the selected method; Agentic may use credits.</p>
            </div>
            {!predefinedMatches.length && <p className="p-2 text-xs text-slate-500">No predefined questions match your search.</p>}
            {predefinedMatches.map(question => (
              <button key={question} type="button" disabled={disabled} onClick={() => choose(question, false)}
                className="block w-full rounded-lg px-3 py-2.5 text-left text-sm text-slate-700 hover:bg-slate-100 focus-visible:bg-slate-100 disabled:opacity-50">{question}</button>
            ))}
          </div>
        </section>
      )}
    </div>
  );
}
