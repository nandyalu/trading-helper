/**
 * The schedule, on the reader's own clock.
 *
 * Every job here is configured in UTC, and UTC is the wrong thing to show
 * anyone: 13:35 UTC is not a fact worth reading. So each time is rendered in
 * the reader's zone with the zone named — "9:35 AM EDT", "7:05 PM IST" — which
 * is unambiguous on its own and needs no second line.
 *
 * **An earlier version printed the market's clock and the reader's side by
 * side.** For anyone already on Eastern that is the same time twice, and for
 * everyone else the zone label was already doing the work the second time was
 * meant to do. One time, named, is enough.
 *
 * What the second line was really carrying — that these times hang off the US
 * market session — belongs in one sentence under the list rather than repeated
 * on every row.
 *
 * **Named zones, never a fixed offset.** Eastern moves twice a year, and
 * hardcoding −5 would put every time an hour out for eight months of it.
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
  /** "9:35 AM", on the reader's clock. */
  time: string;
  /** The zone it is in — "EDT", "IST", "GMT+5:30". */
  zone: string;
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
  return { time: format(instant, zone), zone: zoneLabel(instant, zone), instant };
}

/**
 * A recorded instant — a decision pass, a fill — on the reader's clock.
 *
 * Distinct from ``marketTime`` above, which renders a *scheduled* time that
 * has no date of its own. This takes a real moment from the API.
 *
 * **The API must send an offset for this to be right.** A timestamp without
 * one parses as local time, which moves the instant by the reader's own
 * offset. That was the bug this function was written for: the page formatted
 * in local time and printed a fixed "UTC" label, so the two errors cancelled
 * and the number looked correct to anyone on UTC.
 */
export function readerTime(instant: Date | string): ClockTime {
  const d = instant instanceof Date ? instant : new Date(instant);
  const zone = localZone();
  return { time: format(d, zone), zone: zoneLabel(d, zone), instant: d };
}

/**
 * The same instant with its date — "Thu 3 Sep, 9:35 AM EDT".
 *
 * The decisions feed needs the day as well as the time, because it lists
 * passes going back weeks.
 */
export function readerDateTime(instant: Date | string): string {
  const d = instant instanceof Date ? instant : new Date(instant);
  const zone = localZone();
  const day = new Intl.DateTimeFormat('en-GB', {
    weekday: 'short',
    day: 'numeric',
    month: 'short',
    timeZone: zone,
  }).format(d);
  return `${day}, ${format(d, zone)} ${zoneLabel(d, zone)}`;
}
