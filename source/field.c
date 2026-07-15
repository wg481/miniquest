/* field.c -- exploration mode.
 *
 * Movement is tile-snapped, DQ style: the player commits to a 16px step
 * and slides at 2px/frame until aligned with the grid again. Facing
 * changes even when the step is blocked, so you can turn in place to
 * read signs and talk to NPCs with A.
 */
#include <stdio.h>
#include "field.h"
#include "maps.h"
#include "gfx.h"
#include "ui.h"
#include "save.h"
#include "sound.h"
#include "script.h"

#define STEP_SPEED 2                      /* px per frame */

static const MapDef *map;
static int mapId;
static int px, py;                        /* player position, pixels   */
static int tgx, tgy;                      /* target pixels while moving*/
static bool moving;
static int dir = DIR_DOWN;
static int walkFrames;                    /* animates the step frame   */

/* followers: party members 2 and 3 trail the hero DQ-style, each
 * repeating the step the walker AHEAD of it just made -- follower k
 * walks into the tile its leader is leaving, so the chain only ever
 * visits tiles the hero proved walkable. All targets are computed
 * from PRE-step positions at commit time, which is what makes the
 * caterpillar unfold one link per step from a stacked start. */
#define N_FOLLOW (PARTY_MAX - 1)
static int fx[N_FOLLOW], fy[N_FOLLOW];    /* positions, pixels         */
static int ftgx[N_FOLLOW], ftgy[N_FOLLOW];/* targets while moving      */
static int fdir[N_FOLLOW];
static bool fstep[N_FOLLOW];              /* slides this step          */
static bool pendingLoad;                  /* run on_load events next
                                             tick (never inside a
                                             running script) */

static const int dx[4] = { 0, -1, 0, 1 }; /* DOWN LEFT UP RIGHT */
static const int dy[4] = { 1, 0, -1, 0 };

/* each active member's sheet into its walker slot (leader included:
 * whoever holds party slot 0 walks the map). Inactive slots keep
 * hero art but are never drawn. */
static void loadWalkers(void)
{
	for (int k = 0; k < PARTY_MAX; k++) {
		const unsigned short *g = NULL;
		if (k < party.nParty)
			g = playerDefs[party.slot[k]].gfx;
		gfxLoadWalker(k, g);        /* NULL = hero.png art */
	}
}

/* after a join/leave (script op or NPC recruit): new sheets, and the
 * chain restacks on the leader -- exactly like entering a map, the
 * newcomers unfold on the next step */
void fieldPartyChanged(void)
{
	loadWalkers();
	for (int k = 0; k < N_FOLLOW; k++) {
		fx[k] = px;
		fy[k] = py;
		ftgx[k] = px;
		ftgy[k] = py;
		fdir[k] = dir;
		fstep[k] = false;
	}
}

static void hint(void)
{
	uiStatus();
	uiFrame(0, 7, 31, 10);
	uiPrintAt(2, 8, "%s", map->name);
	uiPrintAt(2, 9, "D-pad: move   A: talk/read");
}

void fieldEnter(int newMap, int tx, int ty)
{
	mapId = newMap;
	map = &maps[mapId];
	px = tx * 16;
	py = ty * 16;
	moving = false;
	for (int k = 0; k < N_FOLLOW; k++) {
		fx[k] = px;                 /* stacked on the hero; unfolds  */
		fy[k] = py;                 /* one link per step (DQ style)  */
		ftgx[k] = px;
		ftgy[k] = py;
		fdir[k] = dir;
		fstep[k] = false;
	}
	loadWalkers();

	gfxLoadTileset(map->tileset);   /* no-op if already resident */
	gfxDrawMap(map);
	for (int i = 0; i < MAX_TROOP; i++)
		gfxEnemySprite(i, 0, 0, true);
	for (int i = 0; i < map->nNpcs; i++) {
		int b = map->npcs[i].boss;
		const unsigned short *gfx =
			b >= 0 ? bossDefs[b].gfx : map->npcs[i].sprite;
		gfxLoadNpc(i, gfx);   /* NULL -> NPC1 art */
	}
	musicPlay(map->music);
	uiClear();
	hint();
	pendingLoad = true;              /* on_load events fire next tick */
}

void fieldRedraw(void)
{
	gfxDrawMap(map);
	for (int i = 0; i < MAX_TROOP; i++)
		gfxEnemySprite(i, 0, 0, true);
	musicPlay(map->music);           /* resume after battle music */
	uiClear();
	hint();
}

