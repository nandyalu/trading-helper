/**
 * When the experiment began.
 *
 * **2 September 2026** — the day the agent was deployed with an empty book, a
 * fresh brokerage account and $10,000, and switched on.
 *
 * Not 1 September. The code that removed every manual control was written that
 * day, and the journal records it under that date because that is when it
 * happened. But nothing was running: no container, no account, no book. The
 * experiment starts when the agent can act, and that was the 2nd.
 *
 * One constant, because a start date written in four places drifts. Anything
 * that says "since" or "day N" reads it from here.
 */
export const EXPERIMENT_START = new Date(Date.UTC(2026, 8, 2));

/** "2 September 2026". */
export function startedOn(): string {
  return new Intl.DateTimeFormat('en-GB', {
    day: 'numeric',
    month: 'long',
    year: 'numeric',
    timeZone: 'UTC',
  }).format(EXPERIMENT_START);
}

/**
 * Which day of the experiment today is, counting the first as day 1.
 *
 * Counted from the start rather than from the first fill. "Day 3" should mean
 * three days of the experiment running, including the days it chose to do
 * nothing — those are results too, and a counter that only starts on the first
 * purchase hides them.
 */
export function dayNumber(now: Date = new Date()): number {
  const days = Math.floor((now.getTime() - EXPERIMENT_START.getTime()) / 86_400_000);
  return Math.max(1, days + 1);
}
