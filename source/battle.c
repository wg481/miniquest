/* battle.c -- classic DQ round-based combat, driven by the database.
 *
 * Encounters arrive as a troop id (see data/database.json); enemies,
 * items, player stats, and the level curve all come from db_data.
 * Blocking UI helpers keep this file straight-line.
 *
 * Damage: base = atk - def/2, dealing base/4 .. base/2 with a floor.
 */
#include <stdio.h>
#include <string.h>
#include "battle.h"
#include "game.h"
#include "gfx.h"
#include "field.h"
#include "ui.h"
#include "sound.h"

typedef struct {
	const EnemyDef *def;
	int hp;
	bool alive;
} BEnemy;

static BEnemy en[MAX_TROOP];
static int nEn;

enum { CMD_NONE, CMD_ATTACK, CMD_DEFEND, CMD_ITEM, CMD_SPELL };
typedef struct { int cmd, target, item, spell; } Action;
static Action act[PARTY_SIZE];

static void frame(void)
{
	swiWaitForVBlank();
	gfxFlush();
}

static void wait(int n)
{
	while (n--)
		frame();
}

static int enemyX(int i)
{
	static const int pos1[] = { 96 };
	static const int pos2[] = { 56, 136 };
	static const int pos3[] = { 24, 96, 168 };
	const int *p = nEn == 1 ? pos1 : nEn == 2 ? pos2 : pos3;
	return p[i];
}

static void drawEnemies(void)
{
	for (int i = 0; i < MAX_TROOP; i++)
		gfxEnemySprite(i, i < nEn ? enemyX(i) : 0, 56,
		               i >= nEn || !en[i].alive);
}

static void flash(int slot)
{
	for (int k = 0; k < 3; k++) {
		gfxEnemySprite(slot, 0, 0, true);
		wait(3);
		drawEnemies();
		wait(3);
	}
}

static int dqDamage(int atk, int def)
{
	int base = atk - def / 2;
	if (base < 2)
		return rnd(2);
	int dmg = base / 4 + rnd(base / 4 + 1);
	return dmg < 1 ? 1 : dmg;
}

static int aliveEnemies(void)
{
	int n = 0;
	for (int i = 0; i < nEn; i++)
		n += en[i].alive;
	return n;
}

static int aliveParty(void)
{
	int n = 0;
	for (int i = 0; i < PARTY_SIZE; i++)
		n += party.member[i].hp > 0;
	return n;
}

/* ---- target / item pickers (blocking; -1 = B pressed) ---- */

static int pickEnemy(void)
{
	if (aliveEnemies() == 1) {
		for (int i = 0; i < nEn; i++)
			if (en[i].alive)
				return i;
	}
	const char *items[MAX_TROOP];
	int map[MAX_TROOP], n = 0;
	for (int i = 0; i < nEn; i++)
		if (en[i].alive) {
			items[n] = en[i].def->name;
			map[n++] = i;
		}
	int s = uiMenu("TARGET?", items, n);
	return s < 0 ? -1 : map[s];
}

static int pickAlly(void)
{
	const char *items[PARTY_SIZE];
	for (int i = 0; i < PARTY_SIZE; i++)
		items[i] = party.member[i].name;
	return uiMenu("ON WHOM?", items, PARTY_SIZE);
}

static int pickItem(void)
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
	int s = uiMenu("ITEM", items, n);
	return s < 0 ? -1 : map[s];
}

/* menu of spells known at the current level; -1 = B pressed */
static int pickSpell(const Fighter *f, const PlayerDef *pd)
{
	static char labels[MAX_SPELLS][20];
	const char *items[MAX_SPELLS];
	int map[MAX_SPELLS], n = 0;
	for (int i = 0; i < pd->nSpells; i++) {
		const SpellDef *sp = &spellDefs[pd->spells[i]];
		if (sp->level > f->level)
			continue;
		snprintf(labels[n], sizeof labels[n], "%-9s%2dMP",
		         sp->name, sp->cost);
		items[n] = labels[n];
		map[n++] = pd->spells[i];
	}
	int sel = uiMenu("SPELL", items, n);
	return sel < 0 ? -1 : map[sel];
}

/* any spell castable at this level? */
static bool knowsSpells(const Fighter *f, const PlayerDef *pd)
{
	for (int i = 0; i < pd->nSpells; i++)
		if (spellDefs[pd->spells[i]].level <= f->level)
			return true;
	return false;
}

