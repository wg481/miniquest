#ifndef SOUND_H
#define SOUND_H

/* maxmod music playback. Modules are compiled into an embedded
 * soundbank from the music folder by mmutil (see Makefile).
 * Per-map track ids come from MapDef.music (-1 = silence). */
void musicInit(void);
void musicPlay(int module);       /* switch track; -1 stops */
void musicPlayOnce(int module);   /* non-loop fanfare; -1 = no-op.
                                   * The next musicPlay always
                                   * restarts, even for the same id. */

/* UI sound effects: fixed-name WAVs in music/ (cursor.wav,
 * confirm.wav, cancel.wav -> SFX_CURSOR/...). Missing files
 * compile to silent no-ops via #ifdef. */
void sfxCursor(void);
void sfxConfirm(void);
void sfxCancel(void);

/* battle SFX, same fixed-name scheme: attack_p.wav (player,
 * high) / attack_e.wav (enemy, low) */
void sfxAttackPlayer(void);
void sfxAttackEnemy(void);

/* heal.wav: item heals, NPC healers, and heal spells (spell heals
 * were silent pre-overhaul; revert point marked in castSpell) */
void sfxHeal(void);

/* spell.wav: offensive spells only, fired with the enemy flash */
void sfxSpell(void);

#endif
