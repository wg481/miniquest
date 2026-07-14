/* main.c -- init, title screen (with title image + continue), and the
 * top-level loop. All game data comes from db_data / map data generated
 * out of the data JSON files -- see the editor and generators in tools/.
 */
#include <stdlib.h>
#include "game.h"
#include "gfx.h"
#include "ui.h"
#include "field.h"
#include "battle.h"
#include "save.h"
#include "sound.h"
#include "script.h"

Party party;

void partyInit(void)
{
	for (int i = 0; i < PARTY_SIZE; i++) {
		const PlayerDef *d = &playerDefs[i];
		Fighter *f = &party.member[i];
		f->name = d->name;
		f->maxhp = f->hp = d->hp;
		f->maxmp = f->mp = d->mp;
		f->atk = d->atk;
		f->def = d->def;
		f->agi = d->agi;
		f->level = 1;
		f->exp = 0;
		f->defending = false;
	}
	party.gold = 0;
	for (int i = 0; i < N_ITEMS; i++)
		party.items[i] = startItems[i];
	for (int i = 0; i < N_VARS; i++)
		party.vars[i] = 0;
}

void partyRestore(void)
{
	for (int i = 0; i < PARTY_SIZE; i++) {
		party.member[i].hp = party.member[i].maxhp;
		party.member[i].mp = party.member[i].maxmp;
	}
}

/* add one of an item, respecting the per-item carry cap */
bool itemAdd(int id)
{
	if (id < 0 || id >= N_ITEMS || party.items[id] >= ITEM_MAX)
		return false;
	party.items[id]++;
	return true;
}

/* event flags live in party.vars, saved with the game. A 0->1
 * transition is reported to the script system so on_flag events can
 * fire (drained by the field loop, never recursively). */
bool flagGet(int id)
{
	return id >= 0 && id < N_VARS && party.vars[id] != 0;
}

void flagPut(int id, int v)
{
	if (id < 0 || id >= N_VARS)
		return;
	if (v && !party.vars[id]) {
		party.vars[id] = 1;
		scriptFlagRaised(id);
	} else if (!v) {
		party.vars[id] = 0;
	}
}

void flagSet(int id)
{
	flagPut(id, 1);
}

/* returns true if a save was loaded (spawn from save position) */
static bool title(void)
{
	gfxShowTitle();
	musicPlay(titleMusic);
	uiClear();
	uiPrintAt((32 - 4 - (int)sizeof(GAME_TITLE)) / 2, 8,
	          "* %s *", GAME_TITLE);
	uiPrintAt(10, 12, "PRESS START");

	u32 seed = 0;
	while (1) {
		swiWaitForVBlank();
		gfxFlush();
		seed++;
		scanKeys();
		if (keysDown() & KEY_START)
			break;
	}
	srand(seed);                 /* human timing = free entropy */

	bool useSave = false;
	if (saveExists()) {
		const char *items[] = { "CONTINUE", "NEW GAME" };
		int s;
		do {
			s = uiMenu(NULL, items, 2);
		} while (s < 0);
		useSave = (s == 0) && loadGame();
	}
	uiClear();
	gfxLoadGame();
	return useSave;
}

int main(void)
{
	gfxInit();
	uiInit();
	saveInit();
	musicInit();
	partyInit();

	if (title())
		fieldEnter(savedMap(), savedX(), savedY());
	else
		fieldEnter(START_MAP, START_X, START_Y);

	while (1) {
		swiWaitForVBlank();
		int ev = fieldUpdate();
		gfxFlush();

		if (ev == EV_ENCOUNTER || ev == EV_BOSS) {
			int bgm = battleMusic;
			if (ev == EV_BOSS && fieldPendingBossMusic() >= 0)
				bgm = fieldPendingBossMusic();
			if (bgm >= 0)
				musicPlay(bgm);
			int r = battleRun(fieldPendingTroop());
			if (r == BATTLE_LOST) {
				party.gold /= 2;
				partyRestore();
				fieldEnter(DEATH_MAP, DEATH_X, DEATH_Y);
				uiMessage("You awaken safe in town.\nHalf your gold is gone...");
				fieldRedraw();
			} else {
				if (ev == EV_BOSS && r == BATTLE_WON)
					flagSet(fieldPendingBossFlag());
				fieldRedraw();
			}
		}
	}
	return 0;
}
