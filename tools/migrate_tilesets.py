#!/usr/bin/env python3
"""
migrate_tilesets.py -- one-time migration to the custom-tileset format.

	python3 tools/migrate_tilesets.py

Two changes, both idempotent (the editor also runs this on load):

1. data/tilesets.json is created if missing, describing the engine's
   original 24-slot tileset as tileset "default": per-tile solid flags
   (the old hardcoded collision), the chest tile (17), the void tile
   (4, drawn outside map bounds and behind battles), and the
   roof-over-grass compositing pairs png2ds bakes (11->15, 12->16
   over tile 0). gfx/overworld.png is copied to
   gfx/tilesets/default.png (the original stays put but is no longer
   read by the tools).

2. data/maps.json rows convert from legend-char strings to lists of
   tile indices, and every map gains "tileset": "default". Zone rows
   stay strings ('.', '0'-'7').

The legend below is the ONLY remaining copy of the old char mapping;
gen_maps.py and the editor now speak tile indices exclusively.
"""

import json
import os
import shutil
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# Old maps.json legend -> RUNTIME tile index (matches the retired
# legend() in the generated maps.c: 'f'/'b' are the slants BAKED over
# grass, i.e. slots 15/16, not the raw slant art in slots 11/12).
LEGEND = {'.': 0, 'T': 1, '~': 2, '=': 3, '#': 4, ' ': 5, '^': 6,
          'H': 7, 'w': 8, 's': 9, 'r': 10, 'f': 15, 'b': 16,
          'B': 13, 'D': 14, 'c': 17}

DEFAULT_TILE_META = [
	("Grass", False), ("Tree", True), ("Water", True), ("Path", False),
	("Black", True), ("Blank", False), ("Mountain", True),
	("House", False), ("Wood", False), ("Sign tile", True),
	("Roof", True), ("Roof slant L", True), ("Roof slant R", True),
	("Brick", True), ("Door", False),
	("Roof slant L (grass)", True), ("Roof slant R (grass)", True),
	("Chest", True),
	("Tile 18", False), ("Tile 19", False), ("Tile 20", False),
	("Tile 21", False), ("Tile 22", False), ("Tile 23", False),
]


def default_tilesets():
	return {"tilesets": [{
		"id": "default",
		"image": "gfx/tilesets/default.png",
		"tiles": [{"name": n, "solid": s} for n, s in DEFAULT_TILE_META],
		"chest_tile": 17,
		"void_tile": 4,
		"roof_base": 0,
		"roof_composite": [[11, 15], [12, 16]],
	}]}


def ensure_tilesets(root=ROOT):
	"""Create data/tilesets.json + gfx/tilesets/default.png if absent.
	Returns True if anything was created."""
	changed = False
	tpath = os.path.join(root, "data", "tilesets.json")
	if not os.path.exists(tpath):
		json.dump(default_tilesets(), open(tpath, "w"), indent=1)
		changed = True
	png = os.path.join(root, "gfx", "tilesets", "default.png")
	old = os.path.join(root, "gfx", "overworld.png")
	if not os.path.exists(png) and os.path.exists(old):
		os.makedirs(os.path.dirname(png), exist_ok=True)
		shutil.copy2(old, png)
		changed = True
	return changed


def migrate(maps_data, root=ROOT):
	"""Convert char rows -> index lists; add per-map tileset field.
	Mutates maps_data; returns True if anything changed. Also makes
	sure tilesets.json exists (the maps now depend on it)."""
	changed = ensure_tilesets(root)
	for m in maps_data.get("maps", []):
		if m.get("tileset") is None:
			m["tileset"] = "default"
			changed = True
		rows = m.get("rows", [])
		if rows and isinstance(rows[0], str):
			new = []
			for y, row in enumerate(rows):
				try:
					new.append([LEGEND[c] for c in row])
				except KeyError as e:
					sys.exit("migrate_tilesets: %s row %d: unknown "
					         "tile char %s" % (m.get("cid", "?"), y, e))
			m["rows"] = new
			changed = True
	return changed


def main():
	path = os.path.join(ROOT, "data", "maps.json")
	with open(path) as f:
		data = json.load(f)
	if migrate(data):
		json.dump(data, open(path, "w"), indent=1)
		print("migrate_tilesets: maps.json converted to tile indices; "
		      "tilesets.json ready")
	else:
		print("migrate_tilesets: nothing to do")


if __name__ == "__main__":
	main()
