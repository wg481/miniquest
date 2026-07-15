/* test_script_run.c -- host-side interpreter harness. Drives the
 * fixture scripts (canonical yesno/if example, battle+lose, plain
 * battle loss, warp) through the REAL script.c against the REAL
 * generated scripts_data.c/maps.c, with the UI and battle system
 * stubbed to scripted answers.
 *
 * Build (from the fixture root):
 *   gcc -Wall -Wextra -Iinclude -Istub -Ibuild \
 *       tools/test_script_run.c source/script.c source/scripts_data.c \
 *       source/maps.c source/db_data.c source/gfx_data.c -o tsr && ./tsr
 *
 * Script indices are resolved from the generated event tables, never
 * hardcoded (data reorders between sessions).
 *
 * REQUIRES the test fixture: three flags (begin_quest, has_sword,
 * gate_open) in database.json and the five test events on
 * MAP_TOWN_WEST -- exact JSON in NOTES.md. Without them the FLAG_*
 * enums below don't exist and this file won't compile; that is
 * intentional (the harness tests those exact scripts).
 */
#include <assert.h>
#include <stdio.h>
#include <string.h>
#include "game.h"
#include "maps.h"
#include "script.h"
#include "ui.h"
#include "battle.h"
#include "field.h"
#include "sound.h"

Party party;

/* ---- engine stubs -------------------------------------------- */

static char logbuf[4096];
static void logmsg(const char *s)
{
	strncat(logbuf, s, sizeof logbuf - strlen(logbuf) - 2);
	strcat(logbuf, "|");
}

void uiMessage(const char *text) { logmsg(text); }
void uiStatus(void) {}
int menuAnswer = 0;                    /* 0 = first item (YES) */
int uiMenu(const char *title, const char *const *items, int n)
{
	(void)title; (void)items; (void)n;
	return menuAnswer;
}

int battleResult = BATTLE_WON;
int battleCount;
int battleRun(int troopId)
{
	(void)troopId;
	battleCount++;
	return battleResult;
}

int enteredMap = -1, enteredX = -1, enteredY = -1, enterCount;
void fieldEnter(int mapId, int tx, int ty)
{
	enteredMap = mapId; enteredX = tx; enteredY = ty;
	enterCount++;
}
void fieldRedraw(void) {}
void musicPlay(int m) { (void)m; }
void sfxHeal(void) {}

/* ---- party logic mirrored from main.c (minus the field-side
 * restack, which is stubbed out here) --------------------------- */

void partyRestore(void)
{
	for (int i = 0; i < party.nParty; i++) {
		Fighter *f = partyMember(i);
		f->hp = f->maxhp;
		f->mp = f->maxmp;
	}
}

int partyChangedCount;
void fieldPartyChanged(void) { partyChangedCount++; }

bool partyHas(int playerId)
{
	for (int i = 0; i < party.nParty; i++)
		if (party.slot[i] == playerId)
			return true;
	return false;
}

int partyJoin(int playerId)
{
	if (playerId < 0 || playerId >= N_PLAYERS)
		return JOIN_ALREADY;
	if (partyHas(playerId))
		return JOIN_ALREADY;
	if (party.nParty >= PARTY_MAX)
		return JOIN_FULL;
	party.slot[party.nParty++] = playerId;
	Fighter *f = &party.roster[playerId];
	f->hp = f->maxhp;
	f->mp = f->maxmp;
	f->defending = false;
	fieldPartyChanged();
	return JOIN_OK;
}

int partyLeave(int playerId)
{
	if (!partyHas(playerId))
		return LEAVE_ABSENT;
	if (party.nParty <= 1)
		return LEAVE_LAST;
	int k = 0;
	while (party.slot[k] != playerId)
		k++;
	for (; k < party.nParty - 1; k++)
		party.slot[k] = party.slot[k + 1];
	party.nParty--;
	fieldPartyChanged();
	return LEAVE_OK;
}

bool itemAdd(int id)
{
	if (id < 0 || id >= N_ITEMS || party.items[id] >= ITEM_MAX)
		return false;
	party.items[id]++;
	return true;
}

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

void flagSet(int id) { flagPut(id, 1); }

/* ---- helpers -------------------------------------------------- */

static int fails;
#define CHECK(cond, ...) do { \
	if (!(cond)) { fails++; printf("FAIL: " __VA_ARGS__); printf("\n"); } \
} while (0)

