/* ui.c -- bottom-screen interface: text console over a tiled window
 * layer built from the player's UI tiles (menu.png).
 *
 * Sub engine layout:
 *   BG0 (priority 0): libnds text console, transparent background
 *   BG1 (priority 1): 4bpp "window" layer -- borders, fills, cursor
 *
 * The window tiles use sub BG palette row 1, entries 1..14 only:
 * the console owns entry 15 of every row for its ANSI colors
 * (libnds console.c writes palette[N*16 - 1]).
 *
 * Screen layout (32x24 cells):
 *   rows  0..5   status window (party stats, gold, herbs)
 *   rows  7..14  message window (also field map-info panel)
 *   rows 15..22  menu window (battle commands / targets)
 *
 * uiMessage / uiMenu / uiWaitA are BLOCKING: they own the vblank loop
 * while active, which keeps battle and dialog code straight-line.
 */
#include <stdio.h>
#include <stdarg.h>
#include <string.h>
#include "ui.h"
#include "gfx.h"
#include "gfx_data.h"
#include "sound.h"

static PrintConsole cons;
static int winBg;
static u16 *winMap;

#define MSG_ROW   8
#define MSG_END   13
#define MENU_TOP  15

/* window-layer tiles (menu.png order: corner, VERTICAL edge,
 * HORIZONTAL edge, fill, cursor -- plus generated blank at 0) */
enum { MT_BLANK = 0, MT_CORNER, MT_V, MT_H, MT_FILL, MT_CURSOR };
#define UI_PAL_ROW 1

static inline u16 ent(int tile, bool hf, bool vf)
{
	return tile | (UI_PAL_ROW << 12)
	            | (hf ? BIT(10) : 0) | (vf ? BIT(11) : 0);
}

static inline void wset(int x, int y, u16 e)
{
	winMap[y * 32 + x] = e;
}

void uiFrame(int x0, int y0, int x1, int y1)
{
	for (int y = y0 + 1; y < y1; y++)
		for (int x = x0 + 1; x < x1; x++)
			wset(x, y, ent(MT_FILL, false, false));
	for (int x = x0 + 1; x < x1; x++) {
		wset(x, y0, ent(MT_H, false, false));
		wset(x, y1, ent(MT_H, false, true));
	}
	for (int y = y0 + 1; y < y1; y++) {
		wset(x0, y, ent(MT_V, false, false));
		wset(x1, y, ent(MT_V, true, false));
	}
	wset(x0, y0, ent(MT_CORNER, false, false));
	wset(x1, y0, ent(MT_CORNER, true,  false));
	wset(x0, y1, ent(MT_CORNER, false, true));
	wset(x1, y1, ent(MT_CORNER, true,  true));
}

void uiFrameClear(int x0, int y0, int x1, int y1)
{
	for (int y = y0; y <= y1; y++)
		for (int x = x0; x <= x1; x++)
			wset(x, y, ent(MT_BLANK, false, false));
}

void uiInit(void)
{
	videoSetModeSub(MODE_0_2D);
	vramSetBankC(VRAM_C_SUB_BG);

	consoleInit(&cons, 0, BgType_Text4bpp, BgSize_T_256x256,
	            31, 0, false, true);
	bgSetPriority(cons.bgId, 0);

	/* window layer behind the text: map base 30 (60K), tiles 16K --
	 * clear of the console's font (0..) and map (62K..64K). */
	winBg = bgInitSub(1, BgType_Text4bpp, BgSize_T_256x256, 30, 1);
	bgSetPriority(winBg, 1);
	winMap = (u16 *)bgGetMapPtr(winBg);

	dmaCopy(menuTiles4Data, bgGetGfxPtr(winBg), N_MENU4_TILES * 32);
	dmaCopy(menuPal16, BG_PALETTE_SUB + UI_PAL_ROW * 16, 16 * 2);

	uiFrameClear(0, 0, 31, 23);
}

void uiClear(void)
{
	consoleSelect(&cons);
	consoleClear();
	uiFrameClear(0, 0, 31, 23);
}

void uiPrintAt(int x, int y, const char *fmt, ...)
{
	char buf[128];
	va_list ap;
	va_start(ap, fmt);
	vsnprintf(buf, sizeof buf, fmt, ap);
	va_end(ap);
	consoleSelect(&cons);
	iprintf("\x1b[%d;%dH%s", y, x, buf);
}

static void clearRow(int y)
{
	uiPrintAt(0, y, "                                ");
}

void uiClearBelow(int row)
{
	for (int y = row; y < 24; y++)
		clearRow(y);
	uiFrameClear(0, row, 31, 23);
}

