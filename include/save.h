#ifndef SAVE_H
#define SAVE_H

#include "game.h"

/* .sav on the SD card / flashcart via FAT. saveInit() once at boot;
 * if FAT init fails, saveGame/loadGame return false gracefully. */
void saveInit(void);
bool saveExists(void);
bool saveGame(void);
bool loadGame(void);        /* fills party + returns spawn via pointers */
int  savedMap(void);
int  savedX(void);
int  savedY(void);

#endif
