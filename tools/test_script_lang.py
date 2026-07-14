#!/usr/bin/env python3
"""test_script_lang.py -- parser/compiler unit tests. Run from the
project root: python3 tools/test_script_lang.py"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import script_lang as sl
from script_lang import ScriptError

fails = 0


def ok(cond, what):
	global fails
	if not cond:
		fails += 1
		print("FAIL:", what)


def rejects(text, frag, what):
	try:
		sl.parse(text)
	except ScriptError as e:
		ok(frag in str(e), "%s: wrong message %r" % (what, str(e)))
		return
	ok(False, "%s: accepted" % what)


REFS = sl.Refs(
	flags=["begin_quest", "has_sword", "gate_open"],
	items=["herb", "supherb"],
	maps=["map_overworld", "map_throne"],
	troops=["slime_solo", "troll_pair"])

CANON = '''say "A traveler? We don't see many."
yesno "Will you help us?"
	set_flag begin_quest 1
	say "Bless you. The troll is north."
	if has_sword
		give supherb 2
		say "Take these for the road."
	else
		say "You'll need a weapon first."
	end
no
	say "A shame. Come back if you reconsider."
end
say "Safe travels."
'''

# ---- golden parse of the canonical example ----
ast = sl.parse(CANON)
ok(len(ast) == 3, "canon: 3 top-level nodes")
ok(ast[0] == ("say", "A traveler? We don't see many."), "canon: say 0")
ok(ast[2] == ("say", "Safe travels."), "canon: trailing say")
yn = ast[1]
ok(yn[0] == "yesno" and yn[1] == "Will you help us?", "canon: yesno")
yes, no = yn[2], yn[3]
ok(len(yes) == 3 and yes[0] == ("set_flag", "begin_quest", 1),
   "canon: yes body")
ok(yes[2][0] == "if" and yes[2][1] == "has_sword", "canon: nested if")
ok(yes[2][2][0] == ("give", "supherb", 2), "canon: then body")
ok(yes[2][3][0] == ("say", "You'll need a weapon first."),
   "canon: else body")
ok(no == [("say", "A shame. Come back if you reconsider.")],
   "canon: no body")
sl.check_refs(ast, REFS)                      # resolves cleanly

# ---- battle / lose ----
ast = sl.parse('battle troll_pair\nlose\n\tsay "Spared."\nend\n'
               'say "after"')
ok(ast[0][0] == "battle" and ast[0][2] == [("say", "Spared.")],
   "battle+lose parsed")
ok(ast[1] == ("say", "after"), "statement after lose block")
ast = sl.parse("battle troll_pair")
ok(ast[0] == ("battle", "troll_pair", None), "plain battle")

# ---- optional clauses ----
ast = sl.parse('if has_sword\n\theal\nend')
ok(ast[0] == ("if", "has_sword", [("heal",)], None), "if without else")
ast = sl.parse('yesno "Go?"\n\theal\nend')
ok(ast[0][3] is None, "yesno without no")

# ---- comments and blanks ----
ast = sl.parse('# comment\n\nsay "hi"\n\t# indented comment\n')
ok(ast == [("say", "hi")], "comments/blanks ignored")

# ---- error catalog ----
rejects('sing "la"', "unknown command", "unknown keyword")
rejects('say hello', "quoted string", "unquoted say")
rejects('say "unterminated', "unterminated", "unterminated string")
rejects('say "a" trailing', "after closing quote", "trailing junk")
rejects('say "bad \\n escape"', "bad escape", "bad escape")
rejects('set_flag only_one', "set_flag needs", "set_flag arity")
rejects('set_flag f 2', "set_flag needs", "set_flag value range")
rejects('give herb', "give needs", "give arity")
rejects('give herb 0', "must be 1..", "give zero")
rejects('warp m 1', "warp needs", "warp arity")
rejects('heal now', "no arguments", "heal with args")
rejects('if a b', "if needs", "if arity")
rejects('if f\n  heal\nend', "space in indentation", "space indent")
rejects('if f\nheal\nend', "expected 1 tab", "body not indented")
rejects('if f\n\t\theal\nend', "expected 1 tab", "body over-indented")
rejects('if f\n\theal\n\tend', "must sit at its opener", "end indented")
rejects('if f\n\theal', "missing its 'end'", "unterminated block")
rejects('end', "without an open block", "stray end")
rejects('else', "without an open block", "stray else")
rejects('lose\n\theal\nend', "without an open block", "stray lose")
rejects('yesno "q"\n\theal\nelse\n\theal\nend', "not valid here",
        "else in yesno")
rejects('if f\n\theal\nno\n\theal\nend', "not valid here", "no in if")
rejects('if f\n\theal\nelse\n\theal\nelse\n\theal\nend',
        "not valid here", "double else")
rejects('battle t\n\tlose\n\theal\nend', "must sit at its battle's",
        "lose mis-indented")
rejects('say ""', "empty say", "empty say")

# unknown references
for text, frag in ((('set_flag nope 1'), "unknown flag"),
                   (('give nope 1'), "unknown item"),
                   (('warp nope 1 1'), "unknown map"),
                   (('battle nope'), "unknown troop"),
                   (('if nope\n\theal\nend'), "unknown flag")):
	try:
		sl.check_refs(sl.parse(text), REFS)
		ok(False, "ref: accepted %r" % text)
	except ScriptError as e:
		ok(frag in str(e), "ref: wrong message for %r: %s" % (text, e))

# ---- wrapping ----
w = sl.wrap_say("one two three")
ok(w == "one two three", "short line unwrapped")
w = sl.wrap_say(" ".join(["word"] * 12))          # 12*5+11 = 71 chars
ok(all(len(l) <= sl.SAY_COLS for l in w.replace("\f", "\n").split("\n")),
   "wrap respects SAY_COLS")
long = " ".join("w%d" % i for i in range(60))
pages = sl.wrap_say(long).split("\f")
ok(all(p.count("\n") < sl.SAY_LINES for p in pages),
   "pagination respects SAY_LINES")
ok(len(pages) > 1, "long text paginates")
try:
	sl.wrap_say("x" * 26)
	ok(False, "overlong word accepted")
except ScriptError as e:
	ok("longer than one" in str(e), "overlong word message")

# ---- compilation goldens ----
def compile_text(text):
	pool, blob = {}, bytearray()
	def addstr(s):
		if s not in pool:
			pool[s] = len(blob)
			blob.extend(s.encode())
			blob.append(0)
		return pool[s]
	code = sl.compile_script(sl.parse(text), REFS, addstr)
	return code, bytes(blob)

code, _ = compile_text('heal')
ok(code == bytes([sl.OP_HEAL, sl.OP_END]), "heal golden")

code, text = compile_text('say "hi"')
ok(code == bytes([sl.OP_SAY, 0, 0, sl.OP_END]) and text == b"hi\x00",
   "say golden")

code, _ = compile_text('set_flag gate_open 1')     # flag index 2
ok(code == bytes([sl.OP_SET_FLAG, 2, 0, 1, sl.OP_END]),
   "set_flag golden")

code, _ = compile_text('give supherb 2')           # item index 1
ok(code == bytes([sl.OP_GIVE, 1, 0, 2, sl.OP_END]), "give golden")

code, _ = compile_text('warp map_throne 6 10')     # map index 1
ok(code == bytes([sl.OP_WARP, 1, 0, 6, 10, sl.OP_END]), "warp golden")

# if/else jump resolution:
# 0: PUSH_FLAG 1 ; 3: JZ 11 ; 6: HEAL ; 7: JMP 12 ; 10..: else HEAL,END
code, _ = compile_text('if has_sword\n\theal\nelse\n\theal\nend')
exp = bytes([sl.OP_PUSH_FLAG, 1, 0,
             sl.OP_JZ, 10, 0,
             sl.OP_HEAL,
             sl.OP_JMP, 11, 0,
             sl.OP_HEAL,
             sl.OP_END])
ok(code == exp, "if/else golden: %s" % code.hex())

# if without else: JZ lands on END
code, _ = compile_text('if has_sword\n\theal\nend')
exp = bytes([sl.OP_PUSH_FLAG, 1, 0,
             sl.OP_JZ, 7, 0,
             sl.OP_HEAL,
             sl.OP_END])
ok(code == exp, "if golden: %s" % code.hex())

# yesno: CHOICE ; JZ no ; yes ; JMP end ; no ; end
code, _ = compile_text('yesno "Go?"\n\theal\nno\n\theal\nend')
exp = bytes([sl.OP_CHOICE, 0, 0,
             sl.OP_JZ, 10, 0,
             sl.OP_HEAL,
             sl.OP_JMP, 11, 0,
             sl.OP_HEAL,
             sl.OP_END])
ok(code == exp, "yesno golden: %s" % code.hex())

# battle+lose: BATTLE_TRY ; JZ end ; lose body ; end
code, _ = compile_text('battle troll_pair\nlose\n\theal\nend')
exp = bytes([sl.OP_BATTLE_TRY, 1, 0,
             sl.OP_JZ, 7, 0,
             sl.OP_HEAL,
             sl.OP_END])
ok(code == exp, "battle_try golden: %s" % code.hex())

# text pool dedup
code, text = compile_text('say "same"\nsay "same"')
ok(text == b"same\x00", "text pool dedup")
ok(code[1] | (code[2] << 8) == 0 and code[4] | (code[5] << 8) == 0,
   "dedup offsets equal")

if fails == 0:
	print("all script_lang tests passed")
sys.exit(1 if fails else 0)
