#ifndef UI_H
#define UI_H

#include "game.h"

void uiInit(void);
void uiClear(void);
void uiStatus(void);                     /* framed party status block   */
void uiPrintAt(int x, int y, const char *fmt, ...);
void uiClearBelow(int row);              /* wipe rows row..23           */

/* window layer (coordinates in 8px cells, 32x24) */
void uiFrame(int x0, int y0, int x1, int y1);
void uiFrameClear(int x0, int y0, int x1, int y1);

/* blocking helpers -- they run the vblank/oam flush loop themselves */
void uiMessage(const char *text);        /* framed message + wait for A */
int  uiMenu(const char *title,           /* framed menu; -1 on B        */
            const char *const *items, int n);
void uiWaitA(void);
void uiShake(void);                      /* bottom-screen impact shake  */

#endif
