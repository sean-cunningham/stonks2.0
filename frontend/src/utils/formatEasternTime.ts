/** All user-visible times use US Eastern (NYSE calendar context), labeled ET. */

const EASTERN = "America/New_York";

const easternDateTime = new Intl.DateTimeFormat("en-US", {
  timeZone: EASTERN,
  dateStyle: "medium",
  timeStyle: "medium",
});

const easternTimeOnly = new Intl.DateTimeFormat("en-US", {
  timeZone: EASTERN,
  timeStyle: "short",
});

function toDate(iso: string | number | Date): Date {
  return typeof iso === "object" && iso instanceof Date ? iso : new Date(iso);
}

/** e.g. Apr 22, 2026, 9:30:00 AM ET */
export function formatEasternDateTime(iso: string | number | Date): string {
  const d = toDate(iso);
  if (Number.isNaN(d.getTime())) return "Invalid date";
  return `${easternDateTime.format(d)} ET`;
}

/** Shorter time for chart axis — still labeled ET */
export function formatEasternTimeOnly(iso: string | number | Date): string {
  const d = toDate(iso);
  if (Number.isNaN(d.getTime())) return "";
  return `${easternTimeOnly.format(d)} ET`;
}
