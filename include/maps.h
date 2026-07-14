#ifndef MAPS_H
#define MAPS_H

#include "game.h"

#define MAX_NPCS        4
#define MAX_WARPS       4
#define MAX_SIGNS       2
#define MAX_ZONE_TROOPS 4
#define MAX_SHOP_ITEMS  6        /* keep in sync with gen_maps.py */
#define MAX_CHESTS      4        /* keep in sync with gen_maps.py */
#define TILESET_TILES   24       /* keep in sync with gen_maps.py +
                                    png2ds.py (128x48 PNG, 8x3 grid) */

/* One entry per data/tilesets.json tileset; table generated into
 * maps.c, gfx arrays by png2ds. All tilesets share the BG palette. */
typedef struct {
	const unsigned short *gfx; /* TILESET_TILES*4 8bpp hw tiles */
	u32 solid;                 /* bit t set = tile t blocks walking */
	u8 voidTile;               /* drawn outside map bounds and as the
	                              battle-scene background fill */
} TilesetDef;

extern const TilesetDef tilesetDefs[];   /* [N_TILESETS] */

typedef struct { u8 troop; u8 weight; } ZoneEntry;

typedef struct {
	char zone;               /* '0'..'7' painted in the zone layer */
	u8 rate;                 /* encounter chance = 1 in rate steps */
	u8 n;
	ZoneEntry e[MAX_ZONE_TROOPS];
} ZoneDef;

typedef struct {
	int x, y;
	const char *text;        /* one dialog line (\n allowed) */
	bool healer;             /* talking restores the party */
	u8 nShop;                /* >0 = shopkeeper; healer must be false */
	u8 shop[MAX_SHOP_ITEMS]; /* ITEM_ indices for sale */
	s16 setsFlag;            /* FLAG_ set after talking; boss: set on
	                            VICTORY instead; -1 = none.
	                            s16: flag indices run 0..N_VARS-1 (255),
	                            which overflows s8 */
	s16 altFlag;             /* if set, show altText instead; -1 = none */
	const char *altText;
	s8 boss;                 /* BOSS_ id: talk -> dialogue -> fight;
	                            altFlag set = beaten, no rematch; -1 */
	const unsigned short *sprite; /* 16x16 OBJ tiles from png2ds
	                            (npcSprite_<stem>); NULL = NPC1 art.
	                            A boss NPC still shows its boss sprite;
	                            this only overrides plain NPCs. */
} Npc;

typedef struct {
	int x, y;                /* stepping here triggers the warp */
	int destMap, destX, destY;
	s16 flag;                /* FLAG_ required to pass; -1 = open
	                            (s16: flag indices reach 255) */
	const char *lockedText;  /* shown when the flag isn't set */
} Warp;

typedef struct {
	int x, y;                /* on a 'c' tile; opened by A, like signs */
	u8 item;                 /* ITEM_ given once */
	u8 flag;                 /* FLAG_ marking it opened */
} Chest;

typedef struct {
	int x, y;
	const char *text;
} Sign;

/* map events -> scripts (tools/gen_scripts.py) */
enum { EVT_LOAD = 0, EVT_FLAG, EVT_TILE };
#define MAX_EVENTS 8             /* keep in sync with gen_scripts.py */

typedef struct {
	u8 kind;                 /* EVT_LOAD / EVT_FLAG / EVT_TILE */
	s16 flag;                /* EVT_FLAG: trigger flag;
	                            EVT_TILE: gate flag or -1; else -1 */
	u8 x, y;                 /* EVT_TILE only */
	u16 script;              /* index into scriptOffset[] */
} Event;

typedef struct {
	const char *name;
	int w, h;
	const unsigned char *tiles; /* w*h tile indices, row-major */
	u8 tileset;                 /* TILESET_ index into tilesetDefs */
	int nNpcs;   Npc  npcs[MAX_NPCS];
	int nWarps;  Warp warps[MAX_WARPS];
	int nSigns;  Sign signs[MAX_SIGNS];
	int nChests; Chest chests[MAX_CHESTS];
	int nEvents; Event events[MAX_EVENTS];
	const char *const *zoneRows;   /* NULL = no encounters on this map */
	int nZones;
	const ZoneDef *zones;
	int music;                     /* MOD_ id from soundbank.h; -1 = off */
	const unsigned short *backdrop;/* 384 hw tiles (24x16, row-major)
	                                  from png2ds; NULL = menu frame */
} MapDef;

extern const MapDef maps[N_MAPS];

int  mapTileAt(const MapDef *m, int x, int y);   /* game tile id */
bool mapSolid(const MapDef *m, int x, int y);

#endif
