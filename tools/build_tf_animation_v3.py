"""Build LXAF v2 lossless RLE3 / 20fps card animation and additional HD poses.

Immutable artist poses are sampled by the local-joint texture rig for all
characters and states. No card or serial access.
"""
from __future__ import annotations
import argparse
import ctypes
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import shutil
import struct
import subprocess
import tempfile
import zipfile
import zlib

import numpy as np
from PIL import Image
import build_tf_animation_v2 as old

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'public/animations/v3'
CACHE = ROOT / 'tmp/tf-v3-clips'
STATES = ('idle','listening','thinking','speaking','comfort','celebrate','greeting','focus','sleepy','stretch')
LABELS = ('自然待机','认真倾听','想一想','开口回应','温柔安慰','完成庆祝','挥手欢迎','陪你专注','轻轻困倦','伸个懒腰')
DURATIONS = (3000,2400,3000,2400,3000,2400,2400,3000,3000,2400)
WEB_MS = 50
BOARD_MS = 50
LOOP = (True,True,True,True,True,False,False,True,True,False)
EXTRA = ROOT / 'firmware/box_audio_ram/assets/tf-v3/kangaroo-extra-source.png'
FW = ROOT / 'firmware/box_audio_ram'
BADGE_REVISION = 'badge-center-r2'
MOTION_REVISION = 'all-characters-r4'
# Source-cell chest anchors, before crop/scale. Poses 2/4/5 supply listening,
# speaking+celebration and comfort respectively; these are not state indices.
BLUE_BADGE_CENTERS = ((276,370),(245,370),(233,370),(273,365),(244,350),(240,307))
EXTRA_BADGE_CENTERS = ((316,425),(302,425),(386,350),(268,390))


def sha(p): return hashlib.sha256(p.read_bytes()).hexdigest()


def write_web_asset(frames, path, loop):
    """Keep stationary holds without adding fake motion to defeat PNG merging."""
    frames[0].save(path, format='PNG', save_all=True, append_images=frames[1:],
                   duration=WEB_MS, loop=0 if loop else 1, disposal=0, blend=0,
                   optimize=False, compress_level=6)
    expected = 0
    with Image.open(path) as decoded:
        count = decoded.n_frames
        if decoded.size != (512, 512):
            raise ValueError('APNG canvas size mismatch')
        for index in range(count):
            decoded.seek(index)
            # Pillow stores a completely stationary clip as a plain PNG.
            # Its one frame represents the full authored hold duration.
            duration = float(decoded.info.get('duration', len(frames) * WEB_MS if count == 1 else 0))
            repeats = round(duration / WEB_MS)
            if repeats < 1 or abs(duration - repeats * WEB_MS) > .01:
                raise ValueError('APNG hold duration mismatch')
            pixels = decoded.convert('RGBA').tobytes()
            for _ in range(repeats):
                if expected >= len(frames) or pixels != frames[expected].tobytes():
                    raise ValueError('APNG frame/hold roundtrip mismatch')
                expected += 1
    if expected != len(frames):
        raise ValueError('APNG total duration mismatch')
    return count


def rle3(raw: bytes) -> bytes:
    pixels = memoryview(raw).cast('B')
    n = len(raw)//3
    def same(a,b):
        return pixels[3*a]==pixels[3*b] and pixels[3*a+1]==pixels[3*b+1] and pixels[3*a+2]==pixels[3*b+2]
    out = bytearray(); i = 0
    while i<n:
        run=1
        while run<128 and i+run<n and same(i,i+run): run+=1
        if run>=2:
            out.append(128|run-1);out.extend(raw[i*3:i*3+3]);i+=run
        else:
            start=i;i+=1
            while i<n and i-start<128:
                if i+1<n and same(i,i+1):break
                i+=1
            out.append(i-start-1);out.extend(raw[start*3:i*3])
    return bytes(out)


def unrle3(data: bytes) -> bytes:
    out=bytearray();pos=0
    while pos<len(data):
        control=data[pos];pos+=1;n=(control&127)+1
        used=3 if control&128 else n*3
        if pos+used>len(data) or len(out)+n*3>49152:raise ValueError('RLE bounds')
        out.extend(data[pos:pos+used]*n if control&128 else data[pos:pos+used]);pos+=used
    if len(out)!=49152:raise ValueError('RLE output size')
    return bytes(out)


