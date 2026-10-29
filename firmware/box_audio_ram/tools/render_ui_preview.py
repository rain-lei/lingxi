"""Render the actual embedded C interface on Windows, without a connected board.

Requires a host gcc on PATH and Pillow. No ESP-IDF or full font is required.
"""
from __future__ import annotations
import argparse
import ctypes
from pathlib import Path
import subprocess
import tempfile
from PIL import Image, ImageDraw, ImageFont


class Region(ctypes.Structure):
    _fields_ = [(key, ctypes.c_int) for key in ('x', 'y', 'w', 'h')]


class Model(ctypes.Structure):
    _fields_ = [('state', ctypes.c_int), ('wifi_connected', ctypes.c_bool),
               ('service_online', ctypes.c_bool), ('network_enabled', ctypes.c_bool),
               ('microphone_silent', ctypes.c_bool), ('elapsed_ms', ctypes.c_uint32),
               ('duration_ms', ctypes.c_uint32), ('levels', ctypes.c_uint8 * 18),
               ('address', ctypes.c_char * 40), ('detail', ctypes.c_char * 40),
               ('error', ctypes.c_char * 40), ('avatar', ctypes.c_uint8),
               ('provisioning', ctypes.c_bool), ('message', ctypes.c_char * 2048),
               ('message_started_ms', ctypes.c_uint32), ('rounded_font', ctypes.c_bool)]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    out = args.output or root / 'preview/v3'
    out.mkdir(parents=True, exist_ok=True)
    temp = Path(tempfile.mkdtemp(prefix='lingxi-ui-preview-'))
    library = temp / 'ui_preview.dll'
    subprocess.run(['gcc', '-std=c11', '-O2', '-Wall', '-Wextra', '-Werror', '-shared',
                    str(root / 'main/ui_scene.c'), str(root / 'main/ui_font.c'), str(root / 'main/ui_mascot.c'),
                    str(root / 'main/ui_kangaroo.c'), str(root / 'main/ui_badge.c'), str(root / 'main/ui_cjk.c'),
                    str(root / 'main/ui_reply_font.c'),
                    str(root / 'main/lxff_format.c'),
                    '-o', str(library), '-lm'], check=True)
    renderer = ctypes.CDLL(str(library))
    renderer.ui_scene_draw.argtypes = [ctypes.POINTER(ctypes.c_uint16), Region,
                                       ctypes.POINTER(Model), ctypes.c_uint32]
    pixels = (ctypes.c_uint16 * (320 * 240))()

    def render(model, ms):
        renderer.ui_scene_draw(pixels, Region(0, 0, 320, 240), ctypes.byref(model), ms)
        data = bytearray()
        for value in pixels:
            data.extend(((value >> 11) * 255 // 31, ((value >> 5) & 63) * 255 // 63,
                         (value & 31) * 255 // 31))
        return Image.frombytes('RGB', (320, 240), bytes(data))

    model = Model(state=1, wifi_connected=True, service_online=True, network_enabled=True,
                  address=b'WiFi: 10.78.247.82', detail=b'API: OK / 0.4-draft', rounded_font=True)
    base = render(model, 1600)
    base.save(out / 'idle.png')
    states = [('01  /  JUST HERE', 1), ('02  /  LISTENING', 2), ('03  /  COMPANION', 3)]
    sheet = Image.new('RGB', (1088, 340), '#e1e8f6')
    draw = ImageDraw.Draw(sheet)
    label = ImageFont.truetype('C:/Windows/Fonts/segoeui.ttf', 13)
    for i, (caption, state) in enumerate(states):
        model.state, model.elapsed_ms, model.duration_ms = state, 2300, 10000 if state == 2 else 3600
        model.message = '今天辛苦啦。想说什么都可以，我在这里认真听。'.encode('utf-8') if state == 3 else b''
        model.levels[:] = [8, 25, 43, 19, 90, 135, 70, 200, 148, 210, 160, 98, 120, 56, 72, 32, 90, 45]
        tile = render(model, 1600)
        tile.save(out / f'{state}.png')
        x = 24 + i * 360
        draw.rounded_rectangle((x - 5, 36, x + 325, 286), radius=18, fill='#303d48')
        mask = Image.new('L', (320, 240))
        ImageDraw.Draw(mask).rounded_rectangle((0, 0, 319, 239), radius=12, fill=255)
        sheet.paste(tile, (x, 41), mask)
        draw.text((x, 302), caption, fill='#586168', font=label)
    sheet.save(out / 'xiaoxi-states.png')
    # Actual RGB565 firmware rendering of a normal reply and both long-text pages.
    model.state = 3
    model.message_started_ms = 1600
    model.message = '当然可以！我们先把任务拆小，选最重要的一步。你愿意先告诉我，今天最让你头疼的是什么吗？'.encode('utf-8')
    render(model, 1600).save(out / 'reply-readable.png')
    render(model, 1600).resize((960, 720), Image.Resampling.NEAREST).save(out / 'reply-readable-3x.png')
    rounded = render(model, 1600)
    model.rounded_font = False
    noto = render(model, 1600)
    noto.save(out / 'reply-noto.png')
    compare = Image.new('RGB', (700, 290), '#e1e8f6')
    compare.paste(rounded, (20, 14))
    compare.paste(noto, (360, 14))
    compare_draw = ImageDraw.Draw(compare)
    compare_draw.text((20, 264), 'WARM / CHEERFUL  -  ROUNDED', font=label, fill='#26364c')
    compare_draw.text((360, 264), 'CALM / DIRECT  -  NOTO', font=label, fill='#26364c')
    compare.save(out / 'reply-font-styles.png')
    model.rounded_font = True
    model.state = 1
    model.message = '当然记得你喜欢蓝色。今天先照顾好自己，我们把任务拆成小步，一次只做一件。做完以后给自己一点奖励，好不好？如果还想继续聊，我也在这里。'.encode('utf-8')
    render(model, 1600).save(out / 'reply-page-1.png')
    render(model, 8600).save(out / 'reply-page-2.png')
    # The scheduled text-only page paint must match the corresponding full render.
    render(model, 1600)
    renderer.ui_scene_draw(pixels, Region(0, 60, 320, 180), ctypes.byref(model), 8600)
    renderer.ui_scene_draw(pixels, Region(0, 0, 320, 60), ctypes.byref(model), 8600)
    partial_reply = bytes(pixels)
    render(model, 8600)
    assert partial_reply == bytes(pixels), 'Paged reply repaint must equal a full render'
    model.message_started_ms = 0
    for ms in (300, 1600, 5800, 5900, 6000, 6400):
        render(model, 0)
        renderer.ui_scene_draw(pixels, Region(0, 0, 320, 60), ctypes.byref(model), ms)
        partial_header = bytes(pixels)
        render(model, ms)
        assert partial_header == bytes(pixels), 'Resting pet header must not alter reply text'
    model.state, model.elapsed_ms, model.duration_ms = 1, 0, 0
    model.message = b''
    frames = [render(model, ms).resize((640, 480), Image.Resampling.NEAREST)
              for ms in range(0, 5400, 150)]
    frames[0].save(out / 'xiaoxi-idle.gif', save_all=True, append_images=frames[1:],
                   duration=150, loop=0, optimize=False, disposal=2)
    # Compare an actual partial paint to a full frame: no stale pixels or DMA crop mistakes.
    render(model, 0)
    renderer.ui_scene_draw(pixels, Region(0, 50, 144, 126), ctypes.byref(model), 1600)
    partial = bytes(pixels)
    render(model, 1600)
    assert partial == bytes(pixels), 'Partial idle animation must equal a full render'
    model.state = 2
    render(model, 1600)
    model.elapsed_ms = 3100
    model.levels[17] = 220
    renderer.ui_scene_draw(pixels, Region(16, 183, 288, 32), ctypes.byref(model), 1600)
    partial = bytes(pixels)
    render(model, 1600)
    assert partial == bytes(pixels), 'Meter strip must equal a full render'
    print(f'Preview: {out / "xiaoxi-states.png"}')
    print('Partial animation and PCM meter repaint comparisons passed.')


if __name__ == '__main__':
    main()
