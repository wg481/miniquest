/* Host-side stub of libnds for syntax checking only. Signatures mirror
 * libnds 1.8+ / devkitARM. NOT for building the actual ROM. */
#ifndef STUB_NDS_H
#define STUB_NDS_H
#include <stdint.h>
#include <stdbool.h>
#include <stdio.h>

typedef uint8_t u8; typedef uint16_t u16; typedef uint32_t u32;
typedef int8_t s8; typedef int16_t s16; typedef int32_t s32;

#define BIT(n) (1 << (n))

/* video */
enum { MODE_0_2D = 0x10000 };
void videoSetMode(u32 mode);
void videoSetModeSub(u32 mode);
void lcdMainOnTop(void);

typedef enum { VRAM_A_MAIN_BG = 1 } VRAM_A_TYPE;
typedef enum { VRAM_B_MAIN_SPRITE = 2 } VRAM_B_TYPE;
typedef enum { VRAM_C_SUB_BG = 4 } VRAM_C_TYPE;
void vramSetBankA(VRAM_A_TYPE t);
void vramSetBankB(VRAM_B_TYPE t);
void vramSetBankC(VRAM_C_TYPE t);

/* backgrounds */
typedef enum {
	BgType_Text8bpp, BgType_Text4bpp, BgType_Rotation,
	BgType_ExRotation, BgType_Bmp8, BgType_Bmp16
} BgType;
typedef enum {
	BgSize_T_256x256, BgSize_T_512x256, BgSize_T_256x512, BgSize_T_512x512
} BgSize;
int  bgInit(int layer, BgType type, BgSize size, int mapBase, int tileBase);
int  bgInitSub(int layer, BgType type, BgSize size, int mapBase, int tileBase);
void bgSetPriority(int id, unsigned priority);
u16 *bgGetMapPtr(int id);
u16 *bgGetGfxPtr(int id);
void bgSetScroll(int id, int x, int y);
void bgUpdate(void);

extern u16 BG_PALETTE[256];
extern u16 SPRITE_PALETTE[256];
extern u16 BG_PALETTE_SUB[256];

void dmaCopy(const void *src, void *dest, u32 size);

/* sprites */
typedef struct OamState OamState;
extern OamState oamMain;
typedef enum { SpriteMapping_1D_32, SpriteMapping_1D_64, SpriteMapping_1D_128 } SpriteMapping;
typedef enum { SpriteSize_8x8, SpriteSize_16x16, SpriteSize_32x32, SpriteSize_64x64 } SpriteSize;
typedef enum { SpriteColorFormat_16Color, SpriteColorFormat_256Color, SpriteColorFormat_Bmp } SpriteColorFormat;
void oamInit(OamState *oam, SpriteMapping mapping, bool extPalette);
u16 *oamAllocateGfx(OamState *oam, SpriteSize size, SpriteColorFormat format);
void oamSet(OamState *oam, int id, int x, int y, int priority,
            int palette_alpha, SpriteSize size, SpriteColorFormat format,
            const void *gfxOffset, int affineIndex, bool sizeDouble,
            bool hide, bool hflip, bool vflip, bool mosaic);
void oamSetHidden(OamState *oam, int id, bool hide);
void oamUpdate(OamState *oam);

/* system / input */
void swiWaitForVBlank(void);
void scanKeys(void);
u32 keysDown(void);
u32 keysHeld(void);
enum {
	KEY_A = BIT(0), KEY_B = BIT(1), KEY_SELECT = BIT(2), KEY_START = BIT(3),
	KEY_RIGHT = BIT(4), KEY_LEFT = BIT(5), KEY_UP = BIT(6), KEY_DOWN = BIT(7),
	KEY_R = BIT(8), KEY_L = BIT(9), KEY_X = BIT(10), KEY_Y = BIT(11),
};

/* console */
typedef struct PrintConsole { int cursorX, cursorY; int bgId; } PrintConsole;
PrintConsole *consoleInit(PrintConsole *console, int layer, BgType type,
                          BgSize size, int mapBase, int tileBase,
                          bool mainDisplay, bool loadGraphics);
void consoleSelect(PrintConsole *console);
void consoleClear(void);
#define iprintf printf

#endif
