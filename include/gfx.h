#ifndef GFX_H
#define GFX_H

#include "game.h"
#include "maps.h"

/* OAM sprite slots (main engine) */
enum {
	SPR_HERO = 0,
	SPR_NPC0,                /* SPR_NPC0 .. SPR_NPC0+MAX_NPCS-1 */
	SPR_ENEMY0 = SPR_NPC0 + MAX_NPCS,   /* .. SPR_ENEMY0 + MAX_TROOP-1 */
	SPR_MAGE = 127,          /* last OAM slot: always under the hero */
};

void gfxInit(void);
void gfxShowTitle(void);                        /* title image on top    */
void gfxLoadGame(void);                         /* restore game tileset  */
void gfxLoadTileset(int ts);

/* field drawing */
void gfxDrawMap(const MapDef *m);
void gfxScroll(int px, int py);                 /* camera scroll in pixels */
void gfxHeroSprite(int sx, int sy, int dir, int step, bool hide);
void gfxMageSprite(int sx, int sy, int dir, int step, bool hide);
void gfxLoadNpc(int slot, const unsigned short *gfx); /* NULL = NPC1 */
void gfxNpcSprite(int slot, int sx, int sy, bool hide);
void gfxHideFieldSprites(void);

/* battle drawing */
void gfxBattleScene(const unsigned short *bd);  /* 384-tile backdrop from
                                                   png2ds; NULL = black bg
                                                   + menu window frame */
void gfxLoadEnemy(int slot, const unsigned short *gfx);
void gfxEnemySprite(int slot, int sx, int sy, bool hide);

void gfxFlush(void);                            /* oamUpdate + bgUpdate */

#endif
