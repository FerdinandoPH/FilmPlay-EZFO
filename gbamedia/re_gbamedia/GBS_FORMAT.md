**English** · [Español](GBS_FORMAT.es.md)

# The .gbs format (GBA Movie Player) — SOLVED

Reverse engineered from `savemu.dll` ("GBA Media Music Encoder"). Reference
implementation: `gbs_decode.py` + `gbs_tables.py` (tables extracted from the
binary).

## Container

Global header of **0x200 bytes**:

    0x00  "GBAL"
    0x04  u32  total file size
    0x08  "MUSI"
    0x0C  u32  zero
    0x10  u32  MusicMode  (0..4)
    0x14  zeros up to 0x200

From 0x200 on, fixed-size blocks depending on the mode. Each block is
**self-contained**: it starts with the predictor and the index, so there is no
error propagation between blocks and you can seek by position.

## The five modes

They all start from **44100 Hz, 16-bit, stereo** audio (the converter's own
help says so). The final sample rate comes from the decimation.

| Mode | Block | Header | Bits | Channels | Samples/block | Decimation | Hz | Ratio |
|---|---|---|---|---|---|---|---|---|
| 0 | 0x400 | 8 B | 4 | stereo | 1017 x2 | /2 by selection | 22050 | 7.95:1 |
| 1 | 0x400 | 4 B | 3 | mono | 2721 | none | 44100 | 10.63:1 |
| 2 | 0x200 | 4 B | 4 | mono | 1017 | /2 by selection | 22050 | 15.89:1 |
| 3 | 0x200 | 4 B | 2 | mono | 2033 | /2 by averaging | 22050 | 31.77:1 |
| 4 | 0x100 | 4 B | 2 | mono | 1009 | /4 by averaging | 11025 | 63.06:1 |

**The converter itself confirms this table**: the Music Converter 1.30 "Mode"
dropdown offers exactly `8:1 Stereo`, `11:1 Mono`, `16:1 Mono`, `32:1 Mono` and
`64:1 Mono`, which are the five ratios computed here in the same order. That is
independent confirmation, and in particular for mode 2: **16:1, not 32:1** as
an earlier version of this document said.

Each block consumes an exact amount of input bytes: 0x1FC8, 0x2A84, 0x1FC8,
0x3F88 and 0x3F10 respectively. The block's first sample goes in the header,
the rest are coded: `samples = 1 + coded`.

**Watch out for the decimation**: modes 0 and 2 **select** one sample out of
two, while modes 3 and 4 **average** (`FUN_100026e0`, mean of `n/2` samples
from the same channel). They are not the same thing, and a converter that
averages where the original selects will not produce equivalent files.

## Block header

    u16  predictor + 0x8000       (the predictor lives in 0..65535)
    u16  quantiser index

In mode 0 it is repeated for the second channel: `predL, idxL, predR, idxR`.
In modes 2, 3 and 4 the index is **clamped to 0xA0** when writing the header.

The output sample is `predictor - 0x8000`.

## Packing

- **Mode 0**: one byte per stereo pair, **low nibble = left**, high = right.
- **Mode 1**: groups of 8 three-bit codes in **24 bits big endian** (3 bytes).
  The first code goes in the lowest bits: `code[k] = (V >> 3*k) & 7`.
  340 groups per block.
- **Mode 2**: one byte per two samples, low nibble first.
- **Modes 3 and 4**: one byte per four samples, the first in bits 0-1.

## Quantisers

**4-bit** (`FUN_10002310`) and **3-bit** (`FUN_100024c0`) are standard IMA
ADPCM over the 89-step table, bit-identical to the reference one:

    4 bits: diff = step>>3; bit2->+step; bit1->+step/2; bit0->+step/4; bit3 = sign
    3 bits: diff = step>>2; bit1->+step; bit0->+step/2; bit2 = sign

    IDX4 = [-1,-1,-1,-1, 2, 4, 6, 8, -1,-1,-1,-1, 2, 4, 6, 8]
    IDX3 = [-1,-1, 2, 6, -1,-1, 2, 6]

The index is clamped to **[0, 88]** and the predictor to **[0, 0xFFFF]**.

