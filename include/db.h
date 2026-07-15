#ifndef DB_H
#define DB_H

#include <nds.h>

/* Database types. Instances are generated into db_data.c from
 * data/database.json by tools/gen_db.py. */

typedef struct {
	const char *name;
	const unsigned short *gfx;      /* 64x64 8bpp OBJ frame */
	int hp, atk, def, agi;
	int exp, gold;
} EnemyDef;

#define MAX_TROOP 3

typedef struct {
	const char *name;               /* "a Slime and a Troll" */
	int n;
	u8 members[MAX_TROOP];          /* indices into enemyDefs */
} TroopDef;

typedef struct {
	const char *name;
	int heal;                       /* HP restored (+ small roll) */
	int price;                      /* gold; 0 = shops won't trade it */
} ItemDef;

#define MAX_SPELLS 6                    /* per player; menu height */

enum { SPELL_HEAL = 0, SPELL_FIRE };    /* SpellDef.effect */

typedef struct {
	const char *name;
	u8 cost;                        /* MP */
	u8 level;                       /* unlocks at this level */
	u8 effect;                      /* SPELL_HEAL / SPELL_FIRE */
	u8 power;                       /* heal amount / damage scale */
	bool all;                       /* whole party / all enemies */
} SpellDef;

typedef struct {
	const unsigned short *gfx;      /* 16x16 8bpp OBJ field sprite */
	u8 troop;                       /* troop fought on talk */
	int music;                      /* MOD_ id; -1 = battleMusic */
} BossDef;

typedef struct {
	const char *name;
	int hp, mp, atk, def, agi;      /* base stats at level 1 */
	int ghp, gmp, gatk, gdef, gagi; /* gains per level */
	u8 nSpells;
	u8 spells[MAX_SPELLS];          /* indices into spellDefs */
	const unsigned short *gfx;      /* 64x32 walking sheet (8 frames,
	                                   hero.png layout) from png2ds
	                                   (playerGfx_<stem>); NULL =
	                                   hero.png art */
} PlayerDef;

#endif
