"""Pack an actual-alpha 3-column, 2-row mascot sheet into flash sprite arrays.

python pack_mascot.py --source ../assets/mascot-source.png

Rows are idle / blink / listening, then thinking / happy / concern. Every pose
uses one common crop, scale and destination origin; no pose is independently
trimmed or stretched. Encoding zeros faint alpha at or below --alpha-zero;
the original PNG is read only. Pillow is required.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path
from collections import Counter, deque

from PIL import Image, ImageChops, ImageFilter


POSES = ("idle", "blink", "listening", "thinking", "happy", "concern")
WIDTH = HEIGHT = 128
PAD = 4
ALPHA_THRESHOLD = 32


def alpha_summary(cell: Image.Image, threshold: int) -> dict:
    values = list(cell.getchannel("A").getdata())
    count = len(values)
    occupied = sum(a >= threshold for a in values)
    return {
        "minimum": min(values), "maximum": max(values),
        "transparent_fraction": sum(a < threshold for a in values) / count,
        "occupied_fraction": occupied / count,
        "partial_fraction": sum(0 < a < 255 for a in values) / count,
    }


def suspicious_checkerboard(cell: Image.Image) -> bool:
    """Reject opaque gray checkerboard backgrounds even with a clear outer edge.

    A transparent sheet should have transparent space around each blue pose.
    Two dominant opaque neutral tones covering most of its outer band indicate
    a baked checkerboard. This deliberately conservative check does not remove
    or invent transparency; the source must be regenerated if it fails.
    """
    w, h = cell.size
    band = max(2, min(w, h) // 10)
    neutral = Counter()
    sampled = 0
    for y in range(0, h, max(1, h // 120)):
        for x in range(0, w, max(1, w // 120)):
            if band <= x < w - band and band <= y < h - band:
                continue
            sampled += 1
            r, g, b, a = cell.getpixel((x, y))
            if a >= 240 and max(r, g, b) - min(r, g, b) <= 10:
                brightness = (r + g + b) // 3
                if 48 <= brightness <= 248:
                    neutral[brightness // 16] += 1
    peaks = neutral.most_common(2)
    return (len(peaks) == 2 and sampled > 0
            and sum(neutral.values()) / sampled > 0.55
            and sum(value for _, value in peaks) / sum(neutral.values()) > 0.80
            and abs(peaks[0][0] - peaks[1][0]) >= 1
            and min(value for _, value in peaks) / sum(neutral.values()) > 0.15)


def largest_component(cell: Image.Image, threshold: int) -> tuple[Image.Image, dict]:
    """Extract the cell's main connected frame, preserving 2 px of soft fur.

    Only the packed frame's alpha changes; color pixels and the source atlas
    are retained. Eight-connected labelling removes detached neighboring pose
    fragments without independently moving or resizing the retained character.
    """
    w, h = cell.size
    remaining = bytearray(cell.getchannel("A").point(
        lambda alpha: 255 if alpha >= threshold else 0).tobytes())
    best, component_sizes = [], []
    for start in range(w * h):
        if not remaining[start]:
            continue
        remaining[start] = 0
        pending = deque([start])
        component = []
        while pending:
            index = pending.popleft()
            component.append(index)
            x, y = index % w, index // w
            for yy in range(max(0, y - 1), min(h, y + 2)):
                row = yy * w
                for xx in range(max(0, x - 1), min(w, x + 2)):
                    neighbor = row + xx
                    if remaining[neighbor]:
                        remaining[neighbor] = 0
                        pending.append(neighbor)
        component_sizes.append(len(component))
        if len(component) > len(best):
            best = component
    if not best:
        raise ValueError("Cannot extract a main component from an empty cell.")
    keep = bytearray(w * h)
    for index in best:
        keep[index] = 255
    keep_mask = Image.frombytes("L", (w, h), bytes(keep)).filter(ImageFilter.MaxFilter(5))
    isolated = cell.copy()
    isolated.putalpha(ImageChops.multiply(cell.getchannel("A"), keep_mask))
    return isolated, {
        "connectivity": 8, "threshold": threshold, "dilation_pixels": 2,
        "component_count": len(component_sizes), "kept_pixels_at_threshold": len(best),
        "removed_pixels_at_threshold": sum(component_sizes) - len(best),
        "largest_component_sizes": sorted(component_sizes, reverse=True)[:8],
    }


def array_lines(name: str, ctype: str, poses: list[list[int]], digits: int, macro: str):
    yield f"const {ctype} {name}[{macro}_POSES][{macro}_WIDTH * {macro}_HEIGHT] = {{"
    for label, values in zip(POSES, poses):
        yield f"    {{ /* {label} */"
        for offset in range(0, len(values), 16):
            yield "        " + ",".join(f"0x{value:0{digits}x}" for value in values[offset:offset + 16]) + ","
        yield "    },"
    yield "};"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--prefix", default="ui_mascot",
                        help="C array/header prefix (default ui_mascot)")
    parser.add_argument("--output", type=Path,
                        help="C output; default is main/<prefix>.c")
    parser.add_argument("--report", type=Path,
                        help="JSON provenance report; default assets/mascot-pack-report.json")
    parser.add_argument("--keep-cell-frame", action="store_true",
                        help="Keep complete cell frames instead of a common union crop")
    parser.add_argument("--largest-component", action="store_true",
                        help="Extract each main 8-connected alpha component, retaining 2 px antialias margin")
    parser.add_argument("--alpha-threshold", type=int, default=ALPHA_THRESHOLD,
                        help="Alpha threshold for the common visible bounds (default 32)")
    parser.add_argument("--alpha-zero", type=int, default=8,
                        help="Encode faint background alpha at or below this value as zero (default 8)")
    args = parser.parse_args()
    if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", args.prefix):
        raise SystemExit("Prefix must be a valid C identifier.")
    if not 1 <= args.alpha_threshold <= 255 or not 0 <= args.alpha_zero < args.alpha_threshold:
        raise SystemExit("Require 0 <= alpha-zero < alpha-threshold <= 255.")
    root = Path(__file__).resolve().parents[1]
    source = args.source.resolve()
    output = (args.output or root / "main" / f"{args.prefix}.c").resolve()
    report_path = (args.report or root / "assets/mascot-pack-report.json").resolve()
    if source in (output, report_path) or output == report_path:
        raise SystemExit("Source, C output and report paths must be different.")
    with Image.open(source) as opened:
        if opened.format != "PNG":
            raise SystemExit("Use a PNG source with an actual alpha channel.")
        original_mode = opened.mode
        if "A" not in opened.getbands() and "transparency" not in opened.info:
            raise SystemExit("The source has no actual alpha channel; a drawn checkerboard is not transparency.")
        sheet = opened.convert("RGBA")
    w, h = sheet.size
    if w < 96 or h < 64:
        raise SystemExit("The 3 x 2 source must provide cells at least 32 x 32 pixels.")
    # Integer boundaries retain every pixel even when dimensions do not divide
    # evenly. Differing cell sizes are padded on their right/bottom only.
    xs, ys = [i * w // 3 for i in range(4)], [i * h // 2 for i in range(3)]
    cell_w = max(xs[i + 1] - xs[i] for i in range(3))
    cell_h = max(ys[i + 1] - ys[i] for i in range(2))
    cells, records, boxes = [], [], []
    for i, label in enumerate(POSES):
        column, row = i % 3, i // 3
        bounds = (xs[column], ys[row], xs[column + 1], ys[row + 1])
        raw = sheet.crop(bounds)
        stats = alpha_summary(raw, args.alpha_threshold)
        if stats["transparent_fraction"] < 0.01:
            raise SystemExit(f"{label}: cell is opaque or has too little actual transparent background.")
        if stats["occupied_fraction"] < 0.02:
            raise SystemExit(f"{label}: cell is empty or its visible character is too small.")
        if suspicious_checkerboard(raw):
            raise SystemExit(f"{label}: suspicious opaque gray checkerboard background; use real transparency.")
        extraction = None
        if args.largest_component:
            raw, extraction = largest_component(raw, args.alpha_threshold)
        cell = Image.new("RGBA", (cell_w, cell_h))
        cell.paste(raw, (0, 0))
        mask = cell.getchannel("A").point(lambda a: 255 if a >= args.alpha_threshold else 0)
        bbox = mask.getbbox()
        if bbox is None:
            raise SystemExit(f"{label}: no visible art.")
        cells.append(cell)
        boxes.append(bbox)
        records.append({"pose": label, "source_bounds": bounds,
                        "visible_bounds_in_cell": bbox, "source_alpha": stats,
                        "alpha": alpha_summary(raw, args.alpha_threshold),
                        "component_extraction": extraction})
    union = (min(b[0] for b in boxes), min(b[1] for b in boxes),
             max(b[2] for b in boxes), max(b[3] for b in boxes))
    framing = (0, 0, cell_w, cell_h) if args.keep_cell_frame else union
    # Retain a one-source-pixel antialias margin around the thresholded union.
    if not args.keep_cell_frame:
        framing = (max(0, framing[0] - 1), max(0, framing[1] - 1),
                   min(cell_w, framing[2] + 1), min(cell_h, framing[3] + 1))
    crop_w, crop_h = framing[2] - framing[0], framing[3] - framing[1]
    scale = min((WIDTH - PAD * 2) / crop_w, (HEIGHT - PAD * 2) / crop_h)
    target_size = (max(1, min(WIDTH - PAD * 2, round(crop_w * scale))),
                   max(1, min(HEIGHT - PAD * 2, round(crop_h * scale))))
    # Common bottom anchor preserves a single baseline and all relative framing.
    origin = ((WIDTH - target_size[0]) // 2, HEIGHT - PAD - target_size[1])
    rgb_poses, alpha_poses = [], []
    for cell in cells:
        # Pillow's RGBA resize uses premultiplied filtering internally, avoiding
        # dark/colored fringes while retaining straight alpha in the result.
        tile = cell.crop(framing).resize(target_size, Image.Resampling.LANCZOS)
        sprite = Image.new("RGBA", (WIDTH, HEIGHT))
        sprite.paste(tile, origin)
        colors, alpha = [], []
        for r, g, b, a in sprite.getdata():
            if a <= args.alpha_zero:
                a = 0
            colors.append(((r >> 3) << 11) | ((g >> 2) << 5) | (b >> 3) if a else 0)
            alpha.append(a)
        rgb_poses.append(colors)
        alpha_poses.append(alpha)
    lines = ["/* Generated by tools/pack_mascot.py; preserve the source art and provenance report. */",
             f'#include "{args.prefix}.h"', ""]
    macro = args.prefix.upper()
    lines.extend(array_lines(f"{args.prefix}_rgb565", "uint16_t", rgb_poses, 4, macro))
    lines.append("")
    lines.extend(array_lines(f"{args.prefix}_alpha", "uint8_t", alpha_poses, 2, macro))
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text("\n".join(lines) + "\n", encoding="utf-8")
    report = {
        "source": str(source), "source_sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
        "source_mode": original_mode, "source_size": [w, h],
        "grid": {"columns": 3, "rows": 2, "x_boundaries": xs, "y_boundaries": ys},
        "poses": records, "alpha_threshold_for_bounds": args.alpha_threshold,
        "largest_component_extraction": args.largest_component,
        "alpha_at_or_below_encoded_as_zero": args.alpha_zero,
        "common_visible_union": union, "common_crop_bounds": framing,
        "normalized_cell_size": [cell_w, cell_h], "keep_cell_frame": args.keep_cell_frame,
        "output_size": [WIDTH, HEIGHT], "padding": PAD,
        "common_scale": scale, "scaled_art_size": target_size, "common_origin": origin,
        "effective_scale_xy": [target_size[0] / crop_w, target_size[1] / crop_h],
        "common_baseline_y": HEIGHT - PAD,
        "encoding": {"color": "RGB565", "alpha": "straight alpha8",
                     "pose_count": len(POSES), "raw_flash_bytes": len(POSES) * WIDTH * HEIGHT * 3},
        "c_output": str(output),
        "c_prefix": args.prefix,
        "source_file_modified": False,
    }
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"Packed {len(POSES)} poses, {len(POSES) * WIDTH * HEIGHT * 3:,} flash bytes: {output}")
    print(f"Common crop {framing}, target {target_size}, origin {origin}; report: {report_path}")


if __name__ == "__main__":
    main()
