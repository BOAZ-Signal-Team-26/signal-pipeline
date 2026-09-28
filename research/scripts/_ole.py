"""HWP 5.0(OLE 복합문서)에서 스트림을 꺼내는 최소 파서. 외부 의존성 없음."""
import struct, zlib

class Ole:
    def __init__(self, data):
        assert data[:8] == b'\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1', 'OLE 아님'
        self.d = data
        self.ssz = 1 << struct.unpack_from('<H', data, 0x1e)[0]
        self.mssz = 1 << struct.unpack_from('<H', data, 0x20)[0]
        nfat = struct.unpack_from('<I', data, 0x2c)[0]
        self.dir0 = struct.unpack_from('<I', data, 0x30)[0]
        self.cutoff = struct.unpack_from('<I', data, 0x38)[0]
        self.mfat0 = struct.unpack_from('<I', data, 0x3c)[0]
        self.difat0 = struct.unpack_from('<I', data, 0x44)[0]
        # DIFAT: 헤더 109개 + 추가 섹터
        difat = list(struct.unpack_from('<109I', data, 0x4c))
        s = self.difat0
        while s not in (0xFFFFFFFE, 0xFFFFFFFF) and len(difat) < nfat + 1000:
            blk = self.sector(s)
            difat += list(struct.unpack_from('<%dI' % (self.ssz // 4 - 1), blk, 0))
            s = struct.unpack_from('<I', blk, self.ssz - 4)[0]
        self.fat = []
        for fs in difat[:nfat]:
            if fs in (0xFFFFFFFE, 0xFFFFFFFF):
                continue
            self.fat += list(struct.unpack_from('<%dI' % (self.ssz // 4), self.sector(fs), 0))
        self.entries = self._dirs()
        root = self.entries[0]
        self.mini = self._chain_bytes(root[2], root[3], mini=False)
        self.mfat = []
        s = self.mfat0
        while s not in (0xFFFFFFFE, 0xFFFFFFFF):
            self.mfat += list(struct.unpack_from('<%dI' % (self.ssz // 4), self.sector(s), 0))
            s = self.fat[s] if s < len(self.fat) else 0xFFFFFFFE

    def sector(self, n):
        off = 512 + n * self.ssz
        return self.d[off:off + self.ssz]

    def _chain_bytes(self, start, size, mini):
        out = b''
        s = start
        unit = self.mssz if mini else self.ssz
        table = self.mfat if mini else self.fat
        while s not in (0xFFFFFFFE, 0xFFFFFFFF) and len(out) < size + unit:
            out += (self.mini[s * unit:(s + 1) * unit] if mini else self.sector(s))
            s = table[s] if s < len(table) else 0xFFFFFFFE
        return out[:size]

    def _dirs(self):
        raw = b''
        s = self.dir0
        while s not in (0xFFFFFFFE, 0xFFFFFFFF):
            raw += self.sector(s)
            s = self.fat[s] if s < len(self.fat) else 0xFFFFFFFE
        out = []
        for i in range(len(raw) // 128):
            e = raw[i * 128:(i + 1) * 128]
            nl = struct.unpack_from('<H', e, 64)[0]
            name = e[:max(0, nl - 2)].decode('utf-16-le', 'replace')
            typ = e[66]
            start = struct.unpack_from('<I', e, 116)[0]
            size = struct.unpack_from('<Q', e, 120)[0]
            out.append((name, typ, start, size))
        return out

    def names(self):
        return [(n, t, sz) for n, t, st, sz in self.entries if n]

    def read(self, name):
        for n, t, st, sz in self.entries:
            if n == name:
                return self._chain_bytes(st, sz, mini=(sz < self.cutoff))
        return None
