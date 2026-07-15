#!/usr/bin/env python3
"""
gen_maps.py -- generate source/maps.c and include/map_ids.h from
data/maps.json. Run from the project root:

	python3 tools/gen_maps.py

The map editor (tools/map_editor.py) calls this automatically before
building. Validation errors abort with a message and touch nothing.
"""

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import gen_scripts

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

TILESET_TILES = 24               # keep in sync with maps.h + png2ds.py
ZONE_CHARS = set(".01234567")
MUSIC_EXTS = (".mod", ".it", ".xm", ".s3m")


def load_tilesets(root=ROOT):
	"""data/tilesets.json -> {id: tileset dict}, validated."""
	path = os.path.join(root, "data", "tilesets.json")
	try:
		data = json.load(open(path))
	except FileNotFoundError:
		fail("data/tilesets.json missing -- run "
		     "tools/migrate_tilesets.py once")
	return tileset_index(data)


def tileset_index(data):
	"""Validate a tilesets.json dict; return {id: tileset dict}."""
	out = {}
	for ts in data.get("tilesets", []):
		tid = ts.get("id", "")
		if not tid.isidentifier():
			fail("tileset id %r is not a valid identifier" % tid)
		if tid in out:
			fail("duplicate tileset id %r" % tid)
		tiles = ts.get("tiles", [])
		if len(tiles) != TILESET_TILES:
			fail("tileset %s: needs exactly %d tile entries (has %d)"
			     % (tid, TILESET_TILES, len(tiles)))
		for key in ("chest_tile", "void_tile"):
			v = ts.get(key)
			if v is not None and not (0 <= v < TILESET_TILES):
				fail("tileset %s: %s must be 0..%d or null"
				     % (tid, key, TILESET_TILES - 1))
		if ts.get("void_tile") is None:
			fail("tileset %s: void_tile is required (drawn outside "
			     "map bounds and behind battles)" % tid)
		for pair in ts.get("roof_composite", []):
			if (len(pair) != 2 or
			    not all(0 <= p < TILESET_TILES for p in pair)):
				fail("tileset %s: bad roof_composite pair %r"
				     % (tid, pair))
		out[tid] = ts
	if not out:
		fail("data/tilesets.json defines no tilesets")
	return out


def music_define(stem):
	"""mmutil's mangling: uppercase, non-alnum -> underscore (verified
	empirically: town-theme.mod -> MOD_TOWN_THEME)."""
	return "MOD_" + "".join(c if c.isalnum() else "_"
	                        for c in stem).upper()


def music_stems():
	mdir = os.path.join(ROOT, "music")
	if not os.path.isdir(mdir):
		return set()
	return {os.path.splitext(f)[0] for f in os.listdir(mdir)
	        if f.lower().endswith(MUSIC_EXTS)}


def backdrop_stems():
	bdir = os.path.join(ROOT, "gfx", "backdrops")
	if not os.path.isdir(bdir):
		return set()
	return {os.path.splitext(f)[0] for f in os.listdir(bdir)
	        if f.lower().endswith(".png")}


def npc_sprite_stems():
	ndir = os.path.join(ROOT, "gfx", "npcs")
	if not os.path.isdir(ndir):
		return set()
	return {os.path.splitext(f)[0] for f in os.listdir(ndir)
	        if f.lower().endswith(".png")}
MAX_NPCS, MAX_WARPS, MAX_SIGNS = 4, 4, 2       # keep in sync with maps.h
MAX_ZONE_TROOPS = 4
MAX_SHOP_ITEMS = 6                             # keep in sync with maps.h
MAX_CHESTS = 4                                 # keep in sync with maps.h
MIN_W, MIN_H, MAX_W, MAX_H = 16, 12, 32, 32    # camera + 512x512 BG limits

