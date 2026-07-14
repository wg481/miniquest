/* save.c -- battery-free saving to a .sav file over FAT.
 *
 * Works on DSi SD (through hbmenu / TWiLight Menu) and on flashcarts
 * with DLDI. Derived stats (maxhp, atk, ...) are NOT stored: they are
 * recomputed from playerDefs + level, so rebalancing the database
 * never corrupts old saves.
 */
#include <stdio.h>
#include <stddef.h>
#include <fat.h>
#include "save.h"

#define SAVE_FILE  "miniquest.sav"
#define SAVE_MAGIC 0x4D515356          /* 'MQSV' */
#define SAVE_VER   2                   /* v2: vars[32] -> vars[256] */
#define N_VARS_V1  32                  /* flag count in version-1 saves */
/* N_VARS comes from game.h now that flags are live */

typedef struct {
	u32 magic;
	u16 version;
	u16 gold;
	u8  map, x, y, pad;
	u8  items[N_ITEMS];
	struct {
		u16 hp, mp, exp;
		u8  level, pad;
	} m[PARTY_SIZE];
	u16 vars[N_VARS];
} SaveData;

static bool fatOk;
static SaveData loaded;
static bool haveLoaded;

void saveInit(void)
{
	fatOk = fatInitDefault();
}

bool saveExists(void)
{
	if (!fatOk)
		return false;
	FILE *f = fopen(SAVE_FILE, "rb");
	if (!f)
		return false;
	fclose(f);
	return true;
}

bool saveGame(void)
{
	if (!fatOk)
		return false;
	SaveData s = { 0 };
	s.magic = SAVE_MAGIC;
	s.version = SAVE_VER;
	s.gold = party.gold;
	extern int fieldMap(void), fieldX(void), fieldY(void);
	s.map = fieldMap();
	s.x = fieldX();
	s.y = fieldY();
	for (int i = 0; i < N_ITEMS; i++)
		s.items[i] = party.items[i];
	for (int i = 0; i < N_VARS; i++)
		s.vars[i] = party.vars[i];
	for (int i = 0; i < PARTY_SIZE; i++) {
		s.m[i].hp = party.member[i].hp;
		s.m[i].mp = party.member[i].mp;
		s.m[i].exp = party.member[i].exp;
		s.m[i].level = party.member[i].level;
	}
	FILE *f = fopen(SAVE_FILE, "wb");
	if (!f)
		return false;
	bool ok = fwrite(&s, sizeof s, 1, f) == 1;
	fclose(f);
	return ok;
}

/* rebuild a Fighter from its PlayerDef at a given level */
static void applyDef(Fighter *out, const PlayerDef *d, int level)
{
	int g = level - 1;
	out->name = d->name;
	out->maxhp = d->hp + d->ghp * g;
	out->maxmp = d->mp + d->gmp * g;
	out->atk = d->atk + d->gatk * g;
	out->def = d->def + d->gdef * g;
	out->agi = d->agi + d->gagi * g;
	out->level = level;
	out->defending = false;
}

bool loadGame(void)
{
	if (!fatOk)
		return false;
	FILE *f = fopen(SAVE_FILE, "rb");
	if (!f)
		return false;
	/* vars[] is the LAST field, so a version-1 save (vars[32]) is
	 * byte-identical to a version-2 file truncated after its 32
	 * vars. Read whatever is there and size-check per version. */
	size_t v1Bytes = offsetof(SaveData, vars)
	               + N_VARS_V1 * sizeof(u16);
	size_t got = fread(&loaded, 1, sizeof loaded, f);
	fclose(f);
	bool ok = got >= v1Bytes
	       && loaded.magic == SAVE_MAGIC
	       && loaded.map < N_MAPS;
	if (ok && loaded.version == SAVE_VER)
		ok = got == sizeof loaded;           /* full v2 file */
	else if (ok && loaded.version == 1)
		;                                    /* short v1 file: ok */
	else
		ok = false;
	if (!ok)
		return false;
	if (loaded.version == 1)                     /* migrate: old flags
	                                                low, rest cleared */
		for (int i = N_VARS_V1; i < N_VARS; i++)
			loaded.vars[i] = 0;

	party.gold = loaded.gold;
	for (int i = 0; i < N_ITEMS; i++)
		party.items[i] = loaded.items[i];
	for (int i = 0; i < N_VARS; i++)
		party.vars[i] = loaded.vars[i];
	for (int i = 0; i < PARTY_SIZE; i++) {
		Fighter *m = &party.member[i];
		int lvl = loaded.m[i].level;
		if (lvl < 1 || lvl > MAX_LEVEL)
			lvl = 1;
		applyDef(m, &playerDefs[i], lvl);
		m->exp = loaded.m[i].exp;
		m->hp = loaded.m[i].hp <= m->maxhp ? loaded.m[i].hp : m->maxhp;
		m->mp = loaded.m[i].mp <= m->maxmp ? loaded.m[i].mp : m->maxmp;
	}
	haveLoaded = true;
	return true;
}

int savedMap(void) { return haveLoaded ? loaded.map : START_MAP; }
int savedX(void)   { return haveLoaded ? loaded.x   : START_X; }
int savedY(void)   { return haveLoaded ? loaded.y   : START_Y; }
