"""A Discord embed, built for a webhook.

Replaces ``discord.Embed``. The webhook API takes the same shape as the bot
API, so the posts read exactly as they did — this only drops the library.

Only the parts this app uses are here: a title, a description, fields, a
footer, a colour and a timestamp. A field this app never set is a field nobody
has to maintain.
"""
import datetime
from dataclasses import dataclass, field

# Discord's limits, and the reason the app splits a long rationale across a
# description and one continuation field.
DESCRIPTION_MAX = 4096
FIELD_MAX = 1024
TITLE_MAX = 256
FOOTER_MAX = 2048


class Color:
    """The colours this app uses, as the integers the API wants.

    Named after `discord.Color`'s own palette so the call sites did not have to
    change when the library went.
    """

    @staticmethod
    def green() -> int:
        return 0x2ECC71

    @staticmethod
    def teal() -> int:
        return 0x1ABC9C

    @staticmethod
    def gold() -> int:
        return 0xF1C40F

    @staticmethod
    def orange() -> int:
        return 0xE67E22

    @staticmethod
    def red() -> int:
        return 0xE74C3C

    @staticmethod
    def blue() -> int:
        return 0x3498DB

    @staticmethod
    def blurple() -> int:
        return 0x5865F2

    @staticmethod
    def greyple() -> int:
        return 0x99AAB5


@dataclass
class Field:
    name: str
    value: str
    inline: bool = False


@dataclass
class Embed:
    """One embed. Call ``to_dict()`` to get what the webhook expects."""

    title: str | None = None
    description: str | None = None
    color: int | None = None
    timestamp: datetime.datetime | None = None
    fields: list[Field] = field(default_factory=list)
    footer_text: str | None = None

    def add_field(self, *, name: str, value: str, inline: bool = False) -> "Embed":
        """Truncated at Discord's own limit rather than rejected.

        A field one character too long makes the whole post fail, and losing an
        alert to a formatting rule is worse than losing its last few words.
        """
        self.fields.append(Field(name=name[:TITLE_MAX], value=value[:FIELD_MAX], inline=inline))
        return self

    def set_footer(self, *, text: str) -> "Embed":
        self.footer_text = text[:FOOTER_MAX]
        return self

    def to_dict(self) -> dict:
        payload: dict = {}
        if self.title:
            payload["title"] = self.title[:TITLE_MAX]
        if self.description:
            payload["description"] = self.description[:DESCRIPTION_MAX]
        if self.color is not None:
            payload["color"] = self.color
        if self.timestamp is not None:
            payload["timestamp"] = self.timestamp.isoformat()
        if self.fields:
            payload["fields"] = [
                {"name": f.name, "value": f.value, "inline": f.inline} for f in self.fields
            ]
        if self.footer_text:
            payload["footer"] = {"text": self.footer_text}
        return payload
