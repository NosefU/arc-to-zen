#!/usr/bin/env python3
"""Read the key/value pairs of a Chromium LevelDB directory without native libraries.

Only what Chromium's localStorage needs: table (.ldb) and log (.log) files,
Snappy-compressed blocks, and the newest record per key winning.
"""

from __future__ import annotations

import struct
from pathlib import Path
from typing import Dict, Iterator, Optional, Tuple

TABLE_MAGIC = 0xDB4775248B80FB57
LOG_BLOCK_SIZE = 32768
TYPE_DELETION = 0
TYPE_VALUE = 1


class LevelDBError(RuntimeError):
    pass


def read_varint(data: bytes, pos: int) -> Tuple[int, int]:
    result = shift = 0
    while True:
        byte = data[pos]
        pos += 1
        result |= (byte & 0x7F) << shift
        if not byte & 0x80:
            return result, pos
        shift += 7


def snappy_decompress(data: bytes) -> bytes:
    length, pos = read_varint(data, 0)
    out = bytearray()
    while pos < len(data):
        tag = data[pos]
        pos += 1
        kind = tag & 3
        if kind == 0:  # literal
            size = tag >> 2
            if size >= 60:
                extra = size - 59
                size = int.from_bytes(data[pos:pos + extra], "little")
                pos += extra
            size += 1
            out += data[pos:pos + size]
            pos += size
            continue
        if kind == 1:
            size = ((tag >> 2) & 7) + 4
            offset = ((tag >> 5) << 8) | data[pos]
            pos += 1
        elif kind == 2:
            size = (tag >> 2) + 1
            offset = int.from_bytes(data[pos:pos + 2], "little")
            pos += 2
        else:
            size = (tag >> 2) + 1
            offset = int.from_bytes(data[pos:pos + 4], "little")
            pos += 4
        if not offset or offset > len(out):
            raise LevelDBError("corrupt snappy data")
        start = len(out) - offset
        for i in range(size):
            out.append(out[start + i])
    if len(out) != length:
        raise LevelDBError("snappy length mismatch")
    return bytes(out)


def read_block(raw: bytes, offset: int, size: int) -> bytes:
    block = raw[offset:offset + size]
    compression = raw[offset + size]
    if compression == 0:
        return block
    if compression == 1:
        return snappy_decompress(block)
    raise LevelDBError(f"unsupported block compression {compression}")


def block_entries(block: bytes) -> Iterator[Tuple[bytes, bytes]]:
    restarts = struct.unpack_from("<I", block, len(block) - 4)[0]
    end = len(block) - 4 - restarts * 4
    pos = 0
    key = b""
    while pos < end:
        shared, pos = read_varint(block, pos)
        non_shared, pos = read_varint(block, pos)
        value_length, pos = read_varint(block, pos)
        key = key[:shared] + block[pos:pos + non_shared]
        pos += non_shared
        yield key, block[pos:pos + value_length]
        pos += value_length


def table_records(path: Path) -> Iterator[Tuple[bytes, int, int, bytes]]:
    """Yield (user_key, sequence, type, value) from a .ldb/.sst table."""
    raw = path.read_bytes()
    if len(raw) < 48 or struct.unpack_from("<Q", raw, len(raw) - 8)[0] != TABLE_MAGIC:
        raise LevelDBError(f"{path.name} is not a LevelDB table")
    footer = raw[-48:]
    _, pos = read_varint(footer, 0)  # metaindex offset
    _, pos = read_varint(footer, pos)  # metaindex size
    index_offset, pos = read_varint(footer, pos)
    index_size, _ = read_varint(footer, pos)
    for _, handle in block_entries(read_block(raw, index_offset, index_size)):
        offset, pos = read_varint(handle, 0)
        size, _ = read_varint(handle, pos)
        for internal_key, value in block_entries(read_block(raw, offset, size)):
            trailer = struct.unpack_from("<Q", internal_key, len(internal_key) - 8)[0]
            yield internal_key[:-8], trailer >> 8, trailer & 0xFF, value


def log_records(path: Path) -> Iterator[bytes]:
    raw = path.read_bytes()
    pending = bytearray()
    pos = 0
    while pos + 7 <= len(raw):
        block_left = LOG_BLOCK_SIZE - pos % LOG_BLOCK_SIZE
        if block_left < 7:
            pos += block_left
            continue
        length, kind = struct.unpack_from("<HB", raw, pos + 4)
        payload = raw[pos + 7:pos + 7 + length]
        pos += 7 + length
        if kind == 0 and length == 0:
            pos += block_left - 7  # zero padding to the end of the block
            continue
        if kind == 1:  # full
            yield payload
        elif kind == 2:  # first
            pending = bytearray(payload)
        elif kind == 3:  # middle
            pending += payload
        elif kind == 4:  # last
            pending += payload
            yield bytes(pending)
            pending = bytearray()


def write_batch_records(batch: bytes) -> Iterator[Tuple[bytes, int, int, bytes]]:
    sequence, count = struct.unpack_from("<QI", batch, 0)
    pos = 12
    for index in range(count):
        kind = batch[pos]
        pos += 1
        key_length, pos = read_varint(batch, pos)
        key = batch[pos:pos + key_length]
        pos += key_length
        value = b""
        if kind == TYPE_VALUE:
            value_length, pos = read_varint(batch, pos)
            value = batch[pos:pos + value_length]
            pos += value_length
        yield key, sequence + index, kind, value


def read_leveldb(directory: Path) -> Dict[bytes, bytes]:
    """Return the live key/value pairs of a LevelDB directory."""
    newest: Dict[bytes, Tuple[int, int, bytes]] = {}

    def add(key: bytes, sequence: int, kind: int, value: bytes) -> None:
        current: Optional[Tuple[int, int, bytes]] = newest.get(key)
        if current is None or sequence > current[0]:
            newest[key] = (sequence, kind, value)

    for path in sorted(directory.glob("*.ldb")) + sorted(directory.glob("*.sst")):
        for record in table_records(path):
            add(*record)
    for path in sorted(directory.glob("*.log")):
        for batch in log_records(path):
            if len(batch) >= 12:
                for record in write_batch_records(batch):
                    add(*record)

    return {key: value for key, (_, kind, value) in newest.items() if kind == TYPE_VALUE}
