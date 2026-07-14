/* Host-side map sanity tests -- project-agnostic. Build & run:
 *   gcc -Iinclude -Istub tools/test_maps.c source/maps.c \
 *       source/db_data.c source/gfx_data.c -o tm && ./tm
 *
 * Checks, for every map: row geometry; warps land on walkable,
 * NPC-free tiles; and reachability -- seeding a BFS from the START
 * position and every warp arrival point on the map, every warp tile
 * must be reachable and every NPC and sign must be talkable.
 */
#include <stdio.h>
#include <string.h>
#include "maps.h"
#include "scripts_data.h"

static int fails;

#define CHECK(cond, ...) do { \
	if (!(cond)) { fails++; printf("FAIL: " __VA_ARGS__); printf("\n"); } \
} while (0)

static bool npcAt(const MapDef *m, int x, int y)
{
	for (int i = 0; i < m->nNpcs; i++)
		if (m->npcs[i].x == x && m->npcs[i].y == y)
			return true;
	return false;
}

static bool reach[64][64];

static void bfs_from(const MapDef *m, int sx, int sy)
{
	if (sx < 0 || sy < 0 || sx >= m->w || sy >= m->h)
		return;
	if (reach[sy][sx] || mapSolid(m, sx, sy) || npcAt(m, sx, sy))
		return;
	static int qx[4096], qy[4096];
	int head = 0, tail = 0;
	qx[tail] = sx; qy[tail] = sy; tail++;
	reach[sy][sx] = true;
	const int dx[] = { 0, 0, -1, 1 }, dy[] = { -1, 1, 0, 0 };
	while (head < tail) {
		int x = qx[head], y = qy[head]; head++;
		for (int d = 0; d < 4; d++) {
			int nx = x + dx[d], ny = y + dy[d];
			if (nx < 0 || ny < 0 || nx >= m->w || ny >= m->h)
				continue;
			if (reach[ny][nx] || mapSolid(m, nx, ny) || npcAt(m, nx, ny))
				continue;
			reach[ny][nx] = true;
			qx[tail] = nx; qy[tail] = ny; tail++;
		}
	}
}

static bool adjacent_reachable(int x, int y)
{
	const int ax[] = { 0, 0, -1, 1 }, ay[] = { -1, 1, 0, 0 };
	for (int d = 0; d < 4; d++) {
		int nx = x + ax[d], ny = y + ay[d];
		if (nx >= 0 && ny >= 0 && nx < 64 && ny < 64 && reach[ny][nx])
			return true;
	}
	return false;
}

int main(void)
{
	/* 1. geometry + warp destinations */
	for (int mi = 0; mi < N_MAPS; mi++) {
		const MapDef *m = &maps[mi];
		CHECK(m->tileset < N_TILESETS,
		      "%s: bad tileset index %d", m->name, m->tileset);
		CHECK(tilesetDefs[m->tileset].voidTile < TILESET_TILES,
		      "%s: tileset void tile out of range", m->name);
		for (int y = 0; y < m->h; y++)
			for (int x = 0; x < m->w; x++)
				CHECK(m->tiles[y * m->w + x] < TILESET_TILES,
				      "%s (%d,%d): tile index %d out of range",
				      m->name, x, y, m->tiles[y * m->w + x]);
		if (m->zoneRows)
			for (int y = 0; y < m->h; y++)
				CHECK((int)strlen(m->zoneRows[y]) == m->w,
				      "%s zone row %d bad length", m->name, y);
		for (int i = 0; i < m->nWarps; i++) {
			const Warp *w = &m->warps[i];
			const MapDef *d = &maps[w->destMap];
			CHECK(!mapSolid(d, w->destX, w->destY),
			      "%s warp %d lands on solid (%d,%d) in %s",
			      m->name, i, w->destX, w->destY, d->name);
			CHECK(!npcAt(d, w->destX, w->destY),
			      "%s warp %d lands on an NPC", m->name, i);
		}
	}

	/* 2. per-map reachability from every entry point */
	for (int mi = 0; mi < N_MAPS; mi++) {
		const MapDef *m = &maps[mi];
		memset(reach, 0, sizeof reach);
		if (mi == START_MAP)
			bfs_from(m, START_X, START_Y);
		if (mi == DEATH_MAP)
			bfs_from(m, DEATH_X, DEATH_Y);
		for (int oi = 0; oi < N_MAPS; oi++)
			for (int i = 0; i < maps[oi].nWarps; i++)
				if (maps[oi].warps[i].destMap == mi)
					bfs_from(m, maps[oi].warps[i].destX,
					         maps[oi].warps[i].destY);

		for (int i = 0; i < m->nWarps; i++)
			CHECK(reach[m->warps[i].y][m->warps[i].x],
			      "%s: warp %d tile unreachable", m->name, i);
		for (int i = 0; i < m->nNpcs; i++)
			CHECK(adjacent_reachable(m->npcs[i].x, m->npcs[i].y),
			      "%s: NPC %d not talkable", m->name, i);
		for (int i = 0; i < m->nSigns; i++)
			CHECK(adjacent_reachable(m->signs[i].x, m->signs[i].y),
			      "%s: sign %d not readable", m->name, i);
		CHECK(m->nEvents <= MAX_EVENTS,
		      "%s: %d events over MAX_EVENTS", m->name, m->nEvents);
		for (int i = 0; i < m->nEvents; i++) {
			const Event *e = &m->events[i];
			CHECK(e->script < SCRIPT_COUNT || SCRIPT_COUNT == 0,
			      "%s: event %d script index %d out of range",
			      m->name, i, e->script);
			if (e->kind == EVT_TILE)
				CHECK(reach[e->y][e->x],
				      "%s: event %d tile (%d,%d) unreachable",
				      m->name, i, e->x, e->y);
			if (e->kind == EVT_FLAG)
				CHECK(e->flag >= 0,
				      "%s: event %d on_flag without a flag",
				      m->name, i);
		}
	}

	if (fails == 0)
		puts("all map tests passed");
	return fails ? 1 : 0;
}
