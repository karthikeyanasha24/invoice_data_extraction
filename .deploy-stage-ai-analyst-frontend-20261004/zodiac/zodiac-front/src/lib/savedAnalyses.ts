export type SavedAnalysis = {
  id: string;
  question: string;
  summary: string;
  title?: string;
  intent?: string;
  rowCount?: number;
  savedAt: number;
};

/**
 * Device-local saved investigations (localStorage).
 *
 * Server persistence is intentionally not implemented: authenticated
 * chat_thread_store exists with user_id isolation, but there is no
 * dedicated saved-investigation table, list/delete API, or ownership
 * contract for bookmarks. Do not fake cloud sync. Fallback is this
 * browser-only list (max 25).
 */
const KEY = 'bridgeedi_saved_analyses';
const MAX = 25;

export function loadSavedAnalyses(): SavedAnalysis[] {
  if (typeof window === 'undefined') return [];
  try {
    const raw = localStorage.getItem(KEY);
    const parsed = raw ? JSON.parse(raw) : [];
    return Array.isArray(parsed) ? parsed : [];
  } catch {
    return [];
  }
}

export function saveAnalysis(entry: Omit<SavedAnalysis, 'id' | 'savedAt'>): SavedAnalysis[] {
  const next: SavedAnalysis = {
    ...entry,
    id: `sa_${Date.now().toString(36)}_${Math.random().toString(36).slice(2, 8)}`,
    savedAt: Date.now(),
  };
  const list = [next, ...loadSavedAnalyses().filter((x) => x.question !== entry.question)].slice(0, MAX);
  localStorage.setItem(KEY, JSON.stringify(list));
  return list;
}

export function removeSavedAnalysis(id: string): SavedAnalysis[] {
  const list = loadSavedAnalyses().filter((x) => x.id !== id);
  localStorage.setItem(KEY, JSON.stringify(list));
  return list;
}
