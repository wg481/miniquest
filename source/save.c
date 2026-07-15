/* save.c -- battery-free saving to a .sav file over FAT.
 *
 * Works on DSi SD (through hbmenu / TWiLight Menu) and on flashcarts
 * with DLDI. Derived stats (maxhp, atk, ...) are NOT stored: they are
 * recomputed from playerDefs + level, so rebalancing the database
 * never corrupts old saves.
 *
 * Version 3 (party overhaul): the file stores the whole ROSTER --
 * MAX_PLAYERS member slots regardless of how many the database
 * currently defines, so adding characters later never invalidates
 * saves -- plus the active lineup (nParty + slot[]). Versions 1
 * (vars[32], two members) and 2 (vars[256], two members) migrate:
 * their two members map to roster entries 0 and 1 and become the
 * lineup; everyone else starts fresh at level 1.
 */
#include <stdio.h>
#include <string.h>
#include <stddef.h>
#include <fat.h>
#include "save.h"

#define SAVE_FILE  "miniquest.sav"
#define SAVE_MAGIC 0x4D515356          /* 'MQSV' */
#define SAVE_VER   3                   /* v3: roster + lineup */
#define N_VARS_V1  32                  /* flag count in version-1 saves */
/* N_VARS / MAX_PLAYERS / PARTY_MAX come from game.h */

typedef struct {
	u16 hp, mp, exp;
	u8  level, pad;
} SavedFighter;

typedef struct {
	u32 magic;
	u16 version;
	u16 gold;
	u8  map, x, y, nParty;
	u8  slot[PARTY_MAX], pad;
	u8  items[N_ITEMS];
	SavedFighter m[MAX_PLAYERS];
	u16 vars[N_VARS];
} SaveData;

/* byte-exact VERSION 2 layout (v1 is this file truncated after 32
 * vars -- vars[] is last, so a short read migrates it) */
typedef struct {
	u32 magic;
	u16 version;
	u16 gold;
	u8  map, x, y, pad;
	u8  items[N_ITEMS];
	SavedFighter m[2];
	u16 vars[N_VARS];
} SaveDataV2;

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
	s.nParty = party.nParty;
	for (int i = 0; i < PARTY_MAX; i++)
		s.slot[i] = i < party.nParty ? party.slot[i] : 0;
	for (int i = 0; i < N_ITEMS; i++)
		s.items[i] = party.items[i];
	for (int i = 0; i < N_VARS; i++)
		s.vars[i] = party.vars[i];
	for (int i = 0; i < N_PLAYERS; i++) {     /* rest stays zeroed */
		s.m[i].hp = party.roster[i].hp;
		s.m[i].mp = party.roster[i].mp;
		s.m[i].exp = party.roster[i].exp;
		s.m[i].level = party.roster[i].level;
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

/* saved state -> a roster Fighter, clamped against its def */
static void applySaved(int i, const SavedFighter *sm)
{
	Fighter *f = &party.roster[i];
	int lvl = sm->level;
	if (lvl < 1 || lvl > MAX_LEVEL)
		lvl = 1;
	applyDef(f, &playerDefs[i], lvl);
	f->exp = sm->exp;
	f->hp = sm->hp <= f->maxhp ? sm->hp : f->maxhp;
	f->mp = sm->mp <= f->maxmp ? sm->mp : f->maxmp;
}

bool loadGame(void)
{
	if (!fatOk)
		return false;
	FILE *f = fopen(SAVE_FILE, "rb");
	if (!f)
		return false;
	/* one buffer, three interpretations: v3 is the largest layout,
	 * v2 is smaller, v1 is a v2 file truncated after 32 vars. */
	static union {
		SaveData v3;
		SaveDataV2 v2;
		u8 raw[sizeof(SaveData) > sizeof(SaveDataV2)
		       ? sizeof(SaveData) : sizeof(SaveDataV2)];
	} u;
	memset(&u, 0, sizeof u);
	size_t got = fread(&u, 1, sizeof u, f);
	fclose(f);

	size_t v1Bytes = offsetof(SaveDataV2, vars)
	               + N_VARS_V1 * sizeof(u16);
	if (got < v1Bytes || u.v2.magic != SAVE_MAGIC)
		return false;                        /* shared header */
	int ver = u.v2.version;

	SaveData s = { 0 };
	if (ver == SAVE_VER) {
		if (got != sizeof(SaveData))
			return false;
		s = u.v3;
	} else if (ver == 2 || ver == 1) {
		if (ver == 2 && got != sizeof(SaveDataV2))
			return false;                    /* v1: short file ok */
		s.gold = u.v2.gold;
		s.map = u.v2.map;
		s.x = u.v2.x;
		s.y = u.v2.y;
		memcpy(s.items, u.v2.items, sizeof s.items);
		/* the old fixed pair -> roster 0/1 + the active lineup */
		s.nParty = N_PLAYERS < 2 ? 1 : 2;
		s.slot[0] = 0;
		s.slot[1] = 1;
		for (int i = 0; i < 2 && i < MAX_PLAYERS; i++)
			s.m[i] = u.v2.m[i];
		int nv = ver == 1 ? N_VARS_V1 : N_VARS;  /* rest zeroed */
		memcpy(s.vars, u.v2.vars, nv * sizeof(u16));
	} else {
		return false;
	}

	if (s.map >= N_MAPS)
		return false;
	if (s.nParty < 1 || s.nParty > PARTY_MAX || s.nParty > N_PLAYERS)
		return false;
	for (int i = 0; i < s.nParty; i++) {         /* valid + unique */
		if (s.slot[i] >= N_PLAYERS)
			return false;
		for (int j = 0; j < i; j++)
			if (s.slot[j] == s.slot[i])
				return false;
	}

	party.gold = s.gold;
	for (int i = 0; i < N_ITEMS; i++)
		party.items[i] = s.items[i];
	for (int i = 0; i < N_VARS; i++)
		party.vars[i] = s.vars[i];
	for (int i = 0; i < N_PLAYERS; i++)
		applySaved(i, &s.m[i]);      /* fresh characters read a
		                                zeroed slot -> level 1 */
	party.nParty = s.nParty;
	for (int i = 0; i < PARTY_MAX; i++)
		party.slot[i] = i < s.nParty ? s.slot[i] : 0;

	loaded = s;
	haveLoaded = true;
	return true;
}

int savedMap(void) { return haveLoaded ? loaded.map : START_MAP; }
int savedX(void)   { return haveLoaded ? loaded.x   : START_X; }
int savedY(void)   { return haveLoaded ? loaded.y   : START_Y; }
