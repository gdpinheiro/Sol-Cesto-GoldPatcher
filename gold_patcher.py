#!/usr/bin/env python3
"""
gold_patcher.py — Patches the gold value in SolCesto save files.

Usage examples:
    python gold_patcher.py --current-gold 100 --target-gold 8190
    python gold_patcher.py --current-gold 50  --target-gold 60
    python gold_patcher.py --current-gold 200 --target-gold 500 \\
        --save-dir "C:/Users/You/AppData/Local/SolCesto/User Data/Default/IndexedDB/chrome-extension_abc.indexeddb.leveldb"

How it works:
    SolCesto uses a Construct 3 runtime that stores save data in a LevelDB database
    (.indexeddb.leveldb folder). Gold ('or' in French) is encoded using V8 integer
    encoding: the value is multiplied by 2, then stored as a base-128 varint, preceded
    by the marker bytes FF 0F 49.

    The replacement MUST use the same number of bytes as the original, otherwise the
    save file is corrupted. The tool enforces this and recalculates the LevelDB record
    CRC-32C checksum automatically (without this step the game treats the save as corrupt).

Safety:
    - Original files are always copied to ./backup/ BEFORE any modification.
    - The tool works on a ./save/ working copy; originals in ./backup/ are never touched.
    - To restore: copy files from ./backup/ back to the original save folder.

Note:
    Target gold must end in 0 (e.g. 10, 20, 60, 100, 8190).
    Values not ending in 0 may not be stored correctly by the game engine.
"""

import argparse
import os
import shutil
import struct
import sys
from pathlib import Path


# -----------------------------------------------------------------
#  V8 varint encoding  (gold -> gold*2 -> base-128 varint)
# -----------------------------------------------------------------

def encode_gold_varint(gold: int) -> bytes:
    """Encode a gold amount as the V8 integer varint stored in the save file."""
    if gold < 0:
        raise ValueError("Gold cannot be negative.")
    value = gold * 2
    if value < 128:
        return bytes([value])
    elif value < 16384:          # fits in 2 bytes
        b0 = (value & 0x7F) | 0x80
        b1 = value >> 7
        return bytes([b0, b1])
    else:
        raise ValueError(
            f"Gold {gold} is too large. "
            f"Encoded value {value} exceeds the 2-byte varint range (max gold: 8191)."
        )


# The 3-byte prefix that always precedes the gold varint in the save file.
GOLD_PREFIX = bytes([0xFF, 0x0F, 0x49])

# The variable name for gold in French, as stored in the save file.
# Used to disambiguate when multiple FF 0F 49 XX matches exist.
GOLD_VAR_NAME = b'or'


# -----------------------------------------------------------------
#  CRC-32C (Castagnoli) -- needed to fix LevelDB record headers
# -----------------------------------------------------------------

def _build_crc32c_table() -> list:
    table = []
    for i in range(256):
        crc = i
        for _ in range(8):
            crc = (crc >> 1) ^ 0x82F63B78 if (crc & 1) else crc >> 1
        table.append(crc)
    return table

_CRC32C_TABLE = _build_crc32c_table()


def crc32c(data: bytes) -> int:
    """Pure-Python CRC-32C (no external dependency)."""
    crc = 0xFFFFFFFF
    for byte in data:
        crc = (crc >> 8) ^ _CRC32C_TABLE[(crc ^ byte) & 0xFF]
    return crc ^ 0xFFFFFFFF


# Try to use a faster C extension if available, fall back to pure Python.
try:
    import crcmod
    _fast_fn = crcmod.predefined.mkCrcFun('crc-32c')
    def crc32c(data: bytes) -> int:  # noqa: F811
        return _fast_fn(data)
except Exception:
    try:
        import crc32c as _crc32c_ext
        def crc32c(data: bytes) -> int:  # noqa: F811
            return _crc32c_ext.crc32c(data)
    except Exception:
        pass  # keep pure-Python version


