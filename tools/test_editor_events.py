#!/usr/bin/env python3
"""Headless editor test for the Events feature. Run from the project
root under a virtual display:
	xvfb-run -a python3 tools/test_editor_events.py
Requires the fixture data (events present on MAP_TOWN_WEST)."""
import copy
import json
import re
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import tkinter as tk
from tkinter import messagebox

tk.Tk.mainloop = lambda self, n=0: None          # never block

errors, infos = [], []
messagebox.showerror = lambda t, m, **k: errors.append(m)
messagebox.showinfo = lambda t, m, **k: infos.append(m)
messagebox.showwarning = lambda t, m, **k: infos.append(m)
messagebox.askyesno = lambda t, m, **k: False

import map_editor
import script_lang

fails = 0
def ok(cond, what):
	global fails
	if not cond:
		fails += 1
		print("FAIL:", what)

ed = map_editor.Editor()
twi = next(i for i, m in enumerate(ed.maps["maps"])
           if m["cid"] == "MAP_TOWN_WEST")
tw = ed.maps["maps"][twi]
ok(len(tw.get("events", [])) == 5, "fixture events loaded")

# 1. clean data validates (incl. scripts)
ok(ed.validate_all(), "validate_all passes on fixture: %s" % errors)

# 2. a broken script fails validation with a useful message
snap = copy.deepcopy(tw["events"])
tw["events"][0]["script"] = 'sing "la la la"'
errors.clear()
ok(not ed.validate_all(), "broken script rejected")
ok(errors and "unknown command" in errors[0],
   "error names the problem: %r" % errors)
tw["events"] = copy.deepcopy(snap)

# 3. event labels render
lbl = ed.ev_label(1, tw["events"][1])
ok("on_tile (3,1)" in lbl and "battle" in lbl,
   "event label: %r" % lbl)

# 4. flag rename propagates into triggers AND script text
# (derive names from the data so the test is rerunnable)
oldfl = tw["events"][3]["trigger"]["flag"]
newfl = "r_" + oldfl
i = ed.db["flags"].index(oldfl)
ed.fl_refresh(i)
ed.fl_lb.selection_set(i)
ed.fl_id.set(newfl)
ed.fl_apply()
ok(newfl in ed.db["flags"], "flag renamed in db")
ok(tw["events"][3]["trigger"]["flag"] == newfl,
   "trigger flag rewritten")
ok("if " + newfl in tw["events"][0]["script"],
   "script if-line rewritten")
ok(not re.search(r"\b%s\b" % oldfl, json.dumps(tw["events"])),
   "no stale flag name anywhere in events")
ok('say "You\'ll need a weapon first."' in tw["events"][0]["script"],
   "string literals untouched by rename")
ok(ed.validate_all(), "still valid after rename")

# 5. flag delete guard sees script/trigger usage
refs = ed.fl_refs(newfl)
ok("MAP_TOWN_WEST" in refs, "fl_refs sees event usage: %r" % refs)

# 6. map delete guard sees script warp target
ed.select_map(next(i for i, m in enumerate(ed.maps["maps"])
                   if m["cid"] == "MAP_OVERWORLD"))
errors.clear()
ed.map_delete()
ok(errors and "event" in errors[0],
   "map delete blocked by script warp: %r" % errors)

# 7. troop rename propagates into battle lines
oldtr = tw["events"][1]["script"].split()[1]
newtr = "r_" + oldtr
ti = next(i for i, t in enumerate(ed.db["troops"])
          if t["id"] == oldtr)
ed.t_refresh(ti)
ed.t_lb.selection_set(ti)
ed.t_id.set(newtr)
ed.t_apply()
ok("battle " + newtr in tw["events"][1]["script"],
   "troop rename rewrote battle line")
ok(ed.validate_all(), "still valid after troop rename")

# 8. save round-trips events
ed.save_all()
saved = json.load(open(os.path.join(map_editor.ROOT, "data",
                                    "maps.json")))
stw = next(m for m in saved["maps"] if m["cid"] == "MAP_TOWN_WEST")
ok(len(stw["events"]) == 5, "events saved")
ok(stw["events"][0]["script"].startswith('say "A traveler?'),
   "script text round-tripped")

if fails == 0:
	print("all editor event tests passed")
sys.exit(1 if fails else 0)
