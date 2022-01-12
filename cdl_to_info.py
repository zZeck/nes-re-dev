import sys
import struct
from itertools import groupby, chain
from typing import List, final, Final, Tuple, cast, Iterator
from dataclasses import dataclass
from strenum import StrEnum
from tap import Tap

@final
class Mirroring(StrEnum):
    HORIZONTAL: Final = 'Horizontal'
    VERTICAL: Final = 'Vertical'
    FOUR_SCREEN: Final = 'Four Screen'

@final
class CdlByteType(StrEnum):
    CODE: Final = 'Code'
    DATA: Final = 'Data'
    UNACCESSED: Final = 'Unaccessed'

@dataclass(frozen=True)
@final
class INESHeader:
    trainer_start: int
    trainer_size_bytes: int
    prg_start: int
    prg_size_bytes: int
    chr_start: int
    chr_size_bytes: int
    mapper: int
    mirroring: Mirroring
    extra_ram: bool

@dataclass(frozen=True)
@final
class CdlBlock:
    rom_address_start: int
    rom_address_end: int
    byte_type: CdlByteType

# bitmasks for CDL data bytes; see http://fceux.com/web/help/CodeDataLogger.html
PRG_PCM_AUDIO: Final     = 1 << 6
PRG_INDIRECT_DATA: Final = 1 << 5
PRG_INDIRECT_CODE: Final = 1 << 4
PRG_CPU_BANK_HI: Final   = 1 << 3
PRG_CPU_BANK_LO: Final   = 1 << 2
PRG_DATA: Final          = 1 << 1
PRG_CODE: Final          = 1 << 0
CHR_READ_PROGRAMMATICALLY: Final = 1 << 1
CHR_RENDERED: Final              = 1 << 0

PRG_CODE_OR_DATA: Final = PRG_DATA | PRG_CODE

KB: Final = 2 ** 10

MS_DOS_EOF: Final = b"\x1A"
INES_ID: Final = b"NES" + MS_DOS_EOF

INES_HEADER_LENGTH: Final = 16

class SimpleArgumentParser(Tap):
    ines_file: str
    cdl_file: str

#doesn't handle iNES 2.0 exponential ROM size format
@final
def ines_header_decode(ines_header: memoryview):
    header_parsed: Final = cast(Tuple[bytes, int, int, int, int], struct.unpack("4s4B8x", ines_header))
    (_id, prg_size_16kb, chr_size_8kb, flags6, flags7) = header_parsed

    prg_size_bytes: Final = (256 if prg_size_16kb == 0 else prg_size_16kb) * 16 * KB
    chr_size_bytes: Final = chr_size_8kb * 8 * KB
    trainer_size_bytes: Final = bool(flags6 & 0x04) * 512

    mirroring: Final = Mirroring.FOUR_SCREEN if flags6 & 0x08 else\
        Mirroring.VERTICAL if flags6 & 0x01 else\
        Mirroring.HORIZONTAL

    return INESHeader(
        trainer_start = 16,
        trainer_size_bytes = trainer_size_bytes,
        prg_start = 16 + trainer_size_bytes,
        prg_size_bytes = prg_size_bytes,
        chr_start = 16 + trainer_size_bytes + trainer_size_bytes,
        chr_size_bytes = chr_size_bytes,
        mapper = (flags7 & 0xf0) | (flags6 >> 4),
        mirroring = mirroring,
        extra_ram = bool(flags6 & 0x02),
    )

@final
def indexed_cdl_byte_to_cdl_chunk(indexed_cdl_byte_group: Tuple[int, Iterator[Tuple[int, int]]]):
    byte: Final = indexed_cdl_byte_group[0]
    indexed_cdl_bytes: Final = list(indexed_cdl_byte_group[1])
    start_index: Final = indexed_cdl_bytes[0][0]
    end_index: Final = indexed_cdl_bytes[-1][0]
    return CdlBlock(
        rom_address_start= start_index,
        rom_address_end= end_index,
        byte_type= CdlByteType.CODE if byte & PRG_CODE else\
            CdlByteType.DATA if byte & PRG_DATA else\
            CdlByteType.UNACCESSED
    )

@final
def cdl_to_blocks(cdl: memoryview):
    cdl_indexed: Final = list(enumerate(cdl))

    cdl_block_groups: Final = groupby(cdl_indexed, lambda indexed_byte: indexed_byte[1] & PRG_CODE_OR_DATA)
    cdl_blocks: Final = list(map(indexed_cdl_byte_to_cdl_chunk, cdl_block_groups))

    return cdl_blocks

@final
def cdl_block_to_info_lines(cdl_block: CdlBlock) -> List[str]:
    label_info = [f"LABEL {{ ADDR ${(0xC000 + cdl_block.rom_address_start):04x}; NAME \"${(0xC000 + cdl_block.rom_address_start):04x}\"; COMMENT \"{cdl_block.byte_type}\"; }};"]\
        if cdl_block.byte_type == CdlByteType.UNACCESSED or cdl_block.byte_type == CdlByteType.DATA else []
    range_type: Final = "CODE" if cdl_block.byte_type == CdlByteType.CODE else "BYTETABLE"
    range_info = [f"RANGE {{ START ${(0xC000 + cdl_block.rom_address_start):04x}; END ${(0xC000 + cdl_block.rom_address_end):04x}; TYPE {range_type}; }};"]
    return label_info + range_info

@final
def main():
    args: Final = SimpleArgumentParser().parse_args()

    try:
        cdl_file: Final = open(args.cdl_file, "rb")
        cdl: Final = memoryview(cdl_file.read())
        cdl_file.close()

        ines_file: Final = open(args.ines_file, "rb")
        ines: Final = memoryview(ines_file.read(INES_HEADER_LENGTH))
        ines_file.close()
    except OSError:
        sys.exit("Error reading the file.")

    ines_header: Final = ines_header_decode(ines)

    cdl_blocks: Final = cdl_to_blocks(cdl[:ines_header.prg_size_bytes])

    info_lines: Final = chain(*map(cdl_block_to_info_lines, cdl_blocks))

    print('\n'.join(info_lines))

main()
