#ifndef FIELD_H
#define FIELD_H

#include "game.h"

void fieldEnter(int mapId, int tx, int ty);   /* load map, place player */
int  fieldUpdate(void);                       /* one frame -> EV_* code */
int  fieldPendingTroop(void);                 /* troop id after EV_ENCOUNTER/EV_BOSS */
int  fieldPendingBossFlag(void);              /* boss victory flag; -1 none */
int  fieldPendingBossMusic(void);             /* boss MOD_ id; -1 = battleMusic */
void fieldRedraw(void);                       /* restore after battle   */
void fieldPartyChanged(void);                 /* after join/leave: reload
                                                 walker sheets + restack
                                                 followers on the leader */
const unsigned short *fieldBackdrop(void);    /* map's backdrop; NULL = frame */
int  fieldMap(void);                          /* current position, for  */
int  fieldX(void);                            /* the save system        */
int  fieldY(void);

#endif
