#!/usr/bin/env python3
"""
script_lang.py -- the event-scripting language: parser, validator,
and bytecode compiler. Imported by BOTH tools/gen_scripts.py and
tools/map_editor.py so the editor's validation and the generator's
compilation can never diverge.

Language (one command per line, tab-indented blocks):

	say "text"                  message, wrapped + paginated
	set_flag <flag_id> <0|1>
	give <item_id> <qty>
	warp <map_id> <x> <y>       ends the script (new field context)
	heal                        full party restore
	battle <troop_id>           loss = death flow, script abandoned
	battle <troop_id> + lose block:
	    battle boss_troop
	    lose
	        say "Beaten... but spared."
	    end                     loss heals party + runs lose body
	join <player_id>            full party = message, continues
	leave <player_id>           last member = silent no-op
	if <flag_id> ... [else ...] end
	yesno "prompt" ... [no ...] end

Blank lines and full-line # comments allowed. Strings are double-
quoted; \\" and \\\\ are the only escapes.
"""

# ---- UI metrics (from ui.c: text col 2, frame col 31, rows 8..13,
# "(A)" indicator at col 27 of the last row) ----
SAY_COLS = 25
SAY_LINES = 6

# ---- opcodes: keep in sync with include/script.h ----
OP_END, OP_SAY, OP_SET_FLAG, OP_GIVE, OP_WARP, OP_HEAL, \
	OP_BATTLE, OP_BATTLE_TRY, OP_JZ, OP_JMP, OP_PUSH_FLAG, \
	OP_CHOICE, OP_JOIN, OP_LEAVE = range(14)

MAX_GIVE = 99


class ScriptError(Exception):
	"""Parse/validation error with a 1-based line number."""

	def __init__(self, line, msg):
		super().__init__("line %d: %s" % (line, msg))
		self.line = line
		self.msg = msg


# ---------------------------------------------------------------- lex

def _string_lit(ln, rest, what):
	"""Parse one double-quoted string that must be the entire rest of
	the line. Returns the unescaped text."""
	rest = rest.strip()
	if not rest.startswith('"'):
		raise ScriptError(ln, "%s needs one quoted string" % what)
	out = []
	i = 1
	while i < len(rest):
		c = rest[i]
		if c == "\\":
			if i + 1 >= len(rest) or rest[i + 1] not in '"\\':
				raise ScriptError(ln, "bad escape (only \\\" and \\\\)")
			out.append(rest[i + 1])
			i += 2
			continue
		if c == '"':
			if rest[i + 1:].strip():
				raise ScriptError(ln, "content after closing quote")
			return "".join(out)
		out.append(c)
		i += 1
	raise ScriptError(ln, "unterminated string")


def _ident(ln, tok, what):
	if not tok.isidentifier():
		raise ScriptError(ln, "%s: %r is not a valid identifier"
		                  % (what, tok))
	return tok


def _int(ln, tok, what, lo, hi):
	if not tok.isdigit():
		raise ScriptError(ln, "%s must be a number (got %r)"
		                  % (what, tok))
	v = int(tok)
	if not (lo <= v <= hi):
		raise ScriptError(ln, "%s must be %d..%d" % (what, lo, hi))
	return v


