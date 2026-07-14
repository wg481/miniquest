#ifndef BATTLE_H
#define BATTLE_H

#include "game.h"

/* Runs a whole battle (blocking) against the given troop id.
 * Returns true if the party survived, false on a wipe. */
int  battleRun(int troopId);   /* BATTLE_WON / FLED / LOST */

#endif
