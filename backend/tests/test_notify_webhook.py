"""Posting to Discord through a webhook.

The app only ever posts, so a webhook is the whole requirement. These cover the
two things that matter to someone running it: an unset URL disables
notifications silently, and Discord being down never stops the agent.
"""
import asyncio
import json
import urllib.error

import pytest

from backend.notifications import notify as notifier
from backend.notifications.embed import Color, Embed


@pytest.fixture
def sent(monkeypatch):
    """Captures what would have been posted, and posts nothing."""
    calls: list[tuple[str, dict]] = []
    monkeypatch.setattr(notifier, "_post", lambda url, payload: calls.append((url, payload)))
    monkeypatch.setenv("DISCORD_WEBHOOK_URL", "https://discord.test/hook")
    return calls


def test_a_message_is_posted(sent):
    assert asyncio.run(notifier.notify("the agent bought 3 NVDA")) is True
    url, payload = sent[0]
    assert url == "https://discord.test/hook"
    assert payload["content"] == "the agent bought 3 NVDA"


def test_an_embed_is_posted_in_the_shape_the_api_wants(sent):
    embed = Embed(title="The agent", description="traded", color=Color.blue())
    embed.add_field(name="Bought", value="3 NVDA")
    embed.set_footer(text="day 2")

    asyncio.run(notifier.notify(embed=embed))
    _, payload = sent[0]

    assert payload["embeds"][0]["title"] == "The agent"
    assert payload["embeds"][0]["fields"] == [
        {"name": "Bought", "value": "3 NVDA", "inline": False}
    ]
    assert payload["embeds"][0]["footer"] == {"text": "day 2"}
    # Must survive json.dumps — a webhook post is JSON over the wire.
    json.dumps(payload)


def test_no_url_means_no_notifications(monkeypatch):
    """Unset is a supported way to run. It must not raise and must not post."""
    monkeypatch.delenv("DISCORD_WEBHOOK_URL", raising=False)
    posted = []
    monkeypatch.setattr(notifier, "_post", lambda *a: posted.append(a))

    assert asyncio.run(notifier.notify("anything")) is False
    assert posted == []


def test_discord_being_down_never_raises(monkeypatch, sent):
    """**The agent must not stop trading because a chat service did.**

    Every caller is a scheduled job or a broker callback. The notification is a
    copy of what the database already holds, not the record itself.
    """
    def boom(url, payload):
        raise urllib.error.URLError("no route to host")

    monkeypatch.setattr(notifier, "_post", boom)
    assert asyncio.run(notifier.notify("this will fail")) is False


def test_a_rate_limit_is_not_retried(monkeypatch, sent):
    """429 is swallowed like any other refusal. Retrying would queue behind a
    window the app cannot see, and the message is not worth blocking a job."""
    def rate_limited(url, payload):
        raise urllib.error.HTTPError("u", 429, "Too Many Requests", {}, None)

    monkeypatch.setattr(notifier, "_post", rate_limited)
    assert asyncio.run(notifier.notify("too fast")) is False


def test_content_is_truncated_rather_than_refused(sent):
    """Discord rejects a post over 2000 characters outright. Losing the tail of
    an alert beats losing the alert."""
    asyncio.run(notifier.notify("x" * 5000))
    _, payload = sent[0]
    assert len(payload["content"]) == notifier.CONTENT_MAX
