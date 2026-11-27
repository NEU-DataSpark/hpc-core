"""Profile sets: the node profiles one program acts for, in ``single`` or ``multi`` mode.

A set in ``single`` mode holds exactly one profile entry and is the same node a configuration file
would have given before this model existed. A set in ``multi`` mode holds 1 to 16 entries, and each
*enabled* entry stands for one node of the team, configured by that entry alone. Disabled entries
are kept as configuration: they take part in every check but produce no node.

The rules live here so the console, the command line and the skills cannot drift. Reading a
document refuses every field that is not part of an entry, so a key path, host name or secret cannot
be stored by accident. Nothing in this module touches a folder, a connection or the environment.
"""

from __future__ import annotations

import json
import secrets
from dataclasses import dataclass, replace

from ..contract.identifiers import ValidationError
from .layout import validate_id, validate_limit, validate_share_pairs
from .profile import parse_share_queue
from .registry import NodeIdentity

__all__ = [
    "DISPLAY_NAME_MAX",
    "MAX_PROFILES",
    "MODE_MULTI",
    "MODE_SINGLE",
    "MODES",
    "ProfileEntry",
    "ProfileSet",
    "identities_for",
    "parse_profile_set",
]

MODE_SINGLE = "single"
MODE_MULTI = "multi"
MODES: tuple[str, ...] = (MODE_SINGLE, MODE_MULTI)
# Equal to the accelerator-type cap, which keeps one console's footprint small.
MAX_PROFILES = 16
DISPLAY_NAME_MAX = 64
# A generated node id is ``<profile>-console-<8 hex digits>``, the form the console already uses.
GENERATED_PROFILE_LENGTH = 40
GENERATED_KIND = "console"
GENERATION_ATTEMPTS = 8

ENTRY_FIELDS: frozenset[str] = frozenset(
    {"profile_id", "node_id", "display_name", "share_queue", "concurrency_limit", "enabled"}
)
DOCUMENT_FIELDS: frozenset[str] = frozenset({"mode", "profiles"})


@dataclass(frozen=True)
class ProfileEntry:
    """One profile entry: the node it stands for and the settings that node alone uses.

    ``node_id`` may be None until a set is built; the set then generates a distinct id.
    ``share_queue`` is the explicit node quota (None means follow the account quota) and
    ``concurrency_limit`` is None when the entry does not name one.
    """

    profile_id: str
    node_id: str | None = None
    display_name: str = ""
    share_queue: dict[str, int] | None = None
    concurrency_limit: int | None = None
    enabled: bool = True

    def __post_init__(self) -> None:
        validate_id(self.profile_id, "profile id")
        if self.node_id is not None:
            validate_id(self.node_id, "node id")
        if not isinstance(self.display_name, str) or len(self.display_name) > DISPLAY_NAME_MAX:
            raise ValidationError(
                f"display name must be text of at most {DISPLAY_NAME_MAX} characters"
            )
        if self.concurrency_limit is not None:
            validate_limit(self.concurrency_limit)
        if not isinstance(self.enabled, bool):
            raise ValidationError("enabled must be true or false")
        if self.share_queue is not None:
            if not isinstance(self.share_queue, dict):
                raise ValidationError("share queue must be a mapping of type to limit")
            folded = validate_share_pairs(self.share_queue.items())
            object.__setattr__(self, "share_queue", folded or None)