static int pendingTroop;
static int pendingBossFlag;
static int pendingBossMusic;

int fieldPendingTroop(void)
{
	return pendingTroop;
}

int fieldPendingBossFlag(void)
{
	return pendingBossFlag;
}

int fieldPendingBossMusic(void)
{
	return pendingBossMusic;
}

const unsigned short *fieldBackdrop(void)
{
	return map->backdrop;
}

int fieldMap(void) { return mapId; }
int fieldX(void)   { return px / 16; }
int fieldY(void)   { return py / 16; }

/* weighted troop pick from the zone under (tx,ty); -1 = no battle */
static int rollEncounter(int tx, int ty)
{
	if (!map->zoneRows)
		return -1;
	char z = map->zoneRows[ty][tx];
	if (z == '.')
		return -1;
	for (int i = 0; i < map->nZones; i++) {
		const ZoneDef *zd = &map->zones[i];
		if (zd->zone != z)
			continue;
		if (rnd(zd->rate) != 0)
			return -1;
		int total = 0;
		for (int k = 0; k < zd->n; k++)
			total += zd->e[k].weight;
		int r = rnd(total);
		for (int k = 0; k < zd->n; k++) {
			r -= zd->e[k].weight;
			if (r < 0)
				return zd->e[k].troop;
		}
	}
	return -1;
}

/* an NPC whose hide flag is set is gone: not solid, not talkable,
 * not drawn (how recruited party members leave the map) */
static bool npcHidden(const Npc *n)
{
	return n->hideFlag >= 0 && flagGet(n->hideFlag);
}

static const Npc *npcAt(int tx, int ty)
{
	for (int i = 0; i < map->nNpcs; i++)
		if (map->npcs[i].x == tx && map->npcs[i].y == ty
		    && !npcHidden(&map->npcs[i]))
			return &map->npcs[i];
	return NULL;
}

static bool blocked(int tx, int ty)
{
	return mapSolid(map, tx, ty) || npcAt(tx, ty) != NULL;
}

/* event dispatch ----------------------------------------------------
 * Scripts run to completion (blocking); dispatch happens only at
 * field-loop granularity, never recursively inside scriptRun. A
 * script may warp or die-respawn (fieldEnter changes mapId), so
 * every scan bails when the map changes -- the new map's on_load
 * queue takes over. */

/* fire on_flag events for every flag raised since the last drain;
 * bounded so a set_flag chain can't loop forever. Returns true if
 * anything ran. */
static bool runFlagEvents(void)
{
	bool ran = false;
	for (int guard = 0; guard < 8; guard++) {
		int fl = scriptTakeRaised();
		if (fl < 0)
			return ran;
		int m0 = mapId;
		for (int i = 0; i < map->nEvents && mapId == m0; i++) {
			const Event *e = &map->events[i];
			if (e->kind == EVT_FLAG && e->flag == fl) {
				scriptRun(e->script);
				ran = true;
			}
		}
		if (mapId != m0)
			return true;
	}
	while (scriptTakeRaised() >= 0)
		;                        /* cap hit: drop the backlog */
	return ran;
}

/* on_load events, queued by fieldEnter */
static bool runLoadEvents(void)
{
	if (!pendingLoad)
		return false;
	pendingLoad = false;
	bool ran = false;
	int m0 = mapId;
	for (int i = 0; i < map->nEvents && mapId == m0; i++)
		if (map->events[i].kind == EVT_LOAD) {
			scriptRun(map->events[i].script);
			ran = true;
		}
	return ran || mapId != m0;
}

/* touch events on arrival at (tx,ty); returns true if any ran */
static bool runTileEvents(int tx, int ty)
{
	bool ran = false;
	int m0 = mapId;
	for (int i = 0; i < map->nEvents && mapId == m0; i++) {
		const Event *e = &map->events[i];
		if (e->kind != EVT_TILE || e->x != tx || e->y != ty)
			continue;
		if (e->flag >= 0 && !flagGet(e->flag))
			continue;
		scriptRun(e->script);
		ran = true;
	}
	return ran;
}

/* items and shopping ------------------------------------------------ */

