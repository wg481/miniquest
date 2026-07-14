#!/usr/bin/env python3
"""
migrate_encounters.py -- one-time migration: move inline per-zone
encounter tables (maps.json zones = {"0": {rate, troops}}) into named
encounter sets in database.json (db["encounters"]), leaving zones as
references ({"0": "enc_overworld_0"}).

The editor runs migrate() automatically on load; run this from the
project root instead if you only use the CLI generators:

	python3 tools/migrate_encounters.py

Backs up both JSONs to *.pre-encounters.bak before writing.
"""

import json
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _set_key(table):
	"""Hashable identity of an inline table for deduplication."""
	return (table["rate"], tuple((t, w) for t, w in table["troops"]))


def migrate(maps_data, db_data):
	"""Convert inline zone tables to database encounter-set references.
	Mutates both dicts in place; returns True if anything changed.
	Identical inline tables (same rate + troops) share one set."""
	sets = db_data.setdefault("encounters", [])
	by_key = {_set_key(s): s["id"] for s in sets}
	ids = {s["id"] for s in sets}
	changed = False

	for m in maps_data["maps"]:
		zones = m.get("zones") or {}
		for z, table in list(zones.items()):
			if not isinstance(table, dict):
				continue                     # already a reference
			key = _set_key(table)
			if key in by_key:
				zones[z] = by_key[key]
			else:
				base = "enc_%s_%s" % (
					re.sub(r"^map_", "", m["cid"].lower()), z)
				sid, n = base, 2
				while sid in ids:
					sid = "%s_%d" % (base, n)
					n += 1
				sets.append({"id": sid, "rate": table["rate"],
				             "troops": table["troops"]})
				by_key[key] = sid
				ids.add(sid)
				zones[z] = sid
			changed = True
	return changed


def main():
	mp = os.path.join(ROOT, "data", "maps.json")
	dp = os.path.join(ROOT, "data", "database.json")
	maps_data = json.load(open(mp))
	db_data = json.load(open(dp))
	if not migrate(maps_data, db_data):
		print("migrate_encounters: nothing to migrate")
		return
	import shutil
	shutil.copy(mp, mp + ".pre-encounters.bak")
	shutil.copy(dp, dp + ".pre-encounters.bak")
	json.dump(maps_data, open(mp, "w"), indent=1)
	json.dump(db_data, open(dp, "w"), indent=1)
	print("migrate_encounters: migrated %d encounter set(s); backups "
	      "written (*.pre-encounters.bak)"
	      % len(db_data["encounters"]))


if __name__ == "__main__":
	main()
