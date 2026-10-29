"""Build four native 20 px OFL font caches and independently named web subsets.

Uses source outlines, never enlarges a low resolution bitmap. The embedded
fallback's advances are the stable layout contract for all four TF styles.
Run with Pillow + fontTools[woff] available (local tmp/font-tools is supported).
"""
from __future__ import annotations
import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import re
import struct
import sys
import zipfile
import zlib

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tmp/font-tools"))
from PIL import Image, ImageDraw, ImageFont
from fontTools.ttLib import TTFont
from fontTools import subset

FW = ROOT / "firmware/box_audio_ram"
ASSETS = FW / "assets"
OUT = ROOT / "public/fonts/v1"
STYLE = [
    ("warm", "柔和圆体", "LingXi Soft", ASSETS / "fonts/ResourceHanRoundedCN-Medium.ttf", None,
     "Resource Han Rounded CN Medium", "https://github.com/CyanoHao/Resource-Han-Rounded", ASSETS / "ResourceHanRounded-OFL.txt"),
    ("calm", "平静宋体", "LingXi Quiet", ASSETS / "fonts-v3/NotoSerifSC-VF.ttf", 600,
     "Noto Serif SC", "https://github.com/google/fonts/tree/main/ofl/notoserifsc", ASSETS / "fonts-v3/NotoSerifSC-OFL.txt"),
    ("cheerful", "灵动手写", "LingXi Hand", ASSETS / "fonts-v3/LXGWWenKai-Regular.ttf", None,
     "LXGW WenKai Regular", "https://github.com/lxgw/LxgwWenKai", ASSETS / "fonts-v3/LXGWWenKai-OFL.txt"),
    ("direct", "清晰黑体", "LingXi Clear", ASSETS / "fonts-v3/NotoSansSC-VF.ttf", 600,
     "Noto Sans SC", "https://github.com/google/fonts/tree/main/ofl/notosanssc", ASSETS / "NotoSansSC-OFL.txt"),
]
spec = importlib.util.spec_from_file_location("native_font", FW / "tools/generate_ui_reply_font.py")
native = importlib.util.module_from_spec(spec)
spec.loader.exec_module(native)

def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()

def source_font(path, weight):
    f = ImageFont.truetype(str(path), 20)
    if weight:
        axes = f.get_variation_axes()
        f.set_variation_by_axes([weight if a["name"].lower() == b"weight" else a["default"] for a in axes])
    return f

def web_subset(path: Path, family: str, codes: list[int], target: Path):
    font = TTFont(path)
    options = subset.Options()
    options.flavor = "woff2"
    options.name_IDs = [0, 1, 2, 3, 4, 5, 6, 13, 14, 16, 17]
    worker = subset.Subsetter(options=options)
    worker.populate(unicodes=codes)
    worker.subset(font)
    # Derived subsets use independent names; copyright/license credits remain.
    for rec in font["name"].names:
        if rec.nameID in (1, 3, 4, 6, 16):
            rec.string = (family.replace(" ", "") if rec.nameID == 6 else family).encode(rec.getEncoding())
        elif rec.nameID in (2, 17):
            rec.string = "Regular".encode(rec.getEncoding())
    font.flavor = "woff2"
    font.save(target)
    font.close()