/* menu of items the party carries; -1 = none / cancelled */
static int pickPartyItem(const char *title)
{
	static char labels[N_ITEMS][20];
	const char *items[N_ITEMS];
	int map[N_ITEMS], n = 0;
	for (int i = 0; i < N_ITEMS; i++)
		if (party.items[i] > 0) {
			snprintf(labels[n], sizeof labels[n], "%s x%d",
			         itemDefs[i].name, party.items[i]);
			items[n] = labels[n];
			map[n++] = i;
		}
	if (n == 0) {
		uiMessage("No items!");
		return -1;
	}
	int s = uiMenu(title, items, n);
	return s < 0 ? -1 : map[s];
}

static void useItem(void)
{
	int it = pickPartyItem("ITEM");
	if (it < 0)
		return;
	if (itemDefs[it].heal <= 0) {
		uiMessage("It has no effect here.");
		return;
	}
	const char *names[PARTY_MAX];
	for (int i = 0; i < party.nParty; i++)
		names[i] = partyMember(i)->name;
	int t = uiMenu("ON WHOM?", names, party.nParty);
	if (t < 0)
		return;
	party.items[it]--;
	sfxHeal();
	Fighter *f = partyMember(t);
	int amt = itemDefs[it].heal + rnd(6);
	f->hp += amt;
	if (f->hp > f->maxhp)
		f->hp = f->maxhp;
	uiStatus();
	char buf[96];
	snprintf(buf, sizeof buf, "Used the %s.\n%s recovers %d HP.",
	         itemDefs[it].name, f->name, amt);
	uiMessage(buf);
}

static void shopBuy(const Npc *n)
{
	static char labels[MAX_SHOP_ITEMS][20];
	const char *items[MAX_SHOP_ITEMS];
	for (int i = 0; i < n->nShop; i++) {
		const ItemDef *it = &itemDefs[n->shop[i]];
		snprintf(labels[i], sizeof labels[i], "%-8s%4dG",
		         it->name, it->price);
		items[i] = labels[i];
	}
	while (1) {
		int s = uiMenu("BUY", items, n->nShop);
		if (s < 0)
			return;
		const ItemDef *it = &itemDefs[n->shop[s]];
		if (party.gold < it->price) {
			uiMessage("Not enough gold!");
			continue;
		}
		if (!itemAdd(n->shop[s])) {
			uiMessage("You can't carry\nany more of those.");
			continue;
		}
		party.gold -= it->price;
		uiStatus();
		char buf[64];
		snprintf(buf, sizeof buf, "Here you are!\nThe %s is yours.",
		         it->name);
		uiMessage(buf);
	}
}

static void shopSell(void)
{
	while (1) {
		static char labels[N_ITEMS][24];
		const char *items[N_ITEMS];
		int map[N_ITEMS], n = 0;
		for (int i = 0; i < N_ITEMS; i++)
			if (party.items[i] > 0 && itemDefs[i].price > 0) {
				snprintf(labels[n], sizeof labels[n], "%s x%d %3dG",
				         itemDefs[i].name, party.items[i],
				         itemDefs[i].price / 2);
				items[n] = labels[n];
				map[n++] = i;
			}
		if (n == 0) {
			uiMessage("You have nothing\nI could buy.");
			return;
		}
		int s = uiMenu("SELL", items, n);
		if (s < 0)
			return;
		int id = map[s];
		party.items[id]--;
		party.gold += itemDefs[id].price / 2;
		uiStatus();
		char buf[64];
		snprintf(buf, sizeof buf, "Sold the %s\nfor %d gold.",
		         itemDefs[id].name, itemDefs[id].price / 2);
		uiMessage(buf);
	}
}

static void shopRun(const Npc *n)
{
	uiStatus();
	uiMessage(n->text);                       /* the keeper's greeting */
	while (1) {
		const char *cmds[] = { "BUY", "SELL", "LEAVE" };
		int s = uiMenu("SHOP", cmds, 3);
		if (s < 0 || s == 2) {
			uiMessage("Come again!");
			return;
		}
		if (s == 0)
			shopBuy(n);
		else
			shopSell();
	}
}

/* interactions and triggers ----------------------------------------- */

