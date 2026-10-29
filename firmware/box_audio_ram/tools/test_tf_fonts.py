"""Check the real C LCD renderer, font cache and pagination without a board."""
from __future__ import annotations
import ctypes as C
import importlib.util
import json
from pathlib import Path
import struct
import subprocess
import sys
from PIL import Image

ROOT = Path(__file__).resolve().parents[3]
FW = ROOT / "firmware/box_audio_ram"
sys.path.insert(0, str(FW / "tools"))
from render_ui_preview import Model, Region

class Font(C.Structure):
    _fields_=[("tone",C.c_uint8),("pixel_size",C.c_uint8),("line_height",C.c_uint8),("alpha_bits",C.c_uint8)]+[(x,C.c_uint32) for x in ("glyph_count","glyph_offset","glyph_bytes","alpha_offset","alpha_bytes","crc32")]+[("name",C.c_char*33)]
class View(C.Structure):
    _fields_=[("glyphs",C.POINTER(C.c_uint8)),("alpha",C.POINTER(C.c_uint8)),("font",Font)]

def main():
    out=ROOT/"tmp/font-tests-v3";out.mkdir(exist_ok=True)
    dll=out/"font_renderer.dll"
    names=["ui_scene","ui_font","ui_reply_font","ui_mascot","ui_kangaroo","ui_badge","ui_cjk","lxff_format"]
    subprocess.run(["gcc","-std=c11","-O2","-Wall","-Wextra","-Werror","-shared",*[str(FW/"main"/(n+".c")) for n in names],"-o",str(dll),"-lm"],check=True)
    lib=C.CDLL(str(dll));lib.ui_scene_draw.argtypes=[C.POINTER(C.c_uint16),Region,C.POINTER(Model),C.c_uint32]
    lib.ui_scene_reply_pages.argtypes=[C.POINTER(Model)];lib.ui_scene_reply_pages.restype=C.c_uint
    lib.ui_scene_external_font.argtypes=[C.POINTER(View)]
    raw=(ROOT/"public/fonts/v1/lingxi-fonts-v1.lxff").read_bytes()
    data=(C.c_uint8*len(raw)).from_buffer_copy(raw)
    full=Region(0,0,320,240)
    model=Model(state=1,wifi_connected=True,service_online=True,rounded_font=True,message_started_ms=100)
    model.message=("当然可以！我们把任务拆小，先照顾好自己。今天累吗？慢慢说，我听着。"*8+"大连理工大学 · LingXi 2026").encode()
    report={"font_count":4,"rendered":[],"font_advance_contract":True,"outside_canvas_guards":True}
    pages=lib.ui_scene_reply_pages(C.byref(model));assert pages>1
    styles=[];screens=[]
    for i in range(4):
        e=struct.unpack_from("<BBBB6II32s",raw,64+i*64)
        tone,size,height,bits,count,go,gb,ao,ab,crc,res,name=e
        font=Font(tone,size,height,bits,count,go,gb,ao,ab,crc,name.rstrip(b"\0"))
        view=View(C.cast(C.byref(data,go),C.POINTER(C.c_uint8)),C.cast(C.byref(data,ao),C.POINTER(C.c_uint8)),font)
        styles.append([struct.unpack_from("<IIBBBb",raw,go+j*12)[4] for j in range(count)])
        lib.ui_scene_external_font(C.byref(view));assert lib.ui_scene_reply_pages(C.byref(model))==pages
        guard=(C.c_uint16*(320*240+32))(*([0xABCD]*(320*240+32)))
        pixels=C.cast(C.byref(guard,32),C.POINTER(C.c_uint16))
        lib.ui_scene_draw(pixels,full,C.byref(model),100)
        assert list(guard[:16])==[0xABCD]*16 and list(guard[-16:])==[0xABCD]*16
        rgb=bytearray()
        for value in guard[16:-16]:rgb.extend(((value>>11)*255//31,((value>>5)&63)*255//63,(value&31)*255//31))
        image=Image.frombytes("RGB",(320,240),bytes(rgb));image.save(out/f"tone-{i}.png");screens.append(image)
        # Every scheduled page change must match full rendering of that page.
        for page in range(1,pages):
            stamp=100+page*7000
            lib.ui_scene_draw(pixels,Region(0,60,320,180),C.byref(model),stamp)
            expected=(C.c_uint16*(320*240))()
            lib.ui_scene_draw(expected,full,C.byref(model),stamp)
            assert list(pixels[60*320:240*320])==list(expected[60*320:240*320])
        report["rendered"].append({"tone":tone,"name":name.rstrip(b"\0").decode(),"pages":pages,"cache_bytes":gb+ab})
    assert all(a==styles[0] for a in styles)
    # Clearing the external cache must retain a readable no-card fallback.
    lib.ui_scene_external_font(None)
    guard=(C.c_uint16*(320*240))();lib.ui_scene_draw(guard,full,C.byref(model),100)
    # Two-bit native alpha intentionally has only four foreground coverages.
    assert len(set(guard[68*320:180*320]))>=4
    assert sum(1 for p in guard[68*320:180*320] if p<0x8000)>500
    # Fast pet-only branches preserve every pixel of their full-screen render.
    for reply, area in [(False,Region(0,48,144,130)),(True,Region(0,0,70,54))]:
        model.message=b"Hello" if reply else b""
        partial=(C.c_uint16*(320*240))();expected=(C.c_uint16*(320*240))()
        lib.ui_scene_draw(partial,full,C.byref(model),100)
        lib.ui_scene_draw(partial,area,C.byref(model),1600)
        lib.ui_scene_draw(expected,full,C.byref(model),1600)
        for row in range(area.y,area.y+area.h):
            begin=row*320+area.x
            assert list(partial[begin:begin+area.w])==list(expected[begin:begin+area.w])
    sheet=Image.new("RGB",(640,480))
    for i,image in enumerate(screens):sheet.paste(image,((i%2)*320,(i//2)*240))
    sheet.save(out/"four-tone-lcd.png")
    (out/"report.json").write_text(json.dumps(report,indent=2),encoding="utf-8")
    print("PASS: 4 real C LCD font renders, stable pagination, every page partial/full equality, canvas sentinels, no-card fallback")

if __name__=="__main__":main()
