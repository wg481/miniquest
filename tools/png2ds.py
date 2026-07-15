#!/usr/bin/env python3
"""
png2ds.py -- convert the game's PNG assets into DS-native C arrays.

Run from the project root:  python3 tools/png2ds.py
Regenerates source/gfx_data.c and include/gfx_data.h from gfx/*.png.

Output formats
--------------
Backgrounds (tilesets from data/tilesets.json + menu.png):
	8bpp tiled ("text") background data sharing one 256-color BG palette.
	Each tileset PNG (128x48) is a grid of 24 16x16 game tiles; each
	becomes four 8x8 hardware tiles stored contiguously (TL, TR, BL,
	BR), so game tile t occupies hardware tiles t*4 .. t*4+3. Emitted
	as tilesetGfx_<id>; the engine loads one at a time (gfxLoadTileset).
	menu.png's five 8x8 tiles go in their own array (menuTiles8Data),
	resident above the tileset slots at MENU_TILE_BASE.

Sprites (hero.png, gfx/players/*.png, NPC1.png, enemies, ...):
	8bpp OBJ tile data sharing one 256-color sprite palette.
	Frames are emitted as sequences of 8x8 tiles, row-major within the
	frame, matching SpriteMapping_1D + SpriteColorFormat_256Color.

Magenta (#FF00FF) and fully transparent pixels map to palette index 0
(transparent for sprites; backdrop-colored for backgrounds).
"""

import os
import sys

try:
	from PIL import Image
except ImportError:
	sys.exit("png2ds.py needs Pillow:  pip install Pillow")

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
GFX = os.path.join(ROOT, "gfx")


def rgb555(r, g, b):
	return (r >> 3) | ((g >> 3) << 5) | ((b >> 3) << 10)


def is_transparent(px):
	r, g, b, a = px
	return a < 128 or (r > 240 and g < 30 and b > 240)


class Palette:
	"""Shared palette builder; index 0 is reserved for transparency."""

	def __init__(self):
		self.colors = [0]           # slot 0 = transparent / backdrop
		self.lookup = {}

	def index_of(self, px):
		if is_transparent(px):
			return 0
		c = rgb555(px[0], px[1], px[2])
		if c not in self.lookup:
			if len(self.colors) >= 256:
				sys.exit("palette overflow: more than 256 colors")
			self.lookup[c] = len(self.colors)
			self.colors.append(c)
		return self.lookup[c]


def tile8(im, pal, ox, oy):
	"""One 8x8 tile at pixel offset (ox, oy) -> 64 palette indices."""
	out = []
	for y in range(8):
		for x in range(8):
			out.append(pal.index_of(im.getpixel((ox + x, oy + y))))
	return out


def frames_16(im, pal, cols, rows):
	"""16x16 frames from a sheet; each frame = 4 tiles (TL,TR,BL,BR)."""
	data = []
	for r in range(rows):
		for c in range(cols):
			for sy in (0, 8):
				for sx in (0, 8):
					data += tile8(im, pal, c * 16 + sx, r * 16 + sy)
	return data


def frame_64(im, pal):
	"""One 64x64 frame = 8x8 grid of tiles, row-major."""
	data = []
	for ty in range(8):
		for tx in range(8):
			data += tile8(im, pal, tx * 8, ty * 8)
	return data


def u16_words(byte_list):
	"""Pack 8-bit palette indices into little-endian 16-bit words."""
	assert len(byte_list) % 2 == 0
	return [byte_list[i] | (byte_list[i + 1] << 8)
	        for i in range(0, len(byte_list), 2)]


def emit_array(f, name, words):
	f.write("const unsigned short %s[%d] = {\n" % (name, len(words)))
	for i in range(0, len(words), 12):
		f.write("\t" + ", ".join("0x%04X" % w for w in words[i:i + 12]) + ",\n")
	f.write("};\n\n")


def load(name):
	return Image.open(os.path.join(GFX, name)).convert("RGBA")