/* ---- command phase; returns true if the party fled ---- */

static bool chooseCommands(void)
{
	int i = 0;
	while (i < PARTY_SIZE) {
		Fighter *f = &party.member[i];
		const PlayerDef *pd = &playerDefs[i];
		f->defending = false;
		act[i].cmd = CMD_NONE;
		if (f->hp <= 0) {
			i++;
			continue;
		}

		const char *items[5];
		int cmds[5], n = 0;
		items[n] = "ATTACK"; cmds[n++] = CMD_ATTACK;
		if (knowsSpells(f, pd)) {
			items[n] = "SPELL"; cmds[n++] = CMD_SPELL;
		}
		items[n] = "DEFEND"; cmds[n++] = CMD_DEFEND;
		items[n] = "ITEM";   cmds[n++] = CMD_ITEM;
		items[n] = "RUN";    cmds[n++] = -1;

		int s = uiMenu(f->name, items, n);
		if (s < 0) {                         /* B: back to previous */
			int p = i - 1;
			while (p >= 0 && party.member[p].hp <= 0)
				p--;
			if (p >= 0)
				i = p;
			continue;
		}
		int cmd = cmds[s];

		if (cmd == -1) {                     /* RUN */
			if (rnd(2)) {
				uiMessage("The party flees!");
				return true;
			}
			uiMessage("Couldn't escape!");
			act[i].cmd = CMD_NONE;
			i++;
			continue;
		}
		if (cmd == CMD_SPELL) {
			int sp = pickSpell(f, pd);
			if (sp < 0)
				continue;
			if (f->mp < spellDefs[sp].cost) {
				uiMessage("Not enough MP!");
				continue;
			}
			act[i].spell = sp;
		}
		if (cmd == CMD_ITEM) {
			int it = pickItem();
			if (it < 0)
				continue;
			act[i].item = it;
		}
		if (cmd == CMD_ATTACK) {
			int t = pickEnemy();
			if (t < 0)
				continue;
			act[i].target = t;
		} else if (cmd == CMD_ITEM) {
			int t = pickAlly();
			if (t < 0)
				continue;
			act[i].target = t;
		} else if (cmd == CMD_SPELL) {
			const SpellDef *sp = &spellDefs[act[i].spell];
			act[i].target = -1;
			if (!sp->all) {
				int t = sp->effect == SPELL_HEAL ? pickAlly()
				                                 : pickEnemy();
				if (t < 0)
					continue;
				act[i].target = t;
			}
		}
		act[i].cmd = cmd;
		i++;
	}
	return false;
}

/* ---- execution phase ---- */

/* apply + report a heal; callers announce the action and play the
 * SFX first (the universal announce -> A -> SFX -> result rhythm) */
static void healAlly(int t, int amount)
{
	Fighter *tf = &party.member[t];
	tf->hp += amount;
	if (tf->hp > tf->maxhp)
		tf->hp = tf->maxhp;
	uiStatus();
	char buf[64];
	snprintf(buf, sizeof buf, "%s recovers %d HP.", tf->name, amount);
	uiMessage(buf);
}

/* fire damage: ignores defense; rolls power/2 .. power */
static int fireDamage(const SpellDef *sp)
{
	int lo = sp->power / 2;
	return lo + rnd(sp->power - lo + 1);
}

