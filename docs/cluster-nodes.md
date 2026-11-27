# Node profiles: pinning a node's share-queue limits

A node can pin its share-queue limit for each accelerator type, so that a node with less capacity
than its account gets exactly the value it was given. The model is in
[`cluster-coordination.md`](cluster-coordination.md#explicit-node-profiles); this page is the
command reference and a local walk-through.

The examples use placeholders only: a team folder at `TEAM`, the profile `alice` and the node
`alice-console-a1`. Replace them with your own values. Nothing here needs a cluster or an account.

## Set the account quota

The account quota is the most a profile may use per type. Set it once per profile; a node cannot pin
more than it.

```sh
hpc-core cluster limits --root TEAM --profile alice --node-id alice-console-a1 --share-queue h200=2
```

The output is JSON with the new `share_queue_account`. A value outside 0 to 1024, a malformed pair or
more than 16 types exits with status 1 and writes nothing.

## Pin a node

Pin the node's values when it beats. Each type must be at most the account quota for that type.

```sh
hpc-core cluster beat --root TEAM --node-id alice-console-a1 --profile alice --kind console --share-queue h200=1
```

A pin above the account quota exits with status 1 and writes no node record. A beat without
`--share-queue` keeps the values the node already has, so pinning once is enough.

## Show a node

```sh
hpc-core cluster limits --root TEAM --profile alice --node-id alice-console-a1 --show-node
```

The output holds the account quota, the node quota (or `null`), the effective limits and the
`profile_source`, which is `explicit` for a pinned node and `default` otherwise.

## Reset a node

Reset removes the node's explicit values, so its effective limits equal the account quota again.
Resetting a node that has no explicit values changes nothing and reports `unchanged`.

```sh
hpc-core cluster limits --root TEAM --profile alice --node-id alice-console-a1 --reset-node
```

## Usage per type

`cluster limits --root TEAM --profile alice` lists, for each accelerator type, the account quota, the
valid and stale typed leases, and each node's held count and effective limit.

## Three nodes on one machine

The three-node suite runs the same team with two nodes that pin `h200=1` and one that pins
`h200=0`, under an account quota of `h200=2`. You can follow it by hand against a temporary folder.
Setting the account quota creates the profile when it does not exist yet, so the account is set
first and the three nodes pin their values after it.

```sh
TEAM=$(mktemp -d)
hpc-core cluster init --root "$TEAM"
hpc-core cluster limits --root "$TEAM" --profile alice --node-id alice-console-a1 --share-queue h200=2
hpc-core cluster beat --root "$TEAM" --node-id alice-console-a1 --profile alice --kind console --share-queue h200=1
hpc-core cluster beat --root "$TEAM" --node-id alice-console-a2 --profile alice --kind console --share-queue h200=1
hpc-core cluster beat --root "$TEAM" --node-id alice-console-a3 --profile alice --kind console --share-queue h200=0
```

Each node then takes a typed slot through the library or the console. The first two nodes get one
H200 slot each; the node with a limit of 0 is refused with `node_limit`, and no file is created for
it. Remove the folder when you are done.

```sh
rm -rf "$TEAM"
```

A node that pins a value higher than the account quota is refused, and a lowered account quota does
not release a slot that is already held.