def main():
	bg_pal = Palette()
	obj_pal = Palette()

	# ---- backgrounds: tilesets from data/tilesets.json ----
	# Each tileset is a 128x48 PNG = 8x3 grid of 16x16 tiles (24 slots,
	# TILESET_TILES). All tilesets share the one BG palette (backdrops
	# and the menu border tiles bake their indices against it too).
	# roof_composite pairs [src, dest] bake tile src over roof_base
	# into slot dest, so one text BG layer can fake transparency.
	import json
	tsdata = json.load(open(os.path.join(ROOT, "data",
	                                     "tilesets.json")))
	N_GAME_TILES = 24

	def composite_roofs(im, ts):
		def tile_box(i):
			return ((i % 8) * 16, (i // 8) * 16)
		bx, by = tile_box(ts.get("roof_base", 0))
		base = im.crop((bx, by, bx + 16, by + 16))
		for src, dest in ts.get("roof_composite", []):
			sx, sy = tile_box(src)
			st = im.crop((sx, sy, sx + 16, sy + 16))
			merged = base.copy()
			mask = Image.new("L", (16, 16), 0)
			for y in range(16):
				for x in range(16):
					if not is_transparent(st.getpixel((x, y))):
						mask.putpixel((x, y), 255)
			merged.paste(st, (0, 0), mask)
			im.paste(merged, tile_box(dest))

	tileset_data = []
	for ts in tsdata["tilesets"]:
		im = Image.open(os.path.join(ROOT, ts["image"])) \
		          .convert("RGBA")
		if im.size != (128, 48):
			sys.exit("tileset %s: %s must be 128x48 (is %dx%d)"
			         % (ts["id"], ts["image"], im.size[0], im.size[1]))
		composite_roofs(im, ts)
		tileset_data.append((ts["id"], frames_16(im, bg_pal, 8, 3)))

	menu = load("menu.png")
	menu_base_hw = N_GAME_TILES * 4      # hw tile index of menu tile 0
	menu8_bytes = []
	for i in range(menu.width // 8):
		menu8_bytes += tile8(menu, bg_pal, i * 8, 0)

	# ---- sprites ----
	hero = load("hero.png")                          # 4 cols x 2 rows of 16x16
	hero_bytes = frames_16(hero, obj_pal, 4, 2)

	# per-player walking sheets: gfx/players/<stem>.png, 64x32,
	# hero.png layout/frame order. Emitted as playerGfx_<stem>;
	# players whose database entry has no sprite fall back to
	# heroGfxData at load time (gfxLoadWalker). The old hardcoded
	# gfx/mage.png was migrated to gfx/players/mage.png by
	# tools/migrate_party.py.
	player_sheet_data = []
	pdir = os.path.join(GFX, "players")
	if os.path.isdir(pdir):
		for fn in sorted(os.listdir(pdir)):
			if not fn.lower().endswith(".png"):
				continue
			stem = os.path.splitext(fn)[0]
			if not stem.isidentifier():
				sys.exit("player sheet %r: filename (minus .png) must"
				         " be a C identifier" % fn)
			img = Image.open(os.path.join(pdir, fn)).convert("RGBA")
			if img.size != (64, 32):
				sys.exit("player sheet %s: must be 64x32 like "
				         "hero.png (is %dx%d)"
				         % (fn, img.size[0], img.size[1]))
			player_sheet_data.append(
				(stem, frames_16(img, obj_pal, 4, 2)))

	npc = load("NPC1.png")
	npc_bytes = frames_16(npc, obj_pal, 1, 1)

	# per-NPC field sprites: gfx/npcs/<stem>.png, 16x16, 8bpp OBJ tiles
	# sharing the OBJ palette (with hero/NPC1/bosses/enemies, <=255).
	# Emitted as npcSprite_<stem>; NPCs whose maps.json entry has no
	# sprite fall back to npcGfxData (NPC1) at load time.
	npc_sprite_data = []
	ndir = os.path.join(GFX, "npcs")
	if os.path.isdir(ndir):
		for fn in sorted(os.listdir(ndir)):
			if not fn.lower().endswith(".png"):
				continue
			stem = os.path.splitext(fn)[0]
			if not stem.isidentifier():
				sys.exit("npc sprite %r: filename (minus .png) must be"
				         " a C identifier" % fn)
			img = Image.open(os.path.join(ndir, fn)).convert("RGBA")
			if img.size != (16, 16):
				sys.exit("npc sprite %s: must be 16x16 (is %dx%d)"
				         % (fn, img.size[0], img.size[1]))
			npc_sprite_data.append((stem, frames_16(img, obj_pal, 1, 1)))

	# enemies come from the database: gfx/enemies/<sprite>
	db = json.load(open(os.path.join(ROOT, "data", "database.json")))
	enemy_data = []
	for e in db["enemies"]:
		img = Image.open(os.path.join(GFX, "enemies", e["sprite"])) \
		           .convert("RGBA")
		if img.size != (64, 64):
			sys.exit("enemy %s: sprite must be 64x64" % e["id"])
		enemy_data.append((e["id"], frame_64(img, obj_pal)))

	# bosses: 16x16 field sprites under gfx/bosses/<sprite>
	boss_data = []
	for b in db.get("bosses", []):
		img = Image.open(os.path.join(GFX, "bosses", b["sprite"])) \
		           .convert("RGBA")
		if img.size != (16, 16):
			sys.exit("boss %s: sprite must be 16x16" % b["id"])
		boss_data.append((b["id"], frames_16(img, obj_pal, 1, 1)))

	# title screen: 256x192 PNG -> deduplicated 8bpp tiles + map + palette
	title = Image.open(os.path.join(GFX, "title.png")).convert("RGB") \
	             .resize((256, 192))
	tpal_lookup, tpal = {}, [0]
	def tindex(px):
		c = rgb555(px[0], px[1], px[2])
		if c not in tpal_lookup:
			if len(tpal) >= 256:
				sys.exit("title.png: more than 255 colors after RGB555 "
				         "quantization -- reduce colors")
			tpal_lookup[c] = len(tpal)
			tpal.append(c)
		return tpal_lookup[c]
	tile_lookup, ttiles, tmap = {}, [], []
	for ty in range(24):
		for tx in range(32):
			t = bytes(tindex(title.getpixel((tx*8+x, ty*8+y)))
			          for y in range(8) for x in range(8))
			if t not in tile_lookup:
				tile_lookup[t] = len(ttiles) // 64
				ttiles += list(t)
			tmap.append(tile_lookup[t])

	# battle backdrops: gfx/backdrops/<stem>.png, 192x128 = 24x16 hw
	# tiles emitted row-major with NO dedup, so the engine can index
	# tile (tx,ty) as base + ty*24 + tx without a map array. Colors
	# join the shared BG palette (magenta/alpha -> entry 0 = black).
	backdrop_data = []
	bdir = os.path.join(GFX, "backdrops")
	if os.path.isdir(bdir):
		for fn in sorted(os.listdir(bdir)):
			if not fn.lower().endswith(".png"):
				continue
			stem = os.path.splitext(fn)[0]
			if not stem.isidentifier():
				sys.exit("backdrop %r: filename (minus .png) must be"
				         " a C identifier" % fn)
			img = Image.open(os.path.join(bdir, fn)).convert("RGBA")
			if img.size != (192, 128):
				sys.exit("backdrop %s: must be 192x128 (is %dx%d)"
				         % (fn, img.size[0], img.size[1]))
			data = []
			for ty in range(16):
				for tx in range(24):
					data += tile8(img, bg_pal, tx * 8, ty * 8)
			backdrop_data.append((stem, data))

	# ---- 4bpp UI tiles for the sub-screen window layer ----
	# Own 16-color palette (row 1 on the sub screen). Entry 15 of every
	# row is reserved: the libnds console writes its ANSI colors there
	# (see libnds console.c), so we cap at 14 colors + transparent.
	menu_pal = [0]
	menu_lookup = {}

	def menu_index(px):
		if is_transparent(px):
			return 0
		c = rgb555(px[0], px[1], px[2])
		if c not in menu_lookup:
			if len(menu_pal) >= 15:
				sys.exit("UI palette >14 colors (entry 15 is the console's)")
			menu_lookup[c] = len(menu_pal)
			menu_pal.append(c)
		return menu_lookup[c]

	def tile4(im, ox, oy):
		out = []
		for y in range(8):
			for x in range(0, 8, 2):
				lo = menu_index(im.getpixel((ox + x, oy + y)))
				hi = menu_index(im.getpixel((ox + x + 1, oy + y)))
				out.append(lo | (hi << 4))
		return out

	menu4 = [0] * 32                     # tile 0 = blank (transparent)
	for i in range(menu.width // 8):
		menu4 += tile4(menu, i * 8, 0)

	# ---- write C ----
	cpath = os.path.join(ROOT, "source", "gfx_data.c")
	hpath = os.path.join(ROOT, "include", "gfx_data.h")

	with open(cpath, "w") as f:
		f.write("/* Generated by tools/png2ds.py -- do not edit by hand. */\n")
		f.write('#include "gfx_data.h"\n\n')
		pal = bg_pal.colors + [0] * (256 - len(bg_pal.colors))
		emit_array(f, "bgPal", pal)
		pal = obj_pal.colors + [0] * (256 - len(obj_pal.colors))
		emit_array(f, "objPal", pal)
		for tid, tbytes in tileset_data:
			emit_array(f, "tilesetGfx_%s" % tid, u16_words(tbytes))
		emit_array(f, "menuTiles8Data", u16_words(menu8_bytes))
		emit_array(f, "heroGfxData", u16_words(hero_bytes))
		for sid, sbytes in player_sheet_data:
			emit_array(f, "playerGfx_%s" % sid, u16_words(sbytes))
		emit_array(f, "npcGfxData", u16_words(npc_bytes))
		for sid, sbytes in npc_sprite_data:
			emit_array(f, "npcSprite_%s" % sid, u16_words(sbytes))
		for eid, ebytes in enemy_data:
			emit_array(f, "enemyGfx_%s" % eid, u16_words(ebytes))
		for bid, bbytes in boss_data:
			emit_array(f, "bossGfx_%s" % bid, u16_words(bbytes))
		for sid, sbytes in backdrop_data:
			emit_array(f, "backdropGfx_%s" % sid, u16_words(sbytes))
		emit_array(f, "titlePal", tpal + [0] * (256 - len(tpal)))
		emit_array(f, "titleTiles", u16_words(ttiles))
		emit_array(f, "titleMap", tmap)
		emit_array(f, "menuTiles4Data", u16_words(menu4))
		emit_array(f, "menuPal16", menu_pal + [0] * (16 - len(menu_pal)))

	with open(hpath, "w") as f:
		f.write("/* Generated by tools/png2ds.py -- do not edit by hand. */\n")
		f.write("#ifndef GFX_DATA_H\n#define GFX_DATA_H\n\n")
		f.write("#define N_GAME_TILES   %d /* per tileset */\n"
		        % N_GAME_TILES)
		f.write("#define MENU_TILE_BASE %d  /* hw tile index of menu tile 0 */\n" % menu_base_hw)
		f.write("#define N_BG_HW_TILES  %d\n" % (menu_base_hw + menu.width // 8))
		f.write("#define HERO_FRAMES    8   /* frame = dir*2 + step; dirs D,L,U,R */\n")
		f.write("#define FRAME16_BYTES  256 /* one 16x16 8bpp frame */\n")
		f.write("#define FRAME64_BYTES  4096\n")
		f.write("#define N_MENU4_TILES  %d /* 0=blank,1=corner,2=vedge,3=hedge,4=fill,5=cursor */\n\n" % (len(menu4) // 32))
		f.write("#define N_TITLE_TILES  %d\n" % (len(ttiles) // 64))
		for eid, ebytes in enemy_data:
			f.write("extern const unsigned short enemyGfx_%s[%d];\n"
			        % (eid, len(ebytes) // 2))
		for bid, bbytes in boss_data:
			f.write("extern const unsigned short bossGfx_%s[%d];\n"
			        % (bid, len(bbytes) // 2))
		for sid, sbytes in npc_sprite_data:
			f.write("extern const unsigned short npcSprite_%s[%d];\n"
			        % (sid, len(sbytes) // 2))
		for sid, sbytes in player_sheet_data:
			f.write("extern const unsigned short playerGfx_%s[%d];\n"
			        % (sid, len(sbytes) // 2))
		f.write("#define BACKDROP_HW_TILES 384 /* 24x16, row-major */\n")
		for tid, tbytes in tileset_data:
			f.write("extern const unsigned short tilesetGfx_%s[%d];\n"
			        % (tid, len(tbytes) // 2))
		for sid, sbytes in backdrop_data:
			f.write("extern const unsigned short backdropGfx_%s[%d];\n"
			        % (sid, len(sbytes) // 2))
		for n, a in (("bgPal", 256), ("objPal", 256),
		             ("titlePal", 256),
		             ("titleTiles", len(ttiles) // 2),
		             ("titleMap", len(tmap)),
		             ("menuTiles8Data", len(menu8_bytes) // 2),
		             ("heroGfxData", len(hero_bytes) // 2),
		             ("npcGfxData", len(npc_bytes) // 2),

		             ("menuTiles4Data", len(menu4) // 2),
		             ("menuPal16", 16)):
			f.write("extern const unsigned short %s[%d];\n" % (n, a))
		f.write("\n#endif\n")

	print("BG palette: %d colors | OBJ palette: %d colors"
	      % (len(bg_pal.colors), len(obj_pal.colors)))
	print("wrote %s and %s" % (cpath, hpath))


if __name__ == "__main__":
	main()