RUNTIME_C = """int mapTileAt(const MapDef *m, int x, int y)
{
	if (x < 0 || y < 0 || x >= m->w || y >= m->h)
		return tilesetDefs[m->tileset].voidTile;
	return m->tiles[y * m->w + x];
}

bool mapSolid(const MapDef *m, int x, int y)
{
	return (tilesetDefs[m->tileset].solid >> mapTileAt(m, x, y)) & 1;
}
"""


def cstr(s):
	return '"%s"' % (s.replace('\\', '\\\\').replace('"', '\\"')
	                  .replace('\n', '\\n'))


def fail(msg):
	sys.exit("gen_maps: " + msg)


def validate(data, tilesets=None):
	tsets = tileset_index(tilesets) if tilesets is not None \
	        else load_tilesets()
	cids = [m["cid"] for m in data["maps"]]
	if len(set(cids)) != len(cids):
		fail("duplicate map cid")
	for m in data["maps"]:
		name = m["cid"]
		if m["rows"] and isinstance(m["rows"][0], str):
			fail("%s: rows are still legend strings -- run "
			     "tools/migrate_tilesets.py once" % name)
		ts = tsets.get(m.get("tileset") or "")
		if ts is None:
			fail("%s: unknown tileset %r (see data/tilesets.json)"
			     % (name, m.get("tileset")))
		if not (MIN_W <= m["w"] <= MAX_W and MIN_H <= m["h"] <= MAX_H):
			fail("%s: size %dx%d outside %dx%d..%dx%d"
			     % (name, m["w"], m["h"], MIN_W, MIN_H, MAX_W, MAX_H))
		if len(m["rows"]) != m["h"]:
			fail("%s: %d rows, expected %d" % (name, len(m["rows"]), m["h"]))
		for y, row in enumerate(m["rows"]):
			if isinstance(row, str):
				fail("%s: rows are still legend strings -- run "
				     "tools/migrate_tilesets.py once" % name)
			if len(row) != m["w"]:
				fail("%s row %d: %d tiles, expected %d"
				     % (name, y, len(row), m["w"]))
			for t in row:
				if not (isinstance(t, int)
				        and 0 <= t < TILESET_TILES):
					fail("%s row %d: bad tile index %r" % (name, y, t))
		if len(m.get("npcs", [])) > MAX_NPCS:
			fail("%s: more than %d NPCs" % (name, MAX_NPCS))
		if len(m.get("warps", [])) > MAX_WARPS:
			fail("%s: more than %d warps" % (name, MAX_WARPS))
		if len(m.get("signs", [])) > MAX_SIGNS:
			fail("%s: more than %d signs" % (name, MAX_SIGNS))
		for w in m.get("warps", []):
			if w["dest"] not in cids:
				fail("%s: warp to unknown map %s" % (name, w["dest"]))
			if w.get("flag") and not w.get("locked_text"):
				fail("%s: flag-gated warp at (%d,%d) needs locked_text"
				     % (name, w["x"], w["y"]))
		for n in m.get("npcs", []):
			shop = n.get("shop") or []
			if len(shop) > MAX_SHOP_ITEMS:
				fail("%s: NPC at (%d,%d): max %d shop items"
				     % (name, n["x"], n["y"], MAX_SHOP_ITEMS))
			if shop and n.get("healer"):
				fail("%s: NPC at (%d,%d) can't be both healer and shop"
				     % (name, n["x"], n["y"]))
			if shop and (n.get("sets_flag") or n.get("alt")):
				fail("%s: NPC at (%d,%d): shopkeepers can't have flag "
				     "dialog (v1)" % (name, n["x"], n["y"]))
			if n.get("boss") and (shop or n.get("healer")):
				fail("%s: NPC at (%d,%d): a boss can't be a healer "
				     "or shopkeeper" % (name, n["x"], n["y"]))
			if n.get("joins") and (shop or n.get("healer")
			                       or n.get("boss")):
				fail("%s: NPC at (%d,%d): a recruiter can't be a "
				     "healer, shopkeeper, or boss"
				     % (name, n["x"], n["y"]))
			alt = n.get("alt")
			if alt and (not alt.get("flag") or "text" not in alt):
				fail("%s: NPC at (%d,%d): alt dialog needs flag + text"
				     % (name, n["x"], n["y"]))
		chests = m.get("chests", [])
		if len(chests) > MAX_CHESTS:
			fail("%s: more than %d chests" % (name, MAX_CHESTS))
		ctile = ts.get("chest_tile")
		if chests and ctile is None:
			fail("%s: has chests but tileset %s defines no chest "
			     "tile" % (name, ts["id"]))
		chest_at = set()
		for ch in chests:
			if not ch.get("item"):
				fail("%s: chest at (%d,%d) needs an item"
				     % (name, ch["x"], ch["y"]))
			if not ch.get("flag"):
				fail("%s: chest at (%d,%d) needs a flag (marks it "
				     "opened)" % (name, ch["x"], ch["y"]))
			if m["rows"][ch["y"]][ch["x"]] != ctile:
				fail("%s: chest at (%d,%d) is not on the chest tile"
				     % (name, ch["x"], ch["y"]))
			chest_at.add((ch["x"], ch["y"]))
		if ctile is not None:
			for y, row in enumerate(m["rows"]):
				for x, t in enumerate(row):
					if t == ctile and (x, y) not in chest_at:
						fail("%s: chest tile at (%d,%d) has no chest "
						     "(use the editor's Chest tool)"
						     % (name, x, y))
		zr = m.get("zone_rows")
		zones = m.get("zones") or {}
		if zr:
			if len(zr) != m["h"] or any(len(r) != m["w"] for r in zr):
				fail("%s: zone layer size mismatch" % name)
			used = set("".join(zr)) - {"."}
			if not used <= (ZONE_CHARS - {"."}):
				fail("%s: bad zone char" % name)
			for z in used:
				if z not in zones:
					fail("%s: zone %s painted but has no encounter set"
					     % (name, z))
			for z, ref in zones.items():
				if isinstance(ref, dict):
					fail("%s: zone %s uses the old inline table format "
					     "-- open the editor once to migrate, or run "
					     "tools/migrate_encounters.py" % (name, z))
				if not isinstance(ref, str) or not ref:
					fail("%s: zone %s must reference an encounter set id"
					     % (name, z))
		elif zones:
			fail("%s: zone tables but no zone layer" % name)
		mus = m.get("music")
		if mus and mus not in music_stems():
			fail("%s: music %r not found in music/" % (name, mus))
		bd = m.get("backdrop")
		if bd and bd not in backdrop_stems():
			fail("%s: backdrop %r not found in gfx/backdrops/"
			     % (name, bd))
		nstems = npc_sprite_stems()
		for n in m.get("npcs", []):
			sp = n.get("sprite")
			if sp and sp not in nstems:
				fail("%s: NPC at (%d,%d): sprite %r not found in "
				     "gfx/npcs/" % (name, n["x"], n["y"], sp))
		evs = m.get("events", [])
		if len(evs) > gen_scripts.MAX_EVENTS:
			fail("%s: more than %d events"
			     % (name, gen_scripts.MAX_EVENTS))
		for i, ev in enumerate(evs):
			t = ev.get("trigger") or {}
			kind = t.get("kind")
			if kind not in gen_scripts.TRIGGER_KINDS:
				fail("%s event %d: bad trigger kind %r"
				     % (name, i, kind))
			if kind == "on_flag" and not t.get("flag"):
				fail("%s event %d: on_flag needs a flag" % (name, i))
			if kind == "on_tile":
				x, y = t.get("x"), t.get("y")
				if not (isinstance(x, int) and isinstance(y, int)
				        and 0 <= x < m["w"] and 0 <= y < m["h"]):
					fail("%s event %d: on_tile (%r,%r) outside map"
					     % (name, i, x, y))
				tile = m["rows"][y][x]
				if ts["tiles"][tile].get("solid"):
					fail("%s event %d: on_tile (%d,%d) is on a solid "
					     "tile -- the player can never step there"
					     % (name, i, x, y))
	for key in ("start", "death"):
		if data[key]["map"] not in cids:
			fail("%s references unknown map" % key)


