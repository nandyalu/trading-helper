"""One-off: correct the purchase dates on holdings imported by a Webull sync.

Until this was fixed, ``run_sync`` recorded every existing holding as a buy
*today* — the day the sync first ran. The cost basis was right, so P&L and
positions were unaffected, but anything date-sensitive was anchored on the
import date. The vs-SPY comparison is the one that matters: SPY gets a few days
to move while the position is credited with months of gains, so the alpha comes
out enormous and meaningless.

New imports now carry the broker's date when it supplies one, and are marked
``(date unknown)`` when it does not. Rows written before that still claim to
have been bought on the import date. This script fixes them, two ways::

    # See what is affected.
    python -m backend.scripts.fix_import_dates

    # You know when you actually bought them — best outcome, restores a real
    # SPY comparison for those lots.
    python -m backend.scripts.fix_import_dates --set NVDA=2026-03-14 --set AAPL=2026-01-20

    # You do not know: mark them so they are excluded from the SPY comparison
    # rather than corrupting it.
    python -m backend.scripts.fix_import_dates --mark-unknown

Setting a date and marking unknown are mutually exclusive per ticker; --set
wins for the tickers it names, and --mark-unknown covers the rest.
"""
import argparse
import datetime
import sys

from sqlmodel import Session, select

from backend.database.engine import write_session
from backend.database.models import Transaction
from backend.services.positions import ESTIMATED_DATE_NOTE

_IMPORT_NOTE = "webull sync: imported holding"
# Written once a real purchase date has been supplied, so a later
# --mark-unknown run does not undo the correction and push the row back out of
# the SPY comparison.
_CONFIRMED_NOTE = "date confirmed"


@write_session
def _imported_rows(*, _session: Session = None) -> list[Transaction]:
    """Sync-imported buys that still carry an unqualified date."""
    rows = _session.exec(select(Transaction).where(Transaction.side == "buy")).all()
    return [
        row
        for row in rows
        if row.note
        and row.note.startswith(_IMPORT_NOTE)
        and ESTIMATED_DATE_NOTE not in row.note
        and _CONFIRMED_NOTE not in row.note
    ]


@write_session
def _apply(dates: dict[str, datetime.date], mark_unknown: bool, *, _session: Session = None) -> tuple[int, int]:
    rows = _session.exec(select(Transaction).where(Transaction.side == "buy")).all()
    dated = marked = 0
    for row in rows:
        if not (row.note and row.note.startswith(_IMPORT_NOTE)):
            continue
        already_settled = ESTIMATED_DATE_NOTE in row.note or _CONFIRMED_NOTE in row.note
        if already_settled and row.ticker not in dates:
            continue
        if row.ticker in dates:
            row.date = dates[row.ticker]
            row.note = f"{_IMPORT_NOTE} ({_CONFIRMED_NOTE})"
            dated += 1
        elif mark_unknown:
            row.note = f"{_IMPORT_NOTE} ({ESTIMATED_DATE_NOTE})"
            marked += 1
        else:
            continue
        _session.add(row)
    _session.commit()
    return dated, marked


