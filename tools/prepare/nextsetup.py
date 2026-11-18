"""An update set up beside the version still played: prepare.py --next writes the outputs the game reads into
<game>/setup-next/, and the next prepare.py run of the new version moves them into place before its steps.

Why: an update ran prepare.py in the game folder itself, so mkwgame and spirv/ were half rewritten until it ended and
the player could not play meanwhile (#429: "no way to just go back to the menu and play the version you already have").
The steps write only these outputs where the runtime reads them; the rest (exefs, the RomFS, setup-work with its
objects, the SM86 spec) is the same for both versions or never read by the game.

spirv/ starts as hard links to the current one: translate.py renames each file it writes over the old link, so the
played version's files stay as they were, and the programs whose output did not change cost nothing (a copy where the
file system has no hard links). Not run on its own.
"""

import json
import os
import shutil
import sys
from pathlib import Path

NEXT = "setup-next"
STATE = "setup-state.json"
OUTPUTS = ("mkwgame.so", "mkwgame.dll", "mkwgame.dll.pdb", "mkwgame.id", "pipeline-pairs.bin", "spirv")  # with STATE


def next_dir(game: Path) -> Path:
    return game / NEXT


def lower_priority() -> None:
    """This process and the tools it starts below normal priority (Windows: its priority class, inherited; elsewhere a
    nice of 10). Best effort: a system that refuses leaves the setup as it was."""
    try:
        if os.name == "nt":
            import ctypes  # noqa: PLC0415

            k32 = ctypes.windll.kernel32
            k32.SetPriorityClass(k32.GetCurrentProcess(), 0x4000)  # BELOW_NORMAL_PRIORITY_CLASS
        else:
            os.nice(10)
    except (OSError, AttributeError) as e:
        print(f"setup: priority not lowered: {e}", file=sys.stderr)


def seed(game: Path) -> Path:
    """setup-next/ with spirv/ linked to the current one; returns the folder. Links already there stay (a resumed run)."""
    out = next_dir(game)
    spirv, dst = game / "spirv", out / "spirv"
    dst.mkdir(parents=True, exist_ok=True)
    if spirv.is_dir():
        have = {p.name for p in dst.iterdir()}
        for p in spirv.iterdir():
            if p.name in have or not p.is_file():
                continue
            try:
                os.link(p, dst / p.name)
            except OSError:
                shutil.copy2(p, dst / p.name)
    return out


def load(game: Path, state: dict) -> dict:
    """The state an update in setup-next/ resumes from: its own when an earlier --next run left one, else a copy of the
    played version's (its finished steps are this one's starting point)."""
    p = next_dir(game) / STATE
    try:
        s = json.loads(p.read_text())
    except OSError, ValueError:
        return json.loads(json.dumps(state))
    return s if s.get("version") == state.get("version", s.get("version")) else json.loads(json.dumps(state))


def promote(game: Path, port: str) -> bool:
    """The outputs of a finished --next run for this port version moved into place (the old ones removed); an
    unfinished or other version's setup-next/ is removed. True when something was promoted."""
    out = next_dir(game)
    if not out.is_dir():
        return False
    try:
        s = json.loads((out / STATE).read_text())
    except OSError, ValueError:
        s = {}
    if not s.get("ready") or (port and s.get("port") != port):
        print(f"setup: {out} is not a finished setup of {port or 'this version'}: removed", file=sys.stderr)
        shutil.rmtree(out, ignore_errors=True)
        return False
    for name in (*OUTPUTS, STATE):
        src, dst = out / name, game / name
        if not src.exists():
            continue
        old = game / (name + ".old")
        shutil.rmtree(old, ignore_errors=True) if old.is_dir() else old.unlink(missing_ok=True)
        if dst.exists():
            dst.rename(old)
        src.rename(dst)
        shutil.rmtree(old, ignore_errors=True) if old.is_dir() else old.unlink(missing_ok=True)
    shutil.rmtree(out, ignore_errors=True)
    print(f"setup: the update set up beside the played version ({port}) is now in place", file=sys.stderr)
    return True
