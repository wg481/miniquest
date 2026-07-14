/* test_save_migration.c -- host-side proof of the v1 -> v2 save
 * migration (N_VARS 32 -> 256, SAVE_VER 1 -> 2).
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

/* ---- a byte-exact copy of the VERSION 1 on-disk layout ---- */
#define N_VARS_V1 32
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
	u16 vars[N_VARS_V1];
} SaveDataV1;

#define MAGIC 0x4D515356

static void writeV1(void)
{
	SaveDataV1 s = { 0 };
	s.magic = MAGIC;
	s.version = 1;
	s.gold = 123;
	s.map = 1; s.x = 9; s.y = 13;
	s.items[0] = 3;
	if (N_ITEMS > 1) s.items[1] = 1;
	for (int i = 0; i < PARTY_SIZE; i++) {
		s.m[i].level = 3 + i;
		s.m[i].exp = 50 + i;
		s.m[i].hp = 5;          /* below any maxhp: survives clamp */
		s.m[i].mp = 2;
	}
	for (int i = 0; i < N_VARS_V1; i++)
		s.vars[i] = i % 2;      /* odd flags set */
	FILE *f = fopen("miniquest.sav", "wb");
	assert(f && fwrite(&s, sizeof s, 1, f) == 1);
	fclose(f);
	printf("v1 file: %zu bytes (v2 struct would be larger)\n", sizeof s);
}

static void wipeParty(void)
{
	memset(&party, 0, sizeof party);
}

int main(void)
{
	saveInit();

	/* 1. version-1 file loads and migrates */
	writeV1();
	wipeParty();
	assert(loadGame());
	assert(party.gold == 123);
	assert(savedMap() == 1 && savedX() == 9 && savedY() == 13);
	assert(party.items[0] == 3);
	for (int i = 0; i < N_VARS_V1; i++)
		assert(party.vars[i] == (u16)(i % 2));      /* preserved */
	for (int i = N_VARS_V1; i < N_VARS; i++)
		assert(party.vars[i] == 0);                 /* zero-filled */
	assert(party.member[0].level == 3);
	assert(party.member[0].hp == 5);
	printf("v1 load+migration OK\n");

	/* 2. saving now writes v2; high flags round-trip */
	party.vars[200] = 1;
	party.vars[255] = 1;
	party.gold = 777;
	assert(saveGame());
	wipeParty();
	assert(loadGame());
	assert(party.gold == 777);
	for (int i = 0; i < N_VARS_V1; i++)
		assert(party.vars[i] == (u16)(i % 2));
	assert(party.vars[200] == 1 && party.vars[255] == 1);
	assert(party.vars[199] == 0 && party.vars[201] == 0);
	printf("v2 round-trip (flags 200/255) OK\n");

	/* 3. unknown version rejected */
	{
		SaveDataV1 s = { 0 };
		s.magic = MAGIC; s.version = 3; s.map = 1;
		FILE *f = fopen("miniquest.sav", "wb");
		assert(f && fwrite(&s, sizeof s, 1, f) == 1);
		fclose(f);
		assert(!loadGame());
	}
	printf("unknown version rejected OK\n");

	/* 4. truncated garbage rejected */
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
