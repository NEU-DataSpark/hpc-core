"""``hpc-core cluster``: the team folder protocol from the command line.

Every subcommand takes ``--root``, the team folder (a mounted or on-cluster path). Data goes to
standard output as JSON; ``--verbose`` writes the coordination events to standard error, once for
the event lines and twice for debug detail. Exit status: 0 for success, 1 when the folder cannot be
used or a rule refuses the change (a live duplicate id, an unknown recipient, a lease the node does
not hold), and 2 for a bad argument such as an invalid id. Error text never names the ``--root``
path or a host.

Each command is one process with its own instance token, so a node record written by one ``beat``
is not ``leave``-able by a later process (see docs/cluster-coordination.md).
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any

from ..contract.identifiers import ValidationError
from ..coordination import check, events, layout
from ..coordination.limits import set_limit, usage
from ..coordination.messages import SendRefused, acknowledge, pending, send
from ..coordination.records import KINDS, ProfileRecord
from ..coordination.registry import (
    OUTCOME_CONFLICT,
    OUTCOME_FAILED,
    NodeIdentity,
    NodeSession,
    discover,
    init_layout,
)
from ..coordination.store import FolderStore, LocalFolderStore, NotFound, StoreError
from ._io import EXIT_OK, EXIT_UNACCEPTABLE, InputError, fail, print_json, read_text

DEFAULT_INTERVAL_SECONDS = 60
Handler = Callable[[argparse.Namespace], int]


class _Refused(Exception):
    """The folder cannot be used for this command. The message names no path."""


class _EventLines(logging.Formatter):
    """One line per event on standard error: the level, the event name and its checked fields."""

    def format(self, record: logging.LogRecord) -> str:
        event = getattr(record, "hpc_event", record.getMessage())
        values: dict[str, Any] = getattr(record, "hpc_fields", {})
        pairs = " ".join(f"{name}={value}" for name, value in values.items())
        return f"{record.levelname.lower()} {event} {pairs}".rstrip()


def _attach_events(verbose: int) -> tuple[logging.Handler, int] | None:
    if verbose <= 0:
        return None
    logger = logging.getLogger(events.LOGGER_NAME)
    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(_EventLines())
    previous = logger.level
    logger.addHandler(handler)
    logger.setLevel(logging.DEBUG if verbose > 1 else logging.INFO)
    return handler, previous


def _detach_events(attached: tuple[logging.Handler, int] | None) -> None:
    if attached is None:
        return
    handler, previous = attached
    logger = logging.getLogger(events.LOGGER_NAME)
    logger.removeHandler(handler)
    logger.setLevel(previous)


def _guarded(run: Handler) -> Handler:
    """Attach the event lines, map folder failures to exit 1, and detach them afterwards."""

    def handler(args: argparse.Namespace) -> int:
        attached = _attach_events(args.verbose)
        try:
            return run(args)
        except _Refused as error:
            return fail(str(error), EXIT_UNACCEPTABLE)
        except StoreError as error:
            return fail(f"the team folder could not be used ({error.kind})", EXIT_UNACCEPTABLE)
        except SendRefused as error:
            return fail(str(error), EXIT_UNACCEPTABLE)
        except NotFound:
            return fail("not found in the team folder", EXIT_UNACCEPTABLE)
        finally:
            _detach_events(attached)

    return handler


def _open(args: argparse.Namespace) -> FolderStore:
    root = Path(args.root)
    if not root.is_dir():
        raise _Refused("the team folder is missing or is not a folder")
    return LocalFolderStore(root)


def _open_set_up(args: argparse.Namespace) -> FolderStore:
    store = _open(args)
    try:
        store.read_text(layout.manifest_path())
    except NotFound:
        raise _Refused("the team folder is not set up; run cluster init first") from None
    return store


def _identity(args: argparse.Namespace) -> NodeIdentity:
    return NodeIdentity(
        node_id=args.node_id,
        profile_id=args.profile,
        kind=args.kind,
        machine=args.machine or "",
        interval_seconds=args.interval_seconds,
    )


def init_run(args: argparse.Namespace) -> int:
    store = _open(args)
    created = init_layout(store)
    print_json({"created": created})
    return EXIT_OK


def nodes_run(args: argparse.Namespace) -> int:
    store = _open_set_up(args)
    found = discover(store)
    rows = [
        {
            "node_id": view.record.node_id,
            "profile_id": view.record.profile_id,
            "kind": view.record.kind,
            "machine": view.record.machine,
            "state": view.state,
            "age_seconds": int(view.age_seconds),
        }
        for view in found.nodes
    ]
    print_json({"nodes": rows, "unreadable": found.unreadable})
    return EXIT_OK


def beat_run(args: argparse.Namespace) -> int:
    store = _open(args)
    result = NodeSession(store, _identity(args)).register()
    if result.outcome == OUTCOME_CONFLICT:
        return fail("the node id is held by another live instance", EXIT_UNACCEPTABLE)
    if result.outcome == OUTCOME_FAILED:
        return fail("the team folder could not be written", EXIT_UNACCEPTABLE)
    print_json({"node_id": args.node_id, "outcome": result.outcome})
    return EXIT_OK


def leave_run(args: argparse.Namespace) -> int:
    store = _open_set_up(args)
    identity = NodeIdentity(node_id=args.node_id, profile_id=args.profile, kind=args.kind)
    outcome = NodeSession(store, identity).leave()
    if outcome in ("not-ours", "failed"):
        message = (
            "the node record belongs to another instance and was not removed"
            if outcome == "not-ours"
            else "the team folder could not be written"
        )
        return fail(message, EXIT_UNACCEPTABLE)
    print_json({"node_id": args.node_id, "outcome": outcome})
    return EXIT_OK


def send_run(args: argparse.Namespace) -> int:
    store = _open_set_up(args)
    body: dict[str, Any] = {}
    if args.body_file is not None:
        try:
            parsed = _parse_body(read_text(args.body_file))
        except ValueError:
            raise InputError("the body file does not hold a JSON object") from None
        body = parsed
    message_id = send(
        store,
        sender=args.node_id,
        recipient=args.to,
        message_type=args.type,
        body=body,
        in_reply_to=args.reply_to,
    )
    print_json({"message_id": message_id})
    return EXIT_OK


def _parse_body(text: str) -> dict[str, Any]:
    value = json.loads(text)
    if not isinstance(value, dict):
        raise ValueError("not an object")
    return value


def inbox_run(args: argparse.Namespace) -> int:
    store = _open_set_up(args)
    listed = pending(store, args.node_id)
    print_json({"messages": list(listed.messages), "skipped": listed.skipped})
    return EXIT_OK


def ack_run(args: argparse.Namespace) -> int:
    store = _open_set_up(args)
    result = acknowledge(store, args.node_id, args.message_id)
    print_json({"message_id": result.message_id, "outcome": result.outcome})
    return EXIT_OK


def limits_run(args: argparse.Namespace) -> int:
    store = _open_set_up(args)
    if args.set is None:
        print_json(usage(store, args.profile))
        return EXIT_OK
    if args.node_id is None:
        raise ValidationError("--set needs --node-id, the node that changes the limit")
    record: ProfileRecord = set_limit(store, args.profile, args.set, node_id=args.node_id)
    print_json({"profile_id": record.profile_id, "concurrency_limit": record.concurrency_limit})
    return EXIT_OK


def check_run(args: argparse.Namespace) -> int:
    store = _open(args)
    results = check.run_check(store, read_only=args.read_only)
    print_json(results)
    clean = all(result.status == check.OK for result in results)
    return EXIT_OK if clean else EXIT_UNACCEPTABLE


def _common(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--root", required=True, help="the team folder (a mounted or cluster path)")
    parser.add_argument(
        "--verbose",
        action="count",
        default=0,
        help="write coordination events to standard error; repeat for debug detail",
    )


def _node(parser: argparse.ArgumentParser, *, required_kind: bool) -> None:
    parser.add_argument("--node-id", required=True, help="this node's id, such as alice-console-a1")
    parser.add_argument("--profile", required=True, help="the profile the node draws slots from")
    parser.add_argument(
        "--kind",
        required=required_kind,
        choices=KINDS,
        default=None,
        help="what kind of node this is",
    )


def _add(
    sub: argparse._SubParsersAction[argparse.ArgumentParser],
    name: str,
    help_text: str,
    run: Handler,
) -> argparse.ArgumentParser:
    parser = sub.add_parser(name, help=help_text)
    _common(parser)
    parser.set_defaults(handler=run)
    return parser


def register(subparsers: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    group = subparsers.add_parser(
        "cluster", help="Team folder coordination: nodes, heartbeats, limits, messages and check."
    )
    sub = group.add_subparsers(metavar="COMMAND", dest="cluster_command", required=True)

    _add(sub, "init", "Create the team folder layout if it is missing.", _guarded(init_run))

    _add(sub, "nodes", "List the nodes with their liveness state.", _guarded(nodes_run))

    beat = _add(
        sub,
        "beat",
        "Register or refresh this node's record (one beat per run).",
        _guarded(beat_run),
    )
    _node(beat, required_kind=True)
    beat.add_argument(
        "--interval-seconds",
        type=int,
        default=DEFAULT_INTERVAL_SECONDS,
        help=f"expected seconds between beats (30 or more; default {DEFAULT_INTERVAL_SECONDS})",
    )
    beat.add_argument("--machine", default="", help="a label for the machine the node runs on")

    leave = _add(sub, "leave", "Remove this node's record.", _guarded(leave_run))
    _node(leave, required_kind=True)

    send_cmd = _add(sub, "send", "Send a message into another node's inbox.", _guarded(send_run))
    send_cmd.add_argument("--node-id", required=True, help="the sending node's id")
    send_cmd.add_argument("--to", required=True, help="the recipient node's id")
    send_cmd.add_argument("--type", required=True, help="message type, such as notice or ping")
    send_cmd.add_argument(
        "--body-file",
        default=None,
        help="a file holding one JSON object as the body, or - for standard input",
    )
    send_cmd.add_argument("--reply-to", default=None, help="the id of the message answered")

    inbox = _add(
        sub, "inbox", "List this node's pending messages, oldest first.", _guarded(inbox_run)
    )
    inbox.add_argument("--node-id", required=True, help="this node's id")

    ack = _add(sub, "ack", "Acknowledge a pending message.", _guarded(ack_run))
    ack.add_argument("--node-id", required=True, help="this node's id")
    ack.add_argument("message_id", metavar="MESSAGE_ID", help="the message to acknowledge")

    limits = _add(
        sub, "limits", "Show a profile's usage, or set its limit with --set.", _guarded(limits_run)
    )
    limits.add_argument("--profile", required=True, help="the profile to show or change")
    limits.add_argument("--node-id", default=None, help="the node making a --set change")
    limits.add_argument(
        "--set",
        metavar="LIMIT",
        type=int,
        default=None,
        help=f"set the concurrency limit ({layout.LIMIT_MIN} to {layout.LIMIT_MAX})",
    )

    check_cmd = _add(
        sub, "check", "Check the team folder and print each finding.", _guarded(check_run)
    )
    check_cmd.add_argument(
        "--read-only", action="store_true", help="skip the write probe; read only"
    )