def mask_crc(crc: int) -> int:
    """Apply LevelDB's CRC masking.
    IMPORTANT: rotate first, mask to 32-bit, THEN add the salt.
    The addition must happen AFTER the mask -- not inside the same expression,
    or Python's operator precedence will use the sum as the mask operand."""
    rot = ((crc >> 15) | (crc << 17)) & 0xFFFFFFFF
    return (rot + 0xa282ead8) & 0xFFFFFFFF


# LevelDB log file constants
_BLOCK_SIZE   = 32768
_HEADER_SIZE  = 7   # 4 (masked CRC32C) + 2 (data length) + 1 (record type)


# -----------------------------------------------------------------
#  LevelDB record scanner
# -----------------------------------------------------------------

def find_record_for_offset(data: bytes | bytearray, byte_offset: int) -> tuple[int, int]:
    """
    Walk the LevelDB log blocks to find the record header whose data region
    contains `byte_offset`.  Returns (header_start, data_end) or (-1, -1).
    """
    block_base = 0
    while block_base < len(data):
        pos = block_base
        block_end = min(block_base + _BLOCK_SIZE, len(data))

        while pos + _HEADER_SIZE <= block_end:
            length = struct.unpack_from('<H', data, pos + 4)[0]
            rtype  = data[pos + 6]

            # Zero-length zero-type means block padding -- skip to next block
            if length == 0 and rtype == 0:
                break

            data_start = pos + _HEADER_SIZE
            data_end   = data_start + length

            if data_end > len(data):
                break  # truncated / corrupt record, stop scanning this block

            if data_start <= byte_offset < data_end:
                return pos, data_end

            pos = data_end

        block_base += _BLOCK_SIZE

    return -1, -1


# -----------------------------------------------------------------
#  Core patch logic
# -----------------------------------------------------------------

# How many bytes around a match to scan for the 'or' variable name.
_CONTEXT_WINDOW = 128


def find_gold_offsets(data: bytes, pattern: bytes) -> list[int]:
    """
    Find all byte offsets where `pattern` appears.
    Prefer matches that have the gold variable name 'or' nearby.
    Falls back to all matches if none have 'or' in context.
    """
    all_positions: list[int] = []
    preferred: list[int] = []

    start = 0
    while True:
        pos = data.find(pattern, start)
        if pos == -1:
            break
        all_positions.append(pos)

        # Check if the French variable name 'or' appears within +/-CONTEXT_WINDOW bytes
        lo = max(0, pos - _CONTEXT_WINDOW)
        hi = min(len(data), pos + len(pattern) + _CONTEXT_WINDOW)
        if GOLD_VAR_NAME in data[lo:hi]:
            preferred.append(pos)

        start = pos + 1

    return preferred if preferred else all_positions


