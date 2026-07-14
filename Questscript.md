# Questscript

Questscript is Miniquest's event scripting language. You write it in
the editor (Maps tab -> Events -> Add/Edit), one command per line;
the Validate button checks it with the exact same parser the build
uses, so a script the editor accepts always builds.

Scripts are attached to a map event with one of three triggers:

| Trigger   | Fires when...                                       |
| --------- | --------------------------------------------------- |
| `on_load` | the map is entered (one tick after arrival)         |
| `on_flag` | its flag goes from unset to set (edge-triggered)    |
| `on_tile` | the player steps onto its tile (optional gate flag) |

A map can have up to 8 events. Scripts run to completion and block
the game while they do.

## Ground rules

- **One command per line.** Blank lines are fine.
- **Comments:** a line starting with `#` is ignored.
- **Strings** are double-quoted. Inside them, `\"` is a quote and
  `\\` is a backslash — those are the only escapes. Don't write
  line breaks; `say` wraps and paginates for you.
- **Indentation is tabs.** Spaces in the indent are an
  error. Block bodies go one tab deeper than their opener; the
  closing `end` sits back at the opener's indent.
- **Identifiers** are the ids straight from your data: flag ids,
  item ids, troop ids, and map **cid**s (like `MAP_TOWN_WEST` —
  cids never change when you rename a map's display name, so warp
  lines never go stale).

## Commands

### say — show a message

```
say "The old man peers at you through the rain."
```

Text is word-wrapped to 25 characters per line, 6 lines per page;
long text automatically becomes multiple pages the player advances
with A. Any single word longer than 25 characters is an error —
break it up.

### set_flag — set or clear a flag

```
set_flag bridge_repaired 1
set_flag bridge_repaired 0
```

`1` sets, `0` clears. Setting a flag that was previously unset can
fire an `on_flag` event on the current map — that's how one script
(or an NPC's sets-flag dialog) chains into another.

### give — add items to the inventory

```
give herb 3
```

Quantity is 1–99. If the inventory hits its per-item cap the extras
are silently dropped, so say what you gave:

```
give herb 3
say "You received 3 herbs!"
```

### heal — restore the party

```
heal
```

Full HP/MP for everyone, with the heal sound. Same effect as a
healer NPC.

### warp — move the player and END the script

```
warp MAP_THRONE 6 10
```

Map cid, then tile x, then y. **Nothing after a warp line runs** —
the script ends and the destination map takes over (its `on_load`
events fire as usual). Put the warp last.

### battle — fight a troop

Two forms. Plain:

```
battle troll_pair
say "The pass is clear."
```

On victory (or fleeing) the script continues. On defeat the normal
death flow happens — half gold, respawn in town — and the rest of
the script is abandoned.

With a `lose` block, defeat is survivable:

```
battle king_slime
lose
    say "The king slime spares you, chuckling."
end
say "Either way, it slithers off."
```

If the player loses, the party is healed, the `lose` body runs, and
the script continues after `end`. If the player wins, the `lose`
body is skipped. `lose` sits at the same indent as its `battle`,
immediately after it; the body goes one tab deeper.

## Branching

### if / else / end — branch on a flag

```
if has_lantern
    say "Your lantern pushes back the dark."
else
    say "It's pitch black. You turn back."
    warp MAP_CAVE_MOUTH 4 12
end
```

The body lines are one tab deeper than the `if`; `else` and `end`
sit at the `if`'s indent. `else` is optional:

```
if troll_beaten
    say "The bridge stands unguarded."
end
```

### yesno / no / end — ask the player

```
yesno "Rest at the inn for 10 gold?"
    heal
    say "You wake refreshed."
no
    say "The innkeeper shrugs."
end
```

Shows a YES/NO menu (pressing B counts as NO). The first body runs
on YES; the `no` body — optional, like `else` — runs on NO. Same
indentation shape as `if`: bodies one tab deeper, `no` and `end` at
the opener's indent.

Short prompts (one line's worth) stay on screen as the menu's
title; longer prompts are shown as message pages first.

## Nesting

Blocks nest freely — each level adds one tab:

```
yesno "Will you help us?"
    set_flag begin_quest 1
    if has_sword
        give herb2 2
        say "Take these for the road."
    else
        say "You'll need a weapon first."
    end
no
    say "A shame. Come back if you reconsider."
end
say "Safe travels."
```

Note `say "Safe travels."` at the end: it's back at zero indent, so
it runs on *both* paths, after the block finishes.

## Odds and ends

- An `on_tile` event re-arms when the player steps off the tile —
  step back on and it fires again. The event's optional gate flag
  fires the event only when that flag is **set** (good for opening
  a path after a quest). For a single event, check and set a flag inside the
  script instead:
  
  ```
  if shrine_visited
      
  else
      say "A voice: 'Only once may you ask.'"
      set_flag shrine_visited 1
  end
  ```

- The step that fires a tile event never also rolls a random
  encounter.

- Renaming a flag, item, or troop in the Database tab rewrites your
  scripts automatically. Text inside `say`/`yesno` strings is never
  touched by renames.

- Deleting a flag, item, troop, or map that a script still uses is
  blocked, and the error tells you which map and event.