def build(skip_web=False):
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "licenses").mkdir(exist_ok=True)
    text = (FW / "main/ui_reply_font.c").read_text(encoding="utf-8")
    matches = re.findall(r"\{0x([0-9a-f]+), (\d+), (\d+), (\d+), (\d+), (-?\d+)\}", text)
    advances = {int(m[0], 16): int(m[4]) for m in matches}
    codes = native.character_codes()
    assert set(codes) == set(advances), "Layout contract has changed; update fallback and pack together"
    han = native.gb2312_han_codes()
    assert len(han) == 6763
    fallback_path = ASSETS / "fonts-v3/NotoSansSC-VF.ttf"
    fallback = source_font(fallback_path, 600)
    fallback_map = TTFont(fallback_path).getBestCmap()
    payloads, entries, metadata, preview_fonts = [], [], [], []
    offset = 64 + 4 * 64
    sources = ["# LingXi TF font sources", "", "All source fonts are under SIL OFL 1.1. Source outlines remain unchanged;", "native bitmaps and web subsets use independent LingXi family names.", "", "TF raster: 20 px / 26 px line box / 2-bit antialiasing / 7029 code points.", "All 6763 GB2312 Han characters are verified in every source cmap.", "Rare punctuation absent in a style uses the Noto Sans source glyph, recorded below.", ""]
    for ident, (tone, label, family, path, weight, credit, url, license_path) in enumerate(STYLE):
        src = source_font(path, weight)
        source_metadata = TTFont(path)
        cmap = source_metadata.getBestCmap()
        copyright_notice = source_metadata["name"].getDebugName(0) or ""
        version = source_metadata["name"].getDebugName(5) or ""
        missing_han = sorted(han - set(cmap))
        assert not missing_han, f"{credit} lacks GB2312 Han: {missing_han}"
        glyphs, alpha, missing = bytearray(), bytearray(), []
        preview_fonts.append(src)
        for code in codes:
            selected = src
            if code not in cmap:
                assert code in fallback_map, f"No source glyph U+{code:04X}"
                selected = fallback
                missing.append(f"U+{code:04X}")
            box = selected.getbbox(chr(code), anchor="ls")
            bearing, width = box[0], max(1, box[2]-box[0])
            assert width <= 32 and -8 <= bearing <= 8
            raster, unused = native.glyph_raster(selected, code, (width, advances[code], bearing))
            glyphs.extend(struct.pack("<IIBBBb", code, len(alpha), width, 26, advances[code], bearing))
            alpha.extend(native.pack_alpha(raster))
        cache = bytes(glyphs + alpha)
        assert len(cache) <= 1200*1024
        crc = zlib.crc32(cache)
        entry = struct.pack("<BBBB6II32s", ident, 20, 26, 2, len(codes), offset, len(glyphs),
                            offset+len(glyphs), len(alpha), crc, 0, family.encode().ljust(32,b"\0"))
        assert len(entry) == 64
        entries.append(entry)
        payloads.append(cache)
        offset += len(cache)
        license_name = tone + "-OFL.txt"
        (OUT / "licenses" / license_name).write_text(
            copyright_notice+"\n\n"+license_path.read_text(encoding="utf-8"),encoding="utf-8")
        webpath = OUT / (tone + ".woff2")
        if not skip_web:
            web_subset(path, family, codes, webpath)
        meta = dict(id=tone, tone=tone, label=label, family=family, source_family=credit,
                    source=url, license="OFL-1.1", license_path=f"/fonts/v1/licenses/{license_name}",
                    copyright=copyright_notice, source_version=version,
                    source_sha256=digest(path.read_bytes()), glyph_count=len(codes), han_count=6763,
                    pixel_size=20, line_height=26, alpha_bits=2, cache_bytes=len(cache),
                    bitmap_sha256=digest(cache), fallback_punctuation=missing,
                    web_path=f"/fonts/v1/{tone}.woff2", web_bytes=webpath.stat().st_size if webpath.exists() else 0)
        metadata.append(meta)
        sources.extend([f"## {label} / {family}", f"- Upstream: [{credit}]({url})", f"- Source version: {version}", f"- Copyright: {copyright_notice}", f"- Source SHA-256: `{meta['source_sha256']}`", f"- License: `licenses/{license_name}` (OFL 1.1)", f"- Glyphs: {len(codes)}; fallback punctuation: {', '.join(missing) or 'none'}", ""])
        print(f"{tone}: {len(codes)} glyphs, {len(cache)} cache bytes", flush=True)
    body = b"".join(entries + payloads)
    raw = struct.pack("<4sHHIHHII8s32s", b"LXFF",1,64,64+len(body),4,12,64,0,b"\0"*8,hashlib.sha256(body).digest())+body
    (OUT / "lingxi-fonts-v1.lxff").write_bytes(raw)
    (OUT / "SHA256SUMS.txt").write_text(digest(raw)+"  lingxi-fonts-v1.lxff\n",encoding="ascii")
    (OUT / "SOURCES.md").write_text("\n".join(sources), encoding="utf-8")
    guide = "灵犀 TF 字体包\n\n将 lingxi-fonts-v1.lxff 复制到 TF 卡 /lingxi/fonts-v1.lxff。\n也可在板子配置页点击“安装语气字体”，由电脑服务下载，不必重装动画。\n需配套 20261023 或更新固件；仅复制文件到旧固件不会改变字体。\nwarm=柔和圆体，calm=平静宋体，cheerful=灵动手写，direct=清晰黑体。\n每次仅缓存当前语气到 PSRAM，屏幕渲染和录音期间不读取卡。\n无卡保留嵌入的 Noto Sans 20px 清晰后备字体。\n\n完整来源、版权与 OFL 许可证见 SOURCES.md / licenses/。\n"
    (OUT / "INSTALL.txt").write_text(guide, encoding="utf-8")
    write_preview(raw, metadata)
    archive = OUT / "lingxi-tf-fonts-v1.zip"
    with zipfile.ZipFile(archive,"w",zipfile.ZIP_DEFLATED,compresslevel=7) as z:
        for name in ["lingxi-fonts-v1.lxff", "SOURCES.md", "INSTALL.txt", "font-styles.png", "SHA256SUMS.txt"]:
            z.write(OUT/name, name)
        for f in sorted((OUT/"licenses").glob("*.txt")):
            z.write(f, "licenses/"+f.name)
    manifest = dict(schema_version=1, pack_id="lingxi-tf-fonts-v1", format_version=1,
                    fonts=metadata, card_path="/lingxi/fonts-v1.lxff", hardware_verified=False,
                    download=dict(path="/fonts/v1/lingxi-fonts-v1.lxff", filename="fonts-v1.lxff",bytes=len(raw),sha256=digest(raw)),
                    archive=dict(path="/fonts/v1/lingxi-tf-fonts-v1.zip",bytes=archive.stat().st_size,sha256=digest(archive.read_bytes())),
                    preview="/fonts/v1/font-styles.png")
    (OUT/"manifest.json").write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding="utf-8")
    (OUT/"install.json").write_text(json.dumps(dict(schema_version=1,download=manifest["download"])),encoding="utf-8")
    print(json.dumps({"bytes":len(raw),"sha256":digest(raw),"zip_bytes":archive.stat().st_size}),flush=True)

