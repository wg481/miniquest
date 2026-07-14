/* sound.c -- maxmod music + sound effects from the embedded soundbank.
 *
 * Functions are named music* (not sound*) because libcalico_ds9
 * exports its own soundInit() -- naming ours the same is a link-time
 * multiple-definition error.
 *
 * The soundbank is built by mmutil from everything in music/ and
 * embedded via bin2s (see the Makefile). Track switching unloads the
 * previous module to keep RAM use flat.
 *
 * SFX are fixed-name WAVs (cursor/confirm/cancel/attack_p/attack_e/
 * heal/spell.wav) so replacing the placeholder sounds needs no code change;
 * a missing WAV means mmutil emits no SFX_ define and the call
 * compiles to a no-op.
 */
#include <nds.h>
#include <maxmod9.h>
#include "sound.h"
#include "soundbank.h"

extern const u8 soundbank_bin[];      /* from bin2s */

static int current = -1;
static bool oneshot = false;          /* current track was PLAY_ONCE */

void musicInit(void)
{
	mmInitDefaultMem((mm_addr)soundbank_bin);

	/* Extended software mixing: 30 active channels instead of the
	 * default hardware mode's 16. The DS has 16 hardware voices;
	 * maxmod's default Mode A maps module channels straight onto
	 * them, and its click-avoidance can push the active count to
	 * the full 16 during busy bars. When a track's densest passage
	 * needs more than that -- always the SAME spot every playthrough
	 * -- the module player culls its lowest-priority voices, and
	 * short frequent retriggers (drum hits) lose first: they thin
	 * out mid-song even though the module is fine in OpenMPT (which
	 * has an effectively unlimited channel pool). Mode C mixes in
	 * software up to 30 channels, clearing the ceiling. Cost is ARM7
	 * CPU (~34% for a 30-channel IT per maxmod's own CpuUsage docs);
	 * fine on DSi. If a future track ever needs to dial this back,
	 * MM_MODE_B keeps interpolation at 16 channels, MM_MODE_A is the
	 * old hardware default. (mmSelectMode/MM_MODE_C verified against
	 * devkitPro/maxmod maxmod9.h.) */
	mmSelectMode(MM_MODE_C);
#ifdef SFX_CURSOR
	mmLoadEffect(SFX_CURSOR);
#endif
#ifdef SFX_CONFIRM
	mmLoadEffect(SFX_CONFIRM);
#endif
#ifdef SFX_CANCEL
	mmLoadEffect(SFX_CANCEL);
#endif
#ifdef SFX_ATTACK_P
	mmLoadEffect(SFX_ATTACK_P);
#endif
#ifdef SFX_ATTACK_E
	mmLoadEffect(SFX_ATTACK_E);
#endif
#ifdef SFX_HEAL
	mmLoadEffect(SFX_HEAL);
#endif
#ifdef SFX_SPELL
	mmLoadEffect(SFX_SPELL);
#endif
}

void musicPlay(int module)
{
	/* same looping track: keep playing -- but a finished one-shot
	 * must restart even under the same id */
	if (module == current && !oneshot)
		return;
	if (current >= 0) {
		mmStop();
		mmUnload(current);
	}
	current = module;
	oneshot = false;
	if (module >= 0) {
		mmLoad(module);
		mmStart(module, MM_PLAY_LOOP);
	}
}

void musicPlayOnce(int module)
{
	if (module < 0)                   /* no fanfare configured */
		return;
	if (current >= 0) {
		mmStop();
		mmUnload(current);
	}
	current = module;
	oneshot = true;
	mmLoad(module);
	mmStart(module, MM_PLAY_ONCE);
}

/* One live handle per effect type: cancel the previous instance
 * before retriggering. Two jobs: restarts the sound DQ-style
 * instead of stacking it, and -- critically -- force-reclaims the
 * effect slot. maxmod's ARM9 side has only 16 effect slots, freed
 * SOLELY by an end-of-effect event from the ARM7; a slot whose
 * event never arrives (mixer channel wedged, event dropped) leaks
 * permanently, and after 16 leaks mmEffect returns handle 0 =
 * total SFX silence until a track change unwedges the mixer (the
 * spam-the-healer bug). mmEffectCancel is the reclaim path: on a
 * finished/reused handle the ARM7 validates the instance byte and
 * no-ops; on a live-or-wedged one it clears the slot AND writes
 * the bit into mm_sfx_clearmask, which guarantees the end-event
 * that frees the ARM9 slot. NEVER use mmEffectCancelAll for this:
 * its ARM7 path (mmResetEffects) zeroes the bitmask WITHOUT
 * emitting end-events, leaking every active ARM9 slot.
 * (All verified against devkitPro/maxmod master:
 * source_calico/mm_comms9.c + source/mm_effect.s.) */
static inline mm_sfxhand sfxFire(mm_sfxhand prev, mm_word id)
{
	if (prev)
		mmEffectCancel(prev);
	return mmEffect(id);
}

void sfxCursor(void)
{
#ifdef SFX_CURSOR
	static mm_sfxhand h;
	h = sfxFire(h, SFX_CURSOR);
#endif
}

void sfxConfirm(void)
{
#ifdef SFX_CONFIRM
	static mm_sfxhand h;
	h = sfxFire(h, SFX_CONFIRM);
#endif
}

void sfxCancel(void)
{
#ifdef SFX_CANCEL
	static mm_sfxhand h;
	h = sfxFire(h, SFX_CANCEL);
#endif
}

void sfxAttackPlayer(void)
{
#ifdef SFX_ATTACK_P
	static mm_sfxhand h;
	h = sfxFire(h, SFX_ATTACK_P);
#endif
}

void sfxAttackEnemy(void)
{
#ifdef SFX_ATTACK_E
	static mm_sfxhand h;
	h = sfxFire(h, SFX_ATTACK_E);
#endif
}

void sfxHeal(void)
{
#ifdef SFX_HEAL
	static mm_sfxhand h;
	h = sfxFire(h, SFX_HEAL);
#endif
}

void sfxSpell(void)
{
#ifdef SFX_SPELL
	static mm_sfxhand h;
	h = sfxFire(h, SFX_SPELL);
#endif
}
