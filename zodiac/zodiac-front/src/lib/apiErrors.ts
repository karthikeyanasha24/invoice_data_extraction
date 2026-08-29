/**
 * Map Axios / fetch failures to user-facing copy.
 * Technical details stay in console logging, not in the UI.
 */
export function publicApiError(err: any, fallback = 'Something went wrong. Please try again.'): string {
  const status = err?.response?.status as number | undefined;
  const code = String(err?.code || '');
  const raw = String(err?.message || '');

  if (err?.code === 'ERR_CANCELED' || err?.name === 'AbortError' || err?.name === 'CanceledError') {
    return 'Request cancelled.';
  }
  if (status === 401) {
    return 'Your session expired. Please sign in again.';
  }
  if (status === 403) {
    return 'You do not have permission to view this.';
  }
  if (status === 404) {
    return 'This dashboard service is temporarily unavailable. Please try again.';
  }
  if (status === 409) {
    return 'This action could not be completed because the data changed. Please refresh and try again.';
  }
  if (status === 429) {
    return 'Too many requests. Please wait a moment and try again.';
  }
  if (status && status >= 500) {
    return 'The server could not complete this request. Please try again.';
  }
  if (code === 'ECONNABORTED' || /timeout/i.test(raw)) {
    return 'This request took too long. Please try again.';
  }
  if (!err?.response && (code === 'ERR_NETWORK' || /network error|failed to fetch/i.test(raw))) {
    return 'Could not reach the server. Check your connection and try again.';
  }
  if (/axioserror|request failed with status code|typeerror|undefined|null|jwt|traceback|stack trace|http\s*50[0-9]/i.test(raw)) {
    return fallback;
  }
  if (raw && raw.length < 180 && !/\/[A-Za-z]:\\|traceback|stack|jwt|bearer/i.test(raw)) {
    return raw;
  }
  return fallback;
}
