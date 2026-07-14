#!/usr/bin/env python3
"""
gen_db.py -- generate source/db_data.c and include/db_data.h from
data/database.json and data/project.json. Run from the project root.

Enemy sprite arrays (enemyGfx_<id>) are produced by tools/png2ds.py;
this generator only references them.
"""

import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MAX_TROOP = 3
ITEM_MAX = 6                     # inventory cap per item type (DQ style)
MAX_ENC_TROOPS = 4               # keep in sync with gen_maps MAX_ZONE_TROOPS
MAX_FLAGS = 256                  # save format reserves vars[256] (v2);
                                 # editor reads this cap too
MAX_SPELLS = 6                   # per player; keep in sync with db.h
SPELL_EFFECTS = ("heal", "fire")


MUSIC_EXTS = (".mod", ".it", ".xm", ".s3m")


def music_define(stem):
	"""mmutil's mangling: uppercase, non-alnum -> underscore.
	Keep in sync with gen_maps.music_define."""
	return "MOD_" + "".join(c if c.isalnum() else "_"
	                        for c in stem).upper()


def music_stems():
	"""Keep in sync with gen_maps.music_stems."""
	mdir = os.path.join(ROOT, "music")
	if not os.path.isdir(mdir):
		return set()
	return {os.path.splitext(f)[0] for f in os.listdir(mdir)
	        if f.lower().endswith(MUSIC_EXTS)}


def cstr(s):
	return '"%s"' % (s.replace('\\', '\\\\').replace('"', '\\"')
	                  .replace('\n', '\\n'))


def cid(kind, ident):
	return "%s_%s" % (kind, ident.upper())


def fail(msg):
	sys.exit("gen_db: " + msg)


def validate(db, project):
	ids = {}
	for kind in ("players", "enemies", "troops", "items"):
		seen = set()
		for e in db[kind]:
			if not e["id"].isidentifier():
				fail("%s id %r is not a valid identifier" % (kind, e["id"]))
			if e["id"] in seen:
				fail("duplicate %s id %r" % (kind, e["id"]))
			seen.add(e["id"])
		ids[kind] = seen
	if len(db["players"]) != 2:
		fail("exactly 2 players supported for now (status UI layout)")
	if not db["enemies"]:
		fail("need at least one enemy")
	if not db["troops"]:
		fail("need at least one troop")
	for t in db["troops"]:
		if not (1 <= len(t["members"]) <= MAX_TROOP):
			fail("troop %s: 1..%d members" % (t["id"], MAX_TROOP))
		for m in t["members"]:
			if m not in ids["enemies"]:
				fail("troop %s: unknown enemy %r" % (t["id"], m))
	if len(db["exp_curve"]) < 2:
		fail("exp_curve needs at least 2 entries")
	for it in db["items"]:
		price = it.get("price", 0)
		if not isinstance(price, int) or not (0 <= price <= 9999):
			fail("item %s: price must be an int 0..9999" % it["id"])
	seen = set()
	for s in db.get("encounters", []):
		if not s["id"].isidentifier():
			fail("encounter set id %r is not a valid identifier" % s["id"])
		if s["id"] in seen:
			fail("duplicate encounter set id %r" % s["id"])
		seen.add(s["id"])
		if not (1 <= s.get("rate", 0) <= 255):
			fail("encounter set %s: rate must be 1..255" % s["id"])
		if not (1 <= len(s.get("troops", [])) <= MAX_ENC_TROOPS):
			fail("encounter set %s: 1..%d troop entries"
			     % (s["id"], MAX_ENC_TROOPS))
		for tr, w in s["troops"]:
			if tr not in ids["troops"]:
				fail("encounter set %s: unknown troop %r" % (s["id"], tr))
			if not (1 <= w <= 255):
				fail("encounter set %s: weight must be 1..255" % s["id"])
	flags = db.get("flags", [])
	if len(flags) > MAX_FLAGS:
		fail("max %d flags (save format reserves vars[%d])"
		     % (MAX_FLAGS, MAX_FLAGS))
	fseen = set()
	for fl in flags:
		if not fl.isidentifier():
			fail("flag %r is not a valid identifier" % fl)
		if fl in fseen:
			fail("duplicate flag %r" % fl)
		fseen.add(fl)
	spell_ids = set()
	for sp in db.get("spells", []):
		if not sp["id"].isidentifier():
			fail("spell id %r is not a valid identifier" % sp["id"])
		if sp["id"] in spell_ids:
			fail("duplicate spell id %r" % sp["id"])
		spell_ids.add(sp["id"])
		if len(sp.get("name", "")) > 9:
			fail("spell %s: name over 9 chars breaks the menu"
			     % sp["id"])
		if sp.get("effect") not in SPELL_EFFECTS:
			fail("spell %s: effect must be one of %s"
			     % (sp["id"], "/".join(SPELL_EFFECTS)))
		if not (0 <= sp.get("cost", -1) <= 99):
			fail("spell %s: cost must be 0..99" % sp["id"])
		if not (1 <= sp.get("level", 0) <= len(db["exp_curve"]) - 1):
			fail("spell %s: level must be 1..MAX_LEVEL(%d)"
			     % (sp["id"], len(db["exp_curve"]) - 1))
		if not (1 <= sp.get("power", 0) <= 255):
			fail("spell %s: power must be 1..255" % sp["id"])
	for p in db["players"]:
		pspells = p.get("spells", [])
		if len(pspells) > MAX_SPELLS:
			fail("player %s: max %d spells" % (p["id"], MAX_SPELLS))
		for sid in pspells:
			if sid not in spell_ids:
				fail("player %s: unknown spell %r" % (p["id"], sid))
	bseen = set()
	for b in db.get("bosses", []):
		if not b["id"].isidentifier():
			fail("boss id %r is not a valid identifier" % b["id"])
		if b["id"] in bseen:
			fail("duplicate boss id %r" % b["id"])
		bseen.add(b["id"])
		if b.get("troop") not in ids["troops"]:
			fail("boss %s: unknown troop %r"
			     % (b["id"], b.get("troop")))
		if not b.get("sprite"):
			fail("boss %s: needs a 16x16 sprite under gfx/bosses/"
			     % b["id"])
		bmus = b.get("music")
		if bmus and bmus not in music_stems():
			fail("boss %s: music %r not found in music/"
			     % (b["id"], bmus))
	for key in ("title_music", "battle_music", "victory_music"):
		mus = project.get(key)
		if mus and mus not in music_stems():
			fail("%s: music %r not found in music/" % (key, mus))
	for item_id, n in project.get("start_items", {}).items():
		if item_id not in ids["items"]:
			fail("start_items: unknown item %r" % item_id)
		if not (0 <= n <= ITEM_MAX):
			fail("start_items: %s count must be 0..%d" % (item_id, ITEM_MAX))