def compressed_clip(frames):
    streams=[rle3(f) for f in frames]
    for source,stream in zip(frames,streams):
        if unrle3(stream)!=source:raise ValueError('RLE3 lossless mismatch')
    offset=len(streams)*8;directory=bytearray()
    for stream in streams:
        directory.extend(struct.pack('<II',offset,len(stream)));offset+=len(stream)
    return bytes(directory)+b''.join(streams)


def extra_art():
    image=Image.open(EXTRA).convert('RGBA');side=image.width//2
    if image.width!=image.height:raise ValueError('Extra source must be a 2x2 square')
    boxes=[];parts=[]
    for n in range(4):
        col,row=n%2,n//2
        bounds=(max(0,col*side-45),max(0,row*side-24),min(image.width,(col+1)*side+45),min(image.height,(row+1)*side+24))
        cell,record=old.largest_component(image.crop(bounds),32)
        box=cell.getchannel('A').point(lambda a:255 if a>=32 else 0).getbbox()
        if not box:raise ValueError('Missing extra pose')
        boxes.append(box);parts.append((cell,bounds,record))
    scale=440/max(max(b[2]-b[0],b[3]-b[1]) for b in boxes)
    eyes=((307,188,384,212),(215,263,290,265),(318,196,400,174),(215,134,287,156))
    centers=EXTRA_BADGE_CENTERS
    widths=(135,90,122,140)
    textures=[];positions=[];badges=[];sizes=[];records=[]
    for n,((cell,bounds,record),box) in enumerate(zip(parts,boxes)):
        size=(round((box[2]-box[0])*scale),round((box[3]-box[1])*scale))
        origin=((512-size[0])//2,476-size[1])
        tile=Image.new('RGBA',(512,512));tile.paste(cell.crop(box).resize(size,Image.Resampling.LANCZOS),origin)
        def transform(x,y):
            return (origin[0]+(x+(n%2)*side-bounds[0]-box[0])*scale,
                    origin[1]+(y+(n//2)*side-bounds[1]-box[1])*scale)
        positions.extend(transform(*eyes[n][:2]));positions.extend(transform(*eyes[n][2:]))
        badges.extend(transform(*centers[n]));sizes.append(widths[n]*scale)
        textures.append(tile.tobytes());record.update(source_bounds=bounds,component_box=box,canonical_origin=origin,canonical_size=size)
        record.update(badge_anchor_source=list(centers[n]),badge_anchor_canonical=list(transform(*centers[n])),badge_width_canonical=widths[n]*scale)
        records.append(record)
    return textures,positions,badges,sizes,records


def rig_setup(temp,avatar,key):
    library=Path(temp)/'tf_animation_v3.dll'
    subprocess.run(['gcc','-std=c11','-O3','-Wall','-Wextra','-Werror','-shared',str(ROOT/'tools/tf_animation_renderer_v3.c'),'-o',str(library),'-lm'],check=True)
    rig=ctypes.CDLL(str(library));ptr=ctypes.POINTER(ctypes.c_uint8)
    rig.tf3_set_avatar.argtypes=[ctypes.c_int,ptr]
    rig.tf3_set_badge.argtypes=[ptr,ctypes.c_int]
    rig.tf3_set_landmarks.argtypes=[ctypes.c_int,ctypes.POINTER(ctypes.c_float),ctypes.POINTER(ctypes.c_float),ctypes.c_float]
    rig.tf3_set_badge_widths.argtypes=[ctypes.POINTER(ctypes.c_float)]
    rig.tf3_render.argtypes=[ptr,ctypes.c_int,ctypes.c_int,ctypes.c_int,ctypes.c_int,ctypes.c_int]
    candidates=(FW/f'assets/tf-v2/{key}-poses-v2-source.png',FW/f'assets/tf-v2/{key}-poses-v2.png')
    source=next((p for p in candidates if p.exists()),old.SOURCES[avatar])
    original,record,eyes,centers,width=old.load_atlas(source,avatar,BLUE_BADGE_CENTERS if avatar==0 else None)
    raw=original.raw[:6*512*512*4];poses=[raw[i*512*512*4:(i+1)*512*512*4] for i in range(6)]
    if avatar==0:
        extra,ep,bc,ws,records=extra_art();poses+=extra;eyes+=ep;centers+=bc;widths=[width]*6+ws
        record['extra']={'source':str(EXTRA.relative_to(ROOT)).replace('\\','/'),'sha256':sha(EXTRA),'poses':records}
        record['badge_alignment']={'revision':BADGE_REVISION,'pose_anchors_source':BLUE_BADGE_CENTERS+EXTRA_BADGE_CENTERS,'pose_anchors_canonical':centers,'pose_widths_canonical':widths}
    else:
        mapping=(4,3,1,4)
        poses += [poses[i] for i in mapping]
        eyes += [v for i in mapping for v in eyes[i*4:i*4+4]]
        centers += [v for i in mapping for v in centers[i*2:i*2+2]]
        widths=[width]*10
    textures=ctypes.create_string_buffer(b''.join(poses));ep=(ctypes.c_float*40)(*eyes);bc=(ctypes.c_float*20)(*centers);ws=(ctypes.c_float*10)(*widths)
    badge=Image.open(FW/'assets/mascot-v3/dlut-badge.png').convert('RGBA').resize((256,256),Image.Resampling.LANCZOS)
    badge_buffer=ctypes.create_string_buffer(badge.tobytes())
    rig.tf3_set_avatar(avatar,ctypes.cast(textures,ptr));rig.tf3_set_badge(ctypes.cast(badge_buffer,ptr),256)
    rig.tf3_set_landmarks(avatar,ep,bc,width);rig.tf3_set_badge_widths(ws)
    return rig,(textures,badge_buffer,ep,bc,ws),record


def process_avatar(key,selected_states=None):
    avatar=[k for k,_ in old.AVATARS].index(key);preview=OUT/'previews';preview.mkdir(parents=True,exist_ok=True);CACHE.mkdir(parents=True,exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='tf-v3-',dir=ROOT/'tmp',ignore_cleanup_errors=True) as temp:
        rig,retained,record=rig_setup(temp,avatar,key)
        fingerprint=hashlib.sha256((sha(ROOT/'tools/tf_animation_renderer_v3.c')+json.dumps(record,sort_keys=True)+str(DURATIONS)+sha(Path(__file__))).encode()).hexdigest()
        for state,name in enumerate(STATES):
            if selected_states is not None and name not in selected_states:continue
            stem=f'{key}-{name}';meta_file=CACHE/f'{stem}.json';payload_file=CACHE/f'{stem}.bin'
            if meta_file.exists() and payload_file.exists():
                previous=json.loads(meta_file.read_text(encoding='utf-8'))
                if previous['fingerprint']==fingerprint and sha(payload_file)==previous['payload_sha256']:
                    print(stem+': verified cache',flush=True);continue
            board_count=DURATIONS[state]//BOARD_MS
            asset_stem=f'{stem}-{MOTION_REVISION}'
            web_duration=old.DURATIONS[state] if state<6 else DURATIONS[state]
            count=web_duration//WEB_MS;frames=[];output=(ctypes.c_uint8*(512*512*4))()
            for n in range(count):
                if rig.tf3_render(output,avatar,state,n,count,512)!=1:raise ValueError('Rig rejected frame')
                frames.append(Image.frombytes('RGBA',(512,512),bytes(output)))
            web=preview/f'{asset_stem}-motion.png';poster=preview/f'{asset_stem}-poster.png'
            web_count=write_web_asset(frames,web,LOOP[state]);frames[0].save(poster)
            web_url=f'/animations/v3/previews/{web.name}';poster_url=f'/animations/v3/previews/{poster.name}'
            board=[old.encode_board(frames[min(len(frames)-1,round(n*(len(frames)-1)/(board_count-1)))]) for n in range(board_count)]
            payload=compressed_clip(board)
            # v3 board preview uses the actual 50ms schedule, independent of V2 helper.
            gif_frames=[]
            for raw in board:
                bg=Image.new('RGBA',(128,128),'#eef3fc');bg.alpha_composite(old.decode_board(raw));gif_frames.append(bg.convert('RGB'))
            gif=preview/f'{asset_stem}.gif';gif_frames[0].save(gif,save_all=True,append_images=gif_frames[1:],duration=BOARD_MS,loop=0 if LOOP[state] else 1,disposal=2,optimize=False)
            meta={'id':name,'label':LABELS[state],'preview_url':f'/animations/v3/previews/{gif.name}','frame_count':board_count,'frame_ms':BOARD_MS,'duration_ms':DURATIONS[state],'loop':LOOP[state],
                  'web_preview_url':web_url,'web_poster_url':poster_url,'web_frame_count':web_count,'web_fps':20,'web_duration_ms':web_duration,'web_width':512,'web_height':512,'web_format':'apng','web_lossless':True,
                  'badge_baked':avatar==0,'web_badge_baked':avatar==0,'board_badge_baked':avatar==0}
            clip={'avatar_id':avatar,'state_id':state,'frames':board_count,'frame_ms':BOARD_MS,'flags':2|int(LOOP[state]),'bytes':len(payload),'crc32':zlib.crc32(payload)&0xffffffff}
            payload_file.write_bytes(payload);meta_file.write_text(json.dumps({'fingerprint':fingerprint,'payload_sha256':sha(payload_file),'clip':clip,'meta':meta,'source':record},ensure_ascii=False),encoding='utf-8')
            print(f'{stem}: {board_count} frames, {len(payload):,} packed / {len(board)*49152:,} raw bytes',flush=True)


def assemble():
    clips=[];payloads=[];avatars=[];offset=64+50*32;index=bytearray()
    for avatar,(key,name) in enumerate(old.AVATARS):
        metadata=[]
        for state in STATES:
            entry=json.loads((CACHE/f'{key}-{state}.json').read_text(encoding='utf-8'));payload=(CACHE/f'{key}-{state}.bin').read_bytes()
            if hashlib.sha256(payload).hexdigest()!=entry['payload_sha256']:raise ValueError('Changed payload cache')
            c=entry['clip'];index.extend(old.INDEX.pack(c['avatar_id'],c['state_id'],c['flags'],c['frames'],BOARD_MS,offset,len(payload),c['crc32'],b'\0'*12))
            c['offset']=offset;offset+=len(payload);clips.append(c);payloads.append(payload);metadata.append(entry['meta'])
        avatars.append({'id':key,'avatar_id':avatar,'name':name,'badge_baked':avatar==0,'clips':metadata})
    body=bytes(index)+b''.join(payloads)
    blob=old.HEADER.pack(b'LXAF',2,64,128,128,1,50,64,1664,64+len(body),0,hashlib.sha256(body).digest())+body
    package=OUT/'lingxi-animations-v3.lxaf';package.write_bytes(blob)
    report={'format_version':2,'bytes':len(blob),'sha256':sha(package),'clip_count':50,'board_frames':sum(c['frames'] for c in clips),'fps_target':20,'clips':clips,'hardware_verified':False}
    (OUT/'pack-report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    archive=OUT/'lingxi-tf-animations-v3.zip'
    with zipfile.ZipFile(archive,'w',zipfile.ZIP_DEFLATED,compresslevel=6) as z:
        z.write(package,'lingxi/animations-v1.lxaf');z.write(OUT/'pack-report.json','lingxi/pack-report.json')
        z.writestr('README.txt','LingXi V3 / LXAF version 2. Requires V3 firmware. Copy lingxi/ to FAT32 card root. Lossless RLE3, 50 clips, 20 fps source schedule. Actual display FPS is hardware dependent.\n')
    manifest={'schema_version':1,'pack_id':'lingxi-tf-animations-v3','asset_revision':MOTION_REVISION,'format_version':2,'created_at':datetime.now(timezone.utc).isoformat(timespec='seconds'),'web_ready':True,
              'frame_size':{'width':128,'height':128},'fps':20,'frame_ms':50,'web_frame_size':{'width':512,'height':512},'web_fps':20,'pixel_format':'RGB565LE+alpha8 / lossless RLE3',
              'download':old.file_meta(package,'/animations/v3'),'archive':old.file_meta(archive,'/animations/v3'),'avatars':avatars,'hardware_verified':False,
              'firmware':{'ready':False,'compiled':False,'hardware_verified':False},'notes':['LXAF version 2 compressed frames need V3 firmware.','20fps is the source schedule, not a claim of measured display FPS.','Fixed stage with local joint motion; no whole-pose dissolve.','Official blue mascot badge baked in every clip.']}
    manifest['download']['filename']='animations-v1.lxaf'
    (OUT/'manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps({'resource_bytes':len(blob),'sha256':sha(package),'archive_bytes':archive.stat().st_size,'frames':report['board_frames']},indent=2))


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--avatars',default='');parser.add_argument('--states',default='');parser.add_argument('--assemble',action='store_true');args=parser.parse_args()
    selected_states=set(args.states.split(',')) if args.states else None
    if selected_states is not None and selected_states-set(STATES):raise ValueError('Unknown animation state')
    OUT.mkdir(parents=True,exist_ok=True)
    if args.assemble:assemble();return
    for key in args.avatars.split(',') if args.avatars else [k for k,_ in old.AVATARS]:process_avatar(key,selected_states)
    if not args.avatars and selected_states is None:assemble()


if __name__=='__main__':main()
