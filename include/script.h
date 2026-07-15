#ifndef SCRIPT_H
#define SCRIPT_H

/* Event-script interpreter. Bytecode is generated into
 * scripts_data.c by tools/gen_scripts.py; the opcode values here
 * must match tools/script_lang.py. */

enum {
	OP_END = 0,
	OP_SAY,          /* u16 textOffset (pre-wrapped, \f pages)      */
	OP_SET_FLAG,     /* u16 flagIdx, u8 val                         */
	OP_GIVE,         /* u16 itemIdx, u8 qty                         */
	OP_WARP,         /* u16 mapIdx, u8 x, u8 y -- ENDS the script   */
	OP_HEAL,         /*                                             */
	OP_BATTLE,       /* u16 troopIdx; loss = death flow + abort     */
	OP_BATTLE_TRY,   /* u16 troopIdx; loss heals, reg=1 (lose blk)  */
	OP_JZ,           /* u16 target; jump when reg == 0              */
	OP_JMP,          /* u16 target                                  */
	OP_PUSH_FLAG,    /* u16 flagIdx -> reg                          */
	OP_CHOICE,       /* u16 textOffset; YES -> reg=1, NO -> reg=0   */
	OP_JOIN,         /* u16 playerIdx; full party = message + cont. */
	OP_LEAVE,        /* u16 playerIdx; last member = silent no-op   */
};

/* Run one script to completion (blocking; may run battles, warp the
 * party, or trigger the death flow). */
void scriptRun(int index);

/* Called by flagPut on every 0->1 flag transition; the field loop
 * drains the raised set to fire on_flag events. */
void scriptFlagRaised(int id);
int  scriptTakeRaised(void);     /* lowest raised flag, or -1 */

#endif
