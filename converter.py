"""Convert audio files to CCITT G.711 u-law WAV (8 kHz, mono, 8-bit).

Usage:
    python converter.py song.mp3 intro.m4a message.wav
    python converter.py -o converted/ *.mp3
    python converter.py                      # prompts for filenames

Decoding uses macOS's built-in `afconvert`, or `ffmpeg` if it is installed.
The u-law encoding and WAV header are written here so the output is a plain
WAVE_FORMAT_MULAW (0x0007) file that phone systems (Asterisk, Cisco, etc.) accept.
"""

import argparse
import array
import os
import shlex
import shutil
import struct
import subprocess
import sys
import tempfile
import wave
from pathlib import Path

WAVE_FORMAT_MULAW = 0x0007
ULAW_BIAS = 0x84
ULAW_CLIP = 32635

# Apps launched from Finder get a minimal PATH, so also look where Homebrew installs tools.
_TOOL_PATH = os.pathsep.join([os.environ.get("PATH", ""), "/opt/homebrew/bin", "/usr/local/bin", "/usr/bin"])


def _ulaw_encode_sample(sample: int) -> int:
    """Encode one signed 16-bit PCM sample as a G.711 u-law byte."""
    sign = 0x80 if sample < 0 else 0
    if sign:
        sample = -sample
    sample = min(sample, ULAW_CLIP) + ULAW_BIAS
    exponent = (sample >> 7).bit_length() - 1
    mantissa = (sample >> (exponent + 3)) & 0x0F
    return ~(sign | (exponent << 4) | mantissa) & 0xFF


# Lookup table indexed by the unsigned 16-bit representation of each sample.
_ULAW_TABLE = bytes(_ulaw_encode_sample(s - 65536 if s >= 32768 else s) for s in range(65536))


def pcm16_to_ulaw(samples: array.array) -> bytes:
    table = _ULAW_TABLE
    return bytes(table[s & 0xFFFF] for s in samples)


def decode_to_pcm16(path: Path, rate: int) -> array.array:
    """Decode any supported audio file to mono signed 16-bit PCM at `rate` Hz."""
    if ffmpeg := shutil.which("ffmpeg", path=_TOOL_PATH):
        result = subprocess.run(
            [ffmpeg, "-v", "error", "-i", str(path),
             "-ac", "1", "-ar", str(rate), "-f", "s16le", "-acodec", "pcm_s16le", "-"],
            capture_output=True,
        )
        if result.returncode != 0:
            raise RuntimeError(result.stderr.decode(errors="replace").strip() or "ffmpeg failed")
        raw = result.stdout
    elif afconvert := shutil.which("afconvert", path=_TOOL_PATH):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_wav = Path(tmp) / "decoded.wav"
            result = subprocess.run(
                [afconvert, "-f", "WAVE", "-d", f"LEI16@{rate}", "-c", "1", str(path), str(tmp_wav)],
                capture_output=True,
            )
            if result.returncode != 0:
                raise RuntimeError(result.stderr.decode(errors="replace").strip() or "afconvert failed")
            with wave.open(str(tmp_wav), "rb") as w:
                raw = w.readframes(w.getnframes())
    else:
        raise RuntimeError("No decoder found: install ffmpeg (brew install ffmpeg) or run on macOS")

    samples = array.array("h")
    samples.frombytes(raw[: len(raw) - len(raw) % 2])
    if sys.byteorder == "big":
        samples.byteswap()
    return samples


def write_ulaw_wav(path: Path, ulaw: bytes, rate: int) -> None:
    fmt = struct.pack("<HHIIHHH", WAVE_FORMAT_MULAW, 1, rate, rate, 1, 8, 0)
    fact = struct.pack("<I", len(ulaw))
    pad = b"\x00" if len(ulaw) % 2 else b""
    body = (
        b"WAVE"
        + b"fmt " + struct.pack("<I", len(fmt)) + fmt
        + b"fact" + struct.pack("<I", len(fact)) + fact
        + b"data" + struct.pack("<I", len(ulaw)) + ulaw + pad
    )
    path.write_bytes(b"RIFF" + struct.pack("<I", len(body)) + body)


def output_path_for(src: Path, out_dir: Path | None, suffix: str) -> Path:
    return (out_dir or src.parent) / f"{src.stem}{suffix}.wav"


def convert(src: Path, dest: Path, rate: int) -> float:
    """Convert `src` to a u-law WAV at `dest`. Returns the duration in seconds."""
    ulaw = pcm16_to_ulaw(decode_to_pcm16(src, rate))
    dest.parent.mkdir(parents=True, exist_ok=True)
    write_ulaw_wav(dest, ulaw, rate)
    return len(ulaw) / rate


def prompt_for_files() -> list[str]:
    print("Enter audio filenames (drag files into the terminal works too).")
    print("Separate multiple files with spaces; quote names containing spaces. Blank line to finish.")
    files: list[str] = []
    while True:
        try:
            line = input("> ").strip()
        except EOFError:
            break
        if not line:
            break
        files.extend(shlex.split(line))
    return files


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Convert audio files to CCITT G.711 u-law WAV (mono, 8-bit).")
    parser.add_argument("files", nargs="*", help="audio files to convert (mp3, m4a, wav, aiff, ...)")
    parser.add_argument("-o", "--output-dir", type=Path,
                        help="directory for converted files (default: next to each input)")
    parser.add_argument("-r", "--rate", type=int, default=8000,
                        help="sample rate in Hz (default: 8000, the telephony standard)")
    parser.add_argument("-s", "--suffix", default="_ulaw",
                        help="text appended to each output filename (default: _ulaw)")
    parser.add_argument("-f", "--force", action="store_true", help="overwrite existing output files")
    args = parser.parse_args(argv)

    files = args.files or prompt_for_files()
    if not files:
        parser.print_usage()
        return 1

    failures = 0
    for name in files:
        src = Path(name).expanduser()
        dest = output_path_for(src, args.output_dir, args.suffix)
        if not src.is_file():
            print(f"✗ {src}: file not found", file=sys.stderr)
            failures += 1
            continue
        if dest.resolve() == src.resolve():
            print(f"✗ {src}: output would overwrite the input; use --suffix or --output-dir", file=sys.stderr)
            failures += 1
            continue
        if dest.exists() and not args.force:
            print(f"✗ {src}: {dest} already exists (use --force to overwrite)", file=sys.stderr)
            failures += 1
            continue
        try:
            seconds = convert(src, dest, args.rate)
        except Exception as e:
            print(f"✗ {src}: {e}", file=sys.stderr)
            failures += 1
            continue
        print(f"✓ {src} → {dest} ({seconds:.1f}s)")

    converted = len(files) - failures
    print(f"\n{converted} of {len(files)} file(s) converted.")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
