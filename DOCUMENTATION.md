# Miniquest Documentation

Here, I will go through pretty much the full engine and what can be changed inside the editor/files to make your game.

## Important constant buttons

`Save` writes the current game data to the active JSON databases.

`Build` invokes devkitPro to actually build out your NDS/ELF to the active directory.

## Maps Tab

In the Maps tab, you will edit the actual maps of the game. The editor will show the default map on startup, but not necessarily where your start point is placed.

**Tiles** shows the active tileset's tiles. Tiles marked (solid) are collision points in game. There are at max 24 active tiles. If your tileset includes a chest tile, it will be missing. Click a tile to paint it. Right click a tile in the map editor to pick it from the map without going back to Tiles.

**Zones** are encounter zones. Click a zone to paint it. Walking in these triggers a battle. Edit what troops appear in these zones using the `Encounter Sets` button.

**Place** tiles are specialty tiles. These are:

* NPC - A person or interactable. Supports text, healing, shopping, flag sets on talk, alt dialog on flag setting, boss fights, and sprite imports. Interactable from cardinal directions.

* Warp - Warps the player to an x and y coordinate on a selected map. Can require a flag and display text if conditions aren't met.

* Sign - Simple text display. Interactable from cardinal directions.

* Chest - places a chest tile. Contains an item. Requires a flag to differentiate open/closed.

* Start point - Where the player begins the game.

* Death respawn - Where the player returns after death.

`New` creates a new map. Give it a unique ID. It will always start with MAP.

`Rename` changes the map name.

`Resize` changes the map size. Maps max at 32x32.

`Encounter Sets` changes the troops in encounter zones.

`Events` allows for event scripting.

`Show Zones` disables/enables encounter zone display.

`Tileset` changes the active tileset.

`Music` adjusts the active music. `Import music...` if you need to import a music file (.mod, .it, .s3m, .xm).

`Backdrop` changes the active battle background. `Import backdrop...` if you need to. (.png, 192x128)

## Tilesets

Tilesets are a 128x48 PNG: an 8x3 grid of 16x16 tiles. Magenta tiles painted with `#FF00FF` show the active void tile beneath them.

Provide your tileset with an ID. Press `Apply` to apply your changes.

Tiles are 0 indexed. The checkbox array beneath turns collision on/off for each tile.

The **Chest tile** is placed using Chest, and will not appear in the editor. The Void tile displays underneath any magenta. I recommend using solid black or your default grass tile as Void.

## Project

Contains very basic project settings.

Title image is a 256x192 PNG that displays in the main menu. Import one from the editor.

Game name displays on the press start screen on the Touch Screen.

Starting items is self explanatory.

Title music plays on the title screen.

Battle music plays in default battles.

Victory music is a fanfare that plays once after the battle like Dragon Quest's arpeggio.

## Database

If you've ever worked in RPG Maker, you'll know the database is where you edit game details. Let's go tab by tab discussing what happens here.

### Enemies

Fields:

* ID: used for reference in engine.

* Name: Display name in the game.

* HP: Health points.

* Attack, Defense: used for calculating damage. `atk - def / 2`

* Agility: determines turn order to an extent.

* EXP: EXPerience provided on death.

* Gold: Gold provided on death.

* `Import sprite` requires a 64x64 PNG with a `#FF00FF` painted background.

Press `Apply` to save changes. Press `Add` for a new character, and `Delete` to remove the active character.

### Troops

Troops are a group of up to three enemies that comprise an encounter.

Fields:

* ID: reference in engine.

* Battle text: what actually shows up in game. For example, filling in the field with "a slime" will make the game say "A slime appears!" when battle begins.

* Member: which enemy ID is added to the troop.

Press `Apply` to save changes. Press `Add` for a new character, and `Delete` to remove the active troop.

### Encounters

To wrap up the confusing cycle, we have Encounters. Encounters encompass troops, troops encompass enemies. Encounters are used in the `Encounter Sets` in the Map editor to justify which enemy troops can appear in each Encounter zone.

For a concise explanation, when an encounter is decided (1 per N steps), the current zone the player is standing in will read from the Encounter ID associated with the zone. That will then select a troop from the Encounter given the weight (higher weight, higher probability of selection). Then, the enemies are loaded from the troop.

Fields:

* ID: reference in engine... again.

* 1 per N steps: odds of rolling given a step. Higher N, lower likelihood of encounters.

* Troop x: which troop you want to appear. Give it a weight. Higher weight, higher likelihood of that enemy being selected.

Press `Apply` to save changes. Press `Add` for a new character, and `Delete` to remove the active troop.

### Items

Healing items to use in the game. These will be in the player's inventory. Max x9 per item. (TODO: Add MP recovery items and warp items.)

- ID: used for reference in engine.

- Name: Display name in the game.

- Heals HP: how much health is healed on use.

- Price (G): price of the item. Halve that for its sale price.

Press `Apply` to save changes. Press `Add` for a new character, and `Delete` to remove the active item.

### Flags

Flags are boolean variables that are adjusted by the game. Used by chests, locked warps, NPCs, scripting, etc.

ID field is the in-engine reference. Press `Apply` to save changes. Press `Add` for a new character, and `Delete` to remove the active flag.

### Spells

Used by either character that knows spells. Can heal or damage.

* ID: used for reference in engine.

* Name (max 9): Name inside of the game, max 9 char length.

* MP cost: magic point cost to use spell.

* Unlocks at lvl: What level should any unit learn this at?

* Power: used in calculation for heals (`healAlly(act[i].target, sp->power + rnd(8))`) or spell attacks (`lo + rnd(sp->power - lo + 1`).

* Effect: fire (damage) and heal.

* Hits/heals all for AoE spells.

ID field is the in-engine reference. Press `Apply` to save changes. Press `Add` for a new character, and `Delete` to remove the active spell.

### Bosses

A special troop supporting custom music.

* ID: used for reference in engine.

* Troop fought: pick a troop for the encounter.

* `Import 16x16 sprite...`: This sprite will be used on the map as the boss encounter when you speak to them.

ID field is the in-engine reference. Press `Apply` to save changes. Press `Add` for a new character, and `Delete` to remove the active boss.

### Players

Adjust the (currently 2 supported) party members.

* Name: the name of the character in the game.

* HP: Health points.

* MP: magic points.

* Attack, Defense: used in damage calculation.

* Agility: used in turn order calculation.

* Spells: supports a maximum of six spells. Select these to add them to the character's repertoire.

Press `Apply` to save changes.

## Events:

See [Questscript](Questscript.md) for now to program in the proprietary engine scripting language!
