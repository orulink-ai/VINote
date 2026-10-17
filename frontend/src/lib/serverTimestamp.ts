/** SQLite drops the offset from API timestamps created in UTC. Explicit offsets
 * from Postgres are retained. Do not apply this to user-entered meeting times. */
export function serverTimestamp(value: string): Date {
  const utcWithoutOffset = /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?$/.test(value)
  return new Date(utcWithoutOffset ? `${value}Z` : value)
}
