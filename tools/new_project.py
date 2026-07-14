#!/usr/bin/env python3
"""
new_project.py -- scaffold a fresh Miniquest Engine project.

	python tools\\new_project.py C:\\path\\to\\MyGame --name "My Game"

Copies the engine (source, include, tools, stub, Makefile, starter
assets) into the target folder, resets data/ to a minimal template
(one grass map, the default database), regenerates the C, and leaves
a project ready for `make` / the editor.

Starter assets are the current project's gfx/ -- replace them with your
own art (same sizes and the magenta #FF00FF transparency convention).
"""

import argparse
import json
import os
import shutil
import subprocess
import sys

ENGINE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ENGINE, "tools"))
import migrate_tilesets

COPY_DIRS = ["source", "include", "tools", "stub", "gfx", "music"]
COPY_FILES = ["Makefile", "README.md"]
SKIP = {"__pycache__", ".git"}

DEFAULT_DB = {
	"exp_curve": [0, 0, 7, 23, 47, 90, 160],
	"players": [
		{"id": "hero", "name": "HERO", "hp": 24, "mp": 0, "atk": 10,
		 "def": 8, "agi": 6, "ghp": 6, "gmp": 0, "gatk": 2, "gdef": 1,
		 "gagi": 1, "spells": []},
		{"id": "mage", "name": "MAGE", "hp": 16, "mp": 8, "atk": 6,
		 "def": 5, "agi": 8, "ghp": 4, "gmp": 3, "gatk": 1, "gdef": 1,
		 "gagi": 2, "spells": []}
	],
	"enemies": [
		{"id": "slime", "name": "Slime", "sprite": "slime.png",
		 "hp": 8, "atk": 6, "def": 4, "agi": 4, "exp": 2, "gold": 3}
	],
	"troops": [
		{"id": "slime_solo", "name": "a Slime", "members": ["slime"]}
	],
	"items": [
		{"id": "herb", "name": "Herb", "heal": 10}
	]
}


def default_maps():
	w, h = 20, 16
	GRASS, TREE = 0, 1                     # default tileset indices
	rows = [[GRASS] * w for _ in range(h)]
	rows[0] = [TREE] * w
	rows[-1] = [TREE] * w
	for y in range(h):
		rows[y][0] = rows[y][-1] = TREE
	return {
		"comment": "Edit with tools/map_editor.py.",
		"start": {"map": "MAP_START", "x": 10, "y": 8},
		"death": {"map": "MAP_START", "x": 10, "y": 8},
		"maps": [{
			"cid": "MAP_START", "name": "Meadow", "w": w, "h": h,
			"rows": rows, "tileset": "default",
			"npcs": [], "warps": [], "signs": [],
			"zone_rows": None, "zones": {}, "music": "town-theme",
		}]
	}


def copy_tree(src, dest):
	for root, dirs, files in os.walk(src):
		dirs[:] = [d for d in dirs if d not in SKIP]
		rel = os.path.relpath(root, src)
		out = os.path.join(dest, rel) if rel != "." else dest
		os.makedirs(out, exist_ok=True)
		for f in files:
			if f.endswith((".o", ".elf", ".nds", ".sav", ".pyc")):
				continue
			shutil.copy2(os.path.join(root, f), os.path.join(out, f))


def main():
	ap = argparse.ArgumentParser()
	ap.add_argument("dest", help="target project folder (created)")
	ap.add_argument("--name", default="My Quest", help="game name")
	args = ap.parse_args()

	dest = os.path.abspath(args.dest)
	if os.path.exists(dest) and os.listdir(dest):
		sys.exit("new_project: %s exists and is not empty" % dest)
	os.makedirs(dest, exist_ok=True)

	for d in COPY_DIRS:
		copy_tree(os.path.join(ENGINE, d), os.path.join(dest, d))
	for f in COPY_FILES:
		p = os.path.join(ENGINE, f)
		if os.path.exists(p):
			shutil.copy2(p, dest)

	# generated C will be rebuilt below; drop the copies to avoid
	# confusion about their source of truth
	for f in ("source/maps.c", "source/db_data.c", "source/gfx_data.c",
	          "include/map_ids.h", "include/db_data.h",
	          "include/gfx_data.h"):
		try:
			os.remove(os.path.join(dest, f))
		except FileNotFoundError:
			pass

	data = os.path.join(dest, "data")
	os.makedirs(data, exist_ok=True)
	json.dump(default_maps(), open(os.path.join(data, "maps.json"), "w"),
	          indent=1)
	json.dump(DEFAULT_DB, open(os.path.join(data, "database.json"), "w"),
	          indent=1)
	json.dump({"name": args.name, "title_image": "gfx/title.png",
	           "title_music": None, "battle_music": None,
	           "victory_music": None,
	           "start_items": {"herb": 2}},
	          open(os.path.join(data, "project.json"), "w"), indent=1)
	migrate_tilesets.ensure_tilesets(dest)
	json.dump({"bash": "C:/devkitPro/msys2/usr/bin/bash.exe",
	           "emulator": "", "copy_to": ""},
	          open(os.path.join(data, "editor_config.json"), "w"),
	          indent=1)

	# keep only the sprites the default database references
	edir = os.path.join(dest, "gfx", "enemies")
	for f in os.listdir(edir):
		if f not in {e["sprite"] for e in DEFAULT_DB["enemies"]}:
			os.remove(os.path.join(edir, f))

	# regenerate the C so the project builds out of the box
	for script in ("gen_db.py", "png2ds.py", "gen_maps.py"):
		r = subprocess.run([sys.executable,
		                    os.path.join(dest, "tools", script)])
		if r.returncode != 0:
			sys.exit("new_project: %s failed" % script)

	print("new_project: created %s" % dest)
	print("  next: python tools\\map_editor.py  (from inside it)")


if __name__ == "__main__":
	main()