@dataclass(frozen=True)
class ProfileSet:
    """A validated profile set. Every entry has a node id once the set exists.

    Build one through the constructor or ``parse_profile_set``; both run the same checks. A set in
    ``single`` mode treats every entry as enabled (its ``enabled`` value is kept but ignored).
    """

    mode: str
    entries: tuple[ProfileEntry, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.mode, str):
            raise ValidationError(f"mode must be text: {MODE_SINGLE} or {MODE_MULTI}")
        mode = self.mode.lower()
        if mode not in MODES:
            raise ValidationError(
                f"mode {self.mode!r} is not allowed; use {MODE_SINGLE} or {MODE_MULTI}"
            )
        entries = _with_generated_ids(tuple(self.entries))
        _check_count(mode, len(entries))
        _check_unique_ids(entries)
        _check_limits(entries)
        if mode == MODE_MULTI and not any(entry.enabled for entry in entries):
            raise ValidationError("multi mode needs at least one enabled profile entry")
        object.__setattr__(self, "mode", mode)
        object.__setattr__(self, "entries", entries)

    def is_active(self, entry: ProfileEntry) -> bool:
        """True when the entry produces a node: every entry in single mode, the enabled ones in
        multi mode."""
        return self.mode == MODE_SINGLE or entry.enabled

    @property
    def active_entries(self) -> tuple[ProfileEntry, ...]:
        return tuple(entry for entry in self.entries if self.is_active(entry))

    def concurrency_limit_for(self, profile_id: str) -> int | None:
        """The one limit the entries of a profile agree on, or None when none of them names one.
        Disabled entries count, as the agreement rule requires."""
        for entry in self.entries:
            if entry.profile_id == profile_id and entry.concurrency_limit is not None:
                return entry.concurrency_limit
        return None


def _check_count(mode: str, count: int) -> None:
    if mode == MODE_SINGLE and count != 1:
        raise ValidationError(f"single mode holds exactly one profile entry, found {count}")
    if mode == MODE_MULTI and not 1 <= count <= MAX_PROFILES:
        raise ValidationError(
            f"multi mode holds from 1 to {MAX_PROFILES} profile entries, found {count}"
        )


def _generate_node_id(profile_id: str, taken: set[str]) -> str:
    for _ in range(GENERATION_ATTEMPTS):
        candidate = (
            f"{profile_id[:GENERATED_PROFILE_LENGTH]}-{GENERATED_KIND}-{secrets.token_hex(4)}"
        )
        if candidate not in taken:
            return candidate
    raise ValidationError("could not generate a distinct node id; give the node ids explicitly")


def _with_generated_ids(entries: tuple[ProfileEntry, ...]) -> tuple[ProfileEntry, ...]:
    taken = {entry.node_id for entry in entries if entry.node_id is not None}
    result: list[ProfileEntry] = []
    for entry in entries:
        if entry.node_id is None:
            node_id = _generate_node_id(entry.profile_id, taken)
            taken.add(node_id)
            entry = replace(entry, node_id=node_id)
        result.append(entry)
    return tuple(result)


def _check_unique_ids(entries: tuple[ProfileEntry, ...]) -> None:
    positions: dict[str, int] = {}
    for position, entry in enumerate(entries, start=1):
        if entry.node_id is None:
            continue
        first = positions.setdefault(entry.node_id, position)
        if first != position:
            raise ValidationError(
                f"node id {entry.node_id!r} is used by profile entries {first} and {position}"
            )


def _check_limits(entries: tuple[ProfileEntry, ...]) -> None:
    agreed: dict[str, int] = {}
    for entry in entries:
        if entry.concurrency_limit is None:
            continue
        known = agreed.setdefault(entry.profile_id, entry.concurrency_limit)
        if known != entry.concurrency_limit:
            raise ValidationError(
                f"profile {entry.profile_id} has conflicting concurrency limits "
                f"{known} and {entry.concurrency_limit}"
            )


def _where(position: int) -> str:
    return f"profile entry {position}"


def _text_field(raw: dict[str, object], name: str, position: int) -> str | None:
    """A text field of an entry, or None when it is absent or null."""
    value = raw.get(name)
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValidationError(f"{_where(position)}, field '{name}' must be text")
    return value