def generate(db, project, root=ROOT):
	validate(db, project)
	enemies, troops = db["enemies"], db["troops"]
	items, players = db["items"], db["players"]
	e_index = {e["id"]: i for i, e in enumerate(enemies)}
	i_index = {it["id"]: i for i, it in enumerate(items)}

	h = ["/* Generated by tools/gen_db.py -- do not edit by hand. */",
	     "#ifndef DB_DATA_H", "#define DB_DATA_H", "",
	     '#include "db.h"', "",
	     "#define GAME_TITLE %s" % cstr(project["name"]),
	     "#define PARTY_SIZE %d" % len(players),
	     "#define MAX_LEVEL  %d" % (len(db["exp_curve"]) - 1),
	     "#define N_ENEMIES  %d" % len(enemies),
	     "#define N_TROOPS   %d" % len(troops),
	     "#define N_ITEMS    %d" % len(items),
	     "#define ITEM_MAX   %d" % ITEM_MAX,
	     "#define N_FLAGS    %d" % len(db.get("flags", [])),
	     "#define N_SPELLS   %d" % len(db.get("spells", [])),
	     "#define N_BOSSES   %d" % len(db.get("bosses", [])), ""]
	bosses_l = db.get("bosses", [])
	if bosses_l:
		h.append("enum { %s };" % ", ".join(
			cid("BOSS", b["id"]) + (" = 0" if i == 0 else "")
			for i, b in enumerate(bosses_l)))
	for kind, lst in (("ENEMY", enemies), ("TROOP", troops),
	                  ("ITEM", items), ("PLAYER", players)):
		h.append("enum { %s };" % ", ".join(
			cid(kind, e["id"]) + (" = 0" if i == 0 else "")
			for i, e in enumerate(lst)))
	if db.get("flags"):
		h.append("enum { %s };" % ", ".join(
			cid("FLAG", fl) + (" = 0" if i == 0 else "")
			for i, fl in enumerate(db["flags"])))
	h += ["",
	      "extern const EnemyDef  enemyDefs[N_ENEMIES];",
	      "extern const TroopDef  troopDefs[N_TROOPS];",
	      "extern const ItemDef   itemDefs[N_ITEMS];",
	      "extern const PlayerDef playerDefs[PARTY_SIZE];",
	      "extern const SpellDef  spellDefs[];",
	      "extern const BossDef   bossDefs[];",
	      "extern const int expNeed[MAX_LEVEL + 1];",
	      "extern const unsigned char startItems[N_ITEMS];",
	      "extern const int titleMusic;   /* MOD_ id; -1 = silence */",
	      "extern const int battleMusic;  /* MOD_ id; -1 = keep map track */",
	      "extern const int victoryMusic; /* MOD_ id; -1 = no fanfare */",
	      "", "#endif", ""]

	c = ["/* Generated by tools/gen_db.py -- do not edit by hand. */",
	     '#include "db_data.h"',
	     '#include "soundbank.h"', ""]
	for e in enemies:
		c.append("extern const unsigned short enemyGfx_%s[];" % e["id"])
	c += ["", "const EnemyDef enemyDefs[N_ENEMIES] = {"]
	for e in enemies:
		c.append("\t{ %s, enemyGfx_%s, %d, %d, %d, %d, %d, %d }," %
		         (cstr(e["name"]), e["id"], e["hp"], e["atk"], e["def"],
		          e["agi"], e["exp"], e["gold"]))
	c += ["};", "", "const TroopDef troopDefs[N_TROOPS] = {"]
	for t in troops:
		members = [str(e_index[m]) for m in t["members"]]
		members += ["0"] * (MAX_TROOP - len(members))
		c.append("\t{ %s, %d, { %s } }," %
		         (cstr(t["name"]), len(t["members"]), ", ".join(members)))
	c += ["};", "", "const ItemDef itemDefs[N_ITEMS] = {"]
	for it in items:
		c.append("\t{ %s, %d, %d }," %
		         (cstr(it["name"]), it["heal"], it.get("price", 0)))
	c += ["};", ""]
	spells = db.get("spells", [])
	s_index = {sp["id"]: i for i, sp in enumerate(spells)}
	c.append("const SpellDef spellDefs[%d] = {" % max(1, len(spells)))
	for sp in spells:
		c.append("\t{ %s, %d, %d, SPELL_%s, %d, %s }," %
		         (cstr(sp["name"]), sp["cost"], sp["level"],
		          sp["effect"].upper(), sp["power"],
		          "true" if sp.get("all") else "false"))
	if not spells:
		c.append("\t{ 0, 0, 0, 0, 0, false },")
	c += ["};", ""]
	bosses = db.get("bosses", [])
	t_index = {t["id"]: i for i, t in enumerate(troops)}
	for b in bosses:
		c.append("extern const unsigned short bossGfx_%s[];" % b["id"])
	c.append("const BossDef bossDefs[%d] = {" % max(1, len(bosses)))
	for b in bosses:
		bmus = music_define(b["music"]) if b.get("music") else "-1"
		c.append("\t{ bossGfx_%s, TROOP_%s, %s }," %
		         (b["id"], b["troop"].upper(), bmus))
	if not bosses:
		c.append("\t{ 0, 0, -1 },")
	c += ["};", "", "const PlayerDef playerDefs[PARTY_SIZE] = {"]
	for p in players:
		pspells = p.get("spells", [])
		slist = ", ".join(str(s_index[s]) for s in pspells) \
		        if pspells else "0"
		c.append("\t{ %s, %d, %d, %d, %d, %d, %d, %d, %d, %d, %d,"
		         " %d, { %s } }," %
		         (cstr(p["name"]), p["hp"], p["mp"], p["atk"], p["def"],
		          p["agi"], p["ghp"], p["gmp"], p["gatk"], p["gdef"],
		          p["gagi"], len(pspells), slist))
	c += ["};", "",
	      "const int expNeed[MAX_LEVEL + 1] = { %s };" %
	      ", ".join(str(v) for v in db["exp_curve"]), ""]
	start = [0] * len(items)
	for item_id, n in project.get("start_items", {}).items():
		start[i_index[item_id]] = n
	c += ["const unsigned char startItems[N_ITEMS] = { %s };" %
	      ", ".join(str(v) for v in start), ""]
	for key, var in (("title_music", "titleMusic"),
	                 ("battle_music", "battleMusic"),
	                 ("victory_music", "victoryMusic")):
		mus = project.get(key)
		c.append("const int %s = %s;" %
		         (var, music_define(mus) if mus else "-1"))
	c.append("")

	with open(os.path.join(root, "include", "db_data.h"), "w") as f:
		f.write("\n".join(h))
	with open(os.path.join(root, "source", "db_data.c"), "w") as f:
		f.write("\n".join(c))
	return ("%d enemies, %d troops, %d items, %d players"
	        % (len(enemies), len(troops), len(items), len(players)))


def main():
	db = json.load(open(os.path.join(ROOT, "data", "database.json")))
	project = json.load(open(os.path.join(ROOT, "data", "project.json")))
	print("gen_db:", generate(db, project))


if __name__ == "__main__":
	main()