def write_preview(raw, metadata):
    # Decode the exact packed TF bytes to inspect the real 2-bit LCD glyphs.
    p = Image.new("RGB",(640,460),"#f3f7fc")
    d = ImageDraw.Draw(p)
    title = ImageFont.truetype(str(ASSETS/"fonts-v3/NotoSansSC-VF.ttf"),20)
    lines = ["你好呀，我是蓝蓝，很高兴遇见你！", "今天有点累吗？慢慢说，我听着。", "大连理工大学 · LingXi 2026"]
    for i, meta in enumerate(metadata):
        e=struct.unpack_from("<BBBB6II32s",raw,64+i*64)
        count,go,gb,ao,ab=e[4:9]
        lookup={struct.unpack_from("<IIBBBb",raw,go+j*12)[0]:struct.unpack_from("<IIBBBb",raw,go+j*12)[1:] for j in range(count)}
        d.text((18,9+i*112),meta["label"]+"  "+meta["family"],font=title,fill="#29638a")
        for k,line in enumerate(lines):
            x,y=22,38+i*112+k*24
            for c in line:
                off,w,h,adv,bx=lookup[ord(c)]
                mask=Image.new("L",(w,h))
                mask.putdata([((raw[ao+off+n//4]>>(6-(n%4)*2))&3)*85 for n in range(w*h)])
                p.paste("#142239",(x+bx,y),mask);x+=adv
    p.save(OUT/"font-styles.png")

if __name__ == "__main__":
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--skip-web",action="store_true")
    args=ap.parse_args();build(args.skip_web)
