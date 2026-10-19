# -*- coding: utf-8 -*-
"""Diablo III console CPK reader with single-file extraction.

Index parsing is index-only (no payload read); extraction decompresses only
the compressed sectors that cover the requested file's range.

Vendored from the D3 mobile port's tools (d3-mobile/tools/d3cpk.py, the
2026-10-19 fixed version: streaming zlib + dec_sz check, no silent zero fill)
for shader_split.py's CPK shader source. Only change: read() finds its first
sector with bisect instead of scanning from sector 0 (byte-identical output,
validated against the original on ClientCommon.cpk samples).
"""
import bisect
import os
import struct
import zlib

MAGIC = 0xA1B2C3D4
CIPHER_INIT = 0x872DCDA7A97A7EE1


def fnv_hash64(name: str) -> int:
    h = 0xCBF29CE484222325
    for c in name.lower().encode("ascii", errors="replace"):
        h = (0x100000001B3 * (h ^ c)) & 0xFFFFFFFFFFFFFFFF
    return h


def read_bits(buf, bit_pos, n):
    bs = bit_pos >> 3
    be = (bit_pos + n + 7) >> 3
    val = int.from_bytes(buf[bs:be], "big")
    return (val >> ((be - bs) * 8 - (bit_pos & 7) - n)) & ((1 << n) - 1)


def decrypt_chunk(ct):
    state = CIPHER_INIT
    out = bytearray(len(ct))
    for i, c in enumerate(ct):
        out[i] = c ^ (state & 0xFF)
        state = ((c & 0xFF) << 56) | (state >> 8)
        state &= 0xFFFFFFFFFFFFFFFF
    return bytes(out)


