**English** · [Español](GBM_FORMAT.es.md)

# The .gbm format (GBA Movie Player) — SOLVED

Reverse engineered from the **ROM's decoder** in `FilmPlay.gba`
(`0x08120000`–`0x08122e9c`), far more readable than the `Gbamvico.dll`
encoder, and **validated over 2715 frames** of three real videos generated with
the original converter.

Reference implementation: `gbm_decode.py` (decodes and dumps PNGs).

## Container

Global header of **0x200 bytes**:

    0x00  "GBAM"          (the audio magic is "GBAL"; they are not shared)
    0x04  u32  total file size
    0x08  "MOVI"
    0x0C  u32  zero
    0x10  u32  Mode
    0x14  zeros up to 0x200

It carries no dimensions, fps or frame count: the player assumes
**240x160 at 10 fps**. The fps are confirmed by squaring the `.gbs` duration
with the `.gbm` frame count in all three videos (63.05/63.00 s, 107.70/108.00 s
and 100.45/100.50 s).

From 0x200 on, a sequence of variable-length frames that **tiles exactly** up
to the last byte of the file:

    u16  payload length
    u8   payload[length]

A video is a pair of files: `Mnnnnn.gbm` + `Mnnnnn.gbs` (audio, see
`GBS_FORMAT.md`).

## A frame's payload

    off 0            u16  bitstream_size (bytes, multiple of 4)
    off 2            u16  colours_size   (bytes, multiple of 2)
    off 4            u32  bitstream[]
    ...              u16  colours[]      GBA-native BGR555
    ...              u8   vectors[]      indices into the motion table

- **bitstream**: read **MSB first, 32 bits per little-endian u32 word**.
  The leftover bits of the last word are padding (always < 32).
- **colours**: `((b>>3)*32 + (g>>3))*32 + (r>>3)`, that is blue in bits 10-14,
  green in 5-9 and red in 0-4. Bit 15 always zero. They are ready to be copied
  into the framebuffer with no conversion.
- **vectors**: one byte per moving block, an index into a table of 256 offsets.
  On high quality it is empty, but **on low quality it is used heavily**
  (701810 bytes in `M00006.gbm`) and is consumed exactly.

## The codec: binary partition tree over 8x8 blocks

The frame is walked in **raster order over 8x8 blocks**: 30 columns x 20 rows =
**600 blocks**. Each block is the root of a binary tree that splits until it
reaches a leaf. The possible shapes are every `w x h` with `w, h` in
{1, 2, 4, 8}: 15 in total, and the ROM has **one function per shape**:

| Shape | Function | Shape | Function | Shape | Function |
|---|---|---|---|---|---|
| 8x8 | (0x081205a0, start lost) | 8x4 | `0x08121494` | 4x8 | `0x08120f5c` |
| 8x2 | `0x08120940` | 4x4 | `0x08120c28` | 2x8 | `0x08120628` |
| 8x1 | `0x08122600` | 4x2 | `0x081221c4` | 2x4 | `0x08121fdc` |
| 1x8 | `0x0812239c` | 4x1 | `0x08121c98` | 2x2 | `0x081219d4` |
| 1x4 | `0x08121b24` | 2x1 | `0x08121ee0` | 1x2 | `0x08121de8` |

### A node's bit code (blocks of more than 2 pixels)

    0 0            copy from the previous frame, same position
    0 1            copy from the previous frame with a vector (consumes 1 byte)
    1 0 [dir]      split into two halves
    1 1 0          copy with a vector and add a colour (consumes 1 byte + 1 colour)
    1 1 1          solid fill with a colour (consumes 1 colour)

The `dir` bit **only exists if both dimensions are greater than 1**:
`0` = vertical split (top half and bottom half), `1` = horizontal split (left
half and right half). A row (`h == 1`) can only be split horizontally and a
column (`w == 1`) only vertically, and in those cases the bit is not emitted.
This detail is essential: without it the bitstream desynchronises at the second
block.

