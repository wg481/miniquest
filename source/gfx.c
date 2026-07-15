/* gfx.c -- everything that touches DS video hardware (main engine).
 *
 * Layout:
 *   Main BG0 : 8bpp text BG, 512x512 (64x64 hw tiles) -> the map / battle
 *   Main OBJ : 8bpp sprites, 1D mapping -> hero, NPCs, battle enemies
 *   Sub      : text console, set up in ui.c
 *
 * Each 16x16 game tile is four 8x8 hardware tiles stored contiguously
 * (see tools/png2ds.py), so game tile t = hw tiles t*4 .. t*4+3.
 */
#include "gfx.h"
#include "gfx_data.h"
#include "maps.h"                /* tilesetDefs */

static int bgId;
static u16 *bgMap;
static int loadedTileset = -1;   /* TILESET_ id resident in BG VRAM */

#include "db.h"

/* walkers: party slot 0 (leader) + up to two followers. Each slot
 * owns an 8-frame buffer, filled from a player's 64x32 sheet by
 * gfxLoadWalker (NULL = hero.png art). */
static u16 *walkerGfx[PARTY_MAX][HERO_FRAMES];
static u16 *npcGfx[MAX_NPCS];            /* per-slot: NPC1 or a boss */
static u16 *enemyGfx[MAX_TROOP];

void gfxInit(void)
{
	videoSetMode(MODE_0_2D);
	vramSetBankA(VRAM_A_MAIN_BG);
	vramSetBankB(VRAM_B_MAIN_SPRITE);
	lcdMainOnTop();

	/* map base 0 (2K units): 512x512 map = 8K = bases 0-3.
	 * tile base 1 (16K units) sits safely above it. */
	bgId = bgInit(0, BgType_Text8bpp, BgSize_T_512x512, 0, 1);
	bgMap = (u16 *)bgGetMapPtr(bgId);

	gfxLoadGame();

	oamInit(&oamMain, SpriteMapping_1D_128, false);
	dmaCopy(objPal, SPRITE_PALETTE, 256 * 2);

	for (int w = 0; w < PARTY_MAX; w++)
		for (int f = 0; f < HERO_FRAMES; f++) {
			walkerGfx[w][f] = oamAllocateGfx(&oamMain,
			                       SpriteSize_16x16,
			                       SpriteColorFormat_256Color);
			dmaCopy((u8 *)heroGfxData + f * FRAME16_BYTES,
			        walkerGfx[w][f], FRAME16_BYTES);
		}
	for (int i = 0; i < MAX_NPCS; i++) {
		npcGfx[i] = oamAllocateGfx(&oamMain, SpriteSize_16x16,
		                           SpriteColorFormat_256Color);
		dmaCopy(npcGfxData, npcGfx[i], FRAME16_BYTES);
	}

	for (int e = 0; e < MAX_TROOP; e++)
		enemyGfx[e] = oamAllocateGfx(&oamMain, SpriteSize_64x64,
		                             SpriteColorFormat_256Color);
}

/* -- BG plotting ---------------------------------------------------- */

/* 512x512 text BGs are four 32x32 screenblocks in quadrant order;
 * this converts hw-tile (x,y) to a map entry index. */
static inline int entryIndex(int x, int y)
{
	return ((y & 31) * 32 + (x & 31))
	     + ((x >> 5) ? 0x400 : 0)
	     + ((y >> 5) ? 0x800 : 0);
}

static inline void set8(int x, int y, int hwTile, bool hf, bool vf)
{
	bgMap[entryIndex(x, y)] =
		hwTile | (hf ? BIT(10) : 0) | (vf ? BIT(11) : 0);
}

static void setTile16(int tx, int ty, int gameTile)
{
	int base = gameTile * 4;
	set8(tx * 2,     ty * 2,     base + 0, false, false);
	set8(tx * 2 + 1, ty * 2,     base + 1, false, false);
	set8(tx * 2,     ty * 2 + 1, base + 2, false, false);
	set8(tx * 2 + 1, ty * 2 + 1, base + 3, false, false);
}