**2-bit** (`FUN_10002730`) **is not IMA**. It uses its own delta table of 89
rows of 4 entries, `[+short, +long, -short, -long]`, with the code as
`sign*2 + magnitude`:

    predictor += DELTA2[index + code]
    index     += (code & 1) ? +4 : -4        clamped to [0, 0x160]

That is, the index advances four at a time (one row) and the number of rows,
89, matches the IMA table's. The table's high rows overflow int16 and must be
reproduced verbatim. It lives in `gbs_tables.py`.

## INI options

`[SaveMusic]`: `MusicMode` (0..4), `Channel` (0 = left, 1 = right) and `Volume`
(0..3). They map one to one onto the interface:

| Control | Values | Key |
|---|---|---|
| Mode | 8:1 Stereo / 11:1 Mono / 16:1 Mono / 32:1 Mono / 64:1 Mono | `MusicMode` 0..4 |
| Channel | Left / Right | `Channel` 0/1 |
| Volume | Normal / Twice / Four Times / Eight Times | `Volume` 0..3 = x1, x2, x4, x8 |

`Channel` shifts the input pointer by one `short` (`FUN_10002560`), so the
average is **always taken over samples of the same channel**, not over a mix.
It only applies to the mono modes, as the program's own help warns. `Volume`
multiplies with saturation in `FUN_10002840`.

All three are **encoding** options: they do not change the format and the
decoder does not need to know about them.

## Validation

**All five modes are validated against real files**, all generated from the
same `furretwalk.wav` (Channel Left, Volume Normal), which lets them be
compared against each other.

The five durations agree, which already validates block sizes, sample counts
and sample rates: if any of those numbers were wrong, the duration would be off
by an integer factor.

| File | Mode | Hz | Samples | Duration | Correlation with mode 0 | RMS |
|---|---|---|---|---|---|---|
| `furretwalk.gbs` | 0 | 22050 st. | 2373678 | 107.65 s | (reference) | 5256 |
| `furretwalk_mono11.gbs` | 1 | 44100 | 4748145 | 107.67 s | 0.9988 | 5251 |
| `furretwalk_mono16.gbs` | 2 | 22050 | 2373678 | 107.65 s | **1.0000** | 5256 |
| `furretwalk_mono32.gbs` | 3 | 22050 | 2372511 | 107.60 s | 0.9901 | 5069 |
| `furretwalk_mono64_l.gbs` | 4 | 11025 | 1186584 | 107.63 s | 0.9759 | 5667 |

### Mode 2 is bit-identical to mode 0's left channel

It does not merely resemble it: **it is exactly the same**. Of the 2373678
samples, **zero differ**. That makes sense, because mode 2 uses the same 4-bit
IMA quantiser and the same selection-based decimation as each channel of mode
0.

It is the strongest validation available, and confirms four things at once: the
4-bit quantiser, the selection decimation (it picks the same samples), the
+0x8000-biased predictor convention, and **that in mode 0 the low nibble is the
left channel** — which until now was only known from the code.

### The other modes

- **Mode 1** (3-bit, 8 codes packed into 24 bits big endian): 0.9988. It was
  the only path through the format that had never been exercised, because it is
  the only one that uses the 3-bit quantiser. Now validated.
- **Modes 3 and 4** (2-bit, own delta table): 0.9901 and 0.9759. The loss is
  simply quantisation noise at 32:1 and 64:1.
- **The `Channel` option** with `furretwalk_mono64_l.gbs` and `_r.gbs`: same
  size, same structure, they differ from byte 13149 on. The source is nearly
  mono (mean |L-R| 2.0 against an RMS of 6162), so the test confirms the option
  acts and does not alter the format, but cannot tell which channel is which.
  Mode 2, above, settles that.

### The new encoder reproduces all six files byte for byte

The original WAV fed to the converter was not needed. The quantiser is
deterministic and its output is reachable, so it is enough to decode an
original `.gbs` and build from it a 44100 Hz input that the mode's decimation
returns intact: repeat each sample `decimation` times, something **both
selection and averaging undo alike**. Encoding that input has to return the
file you started from.

It returns **exactly** the file you started from, in all six and in full,
header included. That validates at once the decimation, the block header, the
0xA0 index clamp, the three quantisers and the three packings. It lives in
`gbamedia/tests/test_gbs_codificador.py`.
