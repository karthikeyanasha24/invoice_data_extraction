/**
 * Investigation launch policy.
 *
 * Isolation: a new Overview / ?q= / saved restore / explicit "new investigation"
 * must not inherit filters from an unrelated dirty thread.
 *
 * Continuity: navigating away and back, refresh, and follow-up chips keep
 * the current investigation. History is never silently replaced with a blank.
 */

export type LaunchSource =
  | 'overview-url'
  | 'overview-chip'
  | 'followup-chip'
  | 'explicit-new'
  | 'typed-continue'
  | 'saved-restore'
  | 'history-restore'
  | 'refresh';

export type InvestigationLaunch = {
  asNew: boolean;
  keepHistory: boolean;
  sendQuestion: boolean;
  banner: string | null;
};

const NEW_SOURCES: LaunchSource[] = [
  'overview-url',
  'overview-chip',
  'explicit-new',
  'saved-restore',
];

export function investigationLaunch(
  source: LaunchSource,
  sessionDirty: boolean,
): InvestigationLaunch {
  const asNew = NEW_SOURCES.includes(source);
  const sendQuestion = source !== 'history-restore' && source !== 'refresh';
  // Never wipe the visible conversation to isolate filters. Only "Start a new
  // investigation" (clearAll) mints a new thread. The new-question toggle is asNew.
  const keepHistory = true;

  let banner: string | null = null;
  if (source === 'overview-url' || source === 'overview-chip') {
    banner = sessionDirty
      ? 'Starting a new investigation from Overview. Filters from the previous investigation were not applied.'
      : 'Starting a recommended investigation.';
  } else if (source === 'explicit-new') {
    banner = 'Starting a new investigation. Previous filters will not be applied.';
  } else if (source === 'saved-restore') {
    banner = sessionDirty
      ? 'Opening a saved investigation as a new question. Previous filters were not applied.'
      : 'Opening a saved investigation.';
  }
  // typed-continue / followup-chip: no banner — continuous chat like ChatGPT

  return { asNew, keepHistory, sendQuestion, banner };
}

export function shouldTreatAsNew(opts: {
  asNewFlag?: boolean;
  newQuestionToggle?: boolean;
  source?: LaunchSource;
}): boolean {
  if (opts.asNewFlag) return true;
  if (opts.newQuestionToggle) return true;
  if (opts.source && NEW_SOURCES.includes(opts.source)) return true;
  return false;
}

/** After an Overview / ?q= question is sent, drop q so refresh does not re-ask. */
export function analystPathWithoutQuery(): string {
  return '/dashboard/ai';
}

export function overviewQuestionHref(question: string): string {
  return `/dashboard/ai?q=${encodeURIComponent(question.trim())}`;
}
