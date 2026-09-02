"""Whether this copy of the app is the public one.

The experiment is meant to be published. The dashboard is served on a domain
through a Cloudflare tunnel, so anyone can reach it — and everything on it is
meant to be read. What is not meant to be reachable is the small write surface:
the settings that choose the model and the budget, and the endpoint that places
exit orders at the broker.

``PUBLIC_MODE=1`` refuses every write.

**It is enforced in the middleware, not in the routes and not in the frontend.**
Hiding a button stops nobody who can type a URL, and a per-route check protects
only the routes somebody remembered to annotate. A middleware that refuses any
method other than GET or HEAD covers the route added next year by someone who
never read this file, which is the case that actually matters.

The private copy runs without the variable and behaves exactly as before.
"""
import os


def is_public() -> bool:
    """True when this deployment is the published, read-only one."""
    return (os.environ.get("PUBLIC_MODE") or "").strip().lower() in (
        "1", "true", "yes", "on",
    )