def _lex(text):
	"""text -> [(lineno, depth, stmt-tuple)]; raises ScriptError."""
	items = []
	for ln, raw in enumerate(text.split("\n"), 1):
		line = raw.rstrip()
		depth = 0
		while depth < len(line) and line[depth] == "\t":
			depth += 1
		body = line[depth:]
		if not body or body.lstrip().startswith("#"):
			continue                       # blank / comment line
		if body[0] == " ":
			raise ScriptError(ln, "space in indentation (tabs only)")

		kw = body.split(None, 1)[0]
		rest = body[len(kw):]

		if kw == "say":
			s = _string_lit(ln, rest, "say")
			if not s.strip():
				raise ScriptError(ln, "empty say text")
			stmt = ("say", s)
		elif kw == "yesno":
			s = _string_lit(ln, rest, "yesno")
			if not s.strip():
				raise ScriptError(ln, "empty yesno prompt")
			stmt = ("yesno", s)
		elif kw == "set_flag":
			a = rest.split()
			if len(a) != 2 or a[1] not in ("0", "1"):
				raise ScriptError(ln, "set_flag needs <flag> <0|1>")
			stmt = ("set_flag", _ident(ln, a[0], "flag"), int(a[1]))
		elif kw == "give":
			a = rest.split()
			if len(a) != 2:
				raise ScriptError(ln, "give needs <item> <count>")
			stmt = ("give", _ident(ln, a[0], "item"),
			        _int(ln, a[1], "count", 1, MAX_GIVE))
		elif kw == "warp":
			a = rest.split()
			if len(a) != 3:
				raise ScriptError(ln, "warp needs <map> <x> <y>")
			stmt = ("warp", _ident(ln, a[0], "map"),
			        _int(ln, a[1], "x", 0, 255),
			        _int(ln, a[2], "y", 0, 255))
		elif kw == "heal":
			if rest.strip():
				raise ScriptError(ln, "heal takes no arguments")
			stmt = ("heal",)
		elif kw == "battle":
			a = rest.split()
			if len(a) != 1:
				raise ScriptError(ln, "battle needs <troop>")
			stmt = ("battle", _ident(ln, a[0], "troop"))
		elif kw in ("join", "leave"):
			a = rest.split()
			if len(a) != 1:
				raise ScriptError(ln, "%s needs <player>" % kw)
			stmt = (kw, _ident(ln, a[0], "player"))
		elif kw == "if":
			a = rest.split()
			if len(a) != 1:
				raise ScriptError(ln, "if needs <flag>")
			stmt = ("if", _ident(ln, a[0], "flag"))
		elif kw in ("else", "no", "lose", "end"):
			if rest.strip():
				raise ScriptError(ln, "'%s' takes no arguments" % kw)
			stmt = (kw,)
		else:
			raise ScriptError(ln, "unknown command %r" % kw)
		items.append((ln, depth, stmt))
	return items


# -------------------------------------------------------------- parse

def parse(text):
	"""Script text -> AST (list of nodes). Node shapes:
	('say', text) ('set_flag', id, v) ('give', id, n)
	('warp', id, x, y) ('heal',) ('battle', id, lose_body|None)
	('if', id, then_body, else_body|None)
	('yesno', prompt, yes_body, no_body|None)
	Raises ScriptError."""
	items = _lex(text)
	pos = [0]

	def peek():
		return items[pos[0]] if pos[0] < len(items) else None

	def take():
		it = items[pos[0]]
		pos[0] += 1
		return it

	def block(depth, opener_ln, stop):
		"""Parse statements at exactly `depth` until a keyword in
		`stop` appears at depth-1. Returns (body, stop_kw, stop_ln)."""
		body = []
		while True:
			it = peek()
			if it is None:
				if stop:
					raise ScriptError(opener_ln,
					                  "block is missing its 'end'")
				return body, None, None
			ln, d, stmt = it
			kw = stmt[0]
			if kw in ("else", "no", "lose", "end"):
				if not stop:
					raise ScriptError(ln, "'%s' without an open block"
					                  % kw)
				if d != depth - 1:
					raise ScriptError(ln, "'%s' must sit at its "
					                  "opener's indent (%d tabs, found "
					                  "%d)" % (kw, depth - 1, d))
				if kw not in stop:
					raise ScriptError(ln, "'%s' not valid here "
					                  "(expected %s)"
					                  % (kw, " or ".join(sorted(stop))))
				take()
				return body, kw, ln
			if d != depth:
				raise ScriptError(ln, "bad indentation: expected %d "
				                  "tab(s), found %d" % (depth, d))
			take()
			if kw == "if":
				then, stop_kw, _ = block(d + 1, ln, {"else", "end"})
				els = None
				if stop_kw == "else":
					els, stop_kw, _ = block(d + 1, ln, {"end"})
				body.append(("if", stmt[1], then, els))
			elif kw == "yesno":
				yes, stop_kw, _ = block(d + 1, ln, {"no", "end"})
				no = None
				if stop_kw == "no":
					no, stop_kw, _ = block(d + 1, ln, {"end"})
				body.append(("yesno", stmt[1], yes, no))
			elif kw == "battle":
				lose = None
				nxt = peek()
				if nxt and nxt[2][0] == "lose":
					if nxt[1] != d:
						raise ScriptError(nxt[0], "'lose' must sit at "
						                  "its battle's indent (%d "
						                  "tabs, found %d)"
						                  % (d, nxt[1]))
					take()
					lose, _, _ = block(d + 1, nxt[0], {"end"})
				body.append(("battle", stmt[1], lose))
			else:
				body.append(stmt)
		# not reached

	ast, _, _ = block(0, 0, set())
	return ast