def patch_file(filepath: Path, current_gold: int, target_gold: int) -> bool:
    """
    Locate the gold pattern in `filepath`, replace it, and recompute the
    LevelDB record CRC so the game accepts the save.  Returns True on success.
    """
    current_varint = encode_gold_varint(current_gold)
    target_varint  = encode_gold_varint(target_gold)

    if len(current_varint) != len(target_varint):
        print(
            f"\n[ERROR] Byte-length mismatch!\n"
            f"        current gold {current_gold} -> {len(current_varint)}-byte varint\n"
            f"        target  gold {target_gold}  -> {len(target_varint)}-byte varint\n"
            f"\n        The replacement MUST use the same number of bytes to avoid corruption.\n"
        )
        if len(current_varint) == 1:
            print("        Tip: your current gold is in the 1-63 range. "
                  "Target must also be 1-63 (and end in 0, so max is 60).")
        else:
            print("        Tip: your current gold is in the 64-8191 range. "
                  "Target must also be 64-8191 (and end in 0, so max is 8190).")
        return False

    pattern     = GOLD_PREFIX + current_varint
    replacement = GOLD_PREFIX + target_varint

    data = bytearray(filepath.read_bytes())
    original_len = len(data)

    positions = find_gold_offsets(bytes(data), pattern)

    if not positions:
        print(
            f"  [SKIP] Pattern {pattern.hex(' ').upper()} not found in {filepath.name}.\n"
            f"         Check that --current-gold matches your exact in-game gold."
        )
        return False

    if len(positions) > 1:
        print(
            f"  [WARN] {len(positions)} matches found -- patching all of them.\n"
            f"         (Only matches with 'or' nearby were selected when available.)"
        )

    for pos in positions:
        data[pos : pos + len(pattern)] = replacement
        print(f"  -> Patched offset 0x{pos:08X}  "
              f"({pattern.hex(' ').upper()} -> {replacement.hex(' ').upper()})")

        # Recalculate the CRC for the LevelDB record that contains this offset
        rec_start, rec_end = find_record_for_offset(data, pos)
        if rec_start != -1:
            rtype    = data[rec_start + 6]
            rec_data = bytes(data[rec_start + _HEADER_SIZE : rec_end])
            new_crc  = mask_crc(crc32c(bytes([rtype]) + rec_data))
            struct.pack_into('<I', data, rec_start, new_crc)
            print(f"  -> CRC-32C updated  (record header at 0x{rec_start:08X})")
        else:
            print(f"  [WARN] Could not locate the LevelDB record for offset 0x{pos:08X}.\n"
                  f"         CRC was NOT updated -- the save may be treated as corrupt by the game.")

    # Sanity check: file size must not change
    assert len(data) == original_len, "BUG: file size changed -- aborting write!"

    filepath.write_bytes(data)
    return True


# -----------------------------------------------------------------
#  Save directory auto-detection
# -----------------------------------------------------------------

def find_save_dir() -> Path | None:
    local_app_data = os.environ.get('LOCALAPPDATA')
    if not local_app_data:
        return None

    base = (
        Path(local_app_data)
        / 'SolCesto'
        / 'User Data'
        / 'Default'
        / 'IndexedDB'
    )
    if not base.exists():
        return None

    for entry in base.iterdir():
        if entry.is_dir() and 'indexeddb.leveldb' in entry.name.lower():
            return entry

    return None


