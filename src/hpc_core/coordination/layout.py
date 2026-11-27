"""Folder and file names of the ``_cluster`` layout, identifier rules and size limits.

Every path is relative to the team's shared area and uses ``/``. A builder validates each
identifier it places in a path, so no path can reach outside ``_cluster``. Nothing here touches a
file.
"""

from __future__ import annotations

import re

from ..contract.identifiers import ValidationError

CLUSTER_FOLDER = "_cluster"
MANIFEST_NAME = "cluster.json"
SUBFOLDERS: tuple[str, ...] = ("nodes", "profiles", "leases", "inbox")
DONE_FOLDER = "done"
TEMP_PREFIX = ".tmp-"
PROBE_PREFIX = ".probe-"
RECLAIM_PREFIX = ".reclaim-"

# A letter, digit or underscore first; then letters, digits, dots, underscores or hyphens.
ID_PATTERN = re.compile(r"[A-Za-z0-9_][A-Za-z0-9._-]*")
ID_MAX_LENGTH = 64
ID_RULE = (
    "must start with a letter, digit or underscore, continue with letters, digits, dots, "
    "underscores or hyphens, and be at most 64 characters"
)
TYPE_PATTERN = re.compile(r"[a-z0-9._-]{1,64}")

NODE_RECORD_LIMIT = 16 * 1024
PROFILE_RECORD_LIMIT = 16 * 1024
LEASE_RECORD_LIMIT = 16 * 1024
MESSAGE_LIMIT = 64 * 1024

LIMIT_MIN = 1
LIMIT_MAX = 1024
SLOT_MAX = LIMIT_MAX
MAX_PENDING_MESSAGES = 500
MESSAGE_TTL_SECONDS = 7 * 24 * 3600
PRUNE_AGE_SECONDS = 7 * 24 * 3600
TEMP_STALE_SECONDS = 10 * 60
# A message id is a 13-digit time, the sender and six random hex digits, joined by hyphens.
MESSAGE_ID_RANDOM_DIGITS = 6


def validate_id(value: str, what: str = "identifier") -> str:
    """Return ``value`` when it follows the identifier rule, else raise ValidationError."""
    if (
        not isinstance(value, str)
        or len(value) > ID_MAX_LENGTH
        or ID_PATTERN.fullmatch(value) is None
    ):
        raise ValidationError(f"{what} {ID_RULE}")
    return value


def validate_limit(limit: int) -> int:
    if isinstance(limit, bool) or not isinstance(limit, int) or not LIMIT_MIN <= limit <= LIMIT_MAX:
        raise ValidationError("concurrency limit must be a whole number from 1 to 1024")
    return limit


def validate_slot(slot: int) -> int:
    if isinstance(slot, bool) or not isinstance(slot, int) or not LIMIT_MIN <= slot <= SLOT_MAX:
        raise ValidationError("slot number must be a whole number from 1 to 1024")
    return slot


def cluster_path() -> str:
    return CLUSTER_FOLDER


def manifest_path() -> str:
    return f"{CLUSTER_FOLDER}/{MANIFEST_NAME}"


def subfolder_path(name: str) -> str:
    if name not in SUBFOLDERS:
        raise ValidationError("unknown cluster sub-folder")
    return f"{CLUSTER_FOLDER}/{name}"


def node_path(node_id: str) -> str:
    return f"{subfolder_path('nodes')}/{validate_id(node_id, 'node id')}.json"


def profile_path(profile_id: str) -> str:
    return f"{subfolder_path('profiles')}/{validate_id(profile_id, 'profile id')}.json"


def lease_dir(profile_id: str) -> str:
    return f"{subfolder_path('leases')}/{validate_id(profile_id, 'profile id')}"


def lease_path(profile_id: str, slot: int) -> str:
    return f"{lease_dir(profile_id)}/slot-{validate_slot(slot):02d}.json"


def inbox_dir(node_id: str) -> str:
    return f"{subfolder_path('inbox')}/{validate_id(node_id, 'node id')}"


def inbox_path(node_id: str, message_id: str) -> str:
    return f"{inbox_dir(node_id)}/{validate_id(message_id, 'message id')}.json"


def done_dir(node_id: str) -> str:
    return f"{inbox_dir(node_id)}/{DONE_FOLDER}"


def done_path(node_id: str, message_id: str) -> str:
    return f"{done_dir(node_id)}/{validate_id(message_id, 'message id')}.json"


def probe_name(probe_id: str) -> str:
    return f"{PROBE_PREFIX}{validate_id(probe_id, 'probe id')}"


def probe_path(probe_id: str) -> str:
    return f"{CLUSTER_FOLDER}/{probe_name(probe_id)}"


def temp_name(token: str) -> str:
    """The name of a temporary file in the target folder; readers ignore names with a dot."""
    return f"{TEMP_PREFIX}{validate_id(token, 'temporary token')}"


def is_hidden(name: str) -> bool:
    return name.startswith(".")
