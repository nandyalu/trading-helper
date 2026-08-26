"""Write the journey files now, rather than waiting for tonight.

The daily job writes them after grading, so the day's verdicts are in the
story. This is for when you want them immediately — before publishing, or
after changing how they read.

Regenerated from the book each time, so running it twice is harmless.

    python -m backend.scripts.write_journey [--root data/journey]
"""
import argparse

from backend.services import journey


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", help="where to write. Defaults to the data volume.")
    args = parser.parse_args()

    written = journey.write_month_files(root=args.root)
    if not written:
        print("Nothing to write yet — the agent has no history.")
        return 0
    for path in written:
        print(f"  {path}")
    print()
    print(f"{len(written)} month(s) written.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
