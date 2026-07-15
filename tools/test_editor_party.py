#!/usr/bin/env python3
"""Headless editor test for the party overhaul (Players tab, NPC
recruiting, start party, rename/delete guards). Run from the project
root under a virtual display:
	xvfb-run -a python3 tools/test_editor_party.py
Requires the fixture data (healer/sage players, the join/leave events
on MAP_TOWN_EAST and its recruiter NPC)."""
import copy
import json
import re
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import tkinter as tk
from tkinter import messagebox

tk.Tk.mainloop = lambda self, n=0: None          # never block

errors, warnings = [], []
messagebox.showerror = lambda t, m, **k: errors.append(m)
messagebox.showinfo = lambda t, m, **k: None
messagebox.showwarning = lambda t, m, **k: warnings.append(m)
messagebox.askyesno = lambda t, m, **k: False

import map_editor
import gen_db

fails = 0
def ok(cond, what):
	global fails
	if not cond:
		fails += 1
		print("FAIL:", what)

ed = map_editor.Editor()
players = ed.db["players"]
pid_of = lambda i: players[i]["id"]
idx_of = lambda pid: next(i for i, p in enumerate(players)
                          if p["id"] == pid)
tei = next(i for i, m in enumerate(ed.maps["maps"])
           if m["cid"] == "MAP_TOWN_EAST")
te = ed.maps["maps"][tei]

# 0. fixture sanity + clean validation
ok(any(p["id"] == "healer" for p in players), "fixture healer present")
ok(any(n.get("joins") == "healer" for n in te.get("npcs", [])),
   "fixture recruiter present")
ok(ed.validate_all(), "validate_all passes on fixture: %s" % errors)

# 1. add players up to the roster cap, then refuse
snap_players = copy.deepcopy(players)
while len(players) < gen_db.MAX_PLAYERS:
	before = len(players)
	ed.p_add()
	ok(len(players) == before + 1, "p_add grew the roster")
errors.clear()
ed.p_add()
ok(len(players) == gen_db.MAX_PLAYERS and errors,
   "7th character refused: %r" % errors)

# 2. class preset stages stats + effect-matched spells
new_i = gen_db.MAX_PLAYERS - 1
ed.p_refresh(new_i)
ed.p_lb.selection_set(new_i)
ed.p_select()
ed.p_class.set("mage")
ed.p_preset()
ed.p_apply()
p = players[new_i]
t = map_editor.Editor.CLASS_PRESETS["mage"]
ok((p["hp"], p["mp"], p["atk"]) == (t[0], t[1], t[2]),
   "preset stats applied: %r" % [(p["hp"], p["mp"], p["atk"])])
fire_spells = [sp["id"] for sp in ed.db.get("spells", [])
               if sp.get("effect") == "fire"]
ok(set(p["spells"]) == set(fire_spells[:gen_db.MAX_SPELLS]),
   "preset picked fire spells: %r" % p["spells"])
ok(p["class"] == "mage", "class label stored")

# 3. long names refused
ed.p_name.set("X" * (gen_db.MAX_PLAYER_NAME + 1))
errors.clear()
ed.p_apply()
ok(errors, "over-long name refused")
ed.p_select()                                    # reload clean values

# 4. player rename propagates: scripts + NPC joins + start_party
snap_events = copy.deepcopy(te["events"])
snap_npcs = copy.deepcopy(te["npcs"])
snap_party = list(ed.project["start_party"])
hi = idx_of("healer")
ed.p_refresh(hi)
ed.p_lb.selection_set(hi)
ed.p_select()
ed.p_id.set("r_healer")
ed.p_apply()
ok(players[hi]["id"] == "r_healer", "player renamed in db")
ok(any("join r_healer" in ev.get("script", "")
       for ev in te["events"]), "script join line rewritten")
ok(any(n.get("joins") == "r_healer" for n in te["npcs"]),
   "NPC joins rewritten")
ok(not re.search(r"\bjoin healer\b",
                 json.dumps(te["events"])), "no stale join lines")
ok(any('say "After join."' in ev.get("script", "")
       for ev in te["events"]),
   "string literals untouched by rename")
# mage is in start_party: renaming it must rewrite the lineup
mi = idx_of("mage")
ed.p_refresh(mi)
ed.p_lb.selection_set(mi)
ed.p_select()
ed.p_id.set("r_mage")
ed.p_apply()
ok("r_mage" in ed.project["start_party"]
   and "mage" not in ed.project["start_party"],
   "start_party rewritten: %r" % ed.project["start_party"])
ok(any("leave r_mage" in ev.get("script", "") for ev in te["events"]),
   "leave line rewritten")
ok(ed.validate_all(), "still valid after renames")

# 5. delete guards: start party membership + references
errors.clear()
ed.p_refresh(idx_of("hero"))
ed.p_lb.selection_set(idx_of("hero"))
ed.p_delete()
ok(any(p["id"] == "hero" for p in players) and errors
   and "start party" in errors[-1],
   "start-party member protected: %r" % errors)
errors.clear()
ed.p_refresh(idx_of("r_healer"))
ed.p_lb.selection_set(idx_of("r_healer"))
ed.p_delete()
ok(any(p["id"] == "r_healer" for p in players) and errors,
   "recruited/scripted player protected: %r" % errors)

# 6. unknown NPC joins fails validation
te["npcs"][-1]["joins"] = "nobody"
errors.clear()
ok(not ed.validate_all(), "unknown joins rejected")
ok(errors and "nobody" in errors[0], "error names it: %r" % errors)
te["npcs"] = copy.deepcopy(snap_npcs)
te["npcs"][-1]["joins"] = "r_healer"             # match rename

# 7. leave-the-sole-member warning (non-fatal)
old_party = list(ed.project["start_party"])
ed.project["start_party"] = ["hero"]
te["events"].append({"trigger": {"kind": "on_tile", "x": 2, "y": 2},
                     "script": "leave hero"})
warnings.clear()
ok(ed.validate_all(), "warning is non-fatal")
ok(warnings and "IGNORED at runtime" in warnings[0],
   "could-empty-party warning fired: %r" % warnings)
te["events"].pop()
ed.project["start_party"] = old_party

# 8. start-party widgets exist and apply
ok(len(ed.pr_party) == gen_db.PARTY_MAX, "3 lineup slots in UI")
ed.pr_party[2].set("r_healer")
ed.apply_project()
ok(ed.project["start_party"][-1] == "r_healer",
   "3rd member applied: %r" % ed.project["start_party"])

if fails == 0:
	print("all editor party tests passed")
sys.exit(1 if fails else 0)