# ----------------------------------------------------------- wrapping

def wrap_say(text, line=0):
	"""Word-wrap to SAY_COLS, paginate to SAY_LINES. Returns the
	payload string: '\\n' between lines, '\\f' between pages."""
	lines, cur = [], ""
	for w in text.split():
		if len(w) > SAY_COLS:
			raise ScriptError(line, "word %r is longer than one "
			                  "%d-char line -- rewrite it"
			                  % (w, SAY_COLS))
		if not cur:
			cur = w
		elif len(cur) + 1 + len(w) <= SAY_COLS:
			cur += " " + w
		else:
			lines.append(cur)
			cur = w
	if cur:
		lines.append(cur)
	pages = ["\n".join(lines[i:i + SAY_LINES])
	         for i in range(0, len(lines), SAY_LINES)]
	return "\f".join(pages)


# --------------------------------------------------------- resolution

class Refs:
	"""Orderings from database.json / maps.json used to resolve
	identifiers to engine indices."""

	def __init__(self, flags, items, maps, troops, players=()):
		self.flags = {f: i for i, f in enumerate(flags)}
		self.items = {f: i for i, f in enumerate(items)}
		self.maps = {f: i for i, f in enumerate(maps)}
		self.troops = {f: i for i, f in enumerate(troops)}
		self.players = {f: i for i, f in enumerate(players)}

	@classmethod
	def from_data(cls, db, mapsdata):
		return cls(db.get("flags", []),
		           [i["id"] for i in db.get("items", [])],
		           [m["cid"] for m in mapsdata["maps"]],
		           [t["id"] for t in db.get("troops", [])],
		           [p["id"] for p in db.get("players", [])])


def _resolve(ln, table, kind, ident):
	if ident not in table:
		raise ScriptError(ln, "unknown %s %r" % (kind, ident))
	return table[ident]


def check_refs(ast, refs):
	"""Walk the AST verifying every identifier resolves. Raises
	ScriptError (line 0: the AST no longer carries line numbers, so
	errors name the identifier instead)."""
	for node in ast:
		k = node[0]
		if k == "set_flag":
			_resolve(0, refs.flags, "flag", node[1])
		elif k == "give":
			_resolve(0, refs.items, "item", node[1])
		elif k == "warp":
			_resolve(0, refs.maps, "map", node[1])
		elif k == "battle":
			_resolve(0, refs.troops, "troop", node[1])
			if node[2] is not None:
				check_refs(node[2], refs)
		elif k == "if":
			_resolve(0, refs.flags, "flag", node[1])
			check_refs(node[2], refs)
			if node[3] is not None:
				check_refs(node[3], refs)
		elif k == "yesno":
			wrap_say(node[1])
			check_refs(node[2], refs)
			if node[3] is not None:
				check_refs(node[3], refs)
		elif k in ("join", "leave"):
			_resolve(0, refs.players, "player", node[1])
		elif k == "say":
			wrap_say(node[1])


def validate_script(text, refs):
	"""Editor entry point: parse + wrap + resolve. Raises
	ScriptError; returns the AST when clean."""
	ast = parse(text)
	check_refs(ast, refs)
	return ast


# ------------------------------------------------- rename propagation

# which command rewrites which identifier kind (argument position 0)
_KIND_KEYWORDS = {
	"flag": ("set_flag", "if"),
	"item": ("give",),
	"map": ("warp",),
	"troop": ("battle",),
	"player": ("join", "leave"),
}


