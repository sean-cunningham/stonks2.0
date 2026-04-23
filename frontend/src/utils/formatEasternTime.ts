/** All user-visible times use US Eastern (NYSE context). */

const EASTERN = "America/New_York";

const easternDateTime = new Intl.DateTimeFormat("en-US", {
  timeZone: EASTERN,
  dateStyle: "medium",
  timeStyle: "medium",
  timeZoneName: "short",
});

const easternTimeOnly = new Intl.DateTimeFormat("en-US", {
  timeZone: EASTERN,
  timeStyle: "short",
  timeZoneName: "short",
});

const easternDateKey = new Intl.DateTimeFormat("en-CA", {
  timeZone: EASTERN,
  year: "numeric",
  month: "2-digit",
  day: "2-digit",
});

const HAS_EXPLICIT_TZ = /(?:Z|[+\-]\d{2}:?\d{2})$/i;

/**
 * Backend should send timezone-aware ISO strings. If a naive ISO slips through,
 * treat it as UTC so browsers do not reinterpret it in local machine time.
 */
export function parseApiDate(value: string | number | Date): Date {
  if (value instanceof Date) return value;
  if (typeof value === "number") return new Date(value);
  const trimmed = value.trim();
  if (/^\d{4}-\d{2}-\d{2}T/.test(trimmed) && !HAS_EXPLICIT_TZ.test(trimmed)) {
    return new Date(`${trimmed}Z`);
  }
  return new Date(trimmed);
}

function normalizeEtZoneLabel(s: string): string {
  return s.replace(/\bEDT\b|\bEST\b/g, "ET");
}

/** e.g. Apr 22, 2026, 9:30:00 AM ET */
export function formatEasternDateTime(value: string | number | Date): string {
  const d = parseApiDate(value);
  if (Number.isNaN(d.getTime())) return "Invalid date";
  return normalizeEtZoneLabel(easternDateTime.format(d));
}

/** Shorter time for chart axis, e.g. 9:30 AM ET */
export function formatEasternTimeOnly(value: string | number | Date): string {
  const d = parseApiDate(value);
  if (Number.isNaN(d.getTime())) return "";
  return normalizeEtZoneLabel(easternTimeOnly.format(d));
}

/** YYYY-MM-DD in US/Eastern for day-bucket comparisons (e.g. \"today\"). */
export function easternDateBucket(value: string | number | Date): string {
  const d = parseApiDate(value);
  if (Number.isNaN(d.getTime())) return "";
  return easternDateKey.format(d);
}
