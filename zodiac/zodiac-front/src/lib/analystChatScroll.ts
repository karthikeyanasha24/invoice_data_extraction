/** Keep automatic replies from pulling a reader away from older messages. */
export function analystScrollPosition(scrollTop: number, scrollHeight: number, clientHeight: number) {
  const maximum = Math.max(0, scrollHeight - clientHeight);
  const position = Math.max(0, Math.min(scrollTop, maximum));
  return {
    canGoUp: position > 24,
    canGoDown: maximum - position > 24,
    nearBottom: maximum - position <= 96,
  };
}
