# Sol Cesto Gold Patcher

A Python tool that patches the gold value in **Sol Cesto** save files directly, without needing a hex editor. Includes an interactive Windows batch launcher for ease of use.

---

## How it works

Sol Cesto is built with Construct 3 and stores save data in a [LevelDB](https://github.com/google/leveldb) database located in your browser's IndexedDB folder. Gold (`or` in French) is stored using V8 integer encoding: the value is multiplied by 2 and written as a base-128 varint, preceded by the marker bytes `FF 0F 49`.

The tool:
1. Auto-detects (or accepts) the save directory
2. Copies **all original files** to `./backup/` and `./save/` before touching anything
3. Searches for the gold pattern `FF 0F 49 <varint>` anchored near the `or` variable name
4. Replaces the varint with the target gold encoding
5. Recalculates the **LevelDB record CRC-32C** checksum — without this step the game treats the save as corrupt and silently reverts to an older state

---

## Requirements

- Python 3.10+
- No external libraries required (CRC-32C is implemented in pure Python; `crcmod` or `crc32c` are used automatically if installed for better performance)

---

## Files

| File | Description |
|------|-------------|
| `gold_patcher.py` | Core patcher script |
| `patch_gold.bat` | Interactive Windows launcher — double-click to run |

---

## Usage

### Option A — Double-click the bat file (Windows)

Place both files in the same folder and double-click `patch_gold.bat`. It will walk you through each input step by step.

### Option B — Run directly from the command line

```bash
python gold_patcher.py --current-gold <N> --target-gold <N>
```

**Arguments:**

| Argument | Required | Description |
|----------|----------|-------------|
| `--current-gold` | Yes | Your exact gold amount shown in-game |
| `--target-gold` | Yes | The gold amount you want (must end in `0`) |
| `--save-dir` | No | Full path to the `.indexeddb.leveldb` folder. Auto-detected if omitted. |

**Examples:**

```bash
# Basic — save path is auto-detected
python gold_patcher.py --current-gold 20 --target-gold 60

# With explicit save path
python gold_patcher.py --current-gold 200 --target-gold 8190 \
  --save-dir "C:/Users/You/AppData/Local/SolCesto/User Data/Default/IndexedDB/chrome-extension_abc.indexeddb.leveldb"
```

---

## Gold value rules

### Must end in 0

Only values ending in `0` are accepted as targets (e.g. `10`, `20`, `60`, `100`, `8190`). The game engine does not store intermediate values reliably.

### Must stay in the same byte-size range as current gold

The replacement bytes must be exactly the same length as the original, otherwise the save file is corrupted. The encoding uses two ranges:

| Current gold | Target gold range | Max safe target |
|---|---|---|
| 1 – 63 | 1 – 63 (ends in 0) | **60** |
| 64 – 8191 | 64 – 8191 (ends in 0) | **8190** |

If your current gold is `20` and you want the maximum, set target to `60`. If your current gold is `100`, you can go up to `8190`.

---

## Save file location

The tool auto-detects the save folder from:

```
%LOCALAPPDATA%\SolCesto\User Data\Default\IndexedDB\<chrome-extension_...>.indexeddb.leveldb
```

The files it patches are `000003.log` and/or `000004.log` inside that folder.

---

## Output folders

After running, two folders are created next to the script:

| Folder | Contents |
|--------|----------|
| `./backup/` | Unmodified originals — never touched after the initial copy |
| `./save/` | Patched working copies |

**After a successful patch**, close Sol Cesto completely, then copy all files from `./save/` back to the original save directory. Relaunch the game to see the updated gold.

**To restore**, copy the files from `./backup/` back to the save directory.

---

## Troubleshooting

**Patcher runs but gold doesn't change / wrong value appears**
- Make sure Sol Cesto is fully closed before running the tool. The game may overwrite the log file while it is open.
- Confirm `--current-gold` matches your exact in-game amount to the unit.

**Pattern not found**
- The save may use `000004.log` instead of (or in addition to) `000003.log`. The tool scans all `.log` files automatically.
- The gold variable encoding can vary. Try spending or earning 1 gold to change the value, then run the tool with the new current amount.

**Game shows corrupted save / reverts to old state**
- Restore from `./backup/` and try again with the game fully closed.

---

## Technical notes

LevelDB log files are split into 32 KB blocks. Each block contains records with a 7-byte header: 4 bytes for a masked CRC-32C checksum, 2 bytes for data length, and 1 byte for record type. When any data bytes in a record are modified, the checksum must be recomputed as:

```
masked_crc = ((crc >> 15 | crc << 17) & 0xFFFFFFFF + 0xa282ead8) & 0xFFFFFFFF
```

Skipping this step causes LevelDB's recovery process to stop reading the log at the bad record, silently falling back to the last valid save state.
