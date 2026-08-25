"""What kind of deployment this is.

One codebase runs two things. The first is a tool someone uses: it tracks a
real portfolio, a local paper book followed by hand, and an auto trader beside
them. The second is an experiment someone watches — an agent with its own
budget, its own broker account, and nothing else.

Forking the code to express that would mean fixing every shared thing twice
forever, so the difference is configuration. ``AGENT_ONLY`` says which one is
running.

It hides pages and skips jobs. It is **not** a safety control: nothing here
decides whether orders are simulated, which account they reach, or whether the
app may short. Those live in sandbox_broker and stay identical in both
deployments, because a flag about what to display must never become a flag
about what is safe.
"""
import os


def is_agent_only() -> bool:
    """True when this deployment runs the autonomous-analyst experiment.

    Read per call rather than at import so a test can change it.
    """
    return (os.environ.get("AGENT_ONLY") or "").strip().lower() in ("1", "true", "yes", "on")