# -----------------------------------------------------------------
#  Entry point
# -----------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description='Patch the gold value in SolCesto save files.',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Examples:\n"
            "  python gold_patcher.py --current-gold 100 --target-gold 8190\n"
            "  python gold_patcher.py --current-gold 50  --target-gold 60\n"
            "  python gold_patcher.py --current-gold 200 --target-gold 500 \\\n"
            '      --save-dir "C:/Users/You/AppData/Local/SolCesto/User Data/Default'
            '/IndexedDB/chrome-extension_abc.indexeddb.leveldb"\n'
            "\nNotes:\n"
            "  * Target gold must end in 0 (e.g. 10, 20, 60, 100, 8190).\n"
            "  * Current and target gold must both fall in the same byte-size range:\n"
            "      1-63    (1-byte varint, max target: 60)\n"
            "      64-8191 (2-byte varint, max target: 8190)\n"
            "  * Original files are backed up to ./backup/ and never modified.\n"
            "  * Patched copies are written to ./save/.\n"
            "  * After verifying the patch worked, copy ./save/ files back to the\n"
            "    original save directory."
        )
    )
    parser.add_argument(
        '--current-gold', type=int, required=True,
        metavar='N',
        help='Your current gold amount shown in-game.'
    )
    parser.add_argument(
        '--target-gold', type=int, required=True,
        metavar='N',
        help='The gold amount you want after patching (must end in 0).'
    )
    parser.add_argument(
        '--save-dir', type=str, default=None,
        metavar='PATH',
        help=(
            'Path to the .indexeddb.leveldb folder. '
            'Auto-detected from %%LOCALAPPDATA%%\\SolCesto\\... if omitted.'
        )
    )
    args = parser.parse_args()

    # -- Validate target gold ends in 0 -------------------------
    if args.target_gold % 10 != 0:
        nearest = (args.target_gold // 10) * 10
        nearest = max(nearest, 10)  # don't suggest 0
        print(
            f'[ERROR] Target gold must end in 0 (e.g. 10, 20, 60, 100, 8190).\n'
            f'        {args.target_gold} is not valid. Did you mean {nearest}?'
        )
        sys.exit(1)

    # -- Resolve save directory ---------------------------------
    if args.save_dir:
        save_dir = Path(args.save_dir)
    else:
        save_dir = find_save_dir()
        if save_dir is None:
            print(
                '[ERROR] Could not auto-detect save directory.\n'
                '        Use --save-dir to specify the path manually.\n'
                '        Expected location:\n'
                '          %LOCALAPPDATA%\\SolCesto\\User Data\\Default\\IndexedDB\\'
                '<chrome-extension_...>.indexeddb.leveldb'
            )
            sys.exit(1)
        print(f'[INFO]  Auto-detected save directory:\n        {save_dir}\n')

    if not save_dir.exists():
        print(f'[ERROR] Save directory not found:\n        {save_dir}')
        sys.exit(1)

    # -- Collect all files in the save directory ----------------
    all_files = [f for f in save_dir.iterdir() if f.is_file()]
    log_files = sorted(f for f in all_files if f.suffix == '.log')

    if not log_files:
        print(f'[ERROR] No .log files found in:\n        {save_dir}')
        sys.exit(1)

    print(f'[INFO]  Found {len(log_files)} log file(s): '
          f'{[f.name for f in log_files]}')

    # -- Backup & working-copy setup ---------------------------
    backup_dir = Path('./backup')
    work_dir   = Path('./save')
    backup_dir.mkdir(exist_ok=True)
    work_dir.mkdir(exist_ok=True)

    for f in all_files:
        shutil.copy2(f, backup_dir / f.name)
        shutil.copy2(f, work_dir   / f.name)

    print(f'[INFO]  Original files backed up -> ./backup/  ({len(all_files)} file(s))')
    print(f'[INFO]  Working copy created     -> ./save/')

    # -- Encode and display the intended patch -----------------
    try:
        cur_varint = encode_gold_varint(args.current_gold)
        tgt_varint = encode_gold_varint(args.target_gold)
    except ValueError as exc:
        print(f'\n[ERROR] {exc}')
        sys.exit(1)

    print(
        f'\n[INFO]  Gold  {args.current_gold:>6}  ->  '
        f'bytes: {(GOLD_PREFIX + cur_varint).hex(" ").upper()}'
    )
    print(
        f'[INFO]  Gold  {args.target_gold:>6}  ->  '
        f'bytes: {(GOLD_PREFIX + tgt_varint).hex(" ").upper()}'
    )

    # -- Patch each log file in the working copy ---------------
    success = False
    for log_file in sorted(work_dir.glob('*.log')):
        print(f'\n[SCAN]  {log_file.name}')
        if patch_file(log_file, args.current_gold, args.target_gold):
            success = True

    # -- Result ------------------------------------------------
    if success:
        print(
            f'\n[SUCCESS] Gold patched: {args.current_gold} -> {args.target_gold}\n'
            f'\n          Next steps:\n'
            f'          1. Close SolCesto completely.\n'
            f'          2. Copy all files from ./save/ back to:\n'
            f'             {save_dir}\n'
            f'          3. Launch the game -- your gold should be updated.\n'
            f'\n          If anything goes wrong, restore from ./backup/.'
        )
    else:
        print(
            '\n[FAILED] No files were patched.\n'
            '         * Confirm --current-gold matches your exact in-game amount.\n'
            '         * Try closing the game before running this tool (it may have\n'
            '           rewritten the log file while it was open).\n'
            '         * Original files in ./backup/ are untouched.'
        )
        sys.exit(1)


if __name__ == '__main__':
    main()
