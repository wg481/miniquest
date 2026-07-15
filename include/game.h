#ifndef GAME_H
#define GAME_H

#include <nds.h>
#include <stdlib.h>

/* ---- 16x16 game tiles of the DEFAULT tileset, in
 * gfx/tilesets/default.png order. Reference only: since custom
 * tilesets landed, the engine reads collision, chest, and void tiles
 * from tilesetDefs (data/tilesets.json) instead of these names. ---- */
enum {
	T_GRASS = 0, T_TREE, T_WATER, T_PATH, T_BLACK, T_BLANK,
	T_MOUNTAIN, T_HOUSE, T_WOOD, T_SIGN,
	T_ROOF, T_ROOF_L, T_ROOF_R, T_BRICK, T_DOOR,
	T_ROOF_LG, T_ROOF_RG,      /* slants composited over grass (baked) */
	T_CHEST,                   /* tileset slot 17 */
};

/* ---- facing, matches hero.png column order ---- */
enum { DIR_DOWN = 0, DIR_LEFT, DIR_UP, DIR_RIGHT };

/* ---- maps: enum + start/death spawn generated from data/maps.json ---- */
#include "map_ids.h"
#include "db_data.h"

/* ---- party ---- */
typedef struct {
	const char *name;
	int hp, maxhp;
	int mp, maxmp;
	int atk, def, agi;
	int level, exp;
	bool defending;          /* battle-only flag */
} Fighter;

#define N_VARS 256               /* event flags/vars; mirrored in the save
                                    (widened from 32 in save version 2) */

#define MAX_PLAYERS 6            /* roster ceiling; the save reserves this
                                    many member slots so adding characters
                                    never breaks old saves (gen_db caps
                                    N_PLAYERS here) */
#define PARTY_MAX   3            /* active members (status UI columns) */

_Static_assert(N_PLAYERS >= 1 && N_PLAYERS <= MAX_PLAYERS,
               "roster size out of range");

typedef struct {
	Fighter roster[MAX_PLAYERS];      /* EVERY playable character keeps
	                                     live state (level/exp persist
	                                     while benched); [0..N_PLAYERS) */
	u8 slot[PARTY_MAX];               /* roster indices of the active
	                                     lineup; slot[0] leads on the map */
	u8 nParty;                        /* 1..PARTY_MAX active members */
	int gold;
	u8 items[N_ITEMS];                /* counts, indexed by ITEM_ enums */
	u16 vars[N_VARS];                 /* event flags, FLAG_ enums index */
} Party;

extern Party party;

/* active member k (0 = leader) */
static inline Fighter *partyMember(int k)
{
	return &party.roster[party.slot[k]];
}

/* partyJoin / partyLeave results */
enum { JOIN_OK = 0, JOIN_ALREADY, JOIN_FULL };
enum { LEAVE_OK = 0, LEAVE_ABSENT, LEAVE_LAST };

int  partyJoin(int playerId);    /* full HP/MP at the saved level */
int  partyLeave(int playerId);   /* LEAVE_LAST: never empties the party */
bool partyHas(int playerId);     /* currently in the active lineup? */

/* field result events */
enum { EV_NONE = 0, EV_ENCOUNTER, EV_BOSS };

/* battleRun results */
enum { BATTLE_LOST = 0, BATTLE_WON, BATTLE_FLED };

void partyInit(void);
void partyRestore(void);
bool itemAdd(int id);            /* respects ITEM_MAX; false when full */
bool flagGet(int id);
void flagSet(int id);
void flagPut(int id, int v);     /* set/clear; 0->1 queues on_flag */

static inline int rnd(int n) { return rand() % n; }   /* 0..n-1 */

#endif