def generate(data, root=ROOT, tilesets=None):
	if tilesets is None:
		tilesets = json.load(open(os.path.join(root, "data",
		                                       "tilesets.json")))
	validate(data, tilesets)
	tlist = tilesets["tilesets"]
	maps = data["maps"]
	tids = troop_ids()
	encs = encounter_sets()
	prices = item_prices()
	flags = flag_ids()
	for m in maps:
		if encs is None and m.get("zones"):
			fail("data/database.json required to resolve encounter sets")
		if encs is not None:
			for z, ref in (m.get("zones") or {}).items():
				if ref not in encs:
					fail("%s zone %s: unknown encounter set %r"
					     % (m["cid"], z, ref))
				if tids is not None:
					for troop, w in encs[ref]["troops"]:
						if troop not in tids:
							fail("encounter set %s: unknown troop %r"
							     % (ref, troop))
		if prices is not None:
			for n in m.get("npcs", []):
				for iid in (n.get("shop") or []):
					if iid not in prices:
						fail("%s: NPC shop: unknown item %r"
						     % (m["cid"], iid))
					if prices[iid] <= 0:
						fail("%s: NPC shop: item %r has no price"
						     % (m["cid"], iid))
			for ch in m.get("chests", []):
				if ch["item"] not in prices:
					fail("%s: chest at (%d,%d): unknown item %r"
					     % (m["cid"], ch["x"], ch["y"], ch["item"]))
		if flags is not None:
			def ck(fl, what):
				if fl and fl not in flags:
					fail("%s: %s: unknown flag %r"
					     % (m["cid"], what, fl))
			for n in m.get("npcs", []):
				ck(n.get("sets_flag"), "NPC sets_flag")
				ck((n.get("alt") or {}).get("flag"), "NPC alt dialog")
				ck(n.get("hidden_when"), "NPC hidden_when")
			for i, ev in enumerate(m.get("events", [])):
				ck((ev.get("trigger") or {}).get("flag"),
				   "event %d trigger" % i)
		bosses = boss_ids()
		if bosses is not None:
			for n in m.get("npcs", []):
				if n.get("boss") and n["boss"] not in bosses:
					fail("%s: NPC at (%d,%d): unknown boss %r"
					     % (m["cid"], n["x"], n["y"], n["boss"]))
		players = player_ids()
		if players is not None:
			for n in m.get("npcs", []):
				if n.get("joins") and n["joins"] not in players:
					fail("%s: NPC at (%d,%d): unknown player %r"
					     % (m["cid"], n["x"], n["y"], n["joins"]))
			for w in m.get("warps", []):
				ck(w.get("flag"), "warp gate")
			for ch in m.get("chests", []):
				ck(ch.get("flag"), "chest")

	# ---- include/map_ids.h ----
	h = ["/* Generated by tools/gen_maps.py -- do not edit by hand. */",
	     "#ifndef MAP_IDS_H", "#define MAP_IDS_H", "", "enum {"]
	for i, m in enumerate(maps):
		h.append("\t%s%s," % (m["cid"], " = 0" if i == 0 else ""))
	h += ["\tN_MAPS,", "};", "", "enum {"]
	for i, ts in enumerate(tlist):
		h.append("\tTILESET_%s%s," % (ts["id"].upper(),
		                              " = 0" if i == 0 else ""))
	h += ["\tN_TILESETS,", "};", ""]
	for key in ("start", "death"):
		K = key.upper()
		h.append("#define %s_MAP %s" % (K, data[key]["map"]))
		h.append("#define %s_X   %d" % (K, data[key]["x"]))
		h.append("#define %s_Y   %d" % (K, data[key]["y"]))
	h += ["", "#endif", ""]

	# ---- source/maps.c ----
	c = ["/* Generated by tools/gen_maps.py from data/maps.json --",
	     " * do not edit by hand. Use tools/map_editor.py instead. */",
	     '#include "maps.h"', '#include "db_data.h"',
	     '#include "soundbank.h"', ""]
	for m in maps:
		c.append("static const unsigned char tiles_%s[] = {"
		         % m["cid"])
		for row in m["rows"]:
			c.append("\t" + ",".join("%d" % t for t in row) + ",")
		c += ["};", ""]
		if m.get("zone_rows"):
			c.append("static const char *const zrows_%s[] = {" % m["cid"])
			for row in m["zone_rows"]:
				c.append("\t%s," % cstr(row))
			c += ["};", ""]
			c.append("static const ZoneDef zones_%s[] = {" % m["cid"])
			for z in sorted(m["zones"]):
				t = encs[m["zones"][z]]
				entries = ", ".join("{ TROOP_%s, %d }" % (tr.upper(), w)
				                    for tr, w in t["troops"])
				c.append("\t{ '%s', %d, %d, { %s } }," %
				         (z, t["rate"], len(t["troops"]), entries))
			c += ["};", ""]

	used_bd = sorted({m["backdrop"] for m in maps if m.get("backdrop")})
	for bd in used_bd:
		c.append("extern const unsigned short backdropGfx_%s[];" % bd)
	used_np = sorted({n["sprite"] for m in maps
	                  for n in m.get("npcs", []) if n.get("sprite")})
	for sp in used_np:
		c.append("extern const unsigned short npcSprite_%s[];" % sp)
	if used_bd or used_np:
		c.append("")
	for ts in tlist:
		c.append("extern const unsigned short tilesetGfx_%s[];"
		         % ts["id"])
	c.append("")
	c.append("const TilesetDef tilesetDefs[N_TILESETS] = {")
	for ts in tlist:
		mask = 0
		for i, t in enumerate(ts["tiles"]):
			if t.get("solid"):
				mask |= 1 << i
		c.append("\t{ tilesetGfx_%s, 0x%06Xu, %d },   /* %s */" %
		         (ts["id"], mask, ts["void_tile"], ts["id"]))
	c += ["};", ""]
	c.append("const MapDef maps[N_MAPS] = {")
	sidx = gen_scripts.script_index(data)
	EVT = {"on_load": "EVT_LOAD", "on_flag": "EVT_FLAG",
	       "on_tile": "EVT_TILE"}
	for mi, m in enumerate(maps):
		c.append("\t{")
		c.append('\t\t.name = %s, .w = %d, .h = %d,' %
		         (cstr(m["name"]), m["w"], m["h"]))
		c.append("\t\t.tiles = tiles_%s," % m["cid"])
		c.append("\t\t.tileset = TILESET_%s," % m["tileset"].upper())
		if m.get("zone_rows"):
			c.append("\t\t.zoneRows = zrows_%s," % m["cid"])
			c.append("\t\t.nZones = %d," % len(m["zones"]))
			c.append("\t\t.zones = zones_%s," % m["cid"])
		c.append("\t\t.music = %s," %
		         (music_define(m["music"]) if m.get("music") else "-1"))
		if m.get("backdrop"):
			c.append("\t\t.backdrop = backdropGfx_%s," % m["backdrop"])
		npcs = m.get("npcs", [])
		if npcs:
			c.append("\t\t.nNpcs = %d," % len(npcs))
			c.append("\t\t.npcs = {")
			for n in npcs:
				shop = n.get("shop") or []
				wares = ", ".join("ITEM_%s" % s.upper() for s in shop) \
				        if shop else "0"
				alt = n.get("alt")
				boss = ("BOSS_%s" % n["boss"].upper()) \
				       if n.get("boss") else "-1"
				sprite = ("npcSprite_%s" % n["sprite"]) \
				         if n.get("sprite") else "0"
				joins = ("PLAYER_%s" % n["joins"].upper()) \
				        if n.get("joins") else "-1"
				c.append("\t\t\t{ %d, %d, %s, %s, %d, { %s },"
				         " %s, %s, %s, %s, %s, %s, %s }," %
				         (n["x"], n["y"], cstr(n["text"]),
				          "true" if n.get("healer") else "false",
				          len(shop), wares,
				          flag_ref(n.get("sets_flag")),
				          flag_ref(alt["flag"] if alt else None),
				          cstr(alt["text"]) if alt else "0", boss,
				          sprite, joins,
				          flag_ref(n.get("hidden_when"))))
			c.append("\t\t},")
		warps = m.get("warps", [])
		if warps:
			c.append("\t\t.nWarps = %d," % len(warps))
			c.append("\t\t.warps = {")
			for w in warps:
				c.append("\t\t\t{ %d, %d, %s, %d, %d, %s, %s }," %
				         (w["x"], w["y"], w["dest"], w["dx"], w["dy"],
				          flag_ref(w.get("flag")),
				          cstr(w["locked_text"]) if w.get("flag")
				          else "0"))
			c.append("\t\t},")
		chests = m.get("chests", [])
		if chests:
			c.append("\t\t.nChests = %d," % len(chests))
			c.append("\t\t.chests = {")
			for ch in chests:
				c.append("\t\t\t{ %d, %d, ITEM_%s, %s }," %
				         (ch["x"], ch["y"], ch["item"].upper(),
				          flag_ref(ch["flag"])))
			c.append("\t\t},")
		signs = m.get("signs", [])
		if signs:
			c.append("\t\t.nSigns = %d," % len(signs))
			c.append("\t\t.signs = {")
			for s in signs:
				c.append("\t\t\t{ %d, %d, %s }," %
				         (s["x"], s["y"], cstr(s["text"])))
			c.append("\t\t},")
		evs = m.get("events", [])
		if evs:
			c.append("\t\t.nEvents = %d," % len(evs))
			c.append("\t\t.events = {")
			for ei, ev in enumerate(evs):
				t = ev["trigger"]
				c.append("\t\t\t{ %s, %s, %d, %d, %d },"
				         % (EVT[t["kind"]], flag_ref(t.get("flag")),
				            t.get("x", 0), t.get("y", 0),
				            sidx[(mi, ei)]))
			c.append("\t\t},")
		c.append("\t},")
	c += ["};", "", RUNTIME_C]

	with open(os.path.join(root, "include", "map_ids.h"), "w") as f:
		f.write("\n".join(h))
	with open(os.path.join(root, "source", "maps.c"), "w") as f:
		f.write("\n".join(c))
	return "%d maps -> source/maps.c + include/map_ids.h" % len(maps)