@write_session
def _rebuild_from_fills(*, _session: Session = None) -> tuple[int, int, list[str]]:
    """Replace synthetic sync imports with lots reconstructed from Webull's
    order history. Returns (tickers rebuilt, lots written, tickers skipped).

    Only rows this tool created are touched — a buy whose note starts with
    "webull sync: imported holding". Anything you entered by hand, and any
    quantity-drift row, is left exactly as it is.

    A ticker is skipped when order history explains none of its shares, which
    happens for holdings transferred in from another broker or bought before
    the 2018 horizon. Those keep their date-unknown row.
    """
    from backend.services import broker

    positions = broker.fetch_broker_positions()
    if positions is None:
        raise SystemExit("Webull isn't reachable — nothing changed.")
    fills = broker.fetch_order_fills()
    if fills is None:
        raise SystemExit("Order history isn't reachable — nothing changed.")

    rebuilt = lots_written = 0
    skipped: list[str] = []
    for position in positions:
        synthetic = [
            row
            for row in _session.exec(
                select(Transaction).where(
                    Transaction.ticker == position.symbol, Transaction.side == "buy"
                )
            ).all()
            if row.note and row.note.startswith(_IMPORT_NOTE)
        ]
        if not synthetic:
            continue
        lots = broker.reconstruct_open_lots(position, fills)
        if not lots or all(lot.date is None for lot in lots):
            skipped.append(position.symbol)
            continue
        for row in synthetic:
            _session.delete(row)
        for lot in lots:
            _session.add(
                Transaction(
                    ticker=lot.ticker,
                    side="buy",
                    date=lot.date or datetime.date.today(),
                    price=lot.price,
                    quantity=lot.quantity,
                    note=f"{_IMPORT_NOTE.rsplit(':', 1)[0]}: {lot.reason}",
                )
            )
            lots_written += 1
        rebuilt += 1
    _session.commit()
    return rebuilt, lots_written, skipped


def _parse_set(values: list[str]) -> dict[str, datetime.date]:
    dates = {}
    for item in values:
        ticker, _, raw = item.partition("=")
        if not raw:
            raise SystemExit(f"--set needs TICKER=YYYY-MM-DD, got {item!r}")
        try:
            parsed = datetime.date.fromisoformat(raw)
        except ValueError:
            raise SystemExit(f"Not a date: {raw!r} (use YYYY-MM-DD)")
        if parsed > datetime.date.today():
            raise SystemExit(f"{ticker}: {parsed} is in the future.")
        dates[ticker.upper().strip()] = parsed
    return dates


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument(
        "--set", action="append", default=[], metavar="TICKER=YYYY-MM-DD",
        help="the real purchase date for a ticker; repeatable",
    )
    parser.add_argument(
        "--mark-unknown", action="store_true",
        help="mark every remaining imported holding as having an unknown date, "
             "which excludes it from the SPY comparison",
    )
    parser.add_argument(
        "--from-webull", action="store_true",
        help="replace synthetic imports with lots rebuilt from Webull order "
             "history — real dates and real fill prices. Try this first.",
    )
    parser.add_argument(
        "--yes", action="store_true",
        help="confirm --from-webull, which deletes and rewrites transaction rows",
    )
    args = parser.parse_args()
    dates = _parse_set(args.set)

    if args.from_webull:
        if not args.yes:
            print(
                "Would fetch Webull order history and replace each synthetic import with\n"
                "the real buys behind it — actual dates, actual fill prices, one row per lot.\n"
                "Only rows noted 'webull sync: imported holding' are touched; anything you\n"
                "entered by hand is left alone.\n\n"
                "Re-run with --yes to do it."
            )
            return 0
        rebuilt, lots, skipped = _rebuild_from_fills()
        print(f"Rebuilt {rebuilt} holding(s) into {lots} dated lot(s).")
        if skipped:
            print(
                f"No order history for: {', '.join(skipped)} — transferred in, or bought "
                "before 2018. These keep their date-unknown row; use --set for them."
            )
        return 0

    rows = _imported_rows()
    if not rows and not dates:
        print("No imported holdings with an unqualified date. Nothing to do.")
        return 0

    print("Imported holdings currently dated as bought on the import day:")
    for row in rows:
        print(f"  {row.ticker:<6} {row.date}  {row.quantity:g} @ ${row.price:,.2f}")

    if not dates and not args.mark_unknown:
        print(
            "\nNothing changed. Re-run with --set TICKER=YYYY-MM-DD for the dates you know,\n"
            "and/or --mark-unknown to exclude the rest from the SPY comparison."
        )
        return 0

    dated, marked = _apply(dates, args.mark_unknown)
    print(f"\nSet a real date on {dated} row(s); marked {marked} row(s) as date-unknown.")
    if marked:
        print("Marked rows keep their cost basis and P&L, and are left out of the SPY comparison.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
