#!/usr/bin/env python3
"""Compose the three maps as ASCII, emit C rows, render a preview PNG.

Legend: . grass  T tree  ~ water  = path  # black  ^ mountain  H house
        w wood floor  s sign  r roof  f roof-slant-L  b roof-slant-R
        B brick  D door
"""
import re
from PIL import Image

LEGEND = {'.':0,'T':1,'~':2,'=':3,'#':4,' ':5,'^':6,'H':7,'w':8,'s':9,
          'r':10,'f':15,'b':16,'B':13,'D':14}

def grid(w, h, fill):
	return [[fill]*w for _ in range(h)]

def put(g, x, y, s):
	for i, ch in enumerate(s):
		g[y][x+i] = ch

def vline(g, x, y0, y1, ch):
	for y in range(y0, y1+1): g[y][x] = ch

def hline(g, y, x0, x1, ch):
	for x in range(x0, x1+1): g[y][x] = ch

def blob(g, x, y, w, h, ch):
	for yy in range(y, y+h):
		for xx in range(x, x+w): g[yy][xx] = ch

# ---------------- overworld 32x24 ----------------
ow = grid(32, 24, '.')
hline(ow, 0, 0, 31, '^'); hline(ow, 23, 0, 31, '^')
vline(ow, 0, 0, 23, '^'); vline(ow, 31, 0, 23, '^')
hline(ow, 1, 0, 5, '^'); hline(ow, 22, 26, 31, '^')
# river down the middle with a ford gap
vline(ow, 16, 1, 9, '~'); vline(ow, 17, 1, 9, '~')
vline(ow, 16, 13, 22, '~'); vline(ow, 17, 13, 22, '~')
# forests
blob(ow, 3, 2, 4, 3, 'T'); blob(ow, 22, 3, 6, 2, 'T')
blob(ow, 5, 15, 3, 4, 'T'); blob(ow, 24, 17, 4, 3, 'T')
blob(ow, 10, 4, 2, 2, 'T'); blob(ow, 20, 12, 2, 2, 'T')
# mountains inland
blob(ow, 26, 8, 4, 2, '^'); blob(ow, 2, 10, 3, 2, '^')
# towns + path between, crossing the ford
ow[8][6] = 'H'          # Westhollow
ow[15][25] = 'H'        # Eastbrook
hline(ow, 8, 7, 16, '=')
vline(ow, 16, 8, 12, '='); vline(ow, 17, 10, 12, '=')  # ford
hline(ow, 12, 17, 25, '=')
vline(ow, 25, 12, 14, '=')
ow[9][6] = '='; ow[10][6] = 's'   # sign below town A... sign is solid; put beside
ow[10][6] = '='; ow[9][7] = 's'

# ---------------- town template 20x16 ----------------
def town(name):
	g = grid(20, 16, '.')
	hline(g, 0, 0, 19, '#'); hline(g, 15, 0, 19, '#')
	vline(g, 0, 0, 15, '#'); vline(g, 19, 0, 15, '#')
	return g

ta = town('west')
# two buildings
put(ta, 3, 3, 'frrb'); put(ta, 3, 4, 'BBDB')
put(ta, 12, 6, 'frrb'); put(ta, 12, 7, 'BDBB')
# plaza path + exit gap at bottom
vline(ta, 9, 5, 14, '='); ta[15][9] = '='   # gap in border = exit
hline(ta, 10, 4, 14, '=')
ta[13][8] = 's'
blob(ta, 14, 11, 3, 2, 'T')

tb = town('east')
put(tb, 5, 2, 'frrb'); put(tb, 5, 3, 'BDBB')
put(tb, 13, 9, 'frrb'); put(tb, 13, 10, 'BBDB')
vline(tb, 10, 4, 14, '='); tb[15][10] = '='
hline(tb, 8, 3, 16, '=')
tb[6][3] = 's'
blob(tb, 2, 10, 2, 3, 'T'); tb[12][16] = 'T'

def emit(name, g):
	print('/* %s  %dx%d */' % (name, len(g[0]), len(g)))
	for row in g:
		print('\t"%s",' % ''.join(row))
	print()

emit('overworld', ow); emit('town_west', ta); emit('town_east', tb)

# ---------------- render preview with real converted tiles ----------------
src = open('source/gfx_data.c').read()
def arr(n):
	m = re.search(r'const unsigned short %s\[\d+\] = \{(.*?)\};' % n, src, re.S)
	return [int(x,16) for x in re.findall(r'0x([0-9A-F]{4})', m.group(1))]
def unpack(ws):
	o=[]
	for w in ws: o += [w&0xFF, w>>8]
	return o
def col(p): return ((p&31)<<3, ((p>>5)&31)<<3, ((p>>10)&31)<<3, 255)
pal = arr('bgPal'); tiles = unpack(arr('bgTilesData'))

def render(g, path):
	img = Image.new('RGBA', (len(g[0])*16, len(g)*16))
	for y,row in enumerate(g):
		for x,ch in enumerate(row):
			t = LEGEND[ch]; off = t*256
			for s,(dx,dy) in enumerate([(0,0),(8,0),(0,8),(8,8)]):
				for py in range(8):
					for px in range(8):
						img.putpixel((x*16+dx+px, y*16+dy+py),
						             col(pal[tiles[off+s*64+py*8+px]]))
	img.save(path)

render(ow, '/home/claude/inspect/map_overworld.png')
render(ta, '/home/claude/inspect/map_town_west.png')
render(tb, '/home/claude/inspect/map_town_east.png')
print('previews rendered')