void uiStatus(void)
{
	uiFrame(0, 0, 31, 5);
	for (int y = 1; y <= 4; y++)
		clearRow(y);
	for (int i = 0; i < PARTY_SIZE; i++) {
		Fighter *f = &party.member[i];
		int x = 2 + i * 15;
		uiPrintAt(x, 1, "%-6s LV%2d", f->name, f->level);
		uiPrintAt(x, 2, "HP %3d/%3d", f->hp, f->maxhp);
		uiPrintAt(x, 3, "MP %3d/%3d", f->mp, f->maxmp);
	}
	uiPrintAt(2, 4, "GOLD %5d", party.gold);
}

static void frame(void)
{
	swiWaitForVBlank();
	gfxFlush();
}

void uiWaitA(void)
{
	while (1) {
		frame();
		scanKeys();
		if (keysDown() & KEY_A)
			return;
	}
}

/* Shake the whole bottom screen: enemy hits landing on the party.
 * Both sub BGs (console + window layer) jitter together so text and
 * borders stay glued. Horizontal on purpose -- the 256px-wide BGs
 * exactly span the screen, so a sideways scroll only wraps a couple
 * of border pixels to the far edge (invisible mid-shake); a vertical
 * scroll would expose the never-written tilemap rows 24-31. */
void uiShake(void)
{
	static const int seq[] = { 3, -3, 3, -3, 2, -2, 2, -2, 1, -1 };
	for (unsigned i = 0; i < sizeof seq / sizeof seq[0]; i++) {
		bgSetScroll(cons.bgId, seq[i], 0);
		bgSetScroll(winBg, seq[i], 0);
		frame();
		frame();
	}
	bgSetScroll(cons.bgId, 0, 0);
	bgSetScroll(winBg, 0, 0);
	frame();
}

void uiMessage(const char *text)
{
	uiFrame(0, MSG_ROW - 1, 31, MSG_END + 1);
	for (int y = MSG_ROW; y <= MSG_END; y++)
		clearRow(y);

	/* print line by line so every line stays indented */
	char buf[160];
	strncpy(buf, text, sizeof buf - 1);
	buf[sizeof buf - 1] = 0;

	int row = MSG_ROW;
	char *line = buf;
	while (line && row <= MSG_END) {
		char *nl = strchr(line, '\n');
		if (nl)
			*nl = 0;
		uiPrintAt(2, row++, "%s", line);
		line = nl ? nl + 1 : NULL;
	}
	uiPrintAt(27, MSG_END, "(A)");
	uiWaitA();

	/* clean up after ourselves so nothing lingers */
	for (int y = MSG_ROW; y <= MSG_END; y++)
		clearRow(y);
	uiFrameClear(0, MSG_ROW - 1, 31, MSG_END + 1);
}

int uiMenu(const char *title, const char *const *items, int n)
{
	int top = MENU_TOP;
	int firstItem = top + 1 + (title ? 1 : 0);
	int bottom = firstItem + n;

	/* Size the frame to the longest label (min 17 = the classic
	 * width, so short menus look unchanged). Labels print at col 4,
	 * the title at col 2; keep one blank cell before the border.
	 * Fixes sell labels like "Supherb x1  10G" (15 ch) clipping. */
	int len = title ? (int)strlen(title) - 2 : 0;
	for (int i = 0; i < n; i++) {
		int l = (int)strlen(items[i]);
		if (l > len)
			len = l;
	}
	int right = 4 + len + 1;
	if (right < 17)
		right = 17;
	if (right > 31)
		right = 31;

	uiFrame(0, top, right, bottom);
	if (title)
		uiPrintAt(2, top + 1, "%s", title);
	for (int i = 0; i < n; i++)
		uiPrintAt(4, firstItem + i, "%s", items[i]);

	int sel = 0;
	while (1) {
		for (int i = 0; i < n; i++)          /* cursor: player's arrow */
			wset(2, firstItem + i,
			     ent(i == sel ? MT_CURSOR : MT_FILL, true, false));
		frame();
		scanKeys();
		u32 down = keysDown();
		if (down & KEY_UP)   { sel = (sel + n - 1) % n; sfxCursor(); }
		if (down & KEY_DOWN) { sel = (sel + 1) % n;     sfxCursor(); }
		if (down & (KEY_A | KEY_B)) {
			if (down & KEY_A)
				sfxConfirm();
			else
				sfxCancel();
			for (int y = top; y <= bottom; y++)
				clearRow(y);
			uiFrameClear(0, top, right, bottom);
			return (down & KEY_A) ? sel : -1;
		}
	}
}
