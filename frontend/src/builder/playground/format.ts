/** Playground-local formatting helpers (ids are shown truncated + mono,
 * timestamps as HH:MM:SS readouts). */

/** First `length` chars of an id with an ellipsis (thread/task ids). */
export function shortId(id: string, length = 8): string {
  return id.length <= length ? id : `${id.slice(0, length)}…`;
}

/** HH:MM:SS local-time readout for ISO timestamps ("–" when absent). */
export function formatTime(iso: string | undefined | null): string {
  if (!iso) return "–";
  return new Date(iso).toLocaleTimeString([], {
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
  });
}