static int talk(void)
{
	int fx = px / 16 + dx[dir], fy = py / 16 + dy[dir];
	char buf[96];

	for (int i = 0; i < map->nChests; i++) {
		const Chest *ch = &map->chests[i];
		if (ch->x != fx || ch->y != fy)
			continue;
		if (flagGet(ch->flag)) {
			uiMessage("The chest is empty.");
		} else if (itemAdd(ch->item)) {
			flagSet(ch->flag);
			uiStatus();
			snprintf(buf, sizeof buf, "Found a %s!",
			         itemDefs[ch->item].name);
			uiMessage(buf);
		} else {
			uiMessage("You can't carry\nany more of those.");
		}
		hint();
		return EV_NONE;
	}

	const Npc *n = npcAt(fx, fy);
	if (n) {
		if (n->boss >= 0) {
			if (n->altFlag >= 0 && flagGet(n->altFlag)) {
				uiMessage(n->altText);   /* beaten: no rematch */
				hint();
				return EV_NONE;
			}
			uiMessage(n->text);
			pendingTroop = bossDefs[n->boss].troop;
			pendingBossFlag = n->setsFlag;   /* set on VICTORY */
			pendingBossMusic = bossDefs[n->boss].music;
			return EV_BOSS;
		}
		if (n->nShop) {
			shopRun(n);
			hint();
			return EV_NONE;
		}
		if (n->joins >= 0) {
			/* recruiter: greeting, then the join attempt. On
			 * success the sets_flag fires -- typically also this
			 * NPC's hide flag, so they step off the map and into
			 * the party. A full party refuses and nothing sticks,
			 * so talking again retries. */
			if (n->altFlag >= 0 && flagGet(n->altFlag)) {
				uiMessage(n->altText);
				hint();
				return EV_NONE;
			}
			uiMessage(n->text);
			int r = partyJoin(n->joins);
			if (r == JOIN_OK) {
				uiStatus();
				snprintf(buf, sizeof buf, "%s joins the party!",
				         party.roster[n->joins].name);
				uiMessage(buf);
				if (n->setsFlag >= 0)
					flagSet(n->setsFlag);
			} else if (r == JOIN_FULL) {
				uiMessage("The party is full!");
			}
			hint();
			return EV_NONE;
		}
		if (n->altFlag >= 0 && flagGet(n->altFlag)) {
			uiMessage(n->altText);
		} else {
			uiMessage(n->text);
			if (n->setsFlag >= 0)
				flagSet(n->setsFlag);
		}
		if (n->healer) {
			sfxHeal();
			partyRestore();
			uiStatus();
		}
		hint();
		return EV_NONE;
	}
	for (int i = 0; i < map->nSigns; i++)
		if (map->signs[i].x == fx && map->signs[i].y == fy) {
			uiMessage(map->signs[i].text);
			hint();
			return EV_NONE;
		}
	return EV_NONE;
}

static int arrived(void)
{
	int tx = px / 16, ty = py / 16;

	for (int i = 0; i < map->nWarps; i++) {
		const Warp *w = &map->warps[i];
		if (w->x == tx && w->y == ty) {
			if (w->flag >= 0 && !flagGet(w->flag)) {
				uiMessage(w->lockedText);
				hint();
				return EV_NONE;
			}
			fieldEnter(w->destMap, w->destX, w->destY);
			return EV_NONE;
		}
	}
	if (runTileEvents(tx, ty)) {
		runFlagEvents();
		hint();
		return EV_NONE;          /* no encounter on an event step */
	}
	int troop = rollEncounter(tx, ty);
	if (troop >= 0) {
		pendingTroop = troop;
		return EV_ENCOUNTER;
	}
	return EV_NONE;
}

/* per-frame update ---------------------------------------------------*/

