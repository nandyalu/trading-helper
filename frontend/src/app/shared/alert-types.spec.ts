import { ALERT_TYPES, alertIcon, alertLabel } from './alert-types';

describe('ALERT_TYPES', () => {
  it('treats a moment that happened as urgent', () => {
    // These record an event: a level was reached, and that stays true. Showing
    // one for three days is right.
    expect(ALERT_TYPES['signal_stop'].urgent).toBe(true);
    expect(ALERT_TYPES['stop_loss'].urgent).toBe(true);
    expect(ALERT_TYPES['target'].urgent).toBe(true);
  });

  it('does not treat an unguarded position as urgent', () => {
    // It is a state, not a moment. Once the exits are placed the alert is
    // stale and nothing retracts it — so it kept the Overview shouting about a
    // position that had been protected two days earlier. The Overview reads
    // that row live from /api/agent/unprotected, which clears itself.
    expect(ALERT_TYPES['unguarded_position'].urgent).toBe(false);
  });

  it('still names the unguarded alert, so the log keeps the record', () => {
    expect(alertLabel('unguarded_position')).toBe('No exit resting');
    expect(alertIcon('unguarded_position')).toBe('🛡️');
  });

  it('falls back to the raw type rather than hiding an unknown alert', () => {
    expect(alertLabel('something_new')).toBe('something_new');
    expect(alertIcon('something_new')).toBe('•');
  });
});