def flag_ref(flag_id):
	"""C expression for an optional flag: FLAG_<ID> or -1."""
	return "FLAG_%s" % flag_id.upper() if flag_id else "-1"


def _load_db():
	try:
		return json.load(open(os.path.join(ROOT, "data",
		                                   "database.json")))
	except FileNotFoundError:
		return None


def troop_ids():
	db = _load_db()
	if db is None:
		return None
	return {t["id"]: i for i, t in enumerate(db["troops"])}


def item_prices():
	db = _load_db()
	if db is None:
		return None
	return {it["id"]: it.get("price", 0) for it in db["items"]}


def encounter_sets():
	db = _load_db()
	if db is None:
		return None
	return {s["id"]: s for s in db.get("encounters", [])}


def flag_ids():
	db = _load_db()
	if db is None:
		return None
	return set(db.get("flags", []))


def boss_ids():
	db = _load_db()
	if db is None:
		return None
	return {b["id"] for b in db.get("bosses", [])}


def player_ids():
	db = _load_db()
	if db is None:
		return None
	return {p["id"] for p in db.get("players", [])}


def main():
	with open(os.path.join(ROOT, "data", "maps.json")) as f:
		data = json.load(f)
	print("gen_maps:", generate(data))


if __name__ == "__main__":
	main()
