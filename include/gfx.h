#ifndef GFX_H
#define GFX_H

#include "game.h"
#include "maps.h"

/* OAM sprite slots (main engine). Followers take the LAST OAM
 * slots so during the caterpillar unfold each walker is drawn under
 * the one ahead of it (hero over follower 1 over follower 2). */
enum {
	SPR_HERO = 0,
	SPR_NPC0,                /* SPR_NPC0 .. SPR_NPC0+MAX_NPCS-1 */
	SPR_ENEMY0 = SPR_NPC0 + MAX_NPCS,   /* .. SPR_ENEMY0 + MAX_TROOP-1 */
	SPR_FOLLOW0 = 126,       /* party slot 1 */
	SPR_FOLLOW1 = 127,       /* party slot 2 */
};

void gfxInit(void);
void gfxShowTitle(void);                        /* title image on top    */
void gfxLoadGame(void);                         /* restore game tileset  */
void gfxLoadTileset(int ts);

/* field drawing */
void gfxDrawMap(const MapDef *m);
void gfxScroll(int px, int py);                 /* camera scroll in pixels */
/* walkers: party slot 0 (leader, OAM SPR_HERO) and followers 1..2
 * (SPR_FOLLOW0/1). Each slot has its own 8-frame buffer, loaded from
 * a player's sheet (NULL = hero.png art) by fieldEnter and on
 * join/leave. Frame = dir*2 + step, hero.png layout. */
void gfxLoadWalker(int slot, const unsigned short *sheet);
void gfxWalkerSprite(int slot, int sx, int sy, int dir, int step,
                     bool hide);
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
