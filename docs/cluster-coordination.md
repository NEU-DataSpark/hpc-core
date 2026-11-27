# Team folder coordination

`hpc_core.coordination` lets several nodes share one folder: each node says it is alive, profiles
share a concurrency limit through slot leases, and nodes send each other small messages. The folder
is the only channel. Nothing here opens a network connection, starts a daemon or runs a command on
a cluster; a host reads the folder through a store (see below).

The protocol is advisory. It coordinates cooperating nodes. The scheduler stays the authority over
what actually runs.

## Layout

All state lives under one `_cluster` folder in the team folder:

```text
_cluster/
  cluster.json              the manifest: schema_version, team_label
  nodes/<node_id>.json      one node record per node
  profiles/<profile_id>.json  the concurrency limit of a profile
  leases/<profile_id>/slot-NN.json  one lease per slot in use
  inbox/<node_id>/<message_id>.json  pending messages
  inbox/<node_id>/done/<message_id>.json  acknowledged messages
```

Nothing outside `_cluster` is written. Readers ignore names that start with a dot. Writers create a
file under a dot-prefixed temporary name and rename it into place, so a reader never sees a partial
record. Exclusive creates use a hard link, so two writers cannot both create the same name.

## Identifiers

A node id, profile id, recipient, sender and message id follow one rule: start with a letter, a
digit or an underscore; then letters, digits, `.`, `_` or `-`; at most 64 characters. So
`alice.k1` is valid, and `../x`, `a/b`, an empty id, an id with a space and a 65-character id are
refused before anything is read or written.

Message types are 1 to 64 lower-case letters, digits, `.`, `_` or `-`. The reserved types are
`ping`, `pong` and `notice`.

## Records

Every record is one line of compact JSON that ends with a newline, and carries `schema_version`.
Fields are sorted by name.

| Record | Fields | Limit |
| --- | --- | --- |
| Manifest | `schema_version`, `team_label` | 16 KiB |
| Node | `schema_version`, `node_id`, `profile_id`, `kind`, `display_name`, `machine`, `software_version`, `started_at`, `interval_seconds`, `heartbeat_count`, `instance_token` | 16 KiB |
| Profile | `schema_version`, `profile_id`, `concurrency_limit`, `updated_by`, `updated_at` | 16 KiB |
| Lease | `schema_version`, `profile_id`, `slot`, `node_id`, `acquired_at`, `interval_seconds` | 16 KiB |
| Message | `schema_version`, `message_id`, `type`, `from_node`, `to_node`, `created_at`, `expires_at`, `in_reply_to`, `body` | 64 KiB |

`kind` is one of `console`, `skill` or `cli`. Times are ISO 8601 in UTC with a `Z` suffix.

Reading never raises for bad input. A record that is not JSON, is not an object, has an unsupported
`schema_version`, has an invalid field, is over its limit, or whose id differs from its file name
is *unreadable*. A listing skips it and counts it. The self-check reports the count.

## Liveness

A node's state comes from its record's file time, not from the time written inside it, so a node
whose clock is wrong is still judged by the folder's clock. The reader's "now" is the folder host's
current time.

The interval is the seconds between beats: 60 by default, and never less than 30.

| State | Age since last file time |
| --- | --- |
| `online` | at most 3 intervals |
| `stale` | more than 3 intervals, at most 20 |
| `offline` | more than 20 intervals |

A node record more than 7 days old is removed by `prune`. Its inbox is removed only when the node
record is gone and every file in the inbox is more than 7 days old. Registration with a live id held by another instance is a conflict and writes
nothing. A crashed holder's id is taken over once its record is no longer live.

## Limits and leases

A profile's limit is between 1 and 1024. The first registration of a profile creates its record
with the limit it names; a later registration keeps the existing value. A change replaces the whole
record and names the node that made it (`updated_by`).

A slot is a lease file `slot-NN.json`, created exclusively. The holder renews it at each heartbeat.
A lease is stale when it has not been renewed for three of its holder's intervals. Taking a slot
first reclaims stale leases: the lease is moved aside, and moved back when it turns out to be fresh.
A renewal that finds the lease missing or held by another node reports `lost`.

If more leases than the limit are valid, for example after the limit was lowered, the lease that
was taken last (by acquisition time, then node id) releases itself. Holders already in place are
not removed, and nothing new is granted until the count is below the limit.

## Explicit node profiles

A profile can also carry a share-queue limit per accelerator type (for example `h200`). Two values
work together:

- The **account quota** is the per-type limit in the profile record (`share_queue_limits`). Each
  type is 0 to 1024, a profile holds at most 16 types, and a type the record does not list counts
  as 0. A type name is 1 to 32 lower-case letters, digits or hyphens that start with a letter or
  digit; an upper-case name is folded to lower case.
- The **node quota** is an explicit value that one node pins for itself. It is written only in that
  node's own record, so one node never writes another node's limits.

The node's **effective limit** for each type is the smaller of its node quota and the current
account quota. A type the node does not list takes the account value. A node quota can never be
above the account quota: a pin that is refused names the type, the requested value and the account
quota, and writes nothing. Lowering the account quota later does not remove the node's explicit
value; the effective limit follows the account, and the explicit value applies again when the
account is raised.

A node has one of two sources. `explicit` means it pinned values; `default` means it uses the
account quota alone, which is also what a node with no share-queue fields in its record gets. A
node keeps its explicit values across ordinary beats (the values stay in its own record), and
`--reset-node` removes them so the node follows the account again. A reset of a node with no
explicit values changes nothing.

### Typed and untyped slots are counted apart

A lease with no type counts only against the profile's concurrency limit, exactly as before. A
lease with a type counts only against that type:

- the profile's valid leases of the type are checked against the account quota of the type;
- the node's own valid leases of the type are checked against the node's effective limit.

The node limit is checked first, so a node with a limit of 0 is refused with `node_limit` even when
the account has room. A refusal with `account_limit` means the account is full for that type. A
refused typed request creates no file. A type the account does not list has an account limit of 0.

Typed and untyped leases share one slot-number sequence per profile. After a typed slot is taken,
the same over-limit repair runs for that type only: when there are more valid leases of the type
than the account quota, the lease taken last releases itself. Lowering a quota never releases a
lease that is already held; it only stops new ones of that type until the holders are below the
limit.

`cluster limits` shows the per-type usage: the account quota, the valid and stale leases, and each
node's held count and effective limit. `cluster check` warns when typed leases are above the
account quota and when a share-queue field cannot be read.

See [`cluster-nodes.md`](cluster-nodes.md) for the commands and for a three-node local example.

### Record fields

Every new field is optional, so records from earlier versions still read, with no accelerator types
and the source `default`. The schema version does not change. An invalid share-queue field makes its
record unreadable, and the record is then not used for any decision.

| Record | New fields |
| --- | --- |
| profile | `share_queue_limits`: the account quota per type |
| node | `share_queue_limits`: the effective limits; `node_quota`: the explicit values, present only when explicit; `profile_source`: `default` or `explicit` |
| lease | `accelerator`: the type of a typed lease, absent for an untyped one |

## Messages

A message is one file, written exclusively and never rewritten. Its id is a 13-digit millisecond
time, the sender id and six random hex digits, so a listing in name order is creation order. Two
sends from one sender in the same millisecond still sort in send order.

- A recipient must have a node record. An offline recipient can receive messages.
- An inbox holds at most 500 pending messages. The 501st is refused.
- A body is a JSON object of at most 64 KiB. It is data: nothing in this package runs, loads or
  opens anything taken from a body.
- Pending messages are listed oldest first. Expired and unreadable files are counted as skipped.
- Acknowledging moves the message to `done/`. Acknowledging twice succeeds the second time.
- A sender learns the state of a message it sent as `pending`, `acknowledged` or `gone`.
- Cleanup removes expired pending messages and `done` messages older than 7 days.

## Trust

Access control is the folder's permissions. Anyone who can write the folder can write any record.
The sender id in a message is a claim, not an authenticated identity. Do not put secrets, keys,
tokens or passwords in messages or node fields. Treat message bodies and node names as untrusted
data: display them, and do not act on them without a person confirming.

## Events

The package logs through the standard `logging` package, to the logger `hpc_core.coordination`. It
has a `NullHandler`, so nothing is printed unless the host attaches a handler. The vocabulary is:

`node.registered`, `node.beat`, `node.beat_failed`, `node.conflict`, `node.left`, `node.pruned`,
`lease.acquired`, `lease.denied`, `lease.reclaimed`, `lease.lost`, `lease.repaired`,
`message.sent`, `message.refused`, `message.acked`, `record.unreadable`, `store.error`.

Every event carries only ids, counts, durations and short codes. A field that looks like a path, a
key-like `name=value` pair or free text, or that is longer than 64 characters, is refused, so a
folder path, a key path, an environment value or a message body cannot reach a log through this
package.

## Command table

