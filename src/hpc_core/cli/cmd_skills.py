"""``hpc-core skills``: list the skills shipped with the package and copy them to a folder.

A skill is ``hpc_core/skills/<name>/SKILL.md``. The bytes are copied as they are, and the copy never
writes outside the destination: a link is refused, not followed, and an existing folder is refused
unless ``--force`` is given.
"""

from __future__ import annotations

import argparse
import re
from importlib import resources
from pathlib import Path

from ._io import EXIT_OK, EXIT_UNACCEPTABLE, EXIT_USAGE, fail, print_json
from ._version import package_version

SKILL_FILE = "SKILL.md"
_FOLDER_NAME = re.compile(r"[a-z0-9][a-z0-9-]*")


def shipped_skills() -> list[str]:
    """The names of the skill folders packaged with this version, sorted."""
    root = resources.files("hpc_core") / "skills"
    return sorted(
        entry.name
        for entry in root.iterdir()
        if _FOLDER_NAME.fullmatch(entry.name) and entry.is_dir() and (entry / SKILL_FILE).is_file()
    )


def list_run(args: argparse.Namespace) -> int:
    del args
    print_json([{"name": name, "version": package_version()} for name in shipped_skills()])
    return EXIT_OK


def _packaged_bytes(name: str) -> bytes:
    return (resources.files("hpc_core") / "skills" / name / SKILL_FILE).read_bytes()


def install_run(args: argparse.Namespace) -> int:
    shipped = shipped_skills()
    names = list(args.skill) if args.skill else shipped
    unknown = [name for name in names if name not in shipped]
    if unknown:
        return fail(
            f"unknown skill {', '.join(unknown)}; shipped skills are: {', '.join(shipped)}",
            EXIT_USAGE,
        )

    dest: Path = Path(args.dest)
    if dest.is_symlink():
        return fail("the destination is a link; give a real folder", EXIT_USAGE)
    folders = {name: dest / name for name in names}
    for name, folder in folders.items():
        if folder.is_symlink():
            return fail(f"'{name}' is a link in the destination; it is not followed", EXIT_USAGE)
    present = [name for name, folder in folders.items() if folder.exists()]
    if present and not args.force:
        return fail(
            f"already present: {', '.join(present)}; nothing was copied (use --force to replace)",
            EXIT_UNACCEPTABLE,
        )

    installed: list[dict[str, str]] = []
    resolved_dest = dest.resolve()
    try:
        dest.mkdir(parents=True, exist_ok=True)
        for name, folder in folders.items():
            if folder.resolve().parent != resolved_dest:
                return fail(f"'{name}' would be written outside the destination", EXIT_USAGE)
            folder.mkdir(exist_ok=True)
            target = folder / SKILL_FILE
            if target.is_symlink():
                return fail(f"'{name}' has a link where its skill file goes", EXIT_USAGE)
            with open(target, "wb" if args.force else "xb") as handle:
                handle.write(_packaged_bytes(name))
            installed.append({"name": name, "path": str(folder)})
    except OSError:
        return fail("the destination could not be written", EXIT_USAGE)
    print_json({"installed": installed})
    return EXIT_OK


def register(subparsers: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    group = subparsers.add_parser(
        "skills", help="List or install the skills shipped with hpc-core."
    )
    sub = group.add_subparsers(metavar="COMMAND", dest="skills_command", required=True)

    listing = sub.add_parser("list", help="Print the shipped skill names and versions as JSON.")
    listing.set_defaults(handler=list_run)

    install = sub.add_parser("install", help="Copy the shipped skill folders into DEST.")
    install.add_argument("dest", metavar="DEST", help="folder to copy the skill folders into")
    install.add_argument(
        "--skill",
        action="append",
        default=None,
        metavar="NAME",
        help="copy only this skill; repeat the option for more than one",
    )
    install.add_argument(
        "--force", action="store_true", help="replace the SKILL.md of folders already present"
    )
    install.set_defaults(handler=install_run)