def _rewrite_lines(text, kind, fn):
	"""Apply fn(old_ident) -> new_ident to the identifier argument of
	every command that takes `kind`. Lenient: lines that don't parse
	are passed through untouched (renames must not die on a script
	the author is mid-way through writing). String literals are never
	touched -- rewriting is positional, not textual."""
	kws = _KIND_KEYWORDS[kind]
	out = []
	for raw in text.split("\n"):
		body = raw.lstrip("\t")
		indent = raw[:len(raw) - len(body)]
		parts = body.split(None, 1)
		if len(parts) == 2 and parts[0] in kws:
			args = parts[1].split()
			if args:
				args[0] = fn(args[0])
				out.append(indent + parts[0] + " " + " ".join(args))
				continue
		out.append(raw)
	return "\n".join(out)


def rename_ident(text, kind, old, new):
	"""Rewrite identifier `old` -> `new` in script text."""
	return _rewrite_lines(text, kind,
	                      lambda a: new if a == old else a)


def uses_ident(text, kind, ident):
	"""True when the script references `ident` as a `kind`."""
	hit = []
	_rewrite_lines(text, kind,
	               lambda a: hit.append(a) or a if a == ident else a)
	return bool(hit)


def uses_leave(text, ident):
	"""True when the script has a `leave` of this player (used by the
	editor's could-empty-the-party warning)."""
	for raw in text.split("\n"):
		parts = raw.lstrip("\t").split()
		if len(parts) == 2 and parts[0] == "leave" and parts[1] == ident:
			return True
	return False


# -------------------------------------------------------------compile

def compile_script(ast, refs, addstr):
	"""AST -> bytecode bytes. addstr(payload) -> u16 offset into the
	global text pool (the caller owns pooling/dedup)."""
	code = bytearray()

	def u8(v):
		code.append(v & 0xFF)

	def u16(v):
		code.append(v & 0xFF)
		code.append((v >> 8) & 0xFF)

	def fixup():
		"""Reserve a u16 jump slot; returns its position."""
		pos = len(code)
		u16(0)
		return pos

	def patch(pos, target=None):
		t = len(code) if target is None else target
		code[pos] = t & 0xFF
		code[pos + 1] = (t >> 8) & 0xFF

	def emit(body):
		for node in body:
			k = node[0]
			if k == "say":
				u8(OP_SAY)
				u16(addstr(wrap_say(node[1])))
			elif k == "set_flag":
				u8(OP_SET_FLAG)
				u16(refs.flags[node[1]])
				u8(node[2])
			elif k == "give":
				u8(OP_GIVE)
				u16(refs.items[node[1]])
				u8(node[2])
			elif k == "warp":
				u8(OP_WARP)
				u16(refs.maps[node[1]])
				u8(node[2])
				u8(node[3])
			elif k == "heal":
				u8(OP_HEAL)
			elif k == "join":
				u8(OP_JOIN)
				u16(refs.players[node[1]])
			elif k == "leave":
				u8(OP_LEAVE)
				u16(refs.players[node[1]])
			elif k == "battle":
				if node[2] is None:
					u8(OP_BATTLE)
					u16(refs.troops[node[1]])
				else:
					u8(OP_BATTLE_TRY)      # reg = 1 when LOST
					u16(refs.troops[node[1]])
					u8(OP_JZ)
					skip = fixup()
					emit(node[2])
					patch(skip)
			elif k == "if":
				u8(OP_PUSH_FLAG)
				u16(refs.flags[node[1]])
				u8(OP_JZ)
				jz = fixup()
				emit(node[2])
				if node[3] is None:
					patch(jz)
				else:
					u8(OP_JMP)
					jend = fixup()
					patch(jz)
					emit(node[3])
					patch(jend)
			elif k == "yesno":
				u8(OP_CHOICE)              # reg = 1 when YES
				u16(addstr(wrap_say(node[1])))
				u8(OP_JZ)
				jz = fixup()
				emit(node[2])
				if node[3] is None:
					patch(jz)
				else:
					u8(OP_JMP)
					jend = fixup()
					patch(jz)
					emit(node[3])
					patch(jend)
	emit(ast)
	u8(OP_END)
	if len(code) > 0xFFFF:
		raise ScriptError(0, "script compiles to %d bytes (max 65535)"
		                  % len(code))
	return bytes(code)