/* Restore the game's shared BG state: palette + menu border tiles.
 * Tile-art slots 0..MENU_TILE_BASE-1 belong to the current map's
 * tileset, (re)loaded by gfxLoadTileset -- invalidated here because
 * the title screen overwrites all of BG VRAM. */
void gfxLoadGame(void)
{
	dmaCopy(menuTiles8Data, (u8 *)bgGetGfxPtr(bgId)
	        + MENU_TILE_BASE * 64,
	        (N_BG_HW_TILES - MENU_TILE_BASE) * 64);
	dmaCopy(bgPal, BG_PALETTE, 256 * 2);
	loadedTileset = -1;
}

/* Copy a tileset's art into BG VRAM (no-op when already resident).
 * fieldEnter calls this on every map change; all tilesets share the
 * BG palette, so only the tile pixels move. */
void gfxLoadTileset(int ts)
{
	if (ts == loadedTileset)
		return;
	dmaCopy(tilesetDefs[ts].gfx, bgGetGfxPtr(bgId),
	        TILESET_TILES * 4 * 64);
	loadedTileset = ts;
}

/* Show the title image: its own tiles + palette replace the game set
 * (gfxLoadGame() restores them before entering the field). */
void gfxShowTitle(void)
{
	gfxScroll(0, 0);
	dmaCopy(titleTiles, bgGetGfxPtr(bgId), N_TITLE_TILES * 64);
	dmaCopy(titlePal, BG_PALETTE, 256 * 2);
	for (int y = 0; y < 32; y++)
		for (int x = 0; x < 32; x++)
			set8(x * 2, y * 2, 0, false, false);   /* clear to tile 0 */
	for (int y = 0; y < 24; y++)
		for (int x = 0; x < 32; x++)
			set8(x, y, titleMap[y * 32 + x], false, false);
}

void gfxDrawMap(const MapDef *m)
{
	for (int y = 0; y < 32; y++)
		for (int x = 0; x < 32; x++)
			setTile16(x, y, mapTileAt(m, x, y));   /* T_BLACK outside */
}

void gfxScroll(int px, int py)
{
	bgSetScroll(bgId, px, py);
}

/* -- sprites --------------------------------------------------------- */

/* refill a walker slot's 8 frames from a player's sheet; NULL keeps
 * the classic behavior: hero.png art */
void gfxLoadWalker(int slot, const unsigned short *sheet)
{
	const u8 *src = (const u8 *)(sheet ? sheet : heroGfxData);
	for (int f = 0; f < HERO_FRAMES; f++)
		dmaCopy(src + f * FRAME16_BYTES,
		        walkerGfx[slot][f], FRAME16_BYTES);
}

/* every player sheet uses hero.png's layout:
 *   row 0 = down f1,f2, left f1,f2 / row 1 = up f1,f2, right f1,f2
 * so with DIR_DOWN,LEFT,UP,RIGHT = 0..3: frame = dir*2 + step */
void gfxWalkerSprite(int slot, int sx, int sy, int dir, int step,
                     bool hide)
{
	static const int oam[PARTY_MAX] = {
		SPR_HERO, SPR_FOLLOW0, SPR_FOLLOW1
	};
	oamSet(&oamMain, oam[slot], sx, sy, 0, 0,
	       SpriteSize_16x16, SpriteColorFormat_256Color,
	       walkerGfx[slot][dir * 2 + step],
	       -1, false, hide, false, false, false);
}

/* Load a slot's field sprite: a boss's 16x16, or NULL for NPC1 art. */
void gfxLoadNpc(int slot, const unsigned short *gfx)
{
	dmaCopy(gfx ? gfx : npcGfxData, npcGfx[slot], FRAME16_BYTES);
}