static void reset(void)
{
	memset(&party, 0, sizeof party);
	for (int i = 0; i < N_PLAYERS; i++) {
		party.roster[i].name = playerDefs[i].name;
		party.roster[i].level = 1;
		party.roster[i].maxhp = 20;
		party.roster[i].hp = 20;
	}
	party.nParty = N_PLAYERS < 2 ? 1 : 2;    /* hero + mage */
	party.slot[0] = 0;
	if (N_PLAYERS >= 2)
		party.slot[1] = 1;
	logbuf[0] = 0;
	enteredMap = enteredX = enteredY = -1;
	enterCount = battleCount = 0;
	while (scriptTakeRaised() >= 0)
		;                        /* clear the raised set */
}

/* find the Nth event of a kind on a map; returns script index */
static int findScript(int mapId, int kind, int nth)
{
	const MapDef *m = &maps[mapId];
	for (int i = 0; i < m->nEvents; i++)
		if (m->events[i].kind == kind && nth-- == 0)
			return m->events[i].script;
	return -1;
}

static bool said(const char *frag)
{
	return strstr(logbuf, frag) != NULL;
}

int main(void)
{
	const int canon = findScript(MAP_TOWN_WEST, EVT_LOAD, 0);
	const int loseB = findScript(MAP_TOWN_WEST, EVT_TILE, 0);
	const int plainB = findScript(MAP_TOWN_WEST, EVT_TILE, 1);
	const int warpS = findScript(MAP_TOWN_WEST, EVT_TILE, 2);
	CHECK(canon >= 0 && loseB >= 0 && plainB >= 0 && warpS >= 0,
	      "fixture scripts resolved (%d %d %d %d)",
	      canon, loseB, plainB, warpS);

	/* A: YES branch, no sword -> else path */
	reset();
	menuAnswer = 0;                            /* YES */
	scriptRun(canon);
	CHECK(flagGet(FLAG_BEGIN_QUEST), "A: begin_quest set");
	CHECK(said("You'll need a weapon"), "A: else branch said");
	CHECK(!said("Take these"), "A: then branch skipped");
	CHECK(party.items[ITEM_HERB2] == 0, "A: no items given");
	CHECK(said("Safe travels."), "A: post-block statement ran");
	CHECK(scriptTakeRaised() == FLAG_BEGIN_QUEST,
	      "A: begin_quest raise queued for on_flag");

	/* B: YES branch with sword -> then path */
	reset();
	party.vars[FLAG_HAS_SWORD] = 1;
	menuAnswer = 0;
	scriptRun(canon);
	CHECK(said("Take these"), "B: then branch said");
	CHECK(!said("You'll need a weapon"), "B: else skipped");
	CHECK(party.items[ITEM_HERB2] == 2, "B: give herb2 2 (got %d)",
	      party.items[ITEM_HERB2]);
	CHECK(said("Safe travels."), "B: post-block statement ran");

	/* C: NO branch */
	reset();
	menuAnswer = 1;                            /* NO */
	scriptRun(canon);
	CHECK(!flagGet(FLAG_BEGIN_QUEST), "C: begin_quest untouched");
	CHECK(said("A shame."), "C: no body said");
	CHECK(!said("Bless you"), "C: yes body skipped");
	CHECK(said("Safe travels."), "C: post-block statement ran");

	/* D1: battle + lose block, WON -> lose body skipped */
	reset();
	battleResult = BATTLE_WON;
	scriptRun(loseB);
	CHECK(battleCount == 1, "D1: battle ran");
	CHECK(!said("Spared."), "D1: lose body skipped on win");
	CHECK(said("After battle."), "D1: script continued");

	/* D2: battle + lose block, LOST -> heal + lose body + continue */
	reset();
	partyMember(0)->hp = 0;
	partyMember(1)->hp = 0;
	battleResult = BATTLE_LOST;
	scriptRun(loseB);
	CHECK(said("Spared."), "D2: lose body ran on loss");
	CHECK(said("After battle."), "D2: script continued after end");
	CHECK(partyMember(0)->hp == partyMember(0)->maxhp,
	      "D2: party healed on spared loss");
	CHECK(enterCount == 0, "D2: no death respawn");

	/* E: plain battle, LOST -> death flow + abandon */
	reset();
	party.gold = 100;
	battleResult = BATTLE_LOST;
	scriptRun(plainB);
	CHECK(!said("Should not run on loss."), "E: script abandoned");
	CHECK(party.gold == 50, "E: gold halved (got %d)", party.gold);
	CHECK(enteredMap == DEATH_MAP && enteredX == DEATH_X
	      && enteredY == DEATH_Y, "E: death respawn");
	CHECK(said("You awaken safe in town."), "E: death message");
	CHECK(partyMember(0)->hp == partyMember(0)->maxhp,
	      "E: party restored");

	/* E2: plain battle, WON -> continues */
	reset();
	battleResult = BATTLE_WON;
	scriptRun(plainB);
	CHECK(said("Should not run on loss."), "E2: continues on win");
	CHECK(enterCount == 0, "E2: no respawn on win");

	/* F: warp ends the script */
	reset();
	scriptRun(warpS);
	CHECK(enteredMap == MAP_OVERWORLD && enteredX == 6
	      && enteredY == 9, "F: warp destination");
	CHECK(!said("Never."), "F: nothing after warp runs");

	/* H: join/leave opcodes (fixture events on MAP_TOWN_EAST;
	 * fixture roster adds healer + sage after hero/mage) */
	const int joinS = findScript(MAP_TOWN_EAST, EVT_TILE, 0);
	const int leaveS = findScript(MAP_TOWN_EAST, EVT_TILE, 1);
	const int fullS = findScript(MAP_TOWN_EAST, EVT_TILE, 2);
	const int lastS = findScript(MAP_TOWN_EAST, EVT_TILE, 3);
	CHECK(joinS >= 0 && leaveS >= 0 && fullS >= 0 && lastS >= 0,
	      "fixture join/leave scripts resolved (%d %d %d %d)",
	      joinS, leaveS, fullS, lastS);

	/* H1: join at the kept level with a full restore */
	reset();
	party.roster[PLAYER_HEALER].level = 5;
	party.roster[PLAYER_HEALER].maxhp = 40;
	party.roster[PLAYER_HEALER].hp = 1;
	scriptRun(joinS);                    /* join healer */
	CHECK(party.nParty == 3, "H1: healer joined (n=%d)", party.nParty);
	CHECK(party.slot[2] == PLAYER_HEALER, "H1: appended to lineup");
	CHECK(party.roster[PLAYER_HEALER].level == 5,
	      "H1: level preserved");
	CHECK(party.roster[PLAYER_HEALER].hp == 40, "H1: full restore");
	CHECK(said("joins the party!"), "H1: auto-announced");
	CHECK(said("After join."), "H1: script continued");

	/* H2: joining again is a silent no-op */
	logbuf[0] = 0;
	scriptRun(joinS);
	CHECK(party.nParty == 3, "H2: no double join");
	CHECK(!said("joins the party!"), "H2: silent when already in");
	CHECK(said("After join."), "H2: script continued");

	/* H3: full party refuses, script continues */
	logbuf[0] = 0;
	scriptRun(fullS);                    /* join sage at 3/3 */
	CHECK(party.nParty == 3, "H3: sage refused");
	CHECK(said("The party is full!"), "H3: refusal message");
	CHECK(said("After full."), "H3: script continued");

	/* H4: leave keeps the roster entry for a rejoin */
	logbuf[0] = 0;
	scriptRun(leaveS);                   /* leave mage */
	CHECK(party.nParty == 2, "H4: mage left (n=%d)", party.nParty);
	CHECK(party.slot[0] == PLAYER_HERO
	      && party.slot[1] == PLAYER_HEALER,
	      "H4: lineup compacted");
	CHECK(said("leaves the party."), "H4: auto-announced");
	CHECK(said("After leave."), "H4: script continued");

	/* H5: leaving an absent member is silent */
	logbuf[0] = 0;
	scriptRun(leaveS);                   /* mage already gone */
	CHECK(party.nParty == 2, "H5: no-op");
	CHECK(!said("leaves the party."), "H5: silent");

	/* H6: leaving the last member is ignored */
	reset();
	party.nParty = 1;
	party.slot[0] = PLAYER_HERO;
	logbuf[0] = 0;
	scriptRun(lastS);                    /* leave hero */
	CHECK(party.nParty == 1, "H6: last member kept");
	CHECK(!said("leaves the party."), "H6: silent");
	CHECK(said("After last."), "H6: script continued");

	/* G: raised-flag mechanics */
	reset();
	flagPut(FLAG_GATE_OPEN, 1);
	flagPut(FLAG_GATE_OPEN, 1);                /* second set: no re-raise */
	CHECK(scriptTakeRaised() == FLAG_GATE_OPEN, "G: raise recorded");
	CHECK(scriptTakeRaised() == -1, "G: raise consumed, no dupes");
	flagPut(FLAG_GATE_OPEN, 0);
	flagPut(FLAG_GATE_OPEN, 1);                /* 0->1 again re-raises */
	CHECK(scriptTakeRaised() == FLAG_GATE_OPEN, "G: re-raise after clear");

	if (fails == 0)
		puts("all script interpreter tests passed");
	return fails ? 1 : 0;
}
