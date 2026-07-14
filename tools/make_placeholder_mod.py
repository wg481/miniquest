#!/usr/bin/env python3
"""
make_placeholder_mod.py -- generate music/town-theme.mod, a tiny valid
ProTracker module (square-wave chiptune loop), so the sound pipeline
works end to end before real tracker files exist. Replace or delete it
once real .it/.xm/.mod files are imported.
"""

import math
import os
import struct
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def square_sample(n=64, volume=90):
	"""One cycle of a square wave, signed 8-bit."""
	return bytes((volume if i < n // 2 else 256 - volume) for i in range(n))


def cell(sample, period, effect=0, param=0):
	return bytes([
		(sample & 0xF0) | ((period >> 8) & 0x0F),
		period & 0xFF,
		((sample & 0x0F) << 4) | (effect & 0x0F),
		param & 0xFF,
	])


def main(out=None):
	out = out or os.path.join(ROOT, "music", "town-theme.mod")
	os.makedirs(os.path.dirname(out), exist_ok=True)

	pcm = square_sample()

	# --- header: title + 31 sample slots ---
	data = b"placeholder theme".ljust(20, b"\0")
	# sample 1: name, length/2 (BE), finetune, volume, loop start/2, loop len/2
	data += (b"square".ljust(22, b"\0")
	         + struct.pack(">H", len(pcm) // 2)
	         + bytes([0, 48])
	         + struct.pack(">HH", 0, len(pcm) // 2))
	for _ in range(30):
		data += b"\0" * 22 + struct.pack(">H", 0) + bytes([0, 0]) \
		        + struct.pack(">HH", 0, 1)

	data += bytes([1, 127])              # song length 1, restart byte
	data += bytes([0]) + b"\0" * 127     # pattern order: just pattern 0
	data += b"M.K."

	# --- pattern 0: gentle 4-note arpeggio on channel 1, 64 rows ---
	periods = {"C2": 428, "E2": 339, "G2": 302, "A2": 269, "C3": 214}
	melody = ["C2", "E2", "G2", "C3", "G2", "E2", "A2", "E2"]
	rows = []
	for r in range(64):
		if r % 8 == 0:
			ch1 = cell(1, periods[melody[(r // 8) % len(melody)]])
		else:
			ch1 = cell(0, 0)
		rows.append(ch1 + cell(0, 0) * 3)
	data += b"".join(rows)

	data += pcm                          # sample PCM (signed 8-bit)

	with open(out, "wb") as f:
		f.write(data)
	print("wrote %s (%d bytes)" % (out, len(data)))


if __name__ == "__main__":
	main(sys.argv[1] if len(sys.argv) > 1 else None)
