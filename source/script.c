/* script.c -- blocking event-script interpreter.
 *
 * Bytecode (scripts_data.c) is compiled from the per-map event
 * scripts in data/maps.json by tools/gen_scripts.py. Every
 * side-effecting op is itself blocking (uiMessage, uiMenu,
 * battleRun), so scriptRun returns only when the whole script is
 * done. One condition register serves if/yesno/lose -- conditions
 * are never composed, so no stack.
 *
 * OP_WARP ends the script: it starts a new field context exactly
 * like stepping on a warp tile, and the destination's on_load
 * events (queued by fieldEnter, drained by fieldUpdate) take over.
 * That keeps scriptRun non-recursive.
 *
 * OP_BATTLE loss mirrors the main loop's death flow (gold/2 +
 * DEATH_* respawn) and abandons the script. OP_BATTLE_TRY (the
 * `lose` block form) instead heals the party and sets the register
 * so the compiled JZ runs the lose body.
 */
#include <stdio.h>
#include <string.h>
#include "game.h"
#include "script.h"
#include "scripts_data.h"
#include "ui.h"
#include "battle.h"
#include "field.h"
#include "sound.h"

/* ---- raised-flag set (on_flag dispatch) ---- */

static u32 raised[(N_VARS + 31) / 32];

void scriptFlagRaised(int id)
{
	if (id >= 0 && id < N_VARS)
		raised[id >> 5] |= (u32)1 << (id & 31);
}

int scriptTakeRaised(void)
{
	for (int w = 0; w < (N_VARS + 31) / 32; w++) {
		if (!raised[w])
			continue;
		for (int b = 0; b < 32; b++)
			if (raised[w] & ((u32)1 << b)) {
				raised[w] &= ~((u32)1 << b);
				return w * 32 + b;
			}
	}
	return -1;
}

/* ---- say / choice ---- */

/* one page: at most SAY_LINES lines of SAY_COLS chars + newlines */
#define PAGE_BUF 192

/* show a pre-wrapped payload (\n lines, \f page breaks) */
static const char *onePage(const char *t, char *buf)
{
	int n = 0;
	while (*t && *t != '\f' && n < PAGE_BUF - 1)
		buf[n++] = *t++;
	buf[n] = 0;
	return *t == '\f' ? t + 1 : NULL;
}

static void sayText(const char *t)
{
	char buf[PAGE_BUF];
	do {
		t = onePage(t, buf);
		uiMessage(buf);
	} while (t);
}

/* two-choice prompt; returns 1 = YES (first option), 0 = NO.
 * B cancels to NO, DQ style. A short single-line prompt becomes the
 * menu title so it stays visible while choosing; longer prompts are
 * shown as message pages first. */
static int choiceRun(const char *prompt)
{
	static const char *const items[] = { "YES", "NO" };
	const char *title = NULL;
	if (!strchr(prompt, '\n') && !strchr(prompt, '\f')
	    && strlen(prompt) <= 26)
		title = prompt;
	else
		sayText(prompt);
	int s = uiMenu(title, items, 2);
	return s == 0 ? 1 : 0;
}

/* ---- battles from scripts ---- */

/* mirror of the main loop's battle entry/exit */
static int scriptBattle(int troop)
{
	if (battleMusic >= 0)
		musicPlay(battleMusic);
	int r = battleRun(troop);
	if (r != BATTLE_LOST)
		fieldRedraw();
	return r;
}

/* mirror of the main loop's death flow */
static void deathFlow(void)
{
	party.gold /= 2;
	partyRestore();
	fieldEnter(DEATH_MAP, DEATH_X, DEATH_Y);
	uiMessage("You awaken safe in town.\nHalf your gold is gone...");
	fieldRedraw();
}

/* ---- the interpreter ---- */

void scriptRun(int index)
{
	if (index < 0 || index >= SCRIPT_COUNT)
		return;
	const unsigned char *base = scriptData + scriptOffset[index];
	const unsigned char *p = base;
	int reg = 0;

	for (;;) {
		int op = *p++;
		switch (op) {
		case OP_END:
			return;
		case OP_SAY: {
			int off = p[0] | (p[1] << 8);
			p += 2;
			sayText(scriptText + off);
			break;
		}
		case OP_SET_FLAG: {
			int fl = p[0] | (p[1] << 8);
			int v = p[2];
			p += 3;
			flagPut(fl, v);
			break;
		}
		case OP_GIVE: {
			int it = p[0] | (p[1] << 8);
			int qty = p[2];
			p += 3;
			while (qty-- > 0)
				if (!itemAdd(it))
					break;         /* silently capped */
			break;
		}
		case OP_WARP: {
			int mp = p[0] | (p[1] << 8);
			int x = p[2], y = p[3];
			fieldEnter(mp, x, y);
			return;                /* new field context owns it */
		}
		case OP_HEAL:
			sfxHeal();
			partyRestore();
			uiStatus();
			break;
		case OP_BATTLE: {
			int tr = p[0] | (p[1] << 8);
			p += 2;
			if (scriptBattle(tr) == BATTLE_LOST) {
				deathFlow();
				return;            /* abandon the script */
			}
			break;
		}
		case OP_BATTLE_TRY: {
			int tr = p[0] | (p[1] << 8);
			p += 2;
			if (scriptBattle(tr) == BATTLE_LOST) {
				partyRestore();    /* spared: heal + lose body */
				fieldRedraw();
				uiStatus();
				reg = 1;
			} else {
				reg = 0;
			}
			break;
		}
		case OP_JZ: {
			int t = p[0] | (p[1] << 8);
			p += 2;
			if (!reg)
				p = base + t;
			break;
		}
		case OP_JMP: {
			int t = p[0] | (p[1] << 8);
			p = base + t;
			break;
		}
		case OP_PUSH_FLAG: {
			int fl = p[0] | (p[1] << 8);
			p += 2;
			reg = flagGet(fl) ? 1 : 0;
			break;
		}
		case OP_CHOICE: {
			int off = p[0] | (p[1] << 8);
			p += 2;
			reg = choiceRun(scriptText + off);
			break;
		}
		default:
			return;                /* corrupt bytecode: bail */
		}
	}
}