static void castSpell(int i)
{
	Fighter *f = &party.member[i];
	const SpellDef *sp = &spellDefs[act[i].spell];
	char buf[160];
	int len;

	if (f->mp < sp->cost)
		return;

	/* announce -> (A) -> SFX/anim -> effect + result */
	snprintf(buf, sizeof buf, "%s casts %s!", f->name, sp->name);
	uiMessage(buf);
	f->mp -= sp->cost;
	uiStatus();

	if (sp->effect == SPELL_HEAL) {
		sfxHeal();       /* NOTE: reverses the old "spell heals stay
		                  * silent" choice -- delete this line (and
		                  * the sound.h comment) to restore silence */
		if (sp->all) {
			for (int k = 0; k < PARTY_SIZE; k++) {
				Fighter *tf = &party.member[k];
				tf->hp += sp->power + rnd(8);
				if (tf->hp > tf->maxhp)
					tf->hp = tf->maxhp;
			}
			uiStatus();
			uiMessage("The party recovers!");
		} else {
			healAlly(act[i].target, sp->power + rnd(8));
		}
		return;
	}

	/* SPELL_FIRE */
	if (sp->all) {
		len = 0;
		for (int k = 0; k < nEn; k++) {
			if (!en[k].alive)
				continue;
			int dmg = fireDamage(sp);
			en[k].hp -= dmg;
			if (en[k].hp <= 0) {
				en[k].alive = false;
				len += snprintf(buf + len, sizeof buf - len,
				                "%s%s is destroyed!",
				                len ? "\n" : "", en[k].def->name);
			} else {
				len += snprintf(buf + len, sizeof buf - len,
				                "%s%s takes %d damage.",
				                len ? "\n" : "", en[k].def->name, dmg);
			}
		}
		sfxSpell();
		for (int k = 0; k < 3; k++) {        /* flash the troop */
			for (int e = 0; e < MAX_TROOP; e++)
				gfxEnemySprite(e, 0, 0, true);
			wait(3);
			drawEnemies();
			wait(3);
		}
		uiMessage(buf);
	} else {
		int t = act[i].target;
		if (!en[t].alive) {                  /* retarget */
			t = -1;
			for (int k = 0; k < nEn; k++)
				if (en[k].alive)
					t = k;
			if (t < 0)
				return;
		}
		int dmg = fireDamage(sp);
		en[t].hp -= dmg;
		sfxSpell();
		flash(t);
		if (en[t].hp <= 0) {
			en[t].alive = false;
			drawEnemies();
			snprintf(buf, sizeof buf,
			         "%s takes %d damage.\n%s is destroyed!",
			         en[t].def->name, dmg, en[t].def->name);
		} else {
			snprintf(buf, sizeof buf, "%s takes %d damage.",
			         en[t].def->name, dmg);
		}
		uiMessage(buf);
	}
}

static void playerAct(int i)
{
	Fighter *f = &party.member[i];
	char buf[96];
	if (f->hp <= 0)
		return;

	switch (act[i].cmd) {
	case CMD_ATTACK: {
		int t = act[i].target;
		if (!en[t].alive) {                  /* retarget */
			t = -1;
			for (int k = 0; k < nEn; k++)
				if (en[k].alive)
					t = k;
			if (t < 0)
				return;
		}
		snprintf(buf, sizeof buf, "%s attacks!", f->name);
		uiMessage(buf);
		int dmg = dqDamage(f->atk, en[t].def->def);
		en[t].hp -= dmg;
		sfxAttackPlayer();
		flash(t);
		if (en[t].hp <= 0) {
			en[t].alive = false;
			drawEnemies();
			snprintf(buf, sizeof buf,
			         "%s takes %d damage.\n%s is defeated!",
			         en[t].def->name, dmg, en[t].def->name);
		} else {
			snprintf(buf, sizeof buf, "%s takes %d damage.",
			         en[t].def->name, dmg);
		}
		uiMessage(buf);
		break;
	}
	case CMD_DEFEND:
		f->defending = true;
		snprintf(buf, sizeof buf, "%s defends.", f->name);
		uiMessage(buf);
		break;
	case CMD_ITEM: {
		int it = act[i].item;
		if (party.items[it] <= 0)
			return;
		snprintf(buf, sizeof buf, "%s uses a %s!",
		         f->name, itemDefs[it].name);
		uiMessage(buf);
		party.items[it]--;
		sfxHeal();
		healAlly(act[i].target, itemDefs[it].heal + rnd(6));
		break;
	}
	case CMD_SPELL:
		castSpell(i);
		break;
	}
}

static void enemyAct(int e)
{
	char buf[96];
	if (!en[e].alive)
		return;

	int t;
	do {
		t = rnd(PARTY_SIZE);
	} while (party.member[t].hp <= 0);

	/* DQ-style impact sequence: announce (wait for A), then the
	 * hit lands -- SFX + bottom-screen shake -- then the stats
	 * refresh and the damage line. */
	Fighter *f = &party.member[t];
	snprintf(buf, sizeof buf, "%s attacks!", en[e].def->name);
	uiMessage(buf);

	sfxAttackEnemy();
	uiShake();

	int dmg = dqDamage(en[e].def->atk, f->def);
	if (f->defending)
		dmg /= 2;
	f->hp -= dmg;
	if (f->hp < 0)
		f->hp = 0;
	uiStatus();
	if (f->hp == 0)
		snprintf(buf, sizeof buf, "%s takes %d damage.\n%s collapses!",
		         f->name, dmg, f->name);
	else
		snprintf(buf, sizeof buf, "%s takes %d damage.",
		         f->name, dmg);
	uiMessage(buf);
}