class CPK:
    def __init__(self, path):
        self.path = path
        self.fsize = os.path.getsize(path)
        with open(path, 'rb') as f:
            self.head = f.read(72)
        self._parse_header()
        with open(path, 'rb') as f:
            self.idx = f.read(min(self.first_sec, self.fsize))
        self._parse_tables()
        self._fh = open(path, 'rb')

    def close(self):
        try:
            self._fh.close()
        except Exception:
            pass

    def _parse_header(self):
        d = self.head
        self.endian = ">" if struct.unpack('>I', d[:4])[0] == MAGIC else "<"
        if struct.unpack(self.endian + 'I', d[:4])[0] != MAGIC:
            raise ValueError('not a D3 CPK: %s' % d[:4].hex())
        u32 = lambda o: struct.unpack(self.endian + 'I', d[o:o + 4])[0]
        u64 = lambda o: struct.unpack(self.endian + 'Q', d[o:o + 8])[0]
        self.version = u32(4)
        self.decomp_fs = u64(8)
        self.fmt_const = u32(16)
        self.file_count = u32(20)
        self.loc_count = u32(24)
        self.header_sector = u32(28)
        self.fs_bc, self.flcnt_bc, self.flidx_bc, self.loc_bc = u32(32), u32(36), u32(40), u32(44)
        self.cs2do_bc = u32(48)
        self.ds2cs_bc = u32(52)
        self.sector_crc32 = u32(56)
        if self.version == 7:
            self.read_sector, self.comp_sector, self.header_size = u32(60), u32(64), 72
        else:
            self.read_sector, self.comp_sector, self.header_size = 0x10000, 0x4000, 64
        if self.fmt_const == 10:
            self.first_sec = self.header_sector
        else:
            self.first_sec = (self.read_sector * self.header_sector) & 0xFFFF0000
            if self.first_sec % self.read_sector:
                self.first_sec += self.read_sector
        self.comp_sector_count = max(0, (self.comp_sector + self.fsize - 1 - self.first_sec) // self.comp_sector)

    def _parse_tables(self):
        d, h = self.idx, self
        u32 = lambda o: struct.unpack(h.endian + 'I', d[o:o + 4])[0]
        eb = 64 + h.fs_bc + h.flcnt_bc + h.flidx_bc
        sfi_bytes = (h.file_count * eb + 7) // 8
        blk = d[h.header_size:h.header_size + sfi_bytes]
        self.sfi = []
        for i in range(h.file_count):
            bp = i * eb
            hh = read_bits(blk, bp, 64); bp += 64
            sz = read_bits(blk, bp, h.fs_bc); bp += h.fs_bc
            lc = read_bits(blk, bp, h.flcnt_bc); bp += h.flcnt_bc
            li = read_bits(blk, bp, h.flidx_bc)
            self.sfi.append((hh, sz, lc, li))
        pos = h.header_size + sfi_bytes

        loc_b = (h.loc_bc * h.loc_count + 7) // 8
        lb = d[pos:pos + loc_b]
        self.locs = [read_bits(lb, i * h.loc_bc, h.loc_bc) for i in range(h.loc_count)]
        pos += loc_b

        cs_b = (h.comp_sector_count * h.cs2do_bc + 7) // 8
        cb = d[pos:pos + cs_b]
        self.cs2do = [read_bits(cb, i * h.cs2do_bc, h.cs2do_bc) for i in range(h.comp_sector_count)]
        pos += cs_b

        ds_n = (h.decomp_fs + h.comp_sector - 1) // h.comp_sector
        ds_bc = h.ds2cs_bc or max(1, h.comp_sector_count.bit_length())
        pos += (ds_bc * ds_n + 7) // 8

        self.name_offs = [u32(pos + i * 4) for i in range(h.file_count)]
        pos += h.file_count * 4
        start = pos
        self.names = []
        for off in self.name_offs:
            a = start + off
            e = d.find(b'\x00', a)
            self.names.append(d[a:e if e != -1 else a + 256].decode('latin-1', 'replace'))

        self.by_name = {}
        h2s = {row[0]: row for row in self.sfi}
        for name in self.names:
            row = h2s.get(fnv_hash64(name))
            if row:
                self.by_name[name] = (row[1], self.locs[row[3]] if row[3] < len(self.locs) else 0)

    def _read_sector_raw(self, s):
        start = self.first_sec + s * self.comp_sector
        self._fh.seek(start)
        return self._fh.read(min(self.comp_sector, self.fsize - start))

    def _sector_chunks(self, s):
        """→ (raw sector bytes, first chunk position, [(position, dec_sz, zsz, enc)])
        Chunks start at offset 0 of every sector, sector 0 included: its first 6 bytes are
        an ordinary chunk header (the original reader took bytes 4..6 for a skip length and
        so dropped sector 0's first chunk in every non-fmt-10 archive, shifting the first
        files' bytes; with the header read as a header the chain total matches the sector
        table for every CPK of the 2.7.7 set)."""
        d = self._read_sector_raw(s)
        p = 0
        out = []
        while p + 6 <= len(d):
            nlow = struct.unpack(self.endian + 'H', d[p:p + 2])[0]
            nhigh = struct.unpack(self.endian + 'H', d[p + 2:p + 4])[0]
            zraw = struct.unpack(self.endian + 'H', d[p + 4:p + 6])[0]
            if zraw == 0:
                break
            dec_sz = (nhigh << 16) | nlow
            zsz, enc = zraw & 0x7FFF, bool(zraw & 0x8000)
            if p + 6 + zsz > len(d):
                break
            out.append((p, dec_sz, zsz, enc))
            p += 6 + zsz
        return d, p, out

    def _decompress_sector(self, s):
        d, _, chunks = self._sector_chunks(s)
        out = bytearray()
        for p, dec_sz, zsz, enc in chunks:
            out += self._inflate_chunk(d, p, dec_sz, zsz, enc, s)
        return bytes(out)

    def _inflate_chunk(self, d, p, dec_sz, zsz, enc, s):
        chunk = d[p + 6:p + 6 + zsz]
        if len(chunk) < zsz:
            return b''
        if enc:
            chunk = decrypt_chunk(chunk)
        # 2026-10-19 修：D3 主机版 CPK 的 zlib 流有相当一部分是「未收尾」的
        # （无 final block / adler32 尾，游戏侧显然是流式 inflate）。严格
        # zlib.decompress 会直接拒绝这类流，旧代码在 except 里静默填零，
        # 把大量完好数据伪装成 stub（实测 ClientCommon 抽样 300 sector：
        # 637 个 chunk 中 222 个属此类，全部可完整恢复，输出长度恒等于声明值）。
        # 现改为流式解压 + 长度校验，任何不符大声报错，绝不静默填零。
        dec_obj = zlib.decompressobj()
        try:
            dec = dec_obj.decompress(chunk)
        except Exception as e:
            raise ValueError(
                'CPK chunk 解压失败: sector %d chunk@%#x dec_sz %d zsz %d enc %s: %s'
                % (s, p, dec_sz, zsz, enc, e))
        if len(dec) != dec_sz:
            raise ValueError(
                'CPK chunk 解压长度不符: sector %d chunk@%#x 声明 %d B, 实得 %d B (eof=%s)'
                % (s, p, dec_sz, len(dec), dec_obj.eof))
        return dec

    def read(self, name, plain_only=False):
        """A file's bytes. plain_only: chunks marked encrypted are skipped instead of
        decrypted (the console cipher behind them is not implemented); the file then
        raises if any of its bytes would fall inside a skipped chunk, so a partial
        read is never mistaken for a complete one. D3's Shaders\\*.shd entries lie
        entirely in plain chunks (checked over every CPK of the 2.7.7 set), which is
        what the shader tools need; the game itself decrypts the rest at run time."""
        size, off = self.by_name[name]
        end = off + size
        buf, have = bytearray(size), bytearray(size)
        # cs2do is sorted ascending: start at the sector that can hold `off`
        # instead of scanning (and skipping) every earlier sector
        s = max(bisect.bisect_right(self.cs2do, off) - 1, 0)
        while s < self.comp_sector_count:
            base = self.cs2do[s]
            if base >= end:
                break
            d, _, chunks = self._sector_chunks(s)
            D = 0
            for p, dec_sz, zsz, enc in chunks:
                if not enc or not plain_only:
                    dec = self._inflate_chunk(d, p, dec_sz, zsz, enc, s)
                    lo, hi = max(base + D, off), min(base + D + len(dec), end)
                    if hi > lo:
                        buf[lo - off:hi - off] = dec[lo - base - D:hi - base - D]
                        have[lo - off:hi - off] = b'\x01' * (hi - lo)
                D += dec_sz
            s += 1
        hole = have.find(0)
        if hole >= 0:
            raise ValueError(
                '%s：%d 字节落在未解出的加密 chunk 里（首个空洞 @%#x，共 %d 字节）| '
                '%s: %d bytes inside skipped encrypted chunks (first hole @%#x of %d)'
                % (name, size - sum(have), off + hole, size, name, size - sum(have), off + hole, size))
        return bytes(buf)
