# Miniquest Engine -- NDS Makefile for libnds 2.x (calico toolchain).
#
#   make            build the .nds (regenerates data first)
#   make data       regenerate C from data/*.json + gfx/*.png
#   make clean
#
# libfat is required for the save system.

TARGET   := miniquest
SOURCES  := $(wildcard source/*.c)
OBJS     := $(SOURCES:.c=.o) build/soundbank_bin.o
DEPS     := $(SOURCES:.c=.d)
MUSIC    := $(wildcard music/*.mod music/*.it music/*.xm music/*.s3m \
                        music/*.wav)

PREFIX   := $(DEVKITARM)/bin/arm-none-eabi-
CC       := $(PREFIX)gcc
NDSTOOL  := $(DEVKITPRO)/tools/bin/ndstool
MMUTIL   := $(DEVKITPRO)/tools/bin/mmutil
BIN2S    := $(DEVKITPRO)/tools/bin/bin2s

CALICO   := $(DEVKITPRO)/calico
LIBNDS   := $(DEVKITPRO)/libnds

ARCH     := -march=armv5te -mtune=arm946e-s
CFLAGS   := -Wall -O2 -MMD -MP -ffunction-sections -fdata-sections $(ARCH) \
            -DARM9 -D__NDS__ \
            -Iinclude -Ibuild -I$(CALICO)/include -I$(LIBNDS)/include
LDFLAGS  := -specs=$(CALICO)/share/ds9.specs $(ARCH) \
            -L$(CALICO)/lib -L$(LIBNDS)/lib
LIBS     := -lfat -lmm9 -lnds9 -lcalico_ds9

$(TARGET).nds: $(TARGET).elf
	$(NDSTOOL) -c $@ -9 $< -7 $(CALICO)/bin/ds7_maine.elf \
		-b $(CALICO)/share/nds-icon.bmp \
		"Miniquest;Miniquest Engine;built with libnds"

$(TARGET).elf: $(OBJS)
	$(CC) $(LDFLAGS) $(OBJS) $(LIBS) -o $@

%.o: %.c
	$(CC) $(CFLAGS) -c $< -o $@

# music/* -> embedded soundbank (mmutil defines: MOD_<STEM UPPER> for
# tracker modules, SFX_<STEM UPPER> for WAV sound effects)
build/soundbank.bin build/soundbank.h: $(MUSIC)
	@mkdir -p build
	$(MMUTIL) $(MUSIC) -d -obuild/soundbank.bin -hbuild/soundbank.h

build/soundbank_bin.o: build/soundbank.bin
	cd build && $(BIN2S) -a 4 soundbank.bin | \
		$(CC) -x assembler-with-cpp -c - -o soundbank_bin.o

# generated sources depend on the soundbank header
source/maps.o source/db_data.o source/sound.o: build/soundbank.h

# auto header deps: any .h change rebuilds every .c that includes it
# (before this, header-only changes linked against stale objects)
-include $(DEPS)

data:
	python3 tools/gen_db.py
	python3 tools/png2ds.py
	python3 tools/gen_maps.py

clean:
	rm -f $(OBJS) $(DEPS) $(TARGET).elf $(TARGET).nds \
	      build/soundbank.bin build/soundbank.h

.PHONY: data clean