static void drawSprites(void)
{
	int sw = map->w * 16, sh = map->h * 16;
	int scx = px - 120, scy = py - 88;
	if (scx < 0) scx = 0;
	if (scy < 0) scy = 0;
	if (scx > sw - 256) scx = sw - 256;
	if (scy > sh - 192) scy = sh - 192;
	gfxScroll(scx, scy);

	int step = moving ? (walkFrames >> 3) & 1 : 0;
	gfxWalkerSprite(0, px - scx, py - scy, dir, step, false);

	/* followers: hidden while exactly stacked on ANY walker ahead
	 * (the front sprite's transparent pixels would show them
	 * through -- covers the unfold AND a reverse step landing the
	 * hero on a follower), offscreen-culled like NPCs otherwise;
	 * the high OAM indices keep each one under its leaders during
	 * partial overlaps */
	for (int k = 0; k < N_FOLLOW; k++) {
		bool active = k < party.nParty - 1;
		bool stacked = fx[k] == px && fy[k] == py;
		for (int j = 0; j < k; j++)
			stacked |= fx[k] == fx[j] && fy[k] == fy[j];
		int sx = fx[k] - scx, sy = fy[k] - scy;
		bool off = !active || stacked
		        || sx < -16 || sx > 255
		        || sy < -16 || sy > 191;
		int fs = fstep[k] ? (walkFrames >> 3) & 1 : 0;
		gfxWalkerSprite(1 + k, sx & 511, sy & 255,
		                fdir[k], fs, off);
	}

	for (int i = 0; i < MAX_NPCS; i++) {
		if (i >= map->nNpcs || npcHidden(&map->npcs[i])) {
			gfxNpcSprite(i, 0, 0, true);
			continue;
		}
		int sx = map->npcs[i].x * 16 - scx;
		int sy = map->npcs[i].y * 16 - scy;
		bool off = sx < -16 || sx > 255 || sy < -16 || sy > 191;
		gfxNpcSprite(i, sx & 511, sy & 255, off);
	}
}

int fieldUpdate(void)
{
	int ev = EV_NONE;

	/* deferred script dispatch: on_load from a map entry (including
	 * one caused by a script warp), then any flags scripts or NPC
	 * talk raised. Blocking, at loop granularity only. */
	bool ranScripts = runLoadEvents();
	ranScripts |= runFlagEvents();
	if (ranScripts)
		hint();

	scanKeys();
	u32 held = keysHeld(), down = keysDown();

	if (!moving) {
		int want = -1;
		if      (held & KEY_DOWN)  want = DIR_DOWN;
		else if (held & KEY_UP)    want = DIR_UP;
		else if (held & KEY_LEFT)  want = DIR_LEFT;
		else if (held & KEY_RIGHT) want = DIR_RIGHT;

		if (want >= 0) {
			dir = want;
			int nx = px / 16 + dx[dir], ny = py / 16 + dy[dir];
			if (!blocked(nx, ny)) {
				moving = true;
				tgx = nx * 16;
				tgy = ny * 16;
				/* each follower repeats its leader's last move:
				 * step into the tile the leader is leaving. All
				 * positions here are PRE-step and tile-aligned,
				 * so follower k+1 reads follower k's vacated
				 * tile; a no-op while still stacked on it (that
				 * IS the unfold). */
				int lx = px, ly = py;
				for (int k = 0; k < party.nParty - 1; k++) {
					fstep[k] = (fx[k] != lx || fy[k] != ly);
					if (fstep[k]) {
						if      (lx > fx[k]) fdir[k] = DIR_RIGHT;
						else if (lx < fx[k]) fdir[k] = DIR_LEFT;
						else if (ly > fy[k]) fdir[k] = DIR_DOWN;
						else                 fdir[k] = DIR_UP;
						ftgx[k] = lx;
						ftgy[k] = ly;
					}
					lx = fx[k];
					ly = fy[k];
				}
			}
		} else if (down & KEY_A) {
			ev = talk();
		} else if (down & KEY_START) {
			const char *items[] = { "ITEM", "SAVE", "CANCEL" };
			int s = uiMenu("MENU", items, 3);
			if (s == 0)
				useItem();
			else if (s == 1)
				uiMessage(saveGame() ? "Saved!"
				                     : "Save failed.\n(No SD access?)");
			hint();
		}
	}

	if (moving) {
		walkFrames++;
		if (px < tgx) px += STEP_SPEED;
		if (px > tgx) px -= STEP_SPEED;
		if (py < tgy) py += STEP_SPEED;
		if (py > tgy) py -= STEP_SPEED;
		for (int k = 0; k < N_FOLLOW; k++) {
			if (!fstep[k])           /* same speed, same 16px --   */
				continue;            /* arrives with the hero      */
			if (fx[k] < ftgx[k]) fx[k] += STEP_SPEED;
			if (fx[k] > ftgx[k]) fx[k] -= STEP_SPEED;
			if (fy[k] < ftgy[k]) fy[k] += STEP_SPEED;
			if (fy[k] > ftgy[k]) fy[k] -= STEP_SPEED;
		}
		if (px == tgx && py == tgy) {
			moving = false;
			for (int k = 0; k < N_FOLLOW; k++)
				fstep[k] = false;
			ev = arrived();          /* may fieldEnter: restacks all */
		}
	}

	drawSprites();
	return ev;
}
