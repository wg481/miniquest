#!/usr/bin/env python3
"""
map_editor.py -- the Miniquest Engine editor.

	python tools\\map_editor.py

Three tabs:
  Maps     -- paint tiles and encounter zones, place NPCs/warps/signs/
              chests (NPCs can be healers or shopkeepers and can set or
              react to flags; warps can be flag-gated), set start/death
              points, pick an encounter set per zone.
  Database -- enemies (with sprite import), troops, encounter sets,
              items (with shop prices), flags, players.
  Project  -- game name, title image, starting items.

Old inline per-zone encounter tables migrate to database encounter
sets automatically on load (see tools/migrate_encounters.py).

Save writes data/*.json (validated first). Build additionally runs the
generators (gen_db -> png2ds -> gen_scripts -> gen_maps) and make via the MSYS2 bash
configured in data/editor_config.json; set "copy_to" there to auto-copy
the .nds to your SD card, "emulator" to auto-launch one.

Requires Python 3.8+ with tkinter and Pillow.
"""

import json
import os
import queue
import re
import shutil
import subprocess
import sys
import threading
import tkinter as tk
from tkinter import ttk, messagebox, simpledialog, filedialog

from PIL import Image, ImageTk

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import gen_maps
import gen_db
import gen_scripts
import script_lang
import migrate_encounters
import migrate_tilesets
import migrate_party

ROOT = gen_maps.ROOT
ZOOM = 2
CELL = 16 * ZOOM

N_TILES = gen_maps.TILESET_TILES     # 24 tiles per tileset

ENT_COLORS = {"npc": "#00e0ff", "warp": "#ffe000", "sign": "#ff8000",
              "chest": "#e8c040",
              "start": "#00ff60", "death": "#ff4060",
              "event": "#d040ff"}
ZONE_COLORS = ["#ff4040", "#40a0ff", "#40ff70", "#ffe040",
               "#c060ff", "#ff9040", "#40ffe0", "#ff60c0"]

DEFAULT_CONFIG = {
	"bash": "C:/devkitPro/msys2/usr/bin/bash.exe",
	"emulator": "",
	"copy_to": "",
}


def win_to_msys(path):
	path = os.path.abspath(path).replace("\\", "/")
	if len(path) > 1 and path[1] == ":":
		return "/" + path[0].lower() + path[2:]
	return path


def jload(name):
	return json.load(open(os.path.join(ROOT, "data", name)))


def jsave(name, data):
	json.dump(data, open(os.path.join(ROOT, "data", name), "w"), indent=1)


