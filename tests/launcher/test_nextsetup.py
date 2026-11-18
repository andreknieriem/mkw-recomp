"""prepare.py --next: the update set up beside the played version (tools/prepare/nextsetup.py)."""

import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools/prepare"))
import nextsetup


def played(game: Path) -> None:
    (game / "spirv").mkdir(parents=True)
    (game / "spirv/a.spv").write_bytes(b"old a")
    (game / "spirv/b.spv").write_bytes(b"old b")
    (game / "mkwgame.so").write_bytes(b"old lib")
    (game / "setup-state.json").write_text(json.dumps({"version": 1, "done": {"compile": "k1"}, "port": "0.1.12"}))


def test_seed_links_and_a_rewrite_leaves_the_played_file(tmp_path: Path) -> None:
    played(tmp_path)
    out = nextsetup.seed(tmp_path)
    assert (out / "spirv/a.spv").read_bytes() == b"old a"
    tmp = out / "spirv/a.spv.tmp"  # as translate.py's put()
    tmp.write_bytes(b"new a")
    os.replace(tmp, out / "spirv/a.spv")
    assert (tmp_path / "spirv/a.spv").read_bytes() == b"old a"
    assert (out / "spirv/a.spv").read_bytes() == b"new a"


def test_load_starts_from_the_played_state_and_resumes_its_own(tmp_path: Path) -> None:
    played(tmp_path)
    state = json.loads((tmp_path / "setup-state.json").read_text())
    s = nextsetup.load(tmp_path, state)
    s["done"]["compile"] = "k2"
    assert state["done"]["compile"] == "k1"  # a copy, not the played one
    nextsetup.seed(tmp_path)
    (tmp_path / "setup-next/setup-state.json").write_text(json.dumps(s))
    assert nextsetup.load(tmp_path, state)["done"]["compile"] == "k2"


def test_promote_moves_a_finished_update_in(tmp_path: Path) -> None:
    played(tmp_path)
    out = nextsetup.seed(tmp_path)
    (out / "mkwgame.so").write_bytes(b"new lib")
    (out / "setup-state.json").write_text(json.dumps({"version": 1, "done": {}, "port": "0.1.13", "ready": True}))
    assert nextsetup.promote(tmp_path, "0.1.13")
    assert (tmp_path / "mkwgame.so").read_bytes() == b"new lib"
    assert json.loads((tmp_path / "setup-state.json").read_text())["port"] == "0.1.13"
    assert not out.exists() and not (tmp_path / "spirv.old").exists()


def test_promote_drops_an_unfinished_or_other_version(tmp_path: Path) -> None:
    played(tmp_path)
    out = nextsetup.seed(tmp_path)
    (out / "mkwgame.so").write_bytes(b"half")
    (out / "setup-state.json").write_text(json.dumps({"version": 1, "done": {}, "port": "0.1.13"}))
    assert not nextsetup.promote(tmp_path, "0.1.13")
    assert (tmp_path / "mkwgame.so").read_bytes() == b"old lib" and not out.exists()