def _parse_entry(raw: object, position: int) -> ProfileEntry:
    if not isinstance(raw, dict):
        raise ValidationError(f"{_where(position)} must be an object")
    unknown = sorted(str(key) for key in raw if key not in ENTRY_FIELDS)
    if unknown:
        names = ", ".join(repr(name) for name in unknown)
        raise ValidationError(f"{_where(position)} has unknown fields {names}")

    profile_id = raw.get("profile_id")
    if profile_id is None:
        raise ValidationError(f"{_where(position)}, field 'profile_id' is required")
    validate_id(profile_id, f"{_where(position)}, field 'profile_id'")

    node_id = _text_field(raw, "node_id", position)
    if node_id is not None:
        validate_id(node_id, f"{_where(position)}, field 'node_id'")

    display_name = _text_field(raw, "display_name", position) or ""

    share_text = _text_field(raw, "share_queue", position)
    try:
        share_queue = parse_share_queue(share_text) if share_text is not None else None
    except ValidationError as error:
        raise ValidationError(f"{_where(position)}, field 'share_queue': {error}") from None

    limit: object = raw.get("concurrency_limit")
    concurrency_limit: int | None = None
    if limit is not None:
        if isinstance(limit, bool) or not isinstance(limit, int):
            raise ValidationError(
                f"{_where(position)}, field 'concurrency_limit' must be a whole number"
            )
        try:
            concurrency_limit = validate_limit(limit)
        except ValidationError as error:
            raise ValidationError(
                f"{_where(position)}, field 'concurrency_limit': {error}"
            ) from None

    enabled: object = raw.get("enabled", True)
    if not isinstance(enabled, bool):
        raise ValidationError(f"{_where(position)}, field 'enabled' must be true or false")

    return ProfileEntry(
        profile_id=profile_id,
        node_id=node_id,
        display_name=display_name,
        share_queue=share_queue or None,
        concurrency_limit=concurrency_limit,
        enabled=enabled,
    )


def parse_profile_set(text: str) -> ProfileSet:
    """Read a profile set from a JSON document: an optional ``mode`` and a list ``profiles``.

    A missing mode is ``single``. Every error names the problem and, for an entry, its position
    and field. No error repeats the document's text, so a secret pasted into it is not echoed.
    """
    try:
        document: object = json.loads(text)
    except ValueError:
        raise ValidationError("the document is not valid JSON") from None
    if not isinstance(document, dict):
        raise ValidationError("the document must be a JSON object with mode and profiles")
    unknown = sorted(str(key) for key in document if key not in DOCUMENT_FIELDS)
    if unknown:
        names = ", ".join(repr(name) for name in unknown)
        raise ValidationError(f"the document has unknown fields {names}")
    profiles = document.get("profiles")
    if not isinstance(profiles, list):
        raise ValidationError("the document must hold a list named profiles")
    entries = tuple(_parse_entry(item, position) for position, item in enumerate(profiles, start=1))
    mode: object = document.get("mode", MODE_SINGLE)
    if not isinstance(mode, str):
        raise ValidationError(f"mode must be text: {MODE_SINGLE} or {MODE_MULTI}")
    return ProfileSet(mode=mode, entries=entries)


def identities_for(profile_set: ProfileSet, base: NodeIdentity) -> tuple[NodeIdentity, ...]:
    """One node identity per active entry, built from the base configuration.

    The base supplies what every node of the program shares (kind, machine, software version and
    heartbeat interval). Each entry supplies its node id, profile, display name, explicit node
    quota and concurrency limit; an entry without a limit uses the limit its profile agrees on,
    then the base limit. The caller keeps its own base identity when it has no profile set, which
    is how the single-node behaviour stays unchanged.
    """
    identities: list[NodeIdentity] = []
    for entry in profile_set.active_entries:
        if entry.node_id is None:
            raise ValidationError("internal: a profile set must hold a node id for every entry")
        limit = profile_set.concurrency_limit_for(entry.profile_id)
        identities.append(
            replace(
                base,
                node_id=entry.node_id,
                profile_id=entry.profile_id,
                display_name=entry.display_name or base.display_name,
                concurrency_limit=limit if limit is not None else base.concurrency_limit,
                node_quota=entry.share_queue,
            )
        )
    return tuple(identities)
