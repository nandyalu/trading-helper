/** Display name and icon for each watchdog alert type.
 *
 * Shared so the Alerts page, the ticker timeline, and the Overview all name
 * the same event the same way. The raw keys are storage identifiers, not
 * labels: `signal_stop` and `stop_loss` both mean a loss, but for different
 * reasons — see evaluate_ticker in backend/services/watchdog.py — and showing
 * the keys would hide that distinction behind jargon.
 */
export const ALERT_TYPES: Record<string, { label: string; icon: string; urgent: boolean }> = {
  signal_stop: { label: 'Thesis broken', icon: '🛑', urgent: true },
  stop_loss: { label: 'Below your cost', icon: '🛑', urgent: true },
  target: { label: 'Target reached', icon: '🎯', urgent: true },
  big_move: { label: 'Big move', icon: '📊', urgent: false },
  volume: { label: 'Volume spike', icon: '📊', urgent: false },
};

export function alertLabel(alertType: string): string {
  return ALERT_TYPES[alertType]?.label ?? alertType;
}

export function alertIcon(alertType: string): string {
  return ALERT_TYPES[alertType]?.icon ?? '•';
}
