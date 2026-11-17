# -*- coding: utf-8 -*-
r"""Dump IL of methods of a type from a .NET assembly (dnfile + dncil)."""
import sys
from pathlib import Path

import dnfile
from dncil.cil.body import CilMethodBody
from dncil.cil.body.reader import CilMethodBodyReaderBase
from dncil.cil.error import MethodBodyFormatError


class Reader(CilMethodBodyReaderBase):
    def __init__(self, pe, rva):
        self.pe = pe
        self.offset = self.pe.get_offset_from_rva(rva)

    def read(self, n):
        data = self.pe.get_data(self.pe.get_rva_from_offset(self.offset), n)
        self.offset += n
        return data

    def tell(self):
        return self.offset

    def seek(self, offset):
        self.offset = offset
        return self.offset


def dump(path, type_name, only=None):
    pe = dnfile.dnPE(str(path))
    tables = pe.net.mdtables
    type_defs = {str(t.TypeName): t for t in tables.TypeDef if t.TypeName}
    td = type_defs.get(type_name)
    if td is None:
        print("type not found:", type_name)
        print("candidates:", [str(t.TypeName) for t in tables.TypeDef
                              if t.TypeName and type_name.lower() in str(t.TypeName).lower()][:10])
        return
    print(f"type {type_name}: {len(td.MethodList)} method(s)")
    for m in td.MethodList:
        row = m.row
        name = row.Name
        if only and only.lower() not in str(name).lower():
            continue
        print(f"\n--- {type_name}.{name}")
        try:
            body = CilMethodBody(Reader(pe, row.Rva))
        except (MethodBodyFormatError, Exception) as exc:
            print("   (no body)", type(exc).__name__)
            continue
        for insn in body.instructions:
            print(f"   {insn.offset:04x} {insn.opcode} {insn.operand or ''}")


if __name__ == "__main__":
    dump(Path(sys.argv[1]), sys.argv[2], sys.argv[3] if len(sys.argv) > 3 else None)
