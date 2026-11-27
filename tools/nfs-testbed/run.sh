#!/usr/bin/env bash
# Opt-in NFS layer for hpc-core (L5). Usage: run.sh up | test | down
#
# up    checks the host, starts the loopback NFS server, and mounts the export twice:
#       A with no client caching (noac), B with a 60 s attribute cache (actimeo=60).
# test  runs pytest -m nfs against the two mounts (paths passed as NFS_TESTBED_A and _B).
# down  unmounts B and A, stops the server and removes its container.
#
# Mounting needs root on this host. This script does not use sudo and does not load kernel
# modules; when the host lacks the NFS client or server it stops and says so.
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO="$(cd "$HERE/../.." && pwd)"
EXPORT="$HERE/export"
STATE="$HERE/.state"
MOUNT_A="$STATE/mount-a"
MOUNT_B="$STATE/mount-b"
PORT=2049
NFS_TESTBED_BIND=127.0.0.1  # loopback only: the server port is never bound elsewhere
export NFS_TESTBED_BIND
COMPOSE=(docker compose -f "$HERE/compose.yaml")

fail() {
  echo "nfs-testbed: $*" >&2
  exit 1
}

preflight() {
  local problems=()
  command -v docker >/dev/null 2>&1 || problems+=("docker is not installed")
  docker compose version >/dev/null 2>&1 || problems+=("docker compose is not available")
  grep -Eq '[[:space:]]nfs4?$' /proc/filesystems ||
    problems+=("this kernel has no NFS client ('nfs' is not in /proc/filesystems); load it as root")
  { grep -Eq '[[:space:]]nfsd$' /proc/filesystems || [ -e /proc/fs/nfsd/versions ]; } ||
    problems+=("this kernel has no NFS server ('nfsd' is not available); load it as root")
  [ "$(id -u)" -eq 0 ] ||
    problems+=("mounting needs root on this host; run as root (see docs/testing-on-nfs.md)")
  if [ "${#problems[@]}" -gt 0 ]; then
    for problem in "${problems[@]}"; do
      echo "nfs-testbed: $problem" >&2
    done
    echo "nfs-testbed: nothing was started or mounted" >&2
    exit 1
  fi
}

wait_for_server() {
  for _ in $(seq 1 30); do
    if (exec 3<>"/dev/tcp/$NFS_TESTBED_BIND/$PORT") 2>/dev/null; then
      return 0
    fi
    sleep 1
  done
  fail "the NFS server did not listen on $NFS_TESTBED_BIND:$PORT"
}

up() {
  preflight
  mkdir -p "$EXPORT" "$MOUNT_A" "$MOUNT_B"
  "${COMPOSE[@]}" up -d
  wait_for_server
  mountpoint -q "$MOUNT_A" ||
    mount -t nfs4 -o rw,hard,noac "$NFS_TESTBED_BIND:/" "$MOUNT_A"
  mountpoint -q "$MOUNT_B" ||
    mount -t nfs4 -o rw,hard,actimeo=60 "$NFS_TESTBED_BIND:/" "$MOUNT_B"
  echo "nfs-testbed: up; mount A (noac) and mount B (actimeo=60) are ready"
}

test_layer() {
  mountpoint -q "$MOUNT_A" && mountpoint -q "$MOUNT_B" ||
    fail "the testbed is not up; run: $0 up"
  cd "$REPO"
  NFS_TESTBED_A="$MOUNT_A" NFS_TESTBED_B="$MOUNT_B" uv run pytest -m nfs tests/nfs -v
}

down() {
  for mount in "$MOUNT_B" "$MOUNT_A"; do
    if mountpoint -q "$mount"; then
      umount "$mount" || fail "could not unmount the testbed mount; check it by hand"
    fi
  done
  "${COMPOSE[@]}" down --volumes --remove-orphans
  rmdir "$MOUNT_A" "$MOUNT_B" 2>/dev/null || true
  echo "nfs-testbed: down"
}

case "${1:-}" in
  up) up ;;
  test) test_layer ;;
  down) down ;;
  *)
    echo "usage: $0 up | test | down" >&2
    exit 2
    ;;
esac
