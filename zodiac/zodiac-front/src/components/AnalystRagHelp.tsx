'use client';

import { useEffect, useId, useRef, useState } from 'react';
import { CircleHelp, X } from 'lucide-react';

export default function AnalystRagHelp() {
  const [open, setOpen] = useState(false);
  const panelId = useId();
  const root = useRef<HTMLDivElement>(null);
  const trigger = useRef<HTMLButtonElement>(null);

  useEffect(() => {
    if (!open) return;
    const closeOutside = (event: PointerEvent) => {
      if (!root.current?.contains(event.target as Node)) setOpen(false);
    };
    document.addEventListener('pointerdown', closeOutside);
    return () => document.removeEventListener('pointerdown', closeOutside);
  }, [open]);

  return (
    <div ref={root} className="relative shrink-0" onKeyDown={event => {
      if (event.key === 'Escape') { setOpen(false); trigger.current?.focus(); }
    }}>
      <button ref={trigger} type="button" aria-expanded={open} aria-controls={panelId}
        onClick={() => setOpen(value => !value)}
        className="inline-flex min-h-10 items-center gap-1.5 rounded-xl border border-slate-200 bg-white px-3 text-xs font-medium text-slate-700 hover:bg-slate-50">
        <CircleHelp className="h-4 w-4" aria-hidden="true" />
        <span className="hidden sm:inline">How Basic works</span><span className="sm:hidden">Help</span>
      </button>
      {open && <section id={panelId} aria-label="How Basic RAG works"
        className="absolute right-0 top-full z-50 mt-2 flex max-h-[min(75dvh,38rem)] w-[min(27rem,calc(100vw-2rem))] flex-col rounded-2xl border border-slate-200 bg-white text-left shadow-xl">
        <div className="flex items-start justify-between gap-3 border-b border-slate-100 p-4">
          <div>
            <h3 className="text-sm font-semibold text-slate-900">How Basic uses RAG</h3>
            <p className="mt-1 text-xs text-slate-600">RAG means retrieving checked work before asking a model to investigate.</p>
          </div>
          <button type="button" aria-label="Close Basic help" onClick={() => { setOpen(false); trigger.current?.focus(); }}
            className="rounded-lg p-1 text-slate-500 hover:bg-slate-100"><X className="h-4 w-4" /></button>
        </div>
        <div className="min-h-0 overflow-y-auto p-4">
        <ol className="space-y-3 text-xs leading-5 text-slate-700">
          <li><strong className="text-slate-900">1. Check saved questions.</strong> A question you reviewed and saved with “Reuse it in Basic Model” can rerun its read-only SQL on current data. The same year, currency, customer, ranking, grouping, and conditions must match. This path makes 0 model calls.</li>
          <li><strong className="text-slate-900">2. Try tested patterns.</strong> Basic can build SQL for supported question shapes, including the database-tested questions under Questions. These also run with 0 model calls, but a tested pattern is separate from a personally checked answer.</li>
          <li><strong className="text-slate-900">3. Investigate a new question.</strong> Basic retrieves related checked examples and passes them to its configured model. Similar examples are guidance only; their SQL is never reused just because the wording looks close. Model calls use tokens. A self-hosted Ollama model has no per-token API fee, though its server still costs money.</li>
          <li><strong className="text-slate-900">4. Teach a good result.</strong> Check the figures, source SQL, filters, and any invoice breakdown. Then save the complete question. Basic remembers the checked query or replayable investigation, not the old numbers or new model weights.</li>
        </ol>
        <p className="mt-4 rounded-xl bg-slate-50 p-3 text-xs leading-5 text-slate-600">Basic does not automatically approve every answer. Changed filters need a new checked query, and older direct billed totals that mix currencies are excluded from replay. Agentic is a separate method and may use API credits. Internet research and Gemini comparisons are not part of Basic RAG.</p>
        </div>
      </section>}
    </div>
  );
}