### 2-pixel leaves (2x1 and 1x2)

There is no more splitting, so the last level changes meaning:

    0 0            copy from the previous frame
    0 1            copy with a vector
    1 0            copy with a vector and add a colour
    1 1 0          both pixels the same colour
    1 1 1          a colour of its own for each pixel (consumes 2 colours)

### Colour addition

The ROM packs the colour into both halves of a word
(`orr r8, r8, r8, lsl #16`) and adds 32 bits at a time, so the carry between
components **is not clipped**. A new encoder must reproduce that exact
arithmetic if it uses this mode.

### Vector table (confirmed)

`r7` points at 256 byte offsets that are added to the previous frame's pointer.
The contents cannot be read (they fall in the ROM's lost area), but they have
been deduced and confirmed with `M00006.gbm`:

    dx = (index & 15) - 8          range [-8, +7]
    dy = (index >> 4) - 8          range [-8, +7]
    offset = dy * 480 + dx * 2      (bytes)

Two independent proofs:

1. **Index histogram**: a sharp peak at `0x88` (6.27 %, over four times the
   next one), which is exactly `dx=0, dy=0`. The next ones are its immediate
   neighbours `0x87`, `0x89`, `0x98`, `0x78`. The distribution is a 2D star
   centred on "no motion", as real vectors should be.
2. **Discontinuity at block edges** over decoded frames, comparing candidates.
   A wrong table displaces blocks and comes out worse than applying no motion
   at all:

   | Table | Excess discontinuity |
   |---|---|
   | dx = low nibble, dy = high | **+0.37** |
   | nibbles swapped | +4.61 |
   | origin at 7 | +3.46 |
   | ignore the vectors (control) | +1.91 |

## The tail on frames 20 to 27

The encoder appends **0x1002 bytes** to the payload of frames 20 to 27: 4096
bytes of an internal table (`DAT_100152d8`, 8 blocks of 4 KB = 32 KB) with each
u16 XORed against a `rand()` seeded with the frame size, plus the key itself at
the end.

**It is inert for playback.** It falls exactly where the vector stream would
go, which is unused, and the decoder never reads it: the bit and colour streams
are consumed exactly to the end in all eight frames. A new converter can omit
it.

## Effect of the converter's options

The `[SaveMovie]` keys in `GBAMedia.ini` and their defaults are `FullOut`,
`ChangeScale`, `ImageV=20`, `ImageH=30`, `FrameSize=8192`, `Scale=1`, `Mode=0`,
`S=2`, `Enhance=10`, `Brightness`, `Contrast=75`. **None of them changes the
format's syntax.**

- **`ImageH` / `ImageV`** (in 8-pixel blocks; multiplied by 8 and clamped to
  [8,240] and [8,160]) are only referenced, outside the INI reader, at
  `0x10003630` and `0x10003646`: the input **scaler**, next to `ChangeScale`.
  They do not appear in the codec. They control what size the image is scaled
  to inside the buffer, not the block grid, which is **always 30x20**.
  Consistent with the output sample size being fixed unconditionally to
  `0x12C00` = 240*160*2, and with the header having nowhere to store
  dimensions.
- **`Scale`** is the quality selector. It is referenced in the codec
  (`0x100052dc`, `0x10005632`, `0x1000589a`, `0x1000599e`), but only affects
  the **decision thresholds**, the number of requantisation passes and the hard
  per-frame cap. All four branches call the same compressor with the same
  arguments and end up in the same serialiser.

  | `Scale` | Passes | Hard cap |
  |---|---|---|
  | 0 | 10 | 0x4000 |
  | 1 | 6 | **0x8000** |
  | 2 | 8 | 0x4000 |
  | 3-5 | 6 | 0x4000 |

  The Movie Converter 1.30 interface does not expose `Scale` directly: it
  offers three presets, which also pin the audio mode of the companion `.gbs`:

  | Preset | `.gbs` audio | Example |
  |---|---|---|
  | High Quality Mode | `MusicMode` 0 (8:1 stereo) | `M00001`, `M00004`, `M00005` |
  | Standard Mode | `MusicMode` 2 (16:1 mono) | `M00008` |
  | High Compression Mode | `MusicMode` 4 (64:1 mono) | `M00006` |

  There is also a "Manual Setting" checkbox giving access to the individual
  parameters, and an output size limit (256 MB by default) for splitting.

### What the five quality parameters really do

They are **difference tolerances**, one per block-size band, and are consulted
in `FUN_100051d7` (and its twins at `0x100055b4` and `0x10005916`): depending
on the level it picks `ca27e8`, `ca27ec`, `ca27f0`, `ca27f4` or `ca27f8`, and
the block is accepted if the differences above the threshold are zero. On top
of that, `Scale == 1` takes a **strictly stricter** branch: it requires two
counters to be zero, while the other qualities only require one.

Comparing `M00004` (high) and `M00008` (standard), which are **the same 630
frame video**:

| | High | Standard |
|---|---|---|
| Total leaves | 1014570 | 707105 |
| Leaves per 8x8 block | 2.68 | 1.87 |
| Copy with a motion vector | **0 %** | **24.2 %** |
| 8x8 blocks that are not split | 29.5 % | 43.1 % |
| Leaves of 1 or 2 pixels | 39.3 % | 9.6 % |
| Average payload | 1583 B | 1181 B |
| PSNR against the original AVI | 32.3 dB | 31.8 dB |

The two underlying differences are that **high quality does not use motion
compensation at all** and that it subdivides down to pixel pairs, while
standard accepts vector copies in a quarter of its leaves and leaves 43 % of
the blocks whole. The cause is the same: with zero tolerance and the strict
test, a displaced copy is almost never accepted and the encoder falls back to
explicit colours.

In performance terms the advantage is slim: **34 % more bytes for 0.4 dB**. The
measurement is over the sync pattern, which is synthetic graphics; on real
video the difference could be larger.

**For the converter**: vector search is only needed to imitate standard or low
quality. An encoder aiming at high quality can do without it entirely.

  The practical effect is size: the average payload goes from 12786 B per frame
  on high quality to **2463 B** on low quality, and low quality compensates by
  using motion vectors, which high does not use.
- **`Brightness`, `Contrast`, `Enhance`** are pixel preprocessing.
- The header's `Mode` field is **4 in all six files**, on both high and low
  quality. It is written by the EXE, not the DLL. A new converter emits 4.
- Stereo/mono only affects the `.gbs`, which is a separate file.

## No periodic reference reset

The encoder's per-frame loop blacks out its reference every 600 frames instead
of updating it. That does **not** require any handling in the decoder: it
self-corrects, because against a black reference the encoder ends up emitting
explicit colours everywhere. Verified by decoding all of `M00001`; frame 1000
comes out with no drift whatsoever.

## Validation

`gbm_decode.py` over the seven available `.gbm` files, covering the converter's
three presets:

| File | Frames | Preset | Uses vectors | Average payload |
|---|---|---|---|---|
| `M00000` / `M00001` / `M00003` | 1080 | high | no | 12784 B |
| `M00004` | 630 | high | no | 1583 B |
| `M00005` | 1005 | high | no | 8891 B |
| `M00006` | 1005 | compression | 1004 frames | 2463 B |
| `M00008` | 630 | standard | 627 frames | 1181 B |

**6510 frames in total.** In every one of them:

- The colour stream is consumed **to the exact last byte**.
- The leftover bits are always fewer than 32 (padding of the last word).
- The frames tile exactly to the end of the file and the header's size field
  matches the real size in all seven.
- The vector stream is consumed entirely except for the 4098-byte tail on
  frames 20 to 27.
- The images are correct, including legible small text in the sync pattern of
  `M00004` and `M00008`.

### Three frames with an unread vector byte

`M00004` (358 and 558) and `M00006` (625) leave **1 byte** unconsumed in the
vector stream. It is not a decoder bug: `M00004` **uses no vectors in any
frame**, and even so two of its frames carry a loose byte there. It is a byte
the encoder writes and nobody references. The colours are consumed exactly in
all three and the images come out fine.

## The ROM's lost area

`0x08104000`–`0x08120000` is all zeros and `0x08120000`–~`0x081204xx` is 0xFF
in all three available copies of the ROM. That is where the per-frame loop
(which sets pointers and traversal order), the bit reload routine
`0x0811fc80`, the start of the 8x8 function and the vector table fall. All of
it has been reconstructed by analogy with the 14 shapes that are complete, and
**confirmed empirically** against the real files.

## What a new converter needs

1. Scale to 240x160 and quantise to BGR555.
2. Per frame, walk 600 8x8 blocks and decide the partition tree (the original
   uses a difference threshold and retries the frame raising it 24 at a time
   until it fits in `FrameSize`, clamped to [0x400, 0x8000]).
3. Emit the bitstream (32 bits per word, MSB first), the colours and, to match
   low quality, motion vectors using the table above. The vectors are optional:
   an encoder that does not use them produces valid files, only larger.
4. A 0x200 header, frames prefixed with a `u16`, and the `.gbs` at 10 video
   fps.

## The new encoder

`gbamedia/src/gbamedia/core/gbm_encode.py`. It follows the semantics deduced
here: a difference tolerance per size band, a leaf accepted if no difference
exceeds it, and a frame retry raising the tolerance until it fits in
`FrameSize`. Three deliberate differences from the original:

1. **The tolerance is measured on the 5 components of BGR555**, not on 8 bits,
   so the retry step is 1 and not 24. A jump of 24 over 32 levels would mean
   going from lossless to anything at all in a single pass.
2. **Vector search is done once per frame**, not once per pass: it does not
   depend on the tolerance except through the set of active blocks, and that
   set only shrinks as the tolerance rises. And vectors are only searched for
   blocks whose direct copy does **not** already fall within tolerance,
   because for the rest the 8x8 node resolves as a copy and never descends.
   The two together brought the test suite down from 168 s to 16 s.
3. **The inert tail on frames 20 to 27 is not emitted.**

The "vector + colour addition" candidate is evaluated **by applying it and
measuring**, with the ROM's packed arithmetic (`(ref + delta) & 0xFFFF`),
rather than reasoning per component. It is the only honest way to handle a
carry that is not clipped.

### Measured over the sync pattern

Same material and same reference for all four, 120 frames:

| | PSNR | Average payload |
|---|---|---|
| `M00004` (original, high) | 28.77 dB | 1693 B |
| **ours, high** | **lossless** | **1011 B** |
| `M00008` (original, standard) | 28.63 dB | 1339 B |
| **ours, standard** | **38.37 dB** | **880 B** |

High quality comes out **mathematically lossless** in BGR555: with zero
tolerance every leaf has to be exact, and the 2-pixel leaf with two colours of
its own always is. And even so it takes 40 % less space than the original.

Speed: 86 ms per frame on high quality and 299 ms on standard, that is about
90 s and 5 min for a 1080-frame video.

### Exact round trip

What guarantees there is no drift is not the PSNR but this: every produced file
is decoded with the reference decoder and checked to reconstruct **exactly**
what the encoder believed it was leaving behind, as well as consuming all three
streams to the last byte. Checked on real material and on pure noise, in all
three presets.

Pure noise is the format's limit case: every pixel pair would ask for two
colours of its own, 76,800 bytes of colour alone, and the size fields are u16.
The size control raises the tolerance until it fits, just as it does with
`FrameSize`.
