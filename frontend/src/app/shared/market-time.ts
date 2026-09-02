/**
 * The schedule, in the market's clock and in the reader's.
 *
 * Every job in this app is configured in UTC, and UTC is the wrong thing to
 * show anyone. The times only mean something against the US market session —
 * 13:35 UTC is not a fact worth reading, "9:35 AM ET, five minutes after the
 * open" is.
 *
 * So Eastern is primary, because that is the clock the experiment actually runs
 * on, and the reader's own zone comes second so they know whether it has
 * already happened where they are.
 *
 * **Eastern, not EST.** The offset changes twice a year, and hardcoding −5
 * would put every time an hour out for eight months of it. `Intl` with the
 * `America/New_York` zone handles the switch.
 */

const ET_ZONE = 'America/New_York';

/** The viewer's zone, or Eastern if the browser will not say. */
export function localZone(): string {
  try {
    return Intl.DateTimeFormat().resolvedOptions().timeZone || ET_ZONE;
  } catch {
    return ET_ZONE;
  }
}

/** True when the reader is already on the market's clock, in which case showing
 * the same time twice is noise rather than help. */
export function readerIsEastern(): boolean {
  return localZone() === ET_ZONE;
}

function at(hour: number, minute: number, on: Date): Date {
  const d = new Date(on);
  d.setUTCHours(hour, minute, 0, 0);
  return d;
}

function format(date: Date, zone: string): string {
  return new Intl.DateTimeFormat('en-US', {
    hour: 'numeric',
    minute: '2-digit',
    timeZone: zone,
  }).format(date);
}

/** The short zone name a reader would recognise — "EDT", "GMT+5:30". */
export function zoneLabel(date: Date, zone: string): string {
  const parts = new Intl.DateTimeFormat('en-US', {
    timeZone: zone,
    timeZoneName: 'short',
  }).formatToParts(date);
  return parts.find((p) => p.type === 'timeZoneName')?.value ?? '';
}

export interface ClockTime {
  /** "9:35 AM" on the market's clock. */
  et: string;
  /** "EDT" or "EST", whichever applies on that date. */
  etZone: string;
  /** The same moment where the reader is, or null when that is the same clock. */
  local: string | null;
  localZone: string | null;
  /** The underlying instant, for deciding what has already happened. */
  instant: Date;
}

/**
 * One scheduled UTC time, rendered for both clocks.
 *
 * ``on`` is the day it runs, so the Eastern offset is resolved against the real
 * date rather than today — a timeline showing yesterday and today crosses a
 * daylight-saving boundary twice a year, and both rows have to be right.
 */
export function marketTime(utcHour: number, utcMinute: number, on: Date = new Date()): ClockTime {
  const instant = at(utcHour, utcMinute, on);
  const zone = localZone();
  const sameClock = readerIsEastern();
  return {
    et: format(instant, ET_ZONE),
    etZone: zoneLabel(instant, ET_ZONE),
    local: sameClock ? null : format(instant, zone),
    localZone: sameClock ? null : zoneLabel(instant, zone),
    instant,
  };
}
