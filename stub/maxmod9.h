/* Host-side stub of maxmod9 for syntax checking only. Signatures
 * mirror devkitPro/maxmod master. */
#ifndef STUB_MAXMOD9_H
#define STUB_MAXMOD9_H
#include <stdint.h>
typedef uint32_t mm_word;
typedef uint16_t mm_sfxhand;
typedef void *mm_addr;
typedef enum { MM_PLAY_LOOP, MM_PLAY_ONCE } mm_pmode;
typedef enum { MM_MODE_A, MM_MODE_B, MM_MODE_C } mm_mode_enum;
void mmSelectMode(mm_mode_enum mode);
void mmInitDefaultMem(const void *soundbank);
void mmLoad(mm_word module_ID);
void mmUnload(mm_word module_ID);
void mmStart(mm_word module_ID, mm_pmode mode);
void mmStop(void);
void mmLoadEffect(mm_word sample_ID);
mm_sfxhand mmEffect(mm_word sample_ID);
void mmEffectCancel(mm_sfxhand handle);
#endif
