/**
 * Every term the site uses that a reader would not already know.
 *
 * **One definition, in one place, used everywhere.** Two explanations of
 * "refused" on two pages would reintroduce exactly the ambiguity the tooltip
 * exists to remove — so nothing defines a term inline in a template.
 *
 * The rule for what belongs here: a word a careful reader could not work out
 * from context, or one that means something narrower here than in ordinary
 * use. "Refused" is the clearest case of the second kind — everyone knows the
 * word, and almost nobody would guess it means Python declined the order
 * before it was ever sent.
 */
export interface Term {
  /** The key used in markup, and the anchor on the glossary page. */
  id: string;
  /** As it appears in a sentence. */
  label: string;
  /** One or two sentences. A tooltip nobody finishes reading is not a
   * tooltip — anything longer belongs on the glossary page. */
  short: string;
  /** The fuller entry, shown only on the glossary page. Optional: most terms
   * do not need one. */
  long?: string;
}

export const TERMS: Term[] = [
  {
    id: 'refused',
    label: 'refused',
    short:
      'Python declined the order before it was sent. The agent asked for something it could not do — more cash than it holds, more shares than it owns.',
    long: 'The agent decides what and how much; Python refuses what cannot be executed as stated, and never resizes. Shrinking an order would quietly turn the agent’s decision into a different one, and the record would then describe a strategy nobody chose. A refusal is fed back once and the agent is asked again, which is how it learns it may sell to fund a buy.',
  },
  {
    id: 'broker-said-no',
    label: 'broker said no',
    short:
      'The order was formed correctly and the broker would not take it — unsettled cash, a closed session, a symbol it will not trade.',
    long: 'Different from a refusal, and the difference matters. A refusal says the agent’s own arithmetic was wrong. This says the arithmetic was right and the world declined anyway. The agent is shown these on its next few passes so it does not simply propose the same thing again.',
  },
  {
    id: 'vs-spy',
    label: 'vs SPY',
    short: 'Whether a call beat the S&P 500 over its own window. The number that actually counts.',
    long: 'An absolute win rate of 70% in a rising market can be worse than useless — holding the index and doing nothing would have beaten it. A Buy passes here only if the stock beat SPY; a Sell passes only if it lagged, because selling something that then underperformed the market was the right call.',
  },
  {
    id: 'alpha',
    label: 'alpha',
    short:
      'How much a call beat or missed SPY by, over the same window. Positive means it added something the index did not.',
  },
  {
    id: 'maturing',
    label: 'maturing',
    short:
      'Not judged yet. A call is graded when its horizon arrives — 14 days for a swing call, 30 for a position call.',
  },
  {
    id: 'graded',
    label: 'graded',
    short:
      'Judged three ways once its horizon arrived: against reality, against SPY, and against its own price target.',
  },
  {
    id: 'research-charge',
    label: 'research charge',
    short:
      'What the agent pays to have one ticker analysed, every morning it keeps that ticker. It comes out of the same money it trades with.',
    long: 'The charge is the point of letting the agent choose what to study. Free research is just a longer watchlist, and an agent that pays nothing for being wrong about what was worth studying learns nothing from being wrong.',
  },
  {
    id: 'untrack',
    label: 'untrack',
    short:
      'The agent dropping a name it no longer wants to pay for. It frees a watchlist slot and stops the daily charge.',
    long: 'It cannot untrack something it holds. A position nobody analyses is a position with nothing looking for its exit, so it has to sell first.',
  },
  {
    id: 'unguarded',
    label: 'unguarded',
    short:
      'The agent holds shares and nothing is resting at the broker to close them. The money is at risk and the exit everyone assumes is there is not.',
    long: 'A buy normally goes out as a bracket — the entry with a stop and a target attached — so the shares are never held bare. Webull refuses a bracket while cash is unsettled, which happens routinely when the agent sells to fund a buy, and the fallback that arms the exits separately can fail. This is the one thing on the site a person is asked to fix.',
  },
  {
    id: 'bracket',
    label: 'bracket',
    short:
      'A buy sent together with its stop and its target, as one order. The broker activates the exits the moment the entry fills.',
  },
  {
    id: 'resting-exit',
    label: 'resting exit',
    short:
      'A stop or a take-profit sitting at the broker, waiting. It executes whether or not this app is running.',
    long: 'Different from the levels a signal proposes. A signal’s stop is what the analysis suggested; a resting exit is what will actually happen. The two disagree often — a discarded level, a volatility-derived fallback, a bracket the broker refused.',
  },
  {
    id: 'r-multiple',
    label: 'R-multiple',
    short:
      'Reward measured in units of what is risked. A 2R target means the gain, if it works, is twice the loss if the stop is hit.',
  },
  {
    id: 'conviction-floor',
    label: 'conviction floor',
    short:
      'The minimum quality a signal must show before the agent may open a position on it. Zero by default, which switches it off.',
  },
  {
    id: 'horizon',
    label: 'horizon',
    short:
      'How far ahead a call is meant to work, and therefore when it gets graded. Swing is 1 to 2 weeks; position is a multi-month hold.',
  },
  {
    id: 'regime',
    label: 'regime',
    short:
      'A one-line reading of the market: VIX, the S&P against its 200-day average, and the yield curve. The agent sees this same sentence first in every prompt.',
  },
  {
    id: 'sweep',
    label: 'sweep',
    short:
      'The morning run that analyses every ticker on the watchlist, at 11:00 UTC, and charges the agent for each one.',
  },
  {
    id: 'decision-pass',
    label: 'decision pass',
    short:
      'The one moment each weekday when the agent reads its book and answers with orders — 13:35 UTC, five minutes after the US market opens.',
    long: 'Deliberately not chained to the sweep that produces the signals. The sweep runs the night before, and Webull rejects a market order in the evening outright, so an agent wired to trade straight after it would look healthy and never fill an order.',
  },
];

export const TERMS_BY_ID = new Map(TERMS.map((t) => [t.id, t]));
