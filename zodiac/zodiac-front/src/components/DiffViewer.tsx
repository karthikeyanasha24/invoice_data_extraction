'use client';

import type { DiffLine } from '@/types';

interface DiffViewerProps {
  originalContent: string;
  fixedContent: string;
  diffs: DiffLine[];
  fileType: string;
  isAiCorrected: boolean;
  totalModifiedLines: number;
}

export default function DiffViewer({
  originalContent,
  fixedContent,
  diffs,
  fileType,
  isAiCorrected,
  totalModifiedLines,
}: DiffViewerProps) {
  return (
    <div className="space-y-3 rounded-lg border border-gray-200 bg-white overflow-hidden">
      <div className="flex flex-wrap items-center gap-2 px-3 py-2 bg-slate-50 border-b text-sm">
        <span className="font-medium text-gray-700">{fileType.toUpperCase()} comparison</span>
        {isAiCorrected ? (
          <span className="rounded bg-violet-100 text-violet-800 px-2 py-0.5 text-xs">AI-corrected</span>
        ) : null}
        <span className="text-gray-500">{totalModifiedLines} line(s) changed</span>
      </div>
      {diffs?.length ? (
        <div className="max-h-96 overflow-auto font-mono text-xs">
          {diffs.map((d, i) => {
            const rowClass =
              d.change_type === 'removed'
                ? 'bg-red-50 text-red-900'
                : d.change_type === 'added'
                  ? 'bg-green-50 text-green-900'
                  : d.is_modified
                    ? 'bg-amber-50 text-amber-900'
                    : 'bg-white text-gray-600';
            let text = d.original_text || d.fixed_text;
            if (d.change_type === 'added') text = d.fixed_text;
            if (d.change_type === 'removed') text = d.original_text;
            if (d.is_modified && d.change_type !== 'added' && d.change_type !== 'removed') {
              text = `${d.original_text} → ${d.fixed_text}`;
            }
            return (
              <div key={i} className={`flex gap-1 border-b border-gray-100 ${rowClass}`}>
                <span className="w-10 shrink-0 text-gray-400 px-1 select-none">{d.line_number}</span>
                <span className="whitespace-pre-wrap break-all py-0.5 pr-2">{text}</span>
              </div>
            );
          })}
        </div>
      ) : (
        <div className="grid grid-cols-1 md:grid-cols-2 gap-0 max-h-96 border-t border-gray-100">
          <pre className="p-3 overflow-auto text-xs bg-red-50/40 border-r border-gray-100">{originalContent}</pre>
          <pre className="p-3 overflow-auto text-xs bg-green-50/40">{fixedContent}</pre>
        </div>
      )}
    </div>
  );
}