Every command takes `--root`, the team folder. `--verbose` writes the events to standard error, and
repeating it adds debug detail. Output is JSON on standard output. The exit status is described in
[`cli.md`](cli.md#cluster).

| Command | What it does |
| --- | --- |
| `hpc-core cluster init --root TEAM` | Creates the layout if it is missing. |
| `hpc-core cluster nodes --root TEAM` | Lists nodes with their state and age. |
| `hpc-core cluster beat --root TEAM --node-id alice-console-a1 --profile alice --kind console` | Registers or refreshes this node's record. |
| `hpc-core cluster leave --root TEAM --node-id alice-console-a1 --profile alice --kind console` | Removes this node's record, if this process wrote it. |
| `hpc-core cluster send --root TEAM --node-id alice-skill-a1 --to alice-console-a1 --type notice` | Sends a message; `--body-file` gives its JSON object. |
| `hpc-core cluster inbox --root TEAM --node-id alice-console-a1` | Lists this node's pending messages. |
| `hpc-core cluster ack --root TEAM --node-id alice-console-a1 MESSAGE_ID` | Acknowledges a pending message. |
| `hpc-core cluster limits --root TEAM --profile alice` | Shows a profile's limit, valid and stale leases, node count and usage per accelerator type. |
| `hpc-core cluster limits --root TEAM --profile alice --node-id alice-console-a1 --set 2` | Changes the limit to 2 (1 to 1024). |
| `hpc-core cluster limits --root TEAM --profile alice --node-id alice-console-a1 --share-queue h200=2` | Sets the account quota for `h200` (0 to 1024). |
| `hpc-core cluster limits --root TEAM --profile alice --node-id alice-console-a1 --show-node` | Shows the account quota, node quota, effective limits and source of a node. |
| `hpc-core cluster limits --root TEAM --profile alice --node-id alice-console-a1 --reset-node` | Removes a node's explicit values so it follows the account quota. |
| `hpc-core cluster check --root TEAM --read-only` | Runs the self-check and prints each finding. |

`TEAM` stands for the team folder, `MESSAGE_ID` for a message id printed by `inbox`.

Each command runs in its own process, with its own instance token. A `beat` writes a token that
the same process holds only for its own run. So a later `beat` with the same id finds a live
record from another instance and exits 1, and a later `leave` cannot remove a record that an
earlier `beat` wrote. A long-running node needs a host that keeps one `NodeSession` alive.

## Self-check

`cluster check` reports one line per finding, with a stable code, a status (`ok`, `warn` or `fail`)
and a one-line hint. It exits 0 only when every finding is `ok`. `--read-only` skips the probe.

| Code | Reported as | Meaning |
| --- | --- | --- |
| `store.unreachable` | fail | The folder could not be read. The message names the error kind, never the path. |
| `layout.manifest` | fail | `cluster.json` is missing or unreadable. |
| `manifest.version` | fail | The manifest is from a schema version this package does not read. |
| `layout.folders` | fail | A sub-folder (`nodes`, `profiles`, `leases`, `inbox`) is missing. |
| `record.unreadable` | warn | Records or messages cannot be read; readers skip and count them. |
| `record.name_mismatch` | warn | A node record's id differs from its file name. |
| `record.version` | warn | A node record uses an unsupported schema version. |
| `lease.over_limit` | warn | A profile holds more valid untyped leases than its limit. |
| `lease.over_account` | warn | A profile holds more valid typed leases of a type than its account quota for that type. |
| `share_queue.unreadable` | warn | Node, profile or lease records hold a share-queue field that cannot be read. |
| `lease.stale` | warn | A profile holds leases whose holders stopped renewing. |
| `profile.no_nodes` | warn | A profile has no node record. |
| `temp.stale` | warn | A temporary file is older than 10 minutes, so a writer probably stopped. |
| `probe.rename` | fail | A file written by rename does not read back with its text. |
| `probe.hardlink` | fail | Hard links are refused, or the probe name already exists. |
| `probe.exclusive` | fail | A second exclusive create overwrote the file instead of being refused. |
| `probe.listing` | fail | The probe file is not listed yet; try again. |
| `probe.listing_delay` | warn | File times lag by more than 10 seconds; intervals need to be longer. |
| `probe.file_time` | ok | Reports whether file times keep fractions of a second or are whole seconds. |
| `probe.cleanup` | warn | A probe file could not be removed. |

The probe writes and removes files named `.probe-*` in `_cluster`. It leaves nothing behind when it
succeeds.

## Advisory limits

The limit is a coordination aid, not a guarantee. Two nodes that race can briefly hold more leases
than the limit until the repair runs, and a node that ignores the protocol is not stopped. Enforce
the real limit in the scheduler.