/* ---- rewards ---- */

static void levelUp(int i)
{
	Fighter *f = &party.member[i];
	const PlayerDef *pd = &playerDefs[i];
	char buf[96];
	while (f->level < MAX_LEVEL && f->exp >= expNeed[f->level + 1]) {
		f->level++;
		f->maxhp += pd->ghp;  f->hp += pd->ghp;
		f->maxmp += pd->gmp;  f->mp += pd->gmp;
		f->atk += pd->gatk;
		f->def += pd->gdef;
		f->agi += pd->gagi;
		uiStatus();
		snprintf(buf, sizeof buf, "%s reached level %d!",
		         f->name, f->level);
		uiMessage(buf);
	}
}

static void victory(void)
{
	/* DQ-style fanfare: plays once over the victory/EXP messages
	 * (uiMessage waits for A); returning to the field restarts the
	 * map track via fieldRedraw -- musicPlayOnce marks the track
	 * one-shot so that resume never no-ops. -1 = old behavior
	 * (battle music keeps looping through the messages). */
	musicPlayOnce(victoryMusic);

	int exp = 0, gold = 0;
	for (int i = 0; i < nEn; i++) {
		exp += en[i].def->exp;
		gold += en[i].def->gold;
	}
	party.gold += gold;
	char buf[96];
	snprintf(buf, sizeof buf,
	         "Victory!\nGained %d EXP and %d gold.", exp, gold);
	uiStatus();
	uiMessage(buf);

	for (int i = 0; i < PARTY_SIZE; i++)
		if (party.member[i].hp > 0) {
			party.member[i].exp += exp;
			levelUp(i);
		}

	/* small chance to find item 0 (whatever it is in the database) */
	if (N_ITEMS > 0 && rnd(4) == 0 && itemAdd(0)) {
		uiStatus();
		snprintf(buf, sizeof buf, "Found a %s!", itemDefs[0].name);
		uiMessage(buf);
	}
}

/* ---- the whole battle ---- */

int battleRun(int troopId)
{
	const TroopDef *troop = &troopDefs[troopId];
	nEn = troop->n;
	for (int i = 0; i < nEn; i++) {
		en[i].def = &enemyDefs[troop->members[i]];
		en[i].hp = en[i].def->hp;
		en[i].alive = true;
		gfxLoadEnemy(i, en[i].def->gfx);
	}

	gfxHideFieldSprites();
	gfxBattleScene(fieldBackdrop());
	drawEnemies();
	uiClear();
	uiStatus();

	char buf[64];
	snprintf(buf, sizeof buf, "%s appears!", troop->name);
	buf[0] = (buf[0] >= 'a' && buf[0] <= 'z') ? buf[0] - 32 : buf[0];
	uiMessage(buf);

	while (1) {
		if (chooseCommands())
			return BATTLE_FLED;

		int order[PARTY_SIZE + MAX_TROOP], n = 0;
		for (int i = 0; i < PARTY_SIZE; i++)
			if (party.member[i].hp > 0)
				order[n++] = i;
		for (int i = 0; i < nEn; i++)
			if (en[i].alive)
				order[n++] = 100 + i;

		int key[PARTY_SIZE + MAX_TROOP];
		for (int i = 0; i < n; i++) {
			int a = (order[i] >= 100)
			      ? en[order[i] - 100].def->agi
			      : party.member[order[i]].agi;
			key[i] = a + rnd(3);
		}
		for (int i = 0; i < n; i++)
			for (int j = i + 1; j < n; j++)
				if (key[j] > key[i]) {
					int t = key[i]; key[i] = key[j]; key[j] = t;
					t = order[i]; order[i] = order[j]; order[j] = t;
				}

		for (int i = 0; i < n; i++) {
			if (order[i] >= 100)
				enemyAct(order[i] - 100);
			else
				playerAct(order[i]);

			if (aliveEnemies() == 0) {
				victory();
				return BATTLE_WON;
			}
			if (aliveParty() == 0) {
				uiMessage("The party has fallen...");
				return BATTLE_LOST;
			}
		}
	}
}