void gfxNpcSprite(int slot, int sx, int sy, bool hide)
{
	oamSet(&oamMain, SPR_NPC0 + slot, sx, sy, 0, 0,
	       SpriteSize_16x16, SpriteColorFormat_256Color,
	       npcGfx[slot], -1, false, hide, false, false, false);
}

void gfxHideFieldSprites(void)
{
	oamSetHidden(&oamMain, SPR_HERO, true);
	oamSetHidden(&oamMain, SPR_FOLLOW0, true);
	oamSetHidden(&oamMain, SPR_FOLLOW1, true);
	for (int i = 0; i < MAX_NPCS; i++)
		oamSetHidden(&oamMain, SPR_NPC0 + i, true);
}

void gfxLoadEnemy(int slot, const unsigned short *gfx)
{
	dmaCopy(gfx, enemyGfx[slot], FRAME64_BYTES);
}

void gfxEnemySprite(int slot, int sx, int sy, bool hide)
{
	oamSet(&oamMain, SPR_ENEMY0 + slot, sx, sy, 0, 0,
	       SpriteSize_64x64, SpriteColorFormat_256Color,
	       enemyGfx[slot], -1, false, hide, false, false, false);
}

/* -- battle backdrop -------------------------------------------------
 * With backdrop art: the map's 192x128 image (24x16 hw tiles from
 * png2ds) fills the window rect, and a menu-tile border is drawn one
 * hw tile OUTSIDE it so the picture sits in a clean frame. Its tiles
 * live above the game set in BG VRAM, loaded here per battle -- one
 * resident at a time, so the backdrop count is unbounded. The map
 * redraw after battle only touches map entries, so nothing needs
 * restoring.
 * Without: black screen with a bordered window built from the menu
 * tiles: MENU_TILE_BASE +0 corner, +1 vert edge, +2 horiz edge,
 * +3 fill.
 */

/* menu-tile border on a hw-tile rect: edges + mirrored corners only
 * (menu.png order: +0 corner, +1 VERTICAL edge, +2 HORIZONTAL edge) */
static void borderRect(int x0, int y0, int x1, int y1)
{
	const int C = MENU_TILE_BASE, V = MENU_TILE_BASE + 1,
	          H = MENU_TILE_BASE + 2;

	for (int x = x0 + 1; x < x1; x++) {
		set8(x, y0, H, false, false);
		set8(x, y1, H, false, true);
	}
	for (int y = y0 + 1; y < y1; y++) {
		set8(x0, y, V, false, false);
		set8(x1, y, V, true, false);
	}
	set8(x0, y0, C, false, false);
	set8(x1, y0, C, true,  false);
	set8(x0, y1, C, false, true);
	set8(x1, y1, C, true,  true);
}

void gfxBattleScene(const unsigned short *bd)
{
	/* battles always start from the field, so a tileset is resident */
	int fill = tilesetDefs[loadedTileset < 0 ? 0
	                       : loadedTileset].voidTile;
	gfxScroll(0, 0);

	for (int y = 0; y < 32; y++)
		for (int x = 0; x < 32; x++)
			setTile16(x, y, fill);

	const int x0 = 4, y0 = 2, x1 = 27, y1 = 17;   /* hw-tile rect */

	if (bd) {
		dmaCopy(bd, (u8 *)bgGetGfxPtr(bgId) + N_BG_HW_TILES * 64,
		        BACKDROP_HW_TILES * 64);
		for (int ty = 0; ty < 16; ty++)
			for (int tx = 0; tx < 24; tx++)
				set8(x0 + tx, y0 + ty,
				     N_BG_HW_TILES + ty * 24 + tx, false, false);
		borderRect(x0 - 1, y0 - 1, x1 + 1, y1 + 1);
		return;
	}

	const int F = MENU_TILE_BASE + 3;

	for (int y = y0 + 1; y < y1; y++)
		for (int x = x0 + 1; x < x1; x++)
			set8(x, y, F, false, false);

	borderRect(x0, y0, x1, y1);
}

void gfxFlush(void)
{
	bgUpdate();
	oamUpdate(&oamMain);
}
