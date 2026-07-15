/* test_save_migration.c -- host-side proof of the v1/v2 -> v3 save
 * migration (roster + lineup) and the v3 round-trip.
 *
 * Build (from project root):
 *   gcc -Wall -Wextra -Iinclude -Istub -Ibuild \
 *       tools/test_save_migration.c source/save.c source/db_data.c \
 *       source/gfx_data.c -o tsm && ./tsm
 *
 * Runs in the current directory (writes/removes miniquest.sav).
 */
#include <assert.h>
#include <stdio.h>
#include <string.h>
#include "game.h"
#include "save.h"

/* ---- stubs for the engine bits save.c touches ---- */
Party party;
bool fatInitDefault(void) { return true; }
static int gMap = 1, gX = 9, gY = 13;
int fieldMap(void) { return gMap; }
int fieldX(void)   { return gX; }
int fieldY(void)   { return gY; }

/* ---- byte-exact copies of the OLD on-disk layouts ---- */
#define N_VARS_V1 32
typedef struct {
	u16 hp, mp, exp;
	u8  level, pad;
} OldFighter;

typedef struct {                       /* version 1: vars[32] */
	u32 magic;
	u16 version;
	u16 gold;
	u8  map, x, y, pad;
	u8  items[N_ITEMS];
	OldFighter m[2];
	u16 vars[N_VARS_V1];
} SaveDataV1;

typedef struct {                       /* version 2: vars[256] */
	u32 magic;
	u16 version;
	u16 gold;
	u8  map, x, y, pad;
	u8  items[N_ITEMS];
	OldFighter m[2];
	u16 vars[N_VARS];
} SaveDataV2T;

#define MAGIC 0x4D515356

static void writeOld(int version)
{
	SaveDataV2T s = { 0 };
	s.magic = MAGIC;
	s.version = version;
	s.gold = 123;
	s.map = 1; s.x = 9; s.y = 13;
	s.items[0] = 3;
	if (N_ITEMS > 1) s.items[1] = 1;
	for (int i = 0; i < 2; i++) {
		s.m[i].level = 3 + i;
		s.m[i].exp = 50 + i;
		s.m[i].hp = 5;          /* below any maxhp: survives clamp */
		s.m[i].mp = 2;
	}
	int nv = version == 1 ? N_VARS_V1 : N_VARS;
	for (int i = 0; i < nv; i++)
		s.vars[i] = i % 2;      /* odd flags set */
	size_t bytes = version == 1 ? sizeof(SaveDataV1)
	                            : sizeof(SaveDataV2T);
	FILE *f = fopen("miniquest.sav", "wb");
	assert(f && fwrite(&s, bytes, 1, f) == 1);
	fclose(f);
	printf("v%d file: %zu bytes\n", version, bytes);
}

static void wipeParty(void)
{
	memset(&party, 0, sizeof party);
}

static void checkMigrated(const char *tag)
{
	assert(party.gold == 123);
	assert(savedMap() == 1 && savedX() == 9 && savedY() == 13);
	assert(party.items[0] == 3);
	assert(party.nParty == (N_PLAYERS < 2 ? 1 : 2));
	assert(party.slot[0] == 0);
	if (N_PLAYERS >= 2)
		assert(party.slot[1] == 1);
	assert(party.roster[0].level == 3);
	assert(party.roster[0].hp == 5);
	assert(party.roster[0].exp == 50);
	if (N_PLAYERS >= 2) {
		assert(party.roster[1].level == 4);
		assert(party.roster[1].hp == 5);
	}
	for (int i = 2; i < N_PLAYERS; i++)     /* fresh characters */
		assert(party.roster[i].level == 1);
	printf("%s: old pair -> roster 0/1 + lineup OK\n", tag);
}

int main(void)
{
	saveInit();

	/* 1. version-1 file loads and migrates (vars zero-extended) */
	writeOld(1);
	wipeParty();
	assert(loadGame());
	checkMigrated("v1");
	for (int i = 0; i < N_VARS_V1; i++)
		assert(party.vars[i] == (u16)(i % 2));      /* preserved */
	for (int i = N_VARS_V1; i < N_VARS; i++)
		assert(party.vars[i] == 0);                 /* zero-filled */
	printf("v1 load+migration OK\n");

	/* 2. version-2 file loads and migrates (all vars preserved) */
	writeOld(2);
	wipeParty();
	assert(loadGame());
	checkMigrated("v2");
	for (int i = 0; i < N_VARS; i++)
		assert(party.vars[i] == (u16)(i % 2));
	printf("v2 load+migration OK\n");

	/* 3. saving writes v3: a modified lineup + roster round-trips */
	party.vars[200] = 1;
	party.vars[255] = 1;
	party.gold = 777;
	party.nParty = 1;                    /* mage-only lineup when the
	                                        roster allows it */
	party.slot[0] = N_PLAYERS >= 2 ? 1 : 0;
	party.roster[0].level = 7;
	party.roster[0].exp = 400;
	party.roster[0].hp = 1;              /* survives clamp */
	party.roster[0].mp = 0;
	assert(saveGame());
	wipeParty();
	assert(loadGame());
	assert(party.gold == 777);
	assert(party.nParty == 1);
	assert(party.slot[0] == (N_PLAYERS >= 2 ? 1 : 0));
	assert(party.roster[0].level == 7);
	assert(party.roster[0].exp == 400);
	assert(party.roster[0].hp == 1);
	for (int i = 0; i < N_VARS_V1; i++)
		assert(party.vars[i] == (u16)(i % 2));
	assert(party.vars[200] == 1 && party.vars[255] == 1);
	assert(party.vars[199] == 1);        /* odd pattern from step 2 */
	printf("v3 round-trip (lineup + flags 200/255) OK\n");

	/* 4. unknown version rejected */
	{
		SaveDataV2T s = { 0 };
		s.magic = MAGIC; s.version = 4; s.map = 1;
		FILE *f = fopen("miniquest.sav", "wb");
		assert(f && fwrite(&s, sizeof s, 1, f) == 1);
		fclose(f);
		assert(!loadGame());
	}
	printf("unknown version rejected OK\n");

	/* 5. corrupt v3 lineups rejected (bad count / dup slots) */
	{
		party.nParty = 1;
		party.slot[0] = 0;
		party.roster[0].level = 2;
		assert(saveGame());
		FILE *f = fopen("miniquest.sav", "r+b");
		assert(f);
		/* nParty sits right after magic/ver/gold/map/x/y */
		long off = 4 + 2 + 2 + 3;
		fseek(f, off, SEEK_SET);
		u8 bad = 0;                      /* nParty = 0 */
		fwrite(&bad, 1, 1, f);
		fclose(f);
		assert(!loadGame());
		assert(saveGame());              /* rewrite clean */
		f = fopen("miniquest.sav", "r+b");
		fseek(f, off, SEEK_SET);
		u8 two[4] = { 2, 0, 0, 0 };      /* nParty=2, slots 0,0: dup */
		fwrite(two, 1, 4, f);
		fclose(f);
		if (N_PLAYERS >= 2)              /* dup only invalid then */
			assert(!loadGame());
	}
	printf("corrupt lineup rejected OK\n");

	/* 6. truncated garbage rejected */
	{
		FILE *f = fopen("miniquest.sav", "wb");
		assert(f && fwrite("junk", 4, 1, f) == 1);
		fclose(f);
		assert(!loadGame());
	}
	printf("truncated file rejected OK\n");

	remove("miniquest.sav");
	printf("test_save_migration: ALL PASS\n");
	return 0;
}
