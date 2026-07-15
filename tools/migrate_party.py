#!/usr/bin/env python3
"""
migrate_party.py -- one-time migration to the party-overhaul format.

	python3 tools/migrate_party.py

Idempotent (the editor also runs this on load). Three changes:

1. Every player in data/database.json gains "class" (guessed from its
   id when it matches hero/mage/healer, else "hero" -- it's an editor
   preset label, the engine never reads it) and keeps/gains "sprite"
   (the gfx/players/<stem>.png walking sheet; null = hero.png art).

2. The retired hardcoded gfx/mage.png is copied to
   gfx/players/mage.png (the original stays put but is no longer
   read by the tools), and any player with id "mage" and no sprite
   gets sprite "mage" so the follower keeps its art.

3. data/project.json gains "start_party": the first one or two
   player ids, matching the old fixed lineup.
"""

import json
import os
import shutil

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def migrate(db, project, root=ROOT):
	"""Mutates db + project in place; returns True when anything
	changed (caller saves)."""
	changed = False

	# 2. relocate the old fixed mage sheet (file copy first, so the
	#    sprite assignment below can point at something real)
	old = os.path.join(root, "gfx", "mage.png")
	pdir = os.path.join(root, "gfx", "players")
	new = os.path.join(pdir, "mage.png")
	if os.path.exists(old) and not os.path.exists(new):
		os.makedirs(pdir, exist_ok=True)
		shutil.copy(old, new)
		changed = True

	# 1. class + sprite fields
	for p in db.get("players", []):
		if "class" not in p:
			p["class"] = p["id"] if p["id"] in ("hero", "mage",
			                                    "healer") else "hero"
			changed = True
		if "sprite" not in p:
			p["sprite"] = "mage" if (p["id"] == "mage"
			                         and os.path.exists(new)) \
			              else None
			changed = True

	# 3. start_party
	if "start_party" not in project:
		project["start_party"] = [p["id"]
		                          for p in db.get("players", [])[:2]]
		changed = True

	return changed


def main():
	dpath = os.path.join(ROOT, "data", "database.json")
	ppath = os.path.join(ROOT, "data", "project.json")
	db = json.load(open(dpath))
	project = json.load(open(ppath))
	if migrate(db, project):
		json.dump(db, open(dpath, "w"), indent=1)
		json.dump(project, open(ppath, "w"), indent=1)
		print("migrate_party: data migrated")
	else:
		print("migrate_party: nothing to do")


if __name__ == "__main__":
	main()
