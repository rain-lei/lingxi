"""Cross-check real LXAF frames through the same portable C LCD renderer.

Runs on Windows with gcc and Pillow. Does not access a serial port or TF card.
"""
from __future__ import annotations
import ctypes
from pathlib import Path
import struct
import subprocess
import tempfile
from PIL import Image, ImageDraw
from render_ui_preview import Model, Region


def main():
    root = Path(__file__).resolve().parents[1]
    repo = root.parents[1]
    package = repo / 'public/animations/v1/lingxi-animations-v1.lxaf'
    output = repo / 'tmp/tf-ui-preview'
    output.mkdir(parents=True, exist_ok=True)
    library = Path(tempfile.mkdtemp(prefix='lingxi-tf-render-')) / 'scene.dll'
    sources = ['ui_scene', 'ui_font', 'ui_reply_font', 'ui_mascot', 'ui_kangaroo', 'ui_badge', 'ui_cjk']
    subprocess.run(['gcc', '-std=c11', '-O2', '-Wall', '-Wextra', '-Werror', '-shared',
                    *(str(root / 'main' / (name + '.c')) for name in sources), '-lm', '-o', str(library)], check=True)
    dll = ctypes.CDLL(str(library))
    dll.ui_scene_draw.argtypes = [ctypes.POINTER(ctypes.c_uint16), Region, ctypes.POINTER(Model), ctypes.c_uint32]
    dll.ui_scene_external_frame.argtypes = [ctypes.POINTER(ctypes.c_uint8)]
    pixels = (ctypes.c_uint16 * (320 * 240))()
    full = Region(0, 0, 320, 240)
    m = Model(state=1, wifi_connected=True, service_online=True, network_enabled=True, rounded_font=True)

    def draw(frame=None, region=full):
        borrowed = (ctypes.c_uint8 * len(frame)).from_buffer_copy(frame) if frame else None
        dll.ui_scene_external_frame(borrowed)
        dll.ui_scene_draw(pixels, region, ctypes.byref(m), 1600)
        dll.ui_scene_external_frame(None)
        return bytes(pixels)

    def image(raw):
        values = (ctypes.c_uint16 * (320 * 240)).from_buffer_copy(raw)
        rgb = bytearray()
        for value in values:
            rgb.extend(((value >> 11) * 255 // 31, ((value >> 5) & 63) * 255 // 63, (value & 31) * 255 // 31))
        return Image.frombytes('RGB', (320, 240), bytes(rgb))

    fallback = draw()
    for avatar in (2, 3, 4):
        m.avatar = avatar
        assert draw() == fallback, 'Missing card must retain blue fallback, not select robot as boolean'
    with package.open('rb') as file:
        h = struct.unpack('<4sHHHHHHIIII32s', file.read(64))
        clips = [struct.unpack('<BBHHHIII12s', file.read(32)) for _ in range(h[6])]
        sheet = Image.new('RGB', (320 * 5, 240 * 2), '#eaf0fa')
        for avatar in range(5):
            m.avatar, m.state, m.message = avatar, 1, b''
            clip = next(c for c in clips if c[0] == avatar and c[1] == 0)
            file.seek(clip[5]); first = file.read(49152)
            a = draw(first)
            sheet.paste(image(a), (avatar * 320, 0))
            file.seek(clip[5] + 10 * 49152); later = file.read(49152)
            expected = draw(later)
            draw(first)
            partial = draw(later, Region(0, 50, 144, 126))
            assert partial == expected, 'Local sprite repaint must match the full renderer'
            m.state = 3
            m.message = '今天辛苦了。先从最小的一步开始，我陪你一起完成。'.encode('utf-8')
            clip = next(c for c in clips if c[0] == avatar and c[1] == 3)
            file.seek(clip[5]); first = file.read(49152)
            before = draw(first)
            file.seek(clip[5] + 10 * 49152); later = file.read(49152)
            after = draw(later, Region(0, 0, 320, 60))
            assert before[320 * 60 * 2:] == after[320 * 60 * 2:], 'Speaking animation changed reply text'
            sheet.paste(image(after), (avatar * 320, 240))
    sheet.save(output / 'tf-five-avatars.png')
    print('OK: five real LXAF avatars render; cardless fallback; local repaint equivalence; still 20px reply during speaking')
    print(output / 'tf-five-avatars.png')


if __name__ == '__main__':
    main()