class Editor:
	def __init__(self):
		self.root = tk.Tk()
		self.root.title("Miniquest Engine")

		self.maps = jload("maps.json")
		self.db = jload("database.json")
		self.project = jload("project.json")
		self.migrated = migrate_encounters.migrate(self.maps, self.db)
		self.migrated |= migrate_tilesets.migrate(self.maps, ROOT)
		self.migrated |= migrate_party.migrate(self.db, self.project)
		self.tilesets = jload("tilesets.json")
		self.config = dict(DEFAULT_CONFIG)
		cfg = os.path.join(ROOT, "data", "editor_config.json")
		if os.path.exists(cfg):
			self.config.update(json.load(open(cfg)))
		else:
			json.dump(self.config, open(cfg, "w"), indent=1)

		self.cur = 0
		self.cur_ts = 0                 # Tilesets tab selection
		self.tool = tk.StringVar(value="t0")
		self.show_zones = tk.BooleanVar(value=True)

		self.load_tiles()

		bar = ttk.Frame(self.root)
		bar.pack(side="top", fill="x", padx=4, pady=2)
		ttk.Button(bar, text="Save", command=self.save_all) \
		   .pack(side="right", padx=2)
		ttk.Button(bar, text="Build", command=self.build) \
		   .pack(side="right", padx=2)
		self.status = ttk.Label(self.root, text="", anchor="w")
		self.status.pack(side="bottom", fill="x")

		self.nb = ttk.Notebook(self.root)
		self.nb.pack(fill="both", expand=True)
		self.build_maps_tab()
		self.build_tilesets_tab()
		self.build_db_tab()
		self.build_project_tab()

		self.select_map(0)
		if self.migrated:
			self.say("Migrated data to the current format "
			         "(written on next Save)")
		self.root.mainloop()

	# ================= shared =================

	def say(self, text):
		self.status.config(text=text)

	def validate_all(self):
		try:
			gen_db.validate(self.db, self.project)
			self.sync_zone_layers()
			self.sync_chests()
			gen_maps.validate(self.maps, self.tilesets)
			gen_scripts.validate(self.maps, self.db)
			encs = {s["id"] for s in self.db.get("encounters", [])}
			prices = {it["id"]: it.get("price", 0)
			          for it in self.db["items"]}
			items = set(prices)
			flags = set(self.db.get("flags", []))

			def ckflag(cid, fl, what):
				if fl and fl not in flags:
					raise SystemExit("%s: %s: unknown flag %r"
					                 % (cid, what, fl))
			for m in self.maps["maps"]:
				for z, ref in (m.get("zones") or {}).items():
					if ref not in encs:
						raise SystemExit(
							"%s zone %s: unknown encounter set %r"
							% (m["cid"], z, ref))
				for np in m.get("npcs", []):
					for s in (np.get("shop") or []):
						if prices.get(s, 0) <= 0:
							raise SystemExit(
								"%s: shop item %r missing or "
								"has no price" % (m["cid"], s))
					ckflag(m["cid"], np.get("sets_flag"), "NPC sets flag")
					ckflag(m["cid"], (np.get("alt") or {}).get("flag"),
					       "NPC alt dialog")
				bosses = {b["id"] for b in self.db.get("bosses", [])}
				nstems = set(self.npc_sprite_stems())
				players = {p["id"] for p in self.db["players"]}
				for np in m.get("npcs", []):
					if np.get("boss") and np["boss"] not in bosses:
						raise SystemExit("%s: unknown boss %r"
						                 % (m["cid"], np["boss"]))
					if np.get("sprite") and np["sprite"] not in nstems:
						raise SystemExit(
							"%s: NPC sprite %r not found in gfx/npcs/"
							% (m["cid"], np["sprite"]))
					if np.get("joins") and np["joins"] not in players:
						raise SystemExit("%s: unknown player %r"
						                 % (m["cid"], np["joins"]))
					ckflag(m["cid"], np.get("hidden_when"),
					       "NPC hidden_when")
				for w in m.get("warps", []):
					ckflag(m["cid"], w.get("flag"), "warp gate")
				for ch in m.get("chests", []):
					if ch["item"] not in items:
						raise SystemExit("%s: chest item %r missing"
						                 % (m["cid"], ch["item"]))
					ckflag(m["cid"], ch.get("flag"), "chest")
		except SystemExit as e:
			messagebox.showerror("Validation", str(e))
			return False
		self.warn_leave_empty()
		return True

	def warn_leave_empty(self):
		"""Non-fatal: a script that leaves the sole starting member
		could try to empty the party (the engine ignores it at
		runtime, so the cutscene silently misbehaves instead)."""
		start = self.project.get("start_party") or []
		if len(start) != 1:
			return
		sole = start[0]
		hits = [m["cid"] for m in self.maps["maps"]
		        if any(script_lang.uses_leave(ev.get("script", ""),
		                                      sole)
		               for ev in m.get("events", []))]
		if hits:
			messagebox.showwarning("Scripts",
				"A script leaves %r, the only starting member.\n"
				"Leaving the last member is IGNORED at runtime --\n"
				"make sure someone joins first.\nMaps: %s"
				% (sole, ", ".join(hits)))

	def save_all(self):
		self.apply_project()
		if not self.validate_all():
			return False
		jsave("maps.json", self.maps)
		jsave("database.json", self.db)
		jsave("project.json", self.project)
		jsave("tilesets.json", self.tilesets)
		self.say("Saved data/*.json")
		return True

	def sync_zone_layers(self):
		"""Prune stale zone tables; drop empty zone layers."""
		for m in self.maps["maps"]:
			zr = m.get("zone_rows")
			if not zr:
				m["zone_rows"] = None
				m["zones"] = {}
				continue
			used = set("".join(zr)) - {"."}
			if not used:
				m["zone_rows"] = None
				m["zones"] = {}
			else:
				m["zones"] = {z: t for z, t in
				              (m.get("zones") or {}).items() if z in used}

	def sync_chests(self):
		"""Drop chest entities whose tile was painted over (or whose
		tileset no longer matches)."""
		for m in self.maps["maps"]:
			ctile = self.ts_of(m).get("chest_tile")
			m["chests"] = [ch for ch in m.get("chests", [])
			               if ctile is not None and
			               m["rows"][ch["y"]][ch["x"]] == ctile]

	def build(self):
		if not self.save_all():
			return
		out = tk.Toplevel(self.root)
		out.title("Build")
		text = tk.Text(out, width=100, height=30, bg="#101018",
		               fg="#d0d0d0", font=("Consolas", 9))
		text.pack(fill="both", expand=True)
		q = queue.Queue()

		def run():
			steps = [[sys.executable, os.path.join(ROOT, "tools", s)]
			         for s in ("gen_db.py", "png2ds.py",
			                   "gen_scripts.py", "gen_maps.py")]
			bash = self.config["bash"]
			if os.path.exists(bash):
				steps.append([bash, "-lc",
				              "cd '%s' && make" % win_to_msys(ROOT)])
			else:
				q.put("NOTE: MSYS2 bash not found at %s -- generated C "
				      "only, no make.\n" % bash)
			code = 0
			for cmd in steps:
				q.put("$ %s\n" % " ".join(os.path.basename(c) if i == 0
				      else c for i, c in enumerate(cmd)))
				p = subprocess.Popen(cmd, stdout=subprocess.PIPE,
				                     stderr=subprocess.STDOUT, text=True,
				                     cwd=ROOT)
				for line in p.stdout:
					q.put(line)
				p.wait()
				if p.returncode != 0:
					code = p.returncode
					break
			q.put("\n[exit code %d]\n" % code)
			if code == 0 and self.config.get("copy_to"):
				dest = self.config["copy_to"]
				nds = os.path.join(ROOT, "miniquest.nds")
				if os.path.isdir(dest) and os.path.exists(nds):
					shutil.copy(nds, dest)
					q.put("copied miniquest.nds -> %s\n" % dest)
				else:
					q.put("copy_to skipped (path or .nds missing)\n")
			if code == 0 and self.config.get("emulator"):
				subprocess.Popen([self.config["emulator"],
				                  os.path.join(ROOT, "miniquest.nds")])
			q.put(None)

		def poll():
			try:
				while True:
					line = q.get_nowait()
					if line is None:
						return
					text.insert("end", line)
					text.see("end")
			except queue.Empty:
				pass
			out.after(100, poll)

		threading.Thread(target=run, daemon=True).start()
		poll()

	# ================= Maps tab =================

	def ts_list(self):
		return self.tilesets["tilesets"]

	def ts_by_id(self, tid):
		for ts in self.ts_list():
			if ts["id"] == tid:
				return ts
		return self.ts_list()[0]

	def ts_of(self, m):
		"""The tileset dict a map paints with."""
		return self.ts_by_id(m.get("tileset") or "default")

	def tile_name(self, ts, i):
		name = (ts["tiles"][i].get("name") or "").strip()
		return name or ("Tile %d" % i)

	def ts_sheet(self, ts):
		"""Tileset PNG with roof_composite pairs baked, like
		png2ds does at Build time (so slots 15/16-style bake targets
		preview correctly)."""
		sheet = Image.open(os.path.join(ROOT, ts["image"])) \
		             .convert("RGBA")

		def box(i):
			return ((i % 8) * 16, (i // 8) * 16)

		def opaque_mask(img):
			mask = img.split()[3].point(
				lambda a: 255 if a >= 128 else 0)
			px, mp = img.load(), mask.load()
			for y in range(16):
				for x in range(16):
					r, g, b, a = px[x, y]
					if r > 240 and g < 30 and b > 240:
						mp[x, y] = 0
			return mask

		bx, by = box(ts.get("roof_base", 0))
		base = sheet.crop((bx, by, bx + 16, by + 16))
		for s, dest in ts.get("roof_composite", []):
			sx, sy = box(s)
			st = sheet.crop((sx, sy, sx + 16, sy + 16))
			merged = base.copy()
			merged.paste(st, (0, 0), opaque_mask(st))
			sheet.paste(merged, box(dest))
		return sheet

	def load_tiles(self, tid=None):
		"""(Re)build the per-tileset CELL-size tile images used by
		the map canvas and palette. tid=None rebuilds everything."""
		if not hasattr(self, "ts_imgs"):
			self.ts_imgs = {}
		dark = Image.new("RGBA", (16, 16), (20, 20, 28, 255))
		for ts in self.ts_list():
			if tid is not None and ts["id"] != tid:
				continue
			sheet = self.ts_sheet(ts)
			imgs = []
			for i in range(N_TILES):
				x, y = (i % 8) * 16, (i // 8) * 16
				tile = sheet.crop((x, y, x + 16, y + 16))
				out = dark.copy()
				mask = tile.split()[3].point(
					lambda a: 255 if a >= 128 else 0)
				px, mp = tile.load(), mask.load()
				for yy in range(16):
					for xx in range(16):
						r, g, b, a = px[xx, yy]
						if r > 240 and g < 30 and b > 240:
							mp[xx, yy] = 0
				out.paste(tile, (0, 0), mask)
				imgs.append(ImageTk.PhotoImage(
					out.resize((CELL, CELL), Image.NEAREST)))
			self.ts_imgs[ts["id"]] = imgs
		# drop images of deleted tilesets
		live = {ts["id"] for ts in self.ts_list()}
		for k in list(self.ts_imgs):
			if k not in live:
				del self.ts_imgs[k]

	def build_maps_tab(self):
		tab = ttk.Frame(self.nb)
		self.nb.add(tab, text="Maps")

		top = ttk.Frame(tab)
		top.pack(side="top", fill="x", padx=4, pady=4)
		self.map_var = tk.StringVar()
		self.map_combo = ttk.Combobox(top, textvariable=self.map_var,
		                              state="readonly", width=24)
		self.map_combo.pack(side="left")
		self.map_combo.bind("<<ComboboxSelected>>",
		                    lambda e: self.select_map(self.map_combo.current()))
		for label, cmd in [("New", self.map_new), ("Rename", self.map_rename),
		                   ("Resize", self.map_resize),
		                   ("Delete", self.map_delete),
		                   ("Encounter Sets", self.zone_tables),
		                   ("Events", self.map_events)]:
			ttk.Button(top, text=label, command=cmd).pack(side="left", padx=2)
		ttk.Checkbutton(top, text="Show zones", variable=self.show_zones,
		                command=self.redraw_zones).pack(side="left", padx=8)
		ttk.Label(top, text="Tileset:").pack(side="left", padx=(10, 2))
		self.tileset_var = tk.StringVar()
		self.tileset_combo = ttk.Combobox(
			top, textvariable=self.tileset_var, state="readonly",
			width=12)
		self.tileset_combo.pack(side="left")
		self.tileset_combo.bind("<<ComboboxSelected>>",
		                        self.set_map_tileset)
		ttk.Label(top, text="Music:").pack(side="left", padx=(10, 2))
		self.music_var = tk.StringVar()
		self.music_combo = ttk.Combobox(top, textvariable=self.music_var,
		                                state="readonly", width=14)
		self.music_combo.pack(side="left")
		self.music_combo.bind("<<ComboboxSelected>>", self.set_music)
		ttk.Button(top, text="Import music...",
		           command=self.import_music).pack(side="left", padx=2)
		ttk.Label(top, text="Backdrop:").pack(side="left", padx=(10, 2))
		self.backdrop_var = tk.StringVar()
		self.backdrop_combo = ttk.Combobox(
			top, textvariable=self.backdrop_var, state="readonly",
			width=14)
		self.backdrop_combo.pack(side="left")
		self.backdrop_combo.bind("<<ComboboxSelected>>",
		                         self.set_backdrop)
		ttk.Button(top, text="Import backdrop...",
		           command=self.import_backdrop).pack(side="left",
		                                              padx=2)

		side = ttk.Frame(tab)
		side.pack(side="left", fill="y", padx=4, pady=4)
		ttk.Label(side, text="Tiles").pack(anchor="w")
		self.pal_frame = ttk.Frame(side)
		self.pal_frame.pack(anchor="w")
		self.refresh_palette()

		ttk.Label(side, text="Zones").pack(anchor="w", pady=(8, 0))
		zf = ttk.Frame(side)
		zf.pack(anchor="w")
		for z in range(8):
			tk.Radiobutton(zf, text=str(z), variable=self.tool,
			               value="z%d" % z, indicatoron=False, width=3,
			               fg=ZONE_COLORS[z]).grid(row=z // 4, column=z % 4,
			                                       padx=1, pady=1)
		tk.Radiobutton(side, text="Zone erase", variable=self.tool,
		               value="z.", indicatoron=False, width=14) \
		  .pack(anchor="w", pady=1)

		ttk.Label(side, text="Place").pack(anchor="w", pady=(8, 0))
		for mode, label in [("npc", "NPC"), ("warp", "Warp"),
		                    ("sign", "Sign text"), ("chest", "Chest"),
		                    ("start", "Start point"),
		                    ("death", "Death respawn")]:
			tk.Radiobutton(side, text=label, variable=self.tool, value=mode,
			               indicatoron=False, width=14,
			               fg=ENT_COLORS[mode]).pack(anchor="w", pady=1)

		wrap = ttk.Frame(tab)
		wrap.pack(side="left", fill="both", expand=True)
		self.canvas = tk.Canvas(wrap, bg="#101018",
		                        width=32 * CELL + 2, height=18 * CELL + 2)
		hbar = ttk.Scrollbar(wrap, orient="horizontal",
		                     command=self.canvas.xview)
		vbar = ttk.Scrollbar(wrap, orient="vertical",
		                     command=self.canvas.yview)
		self.canvas.configure(xscrollcommand=hbar.set,
		                      yscrollcommand=vbar.set)
		self.canvas.grid(row=0, column=0, sticky="nsew")
		vbar.grid(row=0, column=1, sticky="ns")
		hbar.grid(row=1, column=0, sticky="ew")
		wrap.rowconfigure(0, weight=1)
		wrap.columnconfigure(0, weight=1)

		self.canvas.bind("<Button-1>", self.on_click)
		self.canvas.bind("<B1-Motion>", self.on_drag)
		self.canvas.bind("<Button-3>", self.on_pick)
		self.canvas.bind("<Motion>", self.on_hover)

	def refresh_palette(self):
		"""Rebuild the tile palette for the current map's tileset.
		The chest tile is excluded -- the Chest tool paints it."""
		for w in self.pal_frame.winfo_children():
			w.destroy()
		ts = self.ts_of(self.m())
		imgs = self.ts_imgs[ts["id"]]
		ctile = ts.get("chest_tile")
		solid = [t.get("solid") for t in ts["tiles"]]
		r = 0
		for i in range(N_TILES):
			if i == ctile:
				continue
			b = tk.Radiobutton(self.pal_frame, image=imgs[i],
			                   variable=self.tool, value="t%d" % i,
			                   indicatoron=False, width=CELL + 4,
			                   height=CELL + 4)
			b.grid(row=r // 3, column=r % 3, padx=1, pady=1)
			self.bind_tip(b, "%d: %s%s" % (i, self.tile_name(ts, i),
			              " (solid)" if solid[i] else ""))
			r += 1
		if ctile is not None and self.tool.get() == "t%d" % ctile:
			self.tool.set("t0")

	def bind_tip(self, widget, text):
		widget.bind("<Enter>", lambda e: self.say(text))
		widget.bind("<Leave>", lambda e: self.say(""))

	def m(self):
		return self.maps["maps"][self.cur]

	def refresh_combo(self):
		self.map_combo["values"] = ["%s (%s)" % (m["name"], m["cid"])
		                            for m in self.maps["maps"]]
		self.map_combo.current(self.cur)

	def music_stems(self):
		mdir = os.path.join(ROOT, "music")
		if not os.path.isdir(mdir):
			return []
		return sorted(os.path.splitext(f)[0] for f in os.listdir(mdir)
		              if f.lower().endswith((".mod", ".it", ".xm", ".s3m")))

	def refresh_music(self):
		stems = self.music_stems()
		self.music_combo["values"] = ["(none)"] + stems
		self.music_var.set(self.m().get("music") or "(none)")
		if hasattr(self, "pr_music"):
			for var, cb in self.pr_music.values():
				cb["values"] = ["(none)"] + stems
		if hasattr(self, "b_music_cb"):
			self.b_music_cb["values"] = ["(default)"] + stems

	def refresh_tileset_combo(self):
		ids = [ts["id"] for ts in self.ts_list()]
		self.tileset_combo["values"] = ids
		self.tileset_var.set(self.m().get("tileset") or ids[0])

	def set_map_tileset(self, event=None):
		m = self.m()
		new = self.tileset_var.get()
		if new == m.get("tileset"):
			return
		m["tileset"] = new
		ctile = self.ts_of(m).get("chest_tile")
		if m.get("chests") and (ctile is None or any(
				m["rows"][c["y"]][c["x"]] != ctile
				for c in m["chests"])):
			messagebox.showwarning("Tileset",
				"This map has chests; the new tileset uses a "
				"different chest tile, so they'll be dropped on "
				"Save. Re-place them with the Chest tool.")
		self.refresh_palette()
		self.redraw()
		self.say("Map now paints with tileset %s" % new)

	def set_music(self, event=None):
		v = self.music_var.get()
		self.m()["music"] = None if v == "(none)" else v

	def backdrop_stems(self):
		bdir = os.path.join(ROOT, "gfx", "backdrops")
		if not os.path.isdir(bdir):
			return []
		return sorted(os.path.splitext(f)[0] for f in os.listdir(bdir)
		              if f.lower().endswith(".png"))

	def player_sprite_stems(self):
		pdir = os.path.join(ROOT, "gfx", "players")
		if not os.path.isdir(pdir):
			return []
		return sorted(os.path.splitext(f)[0] for f in os.listdir(pdir)
		              if f.lower().endswith(".png"))

	def npc_sprite_stems(self):
		ndir = os.path.join(ROOT, "gfx", "npcs")
		if not os.path.isdir(ndir):
			return []
		return sorted(os.path.splitext(f)[0] for f in os.listdir(ndir)
		              if f.lower().endswith(".png"))

	def import_npc_sprite(self, dlg, var):
		"""Import a 16x16 NPC sprite into gfx/npcs/ and select it.
		Mirrors the boss/backdrop importers: C-identifier stem,
		exact 16x16, converted into the ROM at next Build."""
		path = filedialog.askopenfilename(
			filetypes=[("PNG images", "*.png")], parent=dlg)
		if not path:
			return
		stem = os.path.splitext(os.path.basename(path))[0]
		if not stem.isidentifier():
			messagebox.showerror("NPC sprite",
				"Filename (minus .png) must be a C identifier:\n"
				"letters, digits, underscores; no leading digit.",
				parent=dlg)
			return
		img = Image.open(path)
		if img.size != (16, 16):
			messagebox.showerror("NPC sprite",
				"NPC sprite must be exactly 16x16 (this is %dx%d)."
				% img.size, parent=dlg)
			return
		os.makedirs(os.path.join(ROOT, "gfx", "npcs"), exist_ok=True)
		shutil.copy(path, os.path.join(ROOT, "gfx", "npcs",
		                               stem + ".png"))
		var["combo"]["values"] = ["(default)"] + self.npc_sprite_stems()
		var["v"].set(stem)
		self.say("Imported NPC sprite %s (in ROM at next Build)" % stem)

	def refresh_backdrop(self):
		self.backdrop_combo["values"] = ["(none)"] + self.backdrop_stems()
		self.backdrop_var.set(self.m().get("backdrop") or "(none)")

	def set_backdrop(self, event=None):
		v = self.backdrop_var.get()
		self.m()["backdrop"] = None if v == "(none)" else v

	def import_backdrop(self):
		path = filedialog.askopenfilename(
			filetypes=[("PNG images", "*.png")])
		if not path:
			return
		stem = os.path.splitext(os.path.basename(path))[0]
		if not stem.isidentifier():
			messagebox.showerror("Backdrop",
				"Filename (minus .png) must be a C identifier:\n"
				"letters, digits, underscores; no leading digit.")
			return
		img = Image.open(path)
		if img.size != (192, 128):
			if not messagebox.askyesno("Backdrop",
					"Image is %dx%d, not 192x128 (the battle "
					"window).\nResize on import?" % img.size):
				return
			img = img.convert("RGB").resize((192, 128))
			os.makedirs(os.path.join(ROOT, "gfx", "backdrops"),
			            exist_ok=True)
			img.save(os.path.join(ROOT, "gfx", "backdrops",
			                      stem + ".png"))
		else:
			os.makedirs(os.path.join(ROOT, "gfx", "backdrops"),
			            exist_ok=True)
			shutil.copy(path, os.path.join(ROOT, "gfx", "backdrops",
			                               stem + ".png"))
		self.refresh_backdrop()
		self.say("Imported backdrop %s (converted at next Build)" % stem)

	def import_music(self):
		path = filedialog.askopenfilename(filetypes=[
			("Tracker modules", "*.it *.xm *.mod *.s3m"),
			("UI sound effects (cursor/confirm/cancel.wav)",
			 "*.wav")])
		if not path:
			return
		os.makedirs(os.path.join(ROOT, "music"), exist_ok=True)
		shutil.copy(path, os.path.join(ROOT, "music",
		                               os.path.basename(path)))
		self.refresh_music()
		self.say("Imported %s (in soundbank at next Build)"
		         % os.path.basename(path))

	def select_map(self, idx):
		self.cur = idx
		self.refresh_combo()
		self.refresh_music()
		self.refresh_backdrop()
		self.refresh_tileset_combo()
		self.refresh_palette()
		self.redraw()

	def redraw(self):
		c = self.canvas
		c.delete("all")
		m = self.m()
		imgs = self.ts_imgs[self.ts_of(m)["id"]]
		self.cell_items = {}
		for y in range(m["h"]):
			row = m["rows"][y]
			for x in range(m["w"]):
				self.cell_items[(x, y)] = c.create_image(
					x * CELL + 1, y * CELL + 1, anchor="nw",
					image=imgs[row[x]])
		for i in range(m["w"] + 1):
			c.create_line(i * CELL + 1, 1, i * CELL + 1,
			              m["h"] * CELL + 1, fill="#303040")
		for i in range(m["h"] + 1):
			c.create_line(1, i * CELL + 1, m["w"] * CELL + 1,
			              i * CELL + 1, fill="#303040")
		self.redraw_zones()
		self.redraw_entities()
		c.configure(scrollregion=(0, 0, m["w"] * CELL + 2,
		                          m["h"] * CELL + 2))

	def redraw_zones(self):
		c = self.canvas
		c.delete("zone")
		m = self.m()
		if not self.show_zones.get() or not m.get("zone_rows"):
			return
		for y, row in enumerate(m["zone_rows"]):
			for x, z in enumerate(row):
				if z == '.':
					continue
				col = ZONE_COLORS[int(z)]
				x0, y0 = x * CELL + 1, y * CELL + 1
				c.create_rectangle(x0, y0, x0 + CELL, y0 + CELL,
				                   fill=col, stipple="gray25",
				                   outline="", tags="zone")
				c.create_text(x0 + CELL - 6, y0 + 7, text=z, fill=col,
				              tags="zone",
				              font=("TkDefaultFont", 8, "bold"))

	def redraw_entities(self):
		c = self.canvas
		c.delete("ent")
		m = self.m()

		def mark(x, y, kind, letter):
			x0, y0 = x * CELL + 1, y * CELL + 1
			c.create_rectangle(x0 + 2, y0 + 2, x0 + CELL - 2,
			                   y0 + CELL - 2, outline=ENT_COLORS[kind],
			                   width=2, tags="ent")
			c.create_text(x0 + CELL // 2, y0 + CELL // 2, text=letter,
			              fill=ENT_COLORS[kind], tags="ent",
			              font=("TkDefaultFont", 10, "bold"))

		for n in m.get("npcs", []):
			mark(n["x"], n["y"], "npc", "N")
		for w in m.get("warps", []):
			mark(w["x"], w["y"], "warp", "W")
		for s in m.get("signs", []):
			mark(s["x"], s["y"], "sign", "S")
		for ch in m.get("chests", []):
			mark(ch["x"], ch["y"], "chest", "C")
		for ev in m.get("events", []):
			t = ev.get("trigger") or {}
			if t.get("kind") == "on_tile":
				mark(t["x"], t["y"], "event", "E")
		for key, letter in (("start", "P"), ("death", "D")):
			p = self.maps[key]
			if p["map"] == m["cid"]:
				mark(p["x"], p["y"], key, letter)

	def cell_at(self, event):
		x = int(self.canvas.canvasx(event.x)) // CELL
		y = int(self.canvas.canvasy(event.y)) // CELL
		m = self.m()
		if 0 <= x < m["w"] and 0 <= y < m["h"]:
			return x, y
		return None

	def paint(self, x, y, t):
		m = self.m()
		ts = self.ts_of(m)
		row = m["rows"][y]
		if row[x] != t:
			if row[x] == ts.get("chest_tile"):   # painted over a chest
				m["chests"] = [c for c in m.get("chests", [])
				               if (c["x"], c["y"]) != (x, y)]
				self.redraw_entities()
			row[x] = t
			self.canvas.itemconfig(self.cell_items[(x, y)],
			                       image=self.ts_imgs[ts["id"]][t])

	def paint_zone(self, x, y, z):
		m = self.m()
		if not m.get("zone_rows"):
			m["zone_rows"] = ["." * m["w"] for _ in range(m["h"])]
		row = m["zone_rows"][y]
		if row[x] != z:
			m["zone_rows"][y] = row[:x] + z + row[x + 1:]
			self.redraw_zones()

	def on_click(self, event):
		pos = self.cell_at(event)
		if not pos:
			return
		x, y = pos
		tool = self.tool.get()
		if tool.startswith("t"):
			self.paint(x, y, int(tool[1:]))
		elif tool.startswith("z"):
			self.paint_zone(x, y, tool[1])
		elif tool in ("start", "death"):
			self.maps[tool] = {"map": self.m()["cid"], "x": x, "y": y}
			self.redraw_entities()
		else:
			self.edit_entity(tool, x, y)

	def on_drag(self, event):
		tool = self.tool.get()
		pos = self.cell_at(event)
		if not pos:
			return
		if tool.startswith("t"):
			self.paint(*pos, int(tool[1:]))
		elif tool.startswith("z"):
			self.paint_zone(*pos, tool[1])

	def on_pick(self, event):
		pos = self.cell_at(event)
		if pos:
			t = self.m()["rows"][pos[1]][pos[0]]
			ctile = self.ts_of(self.m()).get("chest_tile")
			self.tool.set("chest" if t == ctile else "t%d" % t)

	def on_hover(self, event):
		pos = self.cell_at(event)
		if pos:
			x, y = pos
			m = self.m()
			t = m["rows"][y][x]
			z = m["zone_rows"][y][x] if m.get("zone_rows") else '.'
			zs = "  zone %s" % z if z != '.' else ""
			self.say("(%d, %d)  %s%s"
			         % (x, y, self.tile_name(self.ts_of(m), t), zs))

	def find_entity(self, kind, x, y):
		for i, e in enumerate(self.m().get(kind + "s", [])):
			if e["x"] == x and e["y"] == y:
				return i
		return -1

	def edit_entity(self, kind, x, y):
		key = kind + "s"
		lst = self.m().setdefault(key, [])
		idx = self.find_entity(kind, x, y)
		limits = {"npcs": gen_maps.MAX_NPCS, "warps": gen_maps.MAX_WARPS,
		          "signs": gen_maps.MAX_SIGNS,
		          "chests": gen_maps.MAX_CHESTS}
		if idx < 0 and len(lst) >= limits[key]:
			messagebox.showwarning("Limit",
				"This map already has %d %s (engine limit)."
				% (limits[key], key))
			return
		ent = lst[idx] if idx >= 0 else {"x": x, "y": y}
		flag_opts = ["(none)"] + self.db.get("flags", [])

		dlg = tk.Toplevel(self.root)
		dlg.title("%s at (%d, %d)" % (kind.upper(), x, y))
		dlg.grab_set()
		result = {}

		def flag_row(parent, label, current):
			f = ttk.Frame(parent)
			f.pack(anchor="w", padx=6, pady=(4, 0), fill="x")
			ttk.Label(f, text=label).pack(side="left")
			v = tk.StringVar(value=current or "(none)")
			ttk.Combobox(f, values=flag_opts, textvariable=v,
			             state="readonly", width=16) \
			   .pack(side="left", padx=4)
			return v

		if kind in ("npc", "sign"):
			ttk.Label(dlg, text="Text (max 6 lines, ~28 chars each):") \
			   .pack(anchor="w", padx=6, pady=(6, 0))
			txt = tk.Text(dlg, width=30, height=6, font=("Consolas", 10))
			txt.pack(padx=6, pady=4)
			txt.insert("1.0", ent.get("text", ""))
			healer = tk.BooleanVar(value=bool(ent.get("healer")))
			shop_lb = sf = af = alt_txt = None
			if kind == "npc":
				ttk.Checkbutton(dlg, text="Healer (restores party)",
				                variable=healer).pack(anchor="w", padx=6)
				ttk.Label(dlg, text="Shop items (max %d; each needs "
				          "a price):" % gen_maps.MAX_SHOP_ITEMS) \
				   .pack(anchor="w", padx=6, pady=(6, 0))
				item_ids = [it["id"] for it in self.db["items"]]
				shop_lb = tk.Listbox(dlg, selectmode="multiple",
				                     height=min(6, len(item_ids)),
				                     exportselection=False)
				for iid in item_ids:
					shop_lb.insert("end", iid)
				for k, iid in enumerate(item_ids):
					if iid in (ent.get("shop") or []):
						shop_lb.selection_set(k)
				shop_lb.pack(padx=6, pady=2, fill="x")
				sf = flag_row(dlg, "Sets flag on talk:",
				              ent.get("sets_flag"))
				af = flag_row(dlg, "Alt dialog if flag set:",
				              (ent.get("alt") or {}).get("flag"))
				ttk.Label(dlg, text="Alt text:").pack(anchor="w", padx=6)
				alt_txt = tk.Text(dlg, width=30, height=3,
				                  font=("Consolas", 10))
				alt_txt.pack(padx=6, pady=2)
				alt_txt.insert("1.0", (ent.get("alt") or {})
				               .get("text", ""))
				bf = ttk.Frame(dlg)
				bf.pack(anchor="w", padx=6, pady=(4, 0), fill="x")
				ttk.Label(bf, text="Boss (fight on talk):") \
				   .pack(side="left")
				bv = tk.StringVar(value=ent.get("boss") or "(none)")
				ttk.Combobox(bf, values=["(none)"] +
				             [b["id"] for b in
				              self.db.get("bosses", [])],
				             textvariable=bv, state="readonly",
				             width=14).pack(side="left", padx=4)

				jf = ttk.Frame(dlg)
				jf.pack(anchor="w", padx=6, pady=(4, 0), fill="x")
				ttk.Label(jf, text="Joins party (on talk):") \
				   .pack(side="left")
				jv = tk.StringVar(value=ent.get("joins") or "(none)")
				ttk.Combobox(jf, values=["(none)"] +
				             [pl["id"] for pl in self.db["players"]],
				             textvariable=jv, state="readonly",
				             width=12).pack(side="left", padx=4)
				hf = flag_row(dlg, "Hidden when flag set:",
				              ent.get("hidden_when"))

				spf = ttk.Frame(dlg)
				spf.pack(anchor="w", padx=6, pady=(4, 0), fill="x")
				ttk.Label(spf, text="Sprite (16x16):").pack(side="left")
				spv = tk.StringVar(value=ent.get("sprite")
				                   or "(default)")
				sp_combo = ttk.Combobox(
					spf, values=["(default)"] + self.npc_sprite_stems(),
					textvariable=spv, state="readonly", width=12)
				sp_combo.pack(side="left", padx=4)
				sp_ref = {"v": spv, "combo": sp_combo}
				ttk.Button(spf, text="Import...",
				           command=lambda: self.import_npc_sprite(
					           dlg, sp_ref)).pack(side="left", padx=2)

			def ok():
				if kind == "npc":
					sel = [shop_lb.get(k)
					       for k in shop_lb.curselection()]
					if len(sel) > gen_maps.MAX_SHOP_ITEMS:
						messagebox.showerror("NPC",
							"Max %d shop items."
							% gen_maps.MAX_SHOP_ITEMS, parent=dlg)
						return
					if sel and healer.get():
						messagebox.showerror("NPC",
							"An NPC can't be both healer "
							"and shopkeeper.", parent=dlg)
						return
					prices = {it["id"]: it.get("price", 0)
					          for it in self.db["items"]}
					bad = [s for s in sel if prices.get(s, 0) <= 0]
					if bad:
						messagebox.showerror("NPC",
							"No price set for: %s\n(Database > "
							"Items)" % ", ".join(bad), parent=dlg)
						return
					setf = None if sf.get() == "(none)" else sf.get()
					altf = None if af.get() == "(none)" else af.get()
					atext = alt_txt.get("1.0", "end-1c").strip()
					if sel and (setf or altf):
						messagebox.showerror("NPC",
							"Shopkeepers can't have flag dialog "
							"(v1).", parent=dlg)
						return
					if bool(altf) != bool(atext):
						messagebox.showerror("NPC",
							"Alt dialog needs both a flag and "
							"text.", parent=dlg)
						return
					boss = None if bv.get() == "(none)" else bv.get()
					if boss and (sel or healer.get()):
						messagebox.showerror("NPC",
							"A boss can't be a healer or "
							"shopkeeper.", parent=dlg)
						return
					joins = None if jv.get() == "(none)" else jv.get()
					if joins and (sel or healer.get() or boss):
						messagebox.showerror("NPC",
							"A recruiter can't be a healer, "
							"shopkeeper, or boss.", parent=dlg)
						return
					result["joins"] = joins
					result["hidden_when"] = None \
						if hf.get() == "(none)" else hf.get()
					result["boss"] = boss
					result["healer"] = healer.get()
					result["shop"] = sel
					result["sets_flag"] = setf
					result["alt"] = {"flag": altf, "text": atext} \
					                if altf else None
					result["sprite"] = None if spv.get() == "(default)" \
					                   else spv.get()
				result["text"] = txt.get("1.0", "end-1c")
				dlg.destroy()
			btns = ttk.Frame(dlg)
			btns.pack(pady=6)
		elif kind == "chest":
			if self.ts_of(self.m()).get("chest_tile") is None:
				dlg.destroy()
				messagebox.showerror("Chest",
					"Tileset %s defines no chest tile "
					"(Tilesets tab)." % self.ts_of(self.m())["id"])
				return
			item_ids = [it["id"] for it in self.db["items"]]
			ttk.Label(dlg, text="Contains item:").grid(
				row=0, column=0, padx=6, pady=4, sticky="w")
			item = ttk.Combobox(dlg, values=item_ids, state="readonly")
			item.grid(row=0, column=1, padx=6, pady=4)
			item.set(ent.get("item", item_ids[0]))
			ttk.Label(dlg, text="Opened flag:").grid(
				row=1, column=0, padx=6, pady=4, sticky="w")
			flg = ttk.Combobox(dlg, values=self.db.get("flags", []),
			                   state="readonly")
			flg.grid(row=1, column=1, padx=6, pady=4)
			if ent.get("flag"):
				flg.set(ent["flag"])
			ttk.Label(dlg, text="(one flag per chest --\n"
			          "add them in Database > Flags)").grid(
				row=2, column=1, sticky="w", padx=6)

			def ok():
				if not flg.get():
					messagebox.showerror("Chest",
						"Pick the flag that marks this chest "
						"opened.", parent=dlg)
					return
				result["item"] = item.get()
				result["flag"] = flg.get()
				dlg.destroy()
			btns = ttk.Frame(dlg)
			btns.grid(row=3, column=0, columnspan=2, pady=6)
		else:
			cids = [m["cid"] for m in self.maps["maps"]]
			ttk.Label(dlg, text="Destination map:").grid(
				row=0, column=0, padx=6, pady=4, sticky="w")
			dest = ttk.Combobox(dlg, values=cids, state="readonly")
			dest.grid(row=0, column=1, padx=6, pady=4)
			dest.set(ent.get("dest", cids[0]))
			dxv = tk.IntVar(value=ent.get("dx", 1))
			dyv = tk.IntVar(value=ent.get("dy", 1))
			for r, (label, var) in enumerate(
					[("Dest X:", dxv), ("Dest Y:", dyv)], start=1):
				ttk.Label(dlg, text=label).grid(row=r, column=0,
				                                padx=6, sticky="w")
				ttk.Spinbox(dlg, from_=0, to=31, textvariable=var,
				            width=6).grid(row=r, column=1, padx=6,
				                          pady=2, sticky="w")
			ttk.Label(dlg, text="Needs flag:").grid(
				row=3, column=0, padx=6, pady=2, sticky="w")
			wfv = tk.StringVar(value=ent.get("flag") or "(none)")
			ttk.Combobox(dlg, values=flag_opts, textvariable=wfv,
			             state="readonly", width=16).grid(
				row=3, column=1, padx=6, pady=2, sticky="w")
			ttk.Label(dlg, text="Locked text:").grid(
				row=4, column=0, padx=6, pady=2, sticky="w")
			lkv = tk.StringVar(value=ent.get("locked_text", ""))
			ttk.Entry(dlg, textvariable=lkv, width=28).grid(
				row=4, column=1, padx=6, pady=2, sticky="w")

			def ok():
				wf = None if wfv.get() == "(none)" else wfv.get()
				if wf and not lkv.get().strip():
					messagebox.showerror("Warp",
						"A flag-gated warp needs locked text "
						"(shown while the flag is unset).",
						parent=dlg)
					return
				result["dest"] = dest.get()
				result["dx"] = dxv.get()
				result["dy"] = dyv.get()
				result["flag"] = wf
				result["locked_text"] = lkv.get().strip() if wf else None
				dlg.destroy()
			btns = ttk.Frame(dlg)
			btns.grid(row=5, column=0, columnspan=2, pady=6)

		ttk.Button(btns, text="OK", command=ok).pack(side="left", padx=4)
		if idx >= 0:
			def delete():
				del lst[idx]
				dlg.destroy()
				if kind == "chest":
					self.paint(x, y, 0)
					self.say("Chest removed -- repaint the floor tile")
				self.redraw_entities()
			ttk.Button(btns, text="Delete", command=delete) \
			   .pack(side="left", padx=4)
		ttk.Button(btns, text="Cancel", command=dlg.destroy) \
		   .pack(side="left", padx=4)

		self.root.wait_window(dlg)
		if result:
			ent.update(result)
			if idx < 0:
				lst.append(ent)
			if kind == "chest":
				self.paint(x, y,
				           self.ts_of(self.m())["chest_tile"])
			self.redraw_entities()

	def zone_tables(self):
		m = self.m()
		zr = m.get("zone_rows")
		used = sorted(set("".join(zr)) - {"."}) if zr else []
		if not used:
			messagebox.showinfo("Encounter Sets",
				"Paint zone tiles first (Zones panel, 0-7).")
			return
		set_ids = [s["id"] for s in self.db.get("encounters", [])]
		if not set_ids:
			messagebox.showinfo("Encounter Sets",
				"Create encounter sets first "
				"(Database > Encounters).")
			return
		zones = m.setdefault("zones", {})

		dlg = tk.Toplevel(self.root)
		dlg.title("Encounter Sets -- %s" % m["name"])
		dlg.grab_set()
		widgets = {}
		for r, z in enumerate(used):
			ttk.Label(dlg, text="Zone %s:" % z,
			          foreground=ZONE_COLORS[int(z)]).grid(
				row=r, column=0, padx=6, pady=3, sticky="w")
			v = tk.StringVar(value=zones.get(z, ""))
			ttk.Combobox(dlg, values=set_ids, textvariable=v,
			             state="readonly", width=22).grid(
				row=r, column=1, padx=6, pady=3, sticky="w")
			widgets[z] = v
		ttk.Label(dlg, text="(rates and troops live in\n"
		          "Database > Encounters)").grid(
			row=len(used), column=1, sticky="w", padx=6)

		def ok():
			for z, v in widgets.items():
				if not v.get():
					messagebox.showerror("Encounter Sets",
						"Zone %s needs an encounter set." % z,
						parent=dlg)
					return
			for z, v in widgets.items():
				zones[z] = v.get()
			dlg.destroy()
		btn = ttk.Frame(dlg)
		btn.grid(row=99, column=0, columnspan=2, pady=6)
		ttk.Button(btn, text="OK", command=ok).pack(side="left", padx=4)
		ttk.Button(btn, text="Cancel", command=dlg.destroy) \
		   .pack(side="left", padx=4)

	def map_new(self):
		cid = simpledialog.askstring("New map",
			"C identifier (e.g. MAP_CAVE):", parent=self.root)
		if not cid:
			return
		cid = cid.strip().upper()
		if not cid.startswith("MAP_"):
			cid = "MAP_" + cid
		if not re.fullmatch(r"MAP_[A-Z0-9_]+", cid) or \
		   any(m["cid"] == cid for m in self.maps["maps"]):
			messagebox.showerror("New map", "Invalid or duplicate id.")
			return
		name = simpledialog.askstring("New map", "Display name:",
		                              parent=self.root) or cid[4:].title()
		w = simpledialog.askinteger("New map", "Width (16-32):",
		                            minvalue=16, maxvalue=32,
		                            initialvalue=20, parent=self.root)
		h = simpledialog.askinteger("New map", "Height (12-32):",
		                            minvalue=12, maxvalue=32,
		                            initialvalue=16, parent=self.root)
		if not w or not h:
			return
		self.maps["maps"].append({
			"cid": cid, "name": name, "w": w, "h": h,
			"rows": [[0] * w for _ in range(h)],
			"tileset": self.m().get("tileset") or
			           self.ts_list()[0]["id"],
			"npcs": [], "warps": [], "signs": [], "chests": [],
			"zone_rows": None, "zones": {},
		})
		self.select_map(len(self.maps["maps"]) - 1)

	def map_rename(self):
		name = simpledialog.askstring("Rename", "Display name:",
		                              initialvalue=self.m()["name"],
		                              parent=self.root)
		if name:
			self.m()["name"] = name
			self.refresh_combo()

	def map_resize(self):
		m = self.m()
		w = simpledialog.askinteger("Resize", "Width (16-32):", minvalue=16,
		                            maxvalue=32, initialvalue=m["w"],
		                            parent=self.root)
		h = simpledialog.askinteger("Resize", "Height (12-32):", minvalue=12,
		                            maxvalue=32, initialvalue=m["h"],
		                            parent=self.root)
		if not w or not h:
			return
		def fit_s(rows, fill):
			rows = [(r + fill * w)[:w] for r in rows[:h]]
			return rows + [fill * w for _ in range(h - len(rows))]
		def fit_i(rows, fill):
			rows = [(r + [fill] * w)[:w] for r in rows[:h]]
			return rows + [[fill] * w for _ in range(h - len(rows))]
		m["rows"] = fit_i(m["rows"], 0)
		if m.get("zone_rows"):
			m["zone_rows"] = fit_s(m["zone_rows"], ".")
		m["w"], m["h"] = w, h
		for key in ("npcs", "warps", "signs"):
			kept = [e for e in m.get(key, []) if e["x"] < w and e["y"] < h]
			if len(kept) != len(m.get(key, [])):
				messagebox.showinfo("Resize",
					"Dropped out-of-bounds %s." % key)
			m[key] = kept
		evs = m.get("events", [])
		kept = [e for e in evs
		        if (e.get("trigger") or {}).get("kind") != "on_tile"
		        or (e["trigger"]["x"] < w and e["trigger"]["y"] < h)]
		if len(kept) != len(evs):
			messagebox.showinfo("Resize",
				"Dropped out-of-bounds tile events.")
		if kept:
			m["events"] = kept
		else:
			m.pop("events", None)
		self.redraw()

	def map_delete(self):
		m = self.m()
		refs = [o["cid"] for o in self.maps["maps"] if o is not m and
		        any(w["dest"] == m["cid"] for w in o.get("warps", []))]
		refs += ["%s event %d" % (o["cid"], i)
		         for o in self.maps["maps"]
		         for i, ev in enumerate(o.get("events", []))
		         if script_lang.uses_ident(ev.get("script", ""),
		                                   "map", m["cid"])]
		for key in ("start", "death"):
			if self.maps[key]["map"] == m["cid"]:
				refs.append(key)
		if refs:
			messagebox.showerror("Delete",
				"Still referenced by: %s" % ", ".join(refs))
			return
		if len(self.maps["maps"]) == 1:
			messagebox.showerror("Delete", "Can't delete the last map.")
			return
		if messagebox.askyesno("Delete", "Delete %s?" % m["cid"]):
			del self.maps["maps"][self.cur]
			self.select_map(0)

	# ================= Events (scripts) =================

	def ev_label(self, i, ev):
		t = ev.get("trigger") or {}
		k = t.get("kind", "?")
		if k == "on_tile":
			w = "on_tile (%d,%d)" % (t.get("x", 0), t.get("y", 0))
			if t.get("flag"):
				w += " if " + t["flag"]
		elif k == "on_flag":
			w = "on_flag " + (t.get("flag") or "?")
		else:
			w = k
		first = next((l.strip() for l in
		              ev.get("script", "").split("\n") if l.strip()),
		             "(empty)")
		return "%d. %-24s %s" % (i + 1, w, first[:32])

	def map_events(self):
		m = self.m()
		dlg = tk.Toplevel(self.root)
		dlg.title("Events -- %s" % m["cid"])
		dlg.grab_set()
		lb = tk.Listbox(dlg, width=64, height=10,
		                font=("Consolas", 10))
		lb.pack(padx=6, pady=6, fill="both", expand=True)

		def refresh(keep=-1):
			lb.delete(0, "end")
			for i, ev in enumerate(m.get("events", [])):
				lb.insert("end", self.ev_label(i, ev))
			if 0 <= keep < lb.size():
				lb.selection_set(keep)
			self.redraw_entities()

		def add():
			evs = m.setdefault("events", [])
			if len(evs) >= gen_scripts.MAX_EVENTS:
				messagebox.showwarning("Limit",
					"This map already has %d events (engine "
					"limit)." % gen_scripts.MAX_EVENTS, parent=dlg)
				return
			ev = {"trigger": {"kind": "on_load"}, "script": ""}
			if self.event_dialog(dlg, ev):
				evs.append(ev)
				refresh(len(evs) - 1)

		def edit(_e=None):
			sel = lb.curselection()
			if sel and self.event_dialog(dlg,
			                             m["events"][sel[0]]):
				refresh(sel[0])

		def delete():
			sel = lb.curselection()
			if not sel:
				return
			if messagebox.askyesno("Delete", "Delete event %d?"
			                       % (sel[0] + 1), parent=dlg):
				del m["events"][sel[0]]
				if not m["events"]:
					m.pop("events", None)
				refresh()

		lb.bind("<Double-Button-1>", edit)
		bf = ttk.Frame(dlg)
		bf.pack(pady=(0, 6))
		for label, cmd in (("Add", add), ("Edit", edit),
		                   ("Delete", delete),
		                   ("Close", dlg.destroy)):
			ttk.Button(bf, text=label, command=cmd) \
			   .pack(side="left", padx=3)
		refresh()
		dlg.wait_window()

	def event_dialog(self, parent, ev):
		"""Edit one event in place; returns True on OK."""
		m = self.m()
		t = ev.setdefault("trigger", {"kind": "on_load"})
		dlg = tk.Toplevel(parent)
		dlg.title("Event")
		dlg.grab_set()
		done = {"ok": False}

		tf = ttk.Frame(dlg)
		tf.pack(anchor="w", padx=6, pady=(6, 0), fill="x")
		ttk.Label(tf, text="Trigger:").pack(side="left")
		kv = tk.StringVar(value=t.get("kind", "on_load"))
		ttk.Combobox(tf, values=list(gen_scripts.TRIGGER_KINDS),
		             textvariable=kv, state="readonly",
		             width=10).pack(side="left", padx=4)
		fv = tk.StringVar(value=t.get("flag") or "(none)")
		flag_box = ttk.Combobox(
			tf, values=["(none)"] + self.db.get("flags", []),
			textvariable=fv, state="readonly", width=16)
		flag_lbl = ttk.Label(tf, text="Flag:")
		xv = tk.IntVar(value=t.get("x", 0))
		yv = tk.IntVar(value=t.get("y", 0))
		x_lbl = ttk.Label(tf, text="x:")
		x_sp = ttk.Spinbox(tf, from_=0, to=m["w"] - 1, width=4,
		                   textvariable=xv)
		y_lbl = ttk.Label(tf, text="y:")
		y_sp = ttk.Spinbox(tf, from_=0, to=m["h"] - 1, width=4,
		                   textvariable=yv)

		def relayout(_e=None):
			for w in (flag_lbl, flag_box, x_lbl, x_sp, y_lbl, y_sp):
				w.pack_forget()
			k = kv.get()
			if k in ("on_flag", "on_tile"):
				flag_lbl.pack(side="left", padx=(8, 0))
				flag_box.pack(side="left", padx=4)
			if k == "on_tile":
				x_lbl.pack(side="left", padx=(8, 0))
				x_sp.pack(side="left")
				y_lbl.pack(side="left", padx=(4, 0))
				y_sp.pack(side="left")
		tf.master.bind_class(str(dlg), "<<ComboboxSelected>>",
		                     relayout)
		kv.trace_add("write", lambda *a: relayout())
		relayout()

		ttk.Label(dlg, text="Script (tabs indent blocks; see the "
		          "docs for commands):").pack(anchor="w", padx=6,
		                                      pady=(8, 0))
		ef = ttk.Frame(dlg)
		ef.pack(padx=6, pady=4, fill="both", expand=True)
		gut = tk.Text(ef, width=3, height=16, font=("Consolas", 10),
		              state="disabled", takefocus=0, bd=0,
		              bg="#e8e8e8", fg="#606060")
		gut.pack(side="left", fill="y")
		txt = tk.Text(ef, width=60, height=16,
		              font=("Consolas", 10), wrap="none", undo=True)
		txt.pack(side="left", fill="both", expand=True)
		txt.insert("1.0", ev.get("script", ""))
		txt.tag_configure("err", background="#ffc0c0")

		def renumber(_e=None):
			n = int(txt.index("end-1c").split(".")[0])
			gut.config(state="normal")
			gut.delete("1.0", "end")
			gut.insert("1.0", "\n".join("%2d" % i
			                            for i in range(1, n + 1)))
			gut.config(state="disabled")
		txt.bind("<KeyRelease>", renumber)
		txt.bind("<Tab>", lambda e: (txt.insert("insert", "\t"),
		                             "break")[1])
		renumber()

		status = ttk.Label(dlg, text="", foreground="#a00000",
		                   wraplength=460, justify="left")
		status.pack(anchor="w", padx=6)

		def current_trigger():
			k = kv.get()
			out = {"kind": k}
			fl = fv.get()
			if k == "on_flag":
				if fl == "(none)":
					raise script_lang.ScriptError(
						0, "on_flag needs a flag")
				out["flag"] = fl
			if k == "on_tile":
				x, y = xv.get(), yv.get()
				if not (0 <= x < m["w"] and 0 <= y < m["h"]):
					raise script_lang.ScriptError(
						0, "tile (%d,%d) outside map" % (x, y))
				out["x"], out["y"] = x, y
				if fl != "(none)":
					out["flag"] = fl
			return out

		def check(show_ok=True):
			txt.tag_remove("err", "1.0", "end")
			try:
				current_trigger()
				refs = script_lang.Refs.from_data(self.db,
				                                  self.maps)
				script_lang.validate_script(
					txt.get("1.0", "end-1c"), refs)
			except script_lang.ScriptError as e:
				status.config(text=str(e))
				if e.line > 0:
					txt.tag_add("err", "%d.0" % e.line,
					            "%d.end" % e.line)
					txt.see("%d.0" % e.line)
				return False
			if show_ok:
				status.config(text="")
				self.say("Script OK")
			return True

		def ok():
			if not check(show_ok=False):
				return
			ev["trigger"] = current_trigger()
			ev["script"] = txt.get("1.0", "end-1c")
			done["ok"] = True
			dlg.destroy()

		bf = ttk.Frame(dlg)
		bf.pack(pady=6)
		ttk.Button(bf, text="Validate",
		           command=check).pack(side="left", padx=3)
		ttk.Button(bf, text="OK", command=ok) \
		   .pack(side="left", padx=3)
		ttk.Button(bf, text="Cancel", command=dlg.destroy) \
		   .pack(side="left", padx=3)
		dlg.wait_window()
		return done["ok"]

	# ================= Tilesets tab =================

	def build_tilesets_tab(self):
		tab = ttk.Frame(self.nb)
		self.nb.add(tab, text="Tilesets")
		left = ttk.Frame(tab)
		left.pack(side="left", fill="y", padx=6, pady=6)
		self.ts_lb = tk.Listbox(left, width=18, height=16,
		                        exportselection=False)
		self.ts_lb.pack()
		self.ts_lb.bind("<<ListboxSelect>>", lambda e: self.ts_select())
		btns = ttk.Frame(left)
		btns.pack(pady=4)
		ttk.Button(btns, text="Import...", command=self.ts_add) \
		   .pack(side="left", padx=2)
		ttk.Button(btns, text="Delete", command=self.ts_delete) \
		   .pack(side="left", padx=2)
		ttk.Label(left, text="A tileset is a 128x48 PNG:\n"
		          "8x3 grid of 16x16 tiles.\n"
		          "Magenta #FF00FF pixels show\n"
		          "the void tile through.\n"
		          "Maps pick a tileset in the\n"
		          "Maps tab.", justify="left").pack(pady=8)

		form = ttk.Frame(tab)
		form.pack(side="left", fill="both", expand=True, padx=6, pady=6)
		row0 = ttk.Frame(form)
		row0.pack(anchor="w")
		ttk.Label(row0, text="ID:").pack(side="left")
		self.ts_id = tk.StringVar()
		ttk.Entry(row0, textvariable=self.ts_id, width=16) \
		   .pack(side="left", padx=4)
		ttk.Button(row0, text="Apply", command=self.ts_apply) \
		   .pack(side="left", padx=4)
		ttk.Button(row0, text="Replace image...",
		           command=self.ts_replace_image) \
		   .pack(side="left", padx=4)

		self.ts_preview = ttk.Label(form)
		self.ts_preview.pack(anchor="w", pady=6)

		ttk.Label(form, text="Solid (blocks walking):") \
		   .pack(anchor="w")
		self.ts_grid = ttk.Frame(form)
		self.ts_grid.pack(anchor="w", pady=2)

		row1 = ttk.Frame(form)
		row1.pack(anchor="w", pady=(8, 0))
		ttk.Label(row1, text="Chest tile:").pack(side="left")
		self.ts_chest = tk.StringVar()
		self.ts_chest_cb = ttk.Combobox(
			row1, textvariable=self.ts_chest, state="readonly",
			width=22)
		self.ts_chest_cb.pack(side="left", padx=4)
		self.ts_chest_cb.bind("<<ComboboxSelected>>",
		                      lambda e: self.ts_set_special())
		ttk.Label(row1, text="Void tile:").pack(side="left",
		                                        padx=(12, 0))
		self.ts_void = tk.StringVar()
		self.ts_void_cb = ttk.Combobox(
			row1, textvariable=self.ts_void, state="readonly",
			width=22)
		self.ts_void_cb.pack(side="left", padx=4)
		self.ts_void_cb.bind("<<ComboboxSelected>>",
		                     lambda e: self.ts_set_special())
		ttk.Label(form, text="Chest tile: painted by the Chest tool; "
		          "(none) = no chests on maps using this tileset.\n"
		          "Void tile: drawn outside map bounds and behind "
		          "battles.\nRoof compositing pairs (advanced) are "
		          "edited in data/tilesets.json directly.",
		          justify="left").pack(anchor="w", pady=6)
		self.ts_refresh()

	def ts(self):
		return self.ts_list()[self.cur_ts]

	def ts_refresh(self, keep=0):
		self.ts_lb.delete(0, "end")
		for ts in self.ts_list():
			self.ts_lb.insert("end", ts["id"])
		keep = min(keep, len(self.ts_list()) - 1)
		self.ts_lb.selection_set(keep)
		self.ts_select()
		if hasattr(self, "tileset_combo"):
			self.refresh_tileset_combo()

	def ts_select(self):
		i = self.sel(self.ts_lb)
		if i < 0:
			return
		self.cur_ts = i
		ts = self.ts()
		self.ts_id.set(ts["id"])
		sheet = self.ts_sheet(ts).resize((128 * 2, 48 * 2),
		                                 Image.NEAREST)
		self._ts_photo = ImageTk.PhotoImage(sheet)
		self.ts_preview.config(image=self._ts_photo)
		for w in self.ts_grid.winfo_children():
			w.destroy()
		self.ts_solid_vars = []
		for i2 in range(N_TILES):
			v = tk.BooleanVar(value=bool(ts["tiles"][i2].get("solid")))
			cb = ttk.Checkbutton(
				self.ts_grid, text="%d" % i2, variable=v,
				command=lambda i3=i2: self.ts_toggle_solid(i3))
			cb.grid(row=i2 // 8, column=i2 % 8, sticky="w",
			        padx=3, pady=1)
			self.bind_tip(cb, self.tile_name(ts, i2))
			self.ts_solid_vars.append(v)
		opts = ["%d: %s" % (i2, self.tile_name(ts, i2))
		        for i2 in range(N_TILES)]
		self.ts_chest_cb["values"] = ["(none)"] + opts
		self.ts_void_cb["values"] = opts
		ct = ts.get("chest_tile")
		self.ts_chest.set("(none)" if ct is None else opts[ct])
		self.ts_void.set(opts[ts["void_tile"]])

	def ts_toggle_solid(self, i):
		self.ts()["tiles"][i]["solid"] = self.ts_solid_vars[i].get()
		self.refresh_palette()

	def ts_set_special(self):
		ts = self.ts()
		c = self.ts_chest.get()
		ts["chest_tile"] = None if c == "(none)" \
		                   else int(c.split(":")[0])
		ts["void_tile"] = int(self.ts_void.get().split(":")[0])
		self.refresh_palette()

	def ts_apply(self):
		ts = self.ts()
		old, new = ts["id"], self.ts_id.get().strip()
		if not new.isidentifier():
			messagebox.showerror("Tileset",
				"ID must be a C identifier.")
			return
		if new != old and any(t["id"] == new for t in self.ts_list()):
			messagebox.showerror("Tileset", "Duplicate id.")
			return
		ts["id"] = new
		if new != old:                       # propagate into maps
			for m in self.maps["maps"]:
				if m.get("tileset") == old:
					m["tileset"] = new
			self.ts_imgs[new] = self.ts_imgs.pop(old)
			self.refresh_tileset_combo()
		self.ts_refresh(self.cur_ts)
		self.say("Tileset %s applied" % new)

	def ts_import_png(self, dest_name=None):
		"""Pick a 128x48 PNG; copy it under gfx/tilesets/.
		Returns (stem, relative image path) or None."""
		path = filedialog.askopenfilename(
			filetypes=[("PNG images", "*.png")])
		if not path:
			return None
		stem = dest_name or os.path.splitext(
			os.path.basename(path))[0]
		if not stem.isidentifier():
			messagebox.showerror("Tileset",
				"Filename (minus .png) must be a C identifier:\n"
				"letters, digits, underscores; no leading digit.")
			return None
		img = Image.open(path)
		if img.size != (128, 48):
			messagebox.showerror("Tileset",
				"Tileset must be exactly 128x48 -- an 8x3 grid of\n"
				"16x16 tiles (this is %dx%d). Resizing would\n"
				"garble tile boundaries, so no auto-resize."
				% img.size)
			return None
		os.makedirs(os.path.join(ROOT, "gfx", "tilesets"),
		            exist_ok=True)
		rel = "gfx/tilesets/%s.png" % stem
		dest = os.path.join(ROOT, "gfx", "tilesets", stem + ".png")
		if not (os.path.exists(dest)
		        and os.path.samefile(path, dest)):
			shutil.copy(path, dest)
		return stem, rel

	def ts_add(self):
		got = self.ts_import_png()
		if not got:
			return
		stem, rel = got
		tid = stem
		n = 1
		while any(t["id"] == tid for t in self.ts_list()):
			n += 1
			tid = "%s%d" % (stem, n)
		self.ts_list().append({
			"id": tid, "image": rel,
			"tiles": [{"name": "Tile %d" % i, "solid": False}
			          for i in range(N_TILES)],
			"chest_tile": None, "void_tile": 0,
			"roof_base": 0, "roof_composite": [],
		})
		self.load_tiles(tid)
		self.ts_refresh(len(self.ts_list()) - 1)
		self.say("Imported tileset %s -- set solid flags and the "
		         "void tile (in ROM at next Build)" % tid)

	def ts_replace_image(self):
		ts = self.ts()
		got = self.ts_import_png(dest_name=os.path.splitext(
			os.path.basename(ts["image"]))[0])
		if not got:
			return
		self.load_tiles(ts["id"])
		self.ts_select()
		self.refresh_palette()
		self.redraw()
		self.say("Replaced art of tileset %s" % ts["id"])

	def ts_delete(self):
		ts = self.ts()
		refs = [m["cid"] for m in self.maps["maps"]
		        if m.get("tileset") == ts["id"]]
		if refs:
			messagebox.showerror("Delete",
				"Used by maps: %s" % ", ".join(refs))
			return
		if len(self.ts_list()) == 1:
			messagebox.showerror("Delete",
				"Can't delete the last tileset.")
			return
		del self.ts_list()[self.cur_ts]
		self.load_tiles()
		self.ts_refresh()

	# ================= Database tab =================

	def build_db_tab(self):
		tab = ttk.Frame(self.nb)
		self.nb.add(tab, text="Database")
		sub = ttk.Notebook(tab)
		sub.pack(fill="both", expand=True)
		self.build_enemies_tab(sub)
		self.build_troops_tab(sub)
		self.build_encounters_tab(sub)
		self.build_items_tab(sub)
		self.build_flags_tab(sub)
		self.build_spells_tab(sub)
		self.build_bosses_tab(sub)
		self.build_players_tab(sub)

	def list_section(self, parent, title, on_select, on_add, on_delete):
		"""Left listbox + Add/Delete; returns (frame_for_form, listbox)."""
		f = ttk.Frame(parent)
		parent.add(f, text=title)
		left = ttk.Frame(f)
		left.pack(side="left", fill="y", padx=6, pady=6)
		lb = tk.Listbox(left, width=18, height=16, exportselection=False)
		lb.pack()
		lb.bind("<<ListboxSelect>>", lambda e: on_select())
		btns = ttk.Frame(left)
		btns.pack(pady=4)
		if on_add:
			ttk.Button(btns, text="Add", command=on_add) \
			   .pack(side="left", padx=2)
		if on_delete:
			ttk.Button(btns, text="Delete", command=on_delete) \
			   .pack(side="left", padx=2)
		form = ttk.Frame(f)
		form.pack(side="left", fill="both", expand=True, padx=6, pady=6)
		return form, lb

	def spin_row(self, parent, row, label, lo, hi):
		ttk.Label(parent, text=label).grid(row=row, column=0, sticky="w",
		                                   pady=1)
		v = tk.IntVar()
		ttk.Spinbox(parent, from_=lo, to=hi, textvariable=v,
		            width=6).grid(row=row, column=1, sticky="w", pady=1)
		return v

	def entry_row(self, parent, row, label, width=18):
		ttk.Label(parent, text=label).grid(row=row, column=0, sticky="w",
		                                   pady=1)
		v = tk.StringVar()
		ttk.Entry(parent, textvariable=v, width=width) \
		   .grid(row=row, column=1, sticky="w", pady=1)
		return v

	def sel(self, lb):
		s = lb.curselection()
		return s[0] if s else -1

	def new_id(self, lst, base):
		n = 1
		while any(e["id"] == "%s%d" % (base, n) for e in lst):
			n += 1
		return "%s%d" % (base, n)

	# ---- enemies ----

	def build_enemies_tab(self, sub):
		form, self.e_lb = self.list_section(sub, "Enemies",
			self.e_select, self.e_add, self.e_delete)
		self.e_id = self.entry_row(form, 0, "ID:")
		self.e_name = self.entry_row(form, 1, "Name:")
		self.e_stats = {}
		for r, (key, label, hi) in enumerate(
				[("hp", "HP:", 999), ("atk", "Attack:", 255),
				 ("def", "Defense:", 255), ("agi", "Agility:", 255),
				 ("exp", "EXP:", 999), ("gold", "Gold:", 999)], start=2):
			self.e_stats[key] = self.spin_row(form, r, label, 0, hi)
		self.e_sprite = ttk.Label(form, text="(no sprite)")
		self.e_sprite.grid(row=8, column=0, columnspan=2, pady=4)
		self.e_preview = ttk.Label(form)
		self.e_preview.grid(row=9, column=0, columnspan=2)
		ttk.Button(form, text="Import sprite (64x64 PNG)...",
		           command=self.e_import).grid(row=10, column=0,
		                                       columnspan=2, pady=4)
		ttk.Button(form, text="Apply", command=self.e_apply) \
		   .grid(row=11, column=0, pady=8, sticky="w")
		self.e_refresh()

	def e_refresh(self, keep=0):
		self.e_lb.delete(0, "end")
		for e in self.db["enemies"]:
			self.e_lb.insert("end", e["id"])
		if self.db["enemies"]:
			self.e_lb.selection_set(min(keep, len(self.db["enemies"]) - 1))
			self.e_select()

	def e_select(self):
		i = self.sel(self.e_lb)
		if i < 0:
			return
		e = self.db["enemies"][i]
		self.e_id.set(e["id"])
		self.e_name.set(e["name"])
		for k, v in self.e_stats.items():
			v.set(e[k])
		self.e_sprite.config(text="sprite: " + e.get("sprite", "?"))
		path = os.path.join(ROOT, "gfx", "enemies", e.get("sprite", ""))
		if e.get("sprite") and os.path.isfile(path):
			img = Image.open(path).convert("RGBA") \
			           .resize((128, 128), Image.NEAREST)
			self._e_photo = ImageTk.PhotoImage(img)
			self.e_preview.config(image=self._e_photo)
		else:
			self.e_preview.config(image="")

	def e_apply(self):
		i = self.sel(self.e_lb)
		if i < 0:
			return
		e = self.db["enemies"][i]
		old = e["id"]
		new = self.e_id.get().strip()
		if not new.isidentifier():
			messagebox.showerror("Enemy", "ID must be a C identifier.")
			return
		if new != old and any(x["id"] == new for x in self.db["enemies"]):
			messagebox.showerror("Enemy", "Duplicate id.")
			return
		e["id"] = new
		e["name"] = self.e_name.get().strip() or new
		for k, v in self.e_stats.items():
			e[k] = v.get()
		if new != old:                       # propagate into troops
			for t in self.db["troops"]:
				t["members"] = [new if m == old else m
				                for m in t["members"]]
		self.e_refresh(i)
		self.say("Enemy %s applied" % new)

	def e_add(self):
		eid = self.new_id(self.db["enemies"], "enemy")
		self.db["enemies"].append({"id": eid, "name": eid.title(),
			"sprite": "", "hp": 8, "atk": 6, "def": 4, "agi": 4,
			"exp": 2, "gold": 3})
		self.e_refresh(len(self.db["enemies"]) - 1)

	def e_delete(self):
		i = self.sel(self.e_lb)
		if i < 0:
			return
		eid = self.db["enemies"][i]["id"]
		refs = [t["id"] for t in self.db["troops"] if eid in t["members"]]
		if refs:
			messagebox.showerror("Delete",
				"Used by troops: %s" % ", ".join(refs))
			return
		if len(self.db["enemies"]) == 1:
			messagebox.showerror("Delete", "Need at least one enemy.")
			return
		del self.db["enemies"][i]
		self.e_refresh()

	def e_import(self):
		i = self.sel(self.e_lb)
		if i < 0:
			return
		path = filedialog.askopenfilename(
			filetypes=[("PNG images", "*.png")])
		if not path:
			return
		img = Image.open(path)
		if img.size != (64, 64):
			messagebox.showerror("Sprite",
				"Sprite must be exactly 64x64 (this is %dx%d)."
				% img.size)
			return
		e = self.db["enemies"][i]
		dest = e["id"] + ".png"
		shutil.copy(path, os.path.join(ROOT, "gfx", "enemies", dest))
		e["sprite"] = dest
		self.e_select()
		self.say("Imported %s" % dest)

	# ---- troops ----

	def build_troops_tab(self, sub):
		form, self.t_lb = self.list_section(sub, "Troops",
			self.t_select, self.t_add, self.t_delete)
		self.t_id = self.entry_row(form, 0, "ID:")
		self.t_name = self.entry_row(form, 1, "Battle text:", 24)
		ttk.Label(form, text='("<name> appears!")').grid(
			row=2, column=1, sticky="w")
		self.t_members = []
		for i in range(gen_db.MAX_TROOP):
			ttk.Label(form, text="Member %d:" % (i + 1)).grid(
				row=3 + i, column=0, sticky="w", pady=1)
			v = tk.StringVar()
			cb = ttk.Combobox(form, textvariable=v, state="readonly",
			                  width=16)
			cb.grid(row=3 + i, column=1, sticky="w", pady=1)
			self.t_members.append((v, cb))
		ttk.Button(form, text="Apply", command=self.t_apply) \
		   .grid(row=7, column=0, pady=8, sticky="w")
		self.t_refresh()

	def t_refresh(self, keep=0):
		self.t_lb.delete(0, "end")
		for t in self.db["troops"]:
			self.t_lb.insert("end", t["id"])
		opts = ["(none)"] + [e["id"] for e in self.db["enemies"]]
		for v, cb in self.t_members:
			cb["values"] = opts
		if self.db["troops"]:
			self.t_lb.selection_set(min(keep, len(self.db["troops"]) - 1))
			self.t_select()

	def t_select(self):
		i = self.sel(self.t_lb)
		if i < 0:
			return
		t = self.db["troops"][i]
		self.t_id.set(t["id"])
		self.t_name.set(t["name"])
		for k, (v, cb) in enumerate(self.t_members):
			v.set(t["members"][k] if k < len(t["members"]) else "(none)")

	def t_apply(self):
		i = self.sel(self.t_lb)
		if i < 0:
			return
		t = self.db["troops"][i]
		old = t["id"]
		new = self.t_id.get().strip()
		if not new.isidentifier():
			messagebox.showerror("Troop", "ID must be a C identifier.")
			return
		if new != old and any(x["id"] == new for x in self.db["troops"]):
			messagebox.showerror("Troop", "Duplicate id.")
			return
		members = [v.get() for v, _ in self.t_members
		           if v.get() and v.get() != "(none)"]
		if not members:
			messagebox.showerror("Troop", "Need at least one member.")
			return
		t["id"] = new
		t["name"] = self.t_name.get().strip() or new
		t["members"] = members
		if new != old:                       # propagate: sets + bosses
			for s in self.db.get("encounters", []):
				s["troops"] = [[new if tr == old else tr, w]
				               for tr, w in s["troops"]]
			for b in self.db.get("bosses", []):
				if b.get("troop") == old:
					b["troop"] = new
			for m in self.maps["maps"]:
				for ev in m.get("events", []):
					ev["script"] = script_lang.rename_ident(
						ev.get("script", ""), "troop", old, new)
		self.n_refresh(max(0, self.sel(self.n_lb)))
		self.t_refresh(i)
		self.say("Troop %s applied" % new)

	def t_add(self):
		tid = self.new_id(self.db["troops"], "troop")
		self.db["troops"].append({"id": tid, "name": "a foe",
			"members": [self.db["enemies"][0]["id"]]})
		self.t_refresh(len(self.db["troops"]) - 1)

	def t_delete(self):
		i = self.sel(self.t_lb)
		if i < 0:
			return
		tid = self.db["troops"][i]["id"]
		refs = [s["id"] for s in self.db.get("encounters", [])
		        if tid in [tr for tr, w in s["troops"]]]
		refs += ["boss " + b["id"] for b in self.db.get("bosses", [])
		         if b.get("troop") == tid]
		refs += ["%s event %d" % (m["cid"], i)
		         for m in self.maps["maps"]
		         for i, ev in enumerate(m.get("events", []))
		         if script_lang.uses_ident(ev.get("script", ""),
		                                   "troop", tid)]
		if refs:
			messagebox.showerror("Delete",
				"Used by: %s" % ", ".join(refs))
			return
		if len(self.db["troops"]) == 1:
			messagebox.showerror("Delete", "Need at least one troop.")
			return
		del self.db["troops"][i]
		self.t_refresh()

	# ---- encounter sets ----

	def build_encounters_tab(self, sub):
		form, self.n_lb = self.list_section(sub, "Encounters",
			self.n_select, self.n_add, self.n_delete)
		self.n_id = self.entry_row(form, 0, "ID:")
		self.n_rate = self.spin_row(form, 1, "1 per N steps:", 1, 255)
		self.n_troops = []
		for i in range(gen_db.MAX_ENC_TROOPS):
			ttk.Label(form, text="Troop %d:" % (i + 1)).grid(
				row=2 + i, column=0, sticky="w", pady=1)
			tv = tk.StringVar()
			cb = ttk.Combobox(form, textvariable=tv, state="readonly",
			                  width=16)
			cb.grid(row=2 + i, column=1, sticky="w", pady=1)
			wv = tk.IntVar(value=1)
			ttk.Spinbox(form, from_=1, to=9, textvariable=wv,
			            width=4).grid(row=2 + i, column=2, sticky="w",
			                          padx=4, pady=1)
			self.n_troops.append((tv, cb, wv))
		ttk.Label(form, text="(weight)").grid(row=2, column=3,
		                                      sticky="w")
		ttk.Button(form, text="Apply", command=self.n_apply) \
		   .grid(row=6, column=0, pady=8, sticky="w")
		self.n_refresh()

	def n_refresh(self, keep=0):
		self.n_lb.delete(0, "end")
		sets = self.db.setdefault("encounters", [])
		for s in sets:
			self.n_lb.insert("end", s["id"])
		opts = ["(none)"] + [t["id"] for t in self.db["troops"]]
		for tv, cb, wv in self.n_troops:
			cb["values"] = opts
		if sets:
			self.n_lb.selection_set(min(keep, len(sets) - 1))
			self.n_select()

	def n_select(self):
		i = self.sel(self.n_lb)
		if i < 0:
			return
		s = self.db["encounters"][i]
		self.n_id.set(s["id"])
		self.n_rate.set(s.get("rate", 14))
		for k, (tv, cb, wv) in enumerate(self.n_troops):
			if k < len(s["troops"]):
				tv.set(s["troops"][k][0])
				wv.set(s["troops"][k][1])
			else:
				tv.set("(none)")
				wv.set(1)

	def n_apply(self):
		i = self.sel(self.n_lb)
		if i < 0:
			return
		s = self.db["encounters"][i]
		old = s["id"]
		new = self.n_id.get().strip()
		if not new.isidentifier():
			messagebox.showerror("Encounter set",
				"ID must be a C identifier.")
			return
		if new != old and any(x["id"] == new
		                      for x in self.db["encounters"]):
			messagebox.showerror("Encounter set", "Duplicate id.")
			return
		troops = [[tv.get(), max(1, wv.get())]
		          for tv, cb, wv in self.n_troops
		          if tv.get() and tv.get() != "(none)"]
		if not troops:
			messagebox.showerror("Encounter set",
				"Need at least one troop.")
			return
		s["id"] = new
		s["rate"] = max(1, self.n_rate.get())
		s["troops"] = troops
		if new != old:                       # propagate into map zones
			for m in self.maps["maps"]:
				zones = m.get("zones") or {}
				for z, ref in zones.items():
					if ref == old:
						zones[z] = new
		self.n_refresh(i)
		self.say("Encounter set %s applied" % new)

	def n_add(self):
		sid = self.new_id(self.db.setdefault("encounters", []), "enc")
		self.db["encounters"].append({"id": sid, "rate": 14,
			"troops": [[self.db["troops"][0]["id"], 1]]})
		self.n_refresh(len(self.db["encounters"]) - 1)

	def n_delete(self):
		i = self.sel(self.n_lb)
		if i < 0:
			return
		sid = self.db["encounters"][i]["id"]
		refs = [m["cid"] for m in self.maps["maps"]
		        if sid in (m.get("zones") or {}).values()]
		if refs:
			messagebox.showerror("Delete",
				"Used by zones in: %s" % ", ".join(refs))
			return
		del self.db["encounters"][i]
		self.n_refresh()

	# ---- items ----

	def build_items_tab(self, sub):
		form, self.i_lb = self.list_section(sub, "Items",
			self.i_select, self.i_add, self.i_delete)
		self.i_id = self.entry_row(form, 0, "ID:")
		self.i_name = self.entry_row(form, 1, "Name:")
		self.i_heal = self.spin_row(form, 2, "Heals HP:", 0, 999)
		self.i_price = self.spin_row(form, 3, "Price (G):", 0, 9999)
		ttk.Label(form, text="(0 = shops won't trade it)").grid(
			row=4, column=1, sticky="w")
		ttk.Button(form, text="Apply", command=self.i_apply) \
		   .grid(row=5, column=0, pady=8, sticky="w")
		self.i_refresh()

	def i_refresh(self, keep=0):
		self.i_lb.delete(0, "end")
		for it in self.db["items"]:
			self.i_lb.insert("end", it["id"])
		if self.db["items"]:
			self.i_lb.selection_set(min(keep, len(self.db["items"]) - 1))
			self.i_select()
		if hasattr(self, "p_start_frame"):
			self.refresh_start_items()

	def i_select(self):
		i = self.sel(self.i_lb)
		if i < 0:
			return
		it = self.db["items"][i]
		self.i_id.set(it["id"])
		self.i_name.set(it["name"])
		self.i_heal.set(it["heal"])
		self.i_price.set(it.get("price", 0))

	def i_apply(self):
		i = self.sel(self.i_lb)
		if i < 0:
			return
		it = self.db["items"][i]
		old = it["id"]
		new = self.i_id.get().strip()
		if not new.isidentifier():
			messagebox.showerror("Item", "ID must be a C identifier.")
			return
		if new != old and any(x["id"] == new for x in self.db["items"]):
			messagebox.showerror("Item", "Duplicate id.")
			return
		it["id"] = new
		it["name"] = self.i_name.get().strip() or new
		it["heal"] = self.i_heal.get()
		it["price"] = self.i_price.get()
		if new != old:                       # propagate into shops etc.
			if old in self.project.get("start_items", {}):
				self.project["start_items"][new] = \
					self.project["start_items"].pop(old)
			for m in self.maps["maps"]:
				for np in m.get("npcs", []):
					if np.get("shop"):
						np["shop"] = [new if s == old else s
						              for s in np["shop"]]
				for ch in m.get("chests", []):
					if ch["item"] == old:
						ch["item"] = new
				for ev in m.get("events", []):
					ev["script"] = script_lang.rename_ident(
						ev.get("script", ""), "item", old, new)
		self.i_refresh(i)
		self.say("Item %s applied" % new)

	def i_add(self):
		iid = self.new_id(self.db["items"], "item")
		self.db["items"].append({"id": iid, "name": iid.title(),
		                         "heal": 10, "price": 0})
		self.i_refresh(len(self.db["items"]) - 1)

	def i_delete(self):
		i = self.sel(self.i_lb)
		if i < 0:
			return
		if len(self.db["items"]) == 1:
			messagebox.showerror("Delete", "Need at least one item.")
			return
		iid = self.db["items"][i]["id"]
		refs = [m["cid"] for m in self.maps["maps"]
		        if any(iid in (np.get("shop") or [])
		               for np in m.get("npcs", []))
		        or any(ch["item"] == iid
		               for ch in m.get("chests", []))
		        or any(script_lang.uses_ident(ev.get("script", ""),
		                                      "item", iid)
		               for ev in m.get("events", []))]
		if refs:
			messagebox.showerror("Delete",
				"Sold or chest-held in: %s" % ", ".join(refs))
			return
		self.project.get("start_items", {}).pop(iid, None)
		del self.db["items"][i]
		self.i_refresh()

	# ---- flags ----

	def build_flags_tab(self, sub):
		form, self.fl_lb = self.list_section(sub, "Flags",
			self.fl_select, self.fl_add, self.fl_delete)
		self.fl_id = self.entry_row(form, 0, "ID:")
		ttk.Label(form, text="Flags are saved booleans (max %d).\n"
		          "Chests mark themselves opened with one;\n"
		          "NPCs can set one or swap dialog on one;\n"
		          "warps can require one."
		          % gen_db.MAX_FLAGS).grid(
			row=1, column=0, columnspan=2, sticky="w", pady=4)
		ttk.Button(form, text="Apply", command=self.fl_apply) \
		   .grid(row=2, column=0, pady=8, sticky="w")
		self.fl_refresh()

	def fl_refresh(self, keep=0):
		self.fl_lb.delete(0, "end")
		flags = self.db.setdefault("flags", [])
		for fl in flags:
			self.fl_lb.insert("end", fl)
		if flags:
			self.fl_lb.selection_set(min(keep, len(flags) - 1))
			self.fl_select()

	def fl_select(self):
		i = self.sel(self.fl_lb)
		if i >= 0:
			self.fl_id.set(self.db["flags"][i])

	def fl_refs(self, fl):
		refs = []
		for m in self.maps["maps"]:
			hit = any(n.get("sets_flag") == fl or
			          n.get("hidden_when") == fl or
			          (n.get("alt") or {}).get("flag") == fl
			          for n in m.get("npcs", []))
			hit = hit or any(w.get("flag") == fl
			                 for w in m.get("warps", []))
			hit = hit or any(c.get("flag") == fl
			                 for c in m.get("chests", []))
			hit = hit or any(
				(ev.get("trigger") or {}).get("flag") == fl
				or script_lang.uses_ident(ev.get("script", ""),
				                          "flag", fl)
				for ev in m.get("events", []))
			if hit:
				refs.append(m["cid"])
		return refs

	def fl_apply(self):
		i = self.sel(self.fl_lb)
		if i < 0:
			return
		old = self.db["flags"][i]
		new = self.fl_id.get().strip()
		if not new.isidentifier():
			messagebox.showerror("Flag", "ID must be a C identifier.")
			return
		if new != old and new in self.db["flags"]:
			messagebox.showerror("Flag", "Duplicate id.")
			return
		self.db["flags"][i] = new
		if new != old:                       # propagate everywhere
			for m in self.maps["maps"]:
				for n in m.get("npcs", []):
					if n.get("sets_flag") == old:
						n["sets_flag"] = new
					if n.get("hidden_when") == old:
						n["hidden_when"] = new
					if (n.get("alt") or {}).get("flag") == old:
						n["alt"]["flag"] = new
				for w in m.get("warps", []):
					if w.get("flag") == old:
						w["flag"] = new
				for c in m.get("chests", []):
					if c.get("flag") == old:
						c["flag"] = new
				for ev in m.get("events", []):
					t = ev.get("trigger") or {}
					if t.get("flag") == old:
						t["flag"] = new
					ev["script"] = script_lang.rename_ident(
						ev.get("script", ""), "flag", old, new)
		self.fl_refresh(i)
		self.say("Flag %s applied" % new)

	def fl_add(self):
		flags = self.db.setdefault("flags", [])
		if len(flags) >= gen_db.MAX_FLAGS:
			messagebox.showerror("Flags", "Max %d flags (save format)."
			                     % gen_db.MAX_FLAGS)
			return
		n = 1
		while "flag%d" % n in flags:
			n += 1
		flags.append("flag%d" % n)
		self.fl_refresh(len(flags) - 1)

	def fl_delete(self):
		i = self.sel(self.fl_lb)
		if i < 0:
			return
		fl = self.db["flags"][i]
		refs = self.fl_refs(fl)
		if refs:
			messagebox.showerror("Delete",
				"Flag used in: %s" % ", ".join(refs))
			return
		del self.db["flags"][i]
		self.fl_refresh()

	# ---- spells ----

	def build_spells_tab(self, sub):
		form, self.sp_lb = self.list_section(sub, "Spells",
			self.sp_select, self.sp_add, self.sp_delete)
		self.sp_id = self.entry_row(form, 0, "ID:")
		self.sp_name = self.entry_row(form, 1, "Name (max 9):", 12)
		self.sp_cost = self.spin_row(form, 2, "MP cost:", 0, 99)
		self.sp_level = self.spin_row(form, 3, "Unlocks at lvl:", 1, 99)
		self.sp_power = self.spin_row(form, 4, "Power:", 1, 255)
		ttk.Label(form, text="Effect:").grid(row=5, column=0,
		                                     sticky="w", pady=1)
		self.sp_effect = tk.StringVar(value="heal")
		ttk.Combobox(form, values=list(gen_db.SPELL_EFFECTS),
		             textvariable=self.sp_effect, state="readonly",
		             width=10).grid(row=5, column=1, sticky="w", pady=1)
		self.sp_all = tk.BooleanVar()
		ttk.Checkbutton(form, text="Hits/heals ALL (party / troop)",
		                variable=self.sp_all).grid(
			row=6, column=0, columnspan=2, sticky="w", pady=2)
		ttk.Button(form, text="Apply", command=self.sp_apply) \
		   .grid(row=7, column=0, pady=8, sticky="w")
		self.sp_refresh()

	def sp_refresh(self, keep=0):
		self.sp_lb.delete(0, "end")
		spells = self.db.setdefault("spells", [])
		for sp in spells:
			self.sp_lb.insert("end", sp["id"])
		if spells:
			self.sp_lb.selection_set(min(keep, len(spells) - 1))
			self.sp_select()

	def sp_select(self):
		i = self.sel(self.sp_lb)
		if i < 0:
			return
		sp = self.db["spells"][i]
		self.sp_id.set(sp["id"])
		self.sp_name.set(sp["name"])
		self.sp_cost.set(sp["cost"])
		self.sp_level.set(sp["level"])
		self.sp_power.set(sp["power"])
		self.sp_effect.set(sp["effect"])
		self.sp_all.set(bool(sp.get("all")))

	def sp_apply(self):
		i = self.sel(self.sp_lb)
		if i < 0:
			return
		sp = self.db["spells"][i]
		old = sp["id"]
		new = self.sp_id.get().strip()
		if not new.isidentifier():
			messagebox.showerror("Spell", "ID must be a C identifier.")
			return
		if new != old and any(x["id"] == new for x in self.db["spells"]):
			messagebox.showerror("Spell", "Duplicate id.")
			return
		name = self.sp_name.get().strip() or new
		if len(name) > 9:
			messagebox.showerror("Spell",
				"Name over 9 chars breaks the menu.")
			return
		sp["id"] = new
		sp["name"] = name
		sp["cost"] = self.sp_cost.get()
		sp["level"] = self.sp_level.get()
		sp["power"] = self.sp_power.get()
		sp["effect"] = self.sp_effect.get()
		sp["all"] = self.sp_all.get()
		if new != old:                       # propagate into players
			for pl in self.db["players"]:
				if "spells" in pl:
					pl["spells"] = [new if x == old else x
					                for x in pl["spells"]]
		self.sp_refresh(i)
		self.say("Spell %s applied" % new)

	def sp_add(self):
		sid = self.new_id(self.db.setdefault("spells", []), "spell")
		self.db["spells"].append({"id": sid, "name": sid.title()[:9],
			"cost": 2, "level": 1, "power": 8, "effect": "heal",
			"all": False})
		self.sp_refresh(len(self.db["spells"]) - 1)

	def sp_delete(self):
		i = self.sel(self.sp_lb)
		if i < 0:
			return
		sid = self.db["spells"][i]["id"]
		refs = [pl["id"] for pl in self.db["players"]
		        if sid in pl.get("spells", [])]
		if refs:
			messagebox.showerror("Delete",
				"Known by players: %s" % ", ".join(refs))
			return
		del self.db["spells"][i]
		self.sp_refresh()

	# ---- bosses ----

	def build_bosses_tab(self, sub):
		form, self.b_lb = self.list_section(sub, "Bosses",
			self.b_select, self.b_add, self.b_delete)
		self.b_id = self.entry_row(form, 0, "ID:")
		ttk.Label(form, text="Troop fought:").grid(row=1, column=0,
		                                           sticky="w", pady=1)
		self.b_troop = tk.StringVar()
		self.b_troop_cb = ttk.Combobox(form, textvariable=self.b_troop,
		                               state="readonly", width=16)
		self.b_troop_cb.grid(row=1, column=1, sticky="w", pady=1)
		self.b_sprite = ttk.Label(form, text="(no sprite)")
		self.b_sprite.grid(row=2, column=1, sticky="w", pady=2)
		ttk.Button(form, text="Import 16x16 sprite...",
		           command=self.b_import).grid(row=2, column=0,
		                                       sticky="w", pady=2)
		ttk.Label(form, text="Battle music:").grid(row=3, column=0,
		                                           sticky="w", pady=1)
		self.b_music = tk.StringVar()
		self.b_music_cb = ttk.Combobox(form, textvariable=self.b_music,
		                               state="readonly", width=16,
		                               values=["(default)"]
		                                      + self.music_stems())
		self.b_music_cb.grid(row=3, column=1, sticky="w", pady=1)
		ttk.Label(form, text="Place him: NPC dialog >\n"
		          "Boss dropdown. Victory sets the\n"
		          "NPC's flag; its alt dialog =\n"
		          "beaten (no rematch).").grid(
			row=4, column=0, columnspan=2, sticky="w", pady=4)
		ttk.Button(form, text="Apply", command=self.b_apply) \
		   .grid(row=5, column=0, pady=8, sticky="w")
		self.b_refresh()

	def b_refresh(self, keep=0):
		self.b_lb.delete(0, "end")
		bosses = self.db.setdefault("bosses", [])
		for b in bosses:
			self.b_lb.insert("end", b["id"])
		self.b_troop_cb["values"] = [t["id"] for t in self.db["troops"]]
		if bosses:
			self.b_lb.selection_set(min(keep, len(bosses) - 1))
			self.b_select()

	def b_select(self):
		i = self.sel(self.b_lb)
		if i < 0:
			return
		b = self.db["bosses"][i]
		self.b_id.set(b["id"])
		self.b_troop.set(b.get("troop", ""))
		self.b_music.set(b.get("music") or "(default)")
		self.b_sprite.config(text=b.get("sprite") or "(no sprite)")

	def b_apply(self):
		i = self.sel(self.b_lb)
		if i < 0:
			return
		b = self.db["bosses"][i]
		old = b["id"]
		new = self.b_id.get().strip()
		if not new.isidentifier():
			messagebox.showerror("Boss", "ID must be a C identifier.")
			return
		if new != old and any(x["id"] == new for x in self.db["bosses"]):
			messagebox.showerror("Boss", "Duplicate id.")
			return
		if not self.b_troop.get():
			messagebox.showerror("Boss", "Pick the troop he fights as.")
			return
		b["id"] = new
		b["troop"] = self.b_troop.get()
		if self.b_music.get() in ("", "(default)"):
			b.pop("music", None)
		else:
			b["music"] = self.b_music.get()
		if new != old:                       # propagate into NPCs
			for m in self.maps["maps"]:
				for n in m.get("npcs", []):
					if n.get("boss") == old:
						n["boss"] = new
		self.b_refresh(i)
		self.say("Boss %s applied" % new)

	def b_import(self):
		i = self.sel(self.b_lb)
		if i < 0:
			return
		path = filedialog.askopenfilename(
			filetypes=[("PNG images", "*.png")])
		if not path:
			return
		img = Image.open(path)
		if img.size != (16, 16):
			messagebox.showerror("Sprite",
				"Boss sprite must be exactly 16x16 (this is %dx%d)."
				% img.size)
			return
		b = self.db["bosses"][i]
		dest = b["id"] + ".png"
		os.makedirs(os.path.join(ROOT, "gfx", "bosses"), exist_ok=True)
		shutil.copy(path, os.path.join(ROOT, "gfx", "bosses", dest))
		b["sprite"] = dest
		self.b_select()
		self.say("Imported %s" % dest)

	def b_add(self):
		bid = self.new_id(self.db.setdefault("bosses", []), "boss")
		self.db["bosses"].append({"id": bid, "sprite": "",
			"troop": self.db["troops"][0]["id"]})
		self.b_refresh(len(self.db["bosses"]) - 1)

	def b_delete(self):
		i = self.sel(self.b_lb)
		if i < 0:
			return
		bid = self.db["bosses"][i]["id"]
		refs = [m["cid"] for m in self.maps["maps"]
		        if any(n.get("boss") == bid for n in m.get("npcs", []))]
		if refs:
			messagebox.showerror("Delete",
				"Placed as an NPC in: %s" % ", ".join(refs))
			return
		del self.db["bosses"][i]
		self.b_refresh()

	# ---- players ----

	CLASS_PRESETS = {
		#         hp  mp atk df ag  ghp gmp gatk gdef gagi  spell effect
		"hero":   (24,  0, 10, 8, 6,  6,  0,  2,  1,  1,  None),
		"mage":   (16,  8,  6, 5, 8,  4,  3,  1,  1,  2,  "fire"),
		"healer": (18, 10,  7, 6, 7,  5,  3,  1,  1,  1,  "heal"),
	}

	def build_players_tab(self, sub):
		form, self.p_lb = self.list_section(sub, "Players",
			self.p_select, self.p_add, self.p_delete)
		self.p_id = self.entry_row(form, 0, "ID:")
		self.p_name = self.entry_row(form, 1, "Name (max %d):"
		                             % gen_db.MAX_PLAYER_NAME)
		ttk.Label(form, text="Class preset:").grid(row=2, column=0,
		                                           sticky="w", pady=1)
		cf = ttk.Frame(form)
		cf.grid(row=2, column=1, columnspan=2, sticky="w", pady=1)
		self.p_class = tk.StringVar()
		ttk.Combobox(cf, textvariable=self.p_class, state="readonly",
		             width=8, values=list(self.CLASS_PRESETS)) \
		   .pack(side="left")
		ttk.Button(cf, text="Apply preset",
		           command=self.p_preset).pack(side="left", padx=4)
		self.p_base, self.p_gain = {}, {}
		labels = [("hp", "HP"), ("mp", "MP"), ("atk", "Attack"),
		          ("def", "Defense"), ("agi", "Agility")]
		ttk.Label(form, text="Base").grid(row=3, column=1)
		ttk.Label(form, text="Per level").grid(row=3, column=2)
		for r, (key, label) in enumerate(labels, start=4):
			ttk.Label(form, text=label + ":").grid(row=r, column=0,
			                                       sticky="w", pady=1)
			bv, gv = tk.IntVar(), tk.IntVar()
			ttk.Spinbox(form, from_=0, to=999, textvariable=bv,
			            width=6).grid(row=r, column=1, pady=1)
			ttk.Spinbox(form, from_=0, to=99, textvariable=gv,
			            width=6).grid(row=r, column=2, pady=1)
			self.p_base[key] = bv
			self.p_gain["g" + key] = gv
		ttk.Label(form, text="Spells (max %d):"
		          % gen_db.MAX_SPELLS).grid(row=9, column=0,
		                                    sticky="nw", pady=2)
		self.p_spells = tk.Listbox(form, selectmode="multiple",
		                           height=6, exportselection=False,
		                           width=14)
		self.p_spells.grid(row=9, column=1, columnspan=2,
		                   sticky="w", pady=2)
		spf = ttk.Frame(form)
		spf.grid(row=10, column=0, columnspan=3, sticky="w", pady=2)
		ttk.Label(spf, text="Walk sheet (64x32):").pack(side="left")
		self.p_sprite = tk.StringVar()
		self.p_sprite_cb = ttk.Combobox(
			spf, textvariable=self.p_sprite, state="readonly",
			width=12,
			values=["(hero art)"] + self.player_sprite_stems())
		self.p_sprite_cb.pack(side="left", padx=4)
		ttk.Button(spf, text="Import...",
		           command=self.p_import).pack(side="left", padx=2)
		ttk.Label(form, text="Up to %d characters; %d fight at\n"
		          "once. Members join/leave via NPC\n"
		          "recruiting or script join/leave.\n"
		          "Benched members keep their level."
		          % (gen_db.MAX_PLAYERS, gen_db.PARTY_MAX)).grid(
			row=11, column=0, columnspan=3, sticky="w", pady=4)
		ttk.Button(form, text="Apply", command=self.p_apply) \
		   .grid(row=12, column=0, pady=8, sticky="w")
		self.p_refresh()

	def p_refresh(self, keep=0):
		self.p_lb.delete(0, "end")
		for p in self.db["players"]:
			self.p_lb.insert("end", p["id"])
		self.p_lb.selection_set(min(keep,
		                            len(self.db["players"]) - 1))
		self.p_select()

	def p_select(self):
		i = self.sel(self.p_lb)
		if i < 0:
			return
		p = self.db["players"][i]
		self.p_id.set(p["id"])
		self.p_name.set(p["name"])
		self.p_class.set(p.get("class") or "hero")
		self.p_sprite_cb["values"] = ["(hero art)"] \
		                             + self.player_sprite_stems()
		self.p_sprite.set(p.get("sprite") or "(hero art)")
		for k, v in self.p_base.items():
			v.set(p[k])
		for k, v in self.p_gain.items():
			v.set(p[k])
		self.p_spells.delete(0, "end")
		spell_ids = [sp["id"] for sp in self.db.get("spells", [])]
		for sid in spell_ids:
			self.p_spells.insert("end", sid)
		for k, sid in enumerate(spell_ids):
			if sid in p.get("spells", []):
				self.p_spells.selection_set(k)

	def p_preset(self):
		"""Stamp the selected class template onto the form (Apply
		still commits): stat bases/gains plus every existing spell
		matching the class's effect (never invents spells)."""
		t = self.CLASS_PRESETS.get(self.p_class.get())
		if not t:
			return
		keys = ("hp", "mp", "atk", "def", "agi")
		for k, v in zip(keys, t[:5]):
			self.p_base[k].set(v)
		for k, v in zip(keys, t[5:10]):
			self.p_gain["g" + k].set(v)
		effect = t[10]
		self.p_spells.selection_clear(0, "end")
		if effect:
			n = 0
			for k, sp in enumerate(self.db.get("spells", [])):
				if sp.get("effect") == effect and n < gen_db.MAX_SPELLS:
					self.p_spells.selection_set(k)
					n += 1
		self.say("Preset %s staged -- hit Apply" % self.p_class.get())

	def p_refs(self, pid):
		"""Maps referencing this player (recruiters + scripts)."""
		refs = []
		for m in self.maps["maps"]:
			hit = any(n.get("joins") == pid
			          for n in m.get("npcs", []))
			hit = hit or any(
				script_lang.uses_ident(ev.get("script", ""),
				                       "player", pid)
				for ev in m.get("events", []))
			if hit:
				refs.append(m["cid"])
		return refs

	def p_apply(self):
		i = self.sel(self.p_lb)
		if i < 0:
			return
		p = self.db["players"][i]
		old = p["id"]
		new = self.p_id.get().strip()
		if not new.isidentifier():
			messagebox.showerror("Player", "ID must be a C identifier.")
			return
		if new != old and any(x["id"] == new
		                      for x in self.db["players"]):
			messagebox.showerror("Player", "Duplicate id.")
			return
		name = self.p_name.get().strip() or p["name"]
		if len(name) > gen_db.MAX_PLAYER_NAME:
			messagebox.showerror("Player",
				"Name over %d chars breaks the status window."
				% gen_db.MAX_PLAYER_NAME)
			return
		sel = [self.p_spells.get(k)
		       for k in self.p_spells.curselection()]
		if len(sel) > gen_db.MAX_SPELLS:
			messagebox.showerror("Player", "Max %d spells."
			                     % gen_db.MAX_SPELLS)
			return
		p["id"] = new
		p["name"] = name
		p["class"] = self.p_class.get() or "hero"
		p["sprite"] = None if self.p_sprite.get() == "(hero art)" \
		              else self.p_sprite.get()
		for k, v in self.p_base.items():
			p[k] = v.get()
		for k, v in self.p_gain.items():
			p[k] = v.get()
		p["spells"] = sel
		p.pop("can_heal", None)
		p.pop("heal_cost", None)
		if new != old:                       # propagate everywhere
			sp = self.project.get("start_party") or []
			self.project["start_party"] = [new if x == old else x
			                               for x in sp]
			for m in self.maps["maps"]:
				for n in m.get("npcs", []):
					if n.get("joins") == old:
						n["joins"] = new
				for ev in m.get("events", []):
					ev["script"] = script_lang.rename_ident(
						ev.get("script", ""), "player", old, new)
			if hasattr(self, "pr_party"):
				self.refresh_start_party()
		self.p_refresh(i)
		self.say("Player %s applied" % new)

	def p_import(self):
		i = self.sel(self.p_lb)
		if i < 0:
			return
		path = filedialog.askopenfilename(
			filetypes=[("PNG images", "*.png")])
		if not path:
			return
		img = Image.open(path)
		if img.size != (64, 32):
			messagebox.showerror("Walk sheet",
				"Player sheet must be 64x32 like hero.png "
				"(this is %dx%d)." % img.size)
			return
		p = self.db["players"][i]
		dest = p["id"] + ".png"
		os.makedirs(os.path.join(ROOT, "gfx", "players"),
		            exist_ok=True)
		shutil.copy(path, os.path.join(ROOT, "gfx", "players", dest))
		p["sprite"] = p["id"]
		self.p_select()
		self.say("Imported %s" % dest)

	def p_add(self):
		if len(self.db["players"]) >= gen_db.MAX_PLAYERS:
			messagebox.showerror("Players", "Max %d characters "
			                     "(save format)." % gen_db.MAX_PLAYERS)
			return
		pid = self.new_id(self.db["players"], "player")
		t = self.CLASS_PRESETS["hero"]
		self.db["players"].append({
			"id": pid, "name": pid.upper()[:gen_db.MAX_PLAYER_NAME],
			"class": "hero", "sprite": None,
			"hp": t[0], "mp": t[1], "atk": t[2], "def": t[3],
			"agi": t[4], "ghp": t[5], "gmp": t[6], "gatk": t[7],
			"gdef": t[8], "gagi": t[9], "spells": []})
		self.p_refresh(len(self.db["players"]) - 1)
		if hasattr(self, "pr_party"):
			self.refresh_start_party()

	def p_delete(self):
		i = self.sel(self.p_lb)
		if i < 0:
			return
		if len(self.db["players"]) <= 1:
			messagebox.showerror("Delete", "Need at least one "
			                     "character.")
			return
		pid = self.db["players"][i]["id"]
		if pid in (self.project.get("start_party") or []):
			messagebox.showerror("Delete",
				"%s is in the start party (Project tab)." % pid)
			return
		refs = self.p_refs(pid)
		if refs:
			messagebox.showerror("Delete",
				"Recruited or scripted in: %s" % ", ".join(refs))
			return
		del self.db["players"][i]
		self.p_refresh()
		if hasattr(self, "pr_party"):
			self.refresh_start_party()

	# ================= Project tab =================

	def build_project_tab(self):
		tab = ttk.Frame(self.nb)
		self.nb.add(tab, text="Project")
		f = ttk.Frame(tab)
		f.pack(anchor="nw", padx=10, pady=10)

		ttk.Label(f, text="Game name:").grid(row=0, column=0, sticky="w")
		self.pr_name = tk.StringVar(value=self.project["name"])
		ttk.Entry(f, textvariable=self.pr_name, width=24) \
		   .grid(row=0, column=1, sticky="w", pady=2)

		ttk.Label(f, text="Title image (256x192):").grid(
			row=1, column=0, sticky="w", pady=(8, 0))
		self.pr_title_preview = ttk.Label(f)
		self.pr_title_preview.grid(row=2, column=0, columnspan=2, pady=4)
		ttk.Button(f, text="Import title image...",
		           command=self.pr_import_title).grid(row=3, column=0,
		                                              sticky="w")
		self.refresh_title_preview()

		ttk.Label(f, text="Starting items:").grid(row=4, column=0,
		                                          sticky="w", pady=(12, 2))
		self.p_start_frame = ttk.Frame(f)
		self.p_start_frame.grid(row=5, column=0, columnspan=2, sticky="w")
		self.refresh_start_items()

		ttk.Label(f, text="Start party (leader first):").grid(
			row=10, column=0, sticky="w", pady=(12, 2))
		self.p_party_frame = ttk.Frame(f)
		self.p_party_frame.grid(row=11, column=0, columnspan=2,
		                        sticky="w")
		self.refresh_start_party()

		self.pr_music = {}
		for r, (key, label) in enumerate(
				(("title_music", "Title music:"),
				 ("battle_music", "Battle music:"),
				 ("victory_music", "Victory music:")), start=6):
			ttk.Label(f, text=label).grid(
				row=r, column=0, sticky="w",
				pady=(12, 1) if r == 6 else 1)
			var = tk.StringVar(value=self.project.get(key) or "(none)")
			cb = ttk.Combobox(f, textvariable=var, state="readonly",
			                  width=16,
			                  values=["(none)"] + self.music_stems())
			cb.grid(row=r, column=1, sticky="w",
			        pady=(12, 1) if r == 6 else 1)
			self.pr_music[key] = (var, cb)
		ttk.Label(f, text="Battle music: encounters + bosses\n"
		          "without their own track. (none) =\n"
		          "the map track keeps playing.\n"
		          "Victory music: plays ONCE after any\n"
		          "won battle (incl. bosses); the map\n"
		          "track resumes back on the field.").grid(
			row=9, column=0, columnspan=2, sticky="w", pady=4)

	def refresh_title_preview(self):
		path = os.path.join(ROOT, "gfx", "title.png")
		if os.path.exists(path):
			img = Image.open(path).convert("RGB").resize((160, 120))
			self._title_photo = ImageTk.PhotoImage(img)
			self.pr_title_preview.config(image=self._title_photo)

	def pr_import_title(self):
		path = filedialog.askopenfilename(
			filetypes=[("PNG images", "*.png")])
		if not path:
			return
		img = Image.open(path)
		if img.size != (256, 192):
			if not messagebox.askyesno("Title image",
					"Image is %dx%d, not 256x192.\nResize on import?"
					% img.size):
				return
			img = img.convert("RGB").resize((256, 192))
			img.save(os.path.join(ROOT, "gfx", "title.png"))
		else:
			shutil.copy(path, os.path.join(ROOT, "gfx", "title.png"))
		self.refresh_title_preview()
		self.say("Title image imported (converted at next Build)")

	def refresh_start_party(self):
		for w in self.p_party_frame.winfo_children():
			w.destroy()
		self.pr_party = []
		start = self.project.get("start_party") or []
		pids = [p["id"] for p in self.db["players"]]
		labels = ("Leader:", "Member 2:", "Member 3:")
		for r in range(gen_db.PARTY_MAX):
			ttk.Label(self.p_party_frame, text=labels[r]).grid(
				row=r, column=0, sticky="w", pady=1)
			cur = start[r] if r < len(start) else "(none)"
			v = tk.StringVar(value=cur)
			vals = pids if r == 0 else ["(none)"] + pids
			ttk.Combobox(self.p_party_frame, values=vals,
			             textvariable=v, state="readonly",
			             width=14).grid(row=r, column=1,
			                            sticky="w", pady=1)
			self.pr_party.append(v)

	def refresh_start_items(self):
		for w in self.p_start_frame.winfo_children():
			w.destroy()
		self.pr_start = {}
		start = self.project.setdefault("start_items", {})
		for r, it in enumerate(self.db["items"]):
			ttk.Label(self.p_start_frame, text=it["name"] + ":").grid(
				row=r, column=0, sticky="w", pady=1)
			v = tk.IntVar(value=start.get(it["id"], 0))
			ttk.Spinbox(self.p_start_frame, from_=0, to=9, textvariable=v,
			            width=4).grid(row=r, column=1, sticky="w", pady=1)
			self.pr_start[it["id"]] = v

	def apply_project(self):
		self.project["name"] = self.pr_name.get().strip() or "Miniquest"
		self.project["start_items"] = {
			iid: v.get() for iid, v in self.pr_start.items() if v.get() > 0}
		party = []
		for v in self.pr_party:
			pid = v.get()
			if pid and pid != "(none)" and pid not in party:
				party.append(pid)
		if party:                    # gen_db validates ids + count
			self.project["start_party"] = party
		for key, (var, _) in self.pr_music.items():
			v = var.get()
			self.project[key] = None if v == "(none)" else v


if __name__ == "__main__":
	Editor()
