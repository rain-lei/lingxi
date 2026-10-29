"""Build and verify deterministic LXAF v1 frames from immutable mascot art.

Host renderer: normal 2D sprite animation using C RGBA texture sampling.
Python only performs atlas framing/downscaling, binary packing and previews.
Requires Pillow and a host gcc; no connected board/card or cloud calls.
"""
from __future__ import annotations
import argparse
import ctypes
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import struct
import subprocess
import sys
import tempfile
import zlib
import zipfile
from PIL import Image, ImageDraw, ImageFont

ROOT=Path(__file__).resolve().parents[1]
FW=ROOT/'firmware/box_audio_ram'
HEADER=struct.Struct('<4sHHHHHHIIII32s')
INDEX=struct.Struct('<BBHHHIII12s')
FRAME_BYTES=128*128*3
STATE_NAMES=('idle','listening','thinking','speaking','comfort','celebrate')
STATE_LABELS=('待机眨眼','认真倾听','想一想','开口回应','温柔安慰','完成庆祝')
AVATARS=(('kangaroo','蓝蓝'),('robot','小犀'),('cat','奶泡'),('otter','团团'),('sprout','芽芽'))
FRAME_COUNTS=(36,24,36,24,36,24)
FRAME_MS=83

def validate_pack(blob: bytes) -> dict:
    if len(blob)<HEADER.size: raise ValueError('Truncated LXAF header')
    if len(blob)>64*1024*1024: raise ValueError('LXAF exceeds the v1 64 MiB limit')
    magic,version,header_size,w,h,fmt,count,index_offset,data_offset,total_size,flags,digest=HEADER.unpack_from(blob)
    if (magic,version,header_size,w,h,fmt,flags)!=(b'LXAF',1,64,128,128,1,0): raise ValueError('Unsupported LXAF header')
    if not 1<=count<=30 or index_offset!=64 or data_offset!=64+count*32 or total_size!=len(blob): raise ValueError('Bad LXAF layout')
    if hashlib.sha256(blob[64:]).digest()!=digest: raise ValueError('Body SHA256 mismatch')
    cursor=data_offset;seen=set();clips=[]
    for n in range(count):
        a,s,cf,frames,ms,offset,size,crc,reserved=INDEX.unpack_from(blob,64+n*32)
        if a>=len(AVATARS) or s>5 or cf&~1 or not 2<=frames<=96 or not 20<=ms<=1000 or reserved!=b'\0'*12: raise ValueError('Bad clip fields')
        if (a,s) in seen: raise ValueError('Duplicate avatar/state')
        if offset!=cursor or size!=frames*FRAME_BYTES or offset+size>len(blob): raise ValueError('Bad clip bounds')
        if zlib.crc32(blob[offset:offset+size])&0xffffffff!=crc: raise ValueError('Clip CRC32 mismatch')
        seen.add((a,s));cursor+=size
        clips.append({'avatar_id':a,'state_id':s,'avatar':AVATARS[a][0],'state':STATE_NAMES[s],'frames':frames,'frame_ms':ms,'loop':bool(cf&1),'offset':offset,'bytes':size,'crc32':f'{crc:08x}'})
    if cursor!=len(blob): raise ValueError('Trailing bytes')
    return {'version':version,'width':w,'height':h,'pixel_format':'RGB565LE+alpha8 interleaved','clip_count':count,'body_sha256':digest.hex(),'clips':clips}

def validate_negative_cases(blob:bytes):
    cases=[blob[:20],blob+b'\0']
    corrupt=bytearray(blob);corrupt[-1]^=1;cases.append(bytes(corrupt))
    bad_index=bytearray(blob);struct.pack_into('<I',bad_index,64+8,0xffffffff);bad_index[32:64]=hashlib.sha256(bad_index[64:]).digest();cases.append(bytes(bad_index))
    bad_crc=bytearray(blob);bad_crc[64+16]^=1;bad_crc[32:64]=hashlib.sha256(bad_crc[64:]).digest();cases.append(bytes(bad_crc))
    for bad in cases:
        try: validate_pack(bad)
        except ValueError: pass
        else: raise AssertionError('Corrupted LXAF was accepted')

def compile_renderer(temp:Path):
    library=temp/('tf_animation.dll' if sys.platform=='win32' else 'tf_animation.so')
    subprocess.run(['gcc','-std=c11','-O2','-Wall','-Wextra','-Werror','-shared',
                    '-I',str(FW/'main'),str(ROOT/'tools/tf_animation_renderer.c'),
                    str(FW/'main/ui_kangaroo.c'),str(FW/'main/ui_mascot.c'),str(FW/'main/ui_badge.c'),'-o',str(library),'-lm'],check=True)
    renderer=ctypes.CDLL(str(library))
    renderer.tf_render_frame.argtypes=[ctypes.POINTER(ctypes.c_uint8),ctypes.c_int,ctypes.c_int,ctypes.c_int,ctypes.c_int]
    renderer.tf_render_frame.restype=ctypes.c_int
    renderer.tf_set_avatar.argtypes=[ctypes.c_int,ctypes.POINTER(ctypes.c_uint16),ctypes.POINTER(ctypes.c_uint8)]
    renderer.tf_set_avatar.restype=ctypes.c_int
    return renderer

def load_generated_atlas(path:Path):
    # Same framing algorithm as the existing immutable atlas packer. Source
    # colors/expressions are never repainted or inferred by this pipeline.
    sys.path.insert(0,str(FW/'tools'))
    from pack_mascot import largest_component, suspicious_checkerboard
    source=Image.open(path).convert('RGBA');w,h=source.size
    xs=[n*w//3 for n in range(4)];ys=[n*h//2 for n in range(3)]
    cw=max(xs[i+1]-xs[i] for i in range(3));ch=max(ys[i+1]-ys[i] for i in range(2))
    cells=[];boxes=[];records=[]
    for n in range(6):
        raw=source.crop((xs[n%3],ys[n//3],xs[n%3+1],ys[n//3+1]))
        if suspicious_checkerboard(raw): raise ValueError(f'{path.name}: opaque checkerboard')
        cell,component=largest_component(raw,32)
        pad=Image.new('RGBA',(cw,ch));pad.paste(cell,(0,0))
        box=pad.getchannel('A').point(lambda a:255 if a>=32 else 0).getbbox()
        if not box: raise ValueError(f'{path.name}: empty pose {n}')
        cells.append(pad);boxes.append(box);records.append(component)
    union=(max(0,min(b[0] for b in boxes)-1),max(0,min(b[1] for b in boxes)-1),min(cw,max(b[2] for b in boxes)+1),min(ch,max(b[3] for b in boxes)+1))
    scale=min(112/(union[2]-union[0]),118/(union[3]-union[1]))
    target=(max(1,round((union[2]-union[0])*scale)),max(1,round((union[3]-union[1])*scale)))
    origin=((128-target[0])//2,124-target[1])
    colors=[];alpha=[]
    for cell in cells:
        tile=Image.new('RGBA',(128,128));tile.paste(cell.crop(union).resize(target,Image.Resampling.LANCZOS),origin)
        for r,g,b,a in tile.getdata():
            if a<=8:a=0
            colors.append(((r>>3)<<11)|((g>>2)<<5)|(b>>3) if a else 0);alpha.append(a)
    return ((ctypes.c_uint16*len(colors))(*colors),(ctypes.c_uint8*len(alpha))(*alpha),{'source':str(path.relative_to(ROOT)).replace('\\','/'),'sha256':hashlib.sha256(path.read_bytes()).hexdigest(),'source_size':source.size,'common_crop':union,'target_size':target,'origin':origin,'components':records})

def decode_frame(raw:bytes):
    data=bytearray(128*128*4)
    for i in range(128*128):
        c=raw[3*i]|raw[3*i+1]<<8;a=raw[3*i+2]
        data[4*i:4*i+4]=bytes(((c>>11)*255//31,((c>>5)&63)*255//63,(c&31)*255//31,a))
    return Image.frombytes('RGBA',(128,128),bytes(data))

def preview_frame(raw:bytes,avatar:int,size=256):
    backgrounds=('#edf3ff','#f0edfc','#fcf1f6','#fff3e8','#eef8ef')
    tile=Image.new('RGBA',(128,128),backgrounds[avatar]);tile.alpha_composite(decode_frame(raw))
    return tile.convert('RGB').resize((size,size),Image.Resampling.NEAREST)

def write_zip(path:Path,entries:dict[str,bytes]):
    with zipfile.ZipFile(path,'w',compression=zipfile.ZIP_DEFLATED,compresslevel=6) as archive:
        for name,data in sorted(entries.items()):
            item=zipfile.ZipInfo(name,(2026,10,21,0,0,0));item.compress_type=zipfile.ZIP_DEFLATED;item.external_attr=0o644<<16
            archive.writestr(item,data)


def write_resource_archive(out:Path,report:dict):
    package=out/'lingxi-animations-v1.lxaf'
    packed=package.read_bytes()
    if len(packed)!=report['bytes'] or hashlib.sha256(packed).hexdigest()!=report['sha256']:
        raise ValueError('Existing LXAF does not match pack-report.json')
    readme='灵犀 TF 动画 v1\n\n将 lingxi/ 目录放在 FAT32 TF 卡根目录。资源文件必须是 lingxi/animations-v1.lxaf。\n本包需要配套 TF 动画固件；旧无卡固件不会自动读取。\n具体步骤请阅读安装说明.md；previews/ 仅供电脑预览，无需复制到卡。\n不要格式化含有其他重要文件的卡；本资源包不会自动格式化卡。\n'
    entries={'lingxi/animations-v1.lxaf':packed,'lingxi/pack-report.json':(out/'pack-report.json').read_bytes(),'README-先读我.txt':readme.encode('utf8'),'安装说明.md':(ROOT/'docs/TF_ANIMATION_INSTALL_GUIDE_20261021.md').read_bytes(),'previews/contact-sheet.png':(out/'previews/contact-sheet.png').read_bytes()}
    for clip in report['clips']:
        filename=f'{clip["avatar"]}-{clip["state"]}.gif'
        entries['previews/'+filename]=(out/'previews'/filename).read_bytes()
    archive=out/'lingxi-tf-animations-v1.zip'
    write_zip(archive,entries)
    with zipfile.ZipFile(archive) as check:
        if check.testzip() is not None or check.namelist()!=sorted(entries):
            raise ValueError('Resource archive verification failed')
    return {'url':'/animations/v1/'+archive.name,'filename':archive.name,'size_bytes':archive.stat().st_size,'sha256':hashlib.sha256(archive.read_bytes()).hexdigest()}


def write_manifest(out:Path,report:dict):
    def asset(filename:str):
        file=out/filename
        return {'url':'/animations/v1/'+filename,'filename':filename,'size_bytes':file.stat().st_size,'sha256':hashlib.sha256(file.read_bytes()).hexdigest()}
    avatars=[]
    for avatar,(key,label) in enumerate(AVATARS):
        clips=[]
        for item in report['clips']:
            if item['avatar_id']!=avatar:continue
            clips.append({'id':item['state'],'label':STATE_LABELS[item['state_id']],'preview_url':f'/animations/v1/previews/{key}-{item["state"]}.gif','frame_count':item['frames'],'frame_ms':item['frame_ms'],'duration_ms':item['frames']*item['frame_ms'],'loop':item['loop']})
        if clips:avatars.append({'id':key,'avatar_id':avatar,'name':label,'clips':clips})
    manifest={'schema_version':1,'pack_id':'lingxi-tf-animations-v1','created_at':datetime.now(timezone.utc).isoformat(timespec='seconds'),'frame_size':{'width':report['width'],'height':report['height']},'fps':report['nominal_fps'],'frame_ms':FRAME_MS,'pixel_format':report['pixel_format'],'hardware_verified':False,'download':asset('lingxi-animations-v1.lxaf'),'archive':asset('lingxi-tf-animations-v1.zip'),'avatars':avatars,'firmware':{'ready':False,'compiled':False,'hardware_verified':False},'notes':report['notes']}
    (out/'manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2)+'\n',encoding='utf8')
    return manifest

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path,default=ROOT/'public/animations/v1')
    parser.add_argument('--only-embedded',action='store_true')
    parser.add_argument('--archive-only',action='store_true',help='Repackage existing frames and update only manifest.archive, preserving published firmware/install fields')
    args=parser.parse_args();out=args.output.resolve();(out/'previews').mkdir(parents=True,exist_ok=True)
    if args.archive_only:
        report=json.loads((out/'pack-report.json').read_text(encoding='utf8'))
        archive=write_resource_archive(out,report)
        manifest_path=out/'manifest.json'
        manifest=json.loads(manifest_path.read_text(encoding='utf8'));manifest['archive']=archive
        manifest_path.write_text(json.dumps(manifest,ensure_ascii=False,indent=2)+'\n',encoding='utf8')
        print(json.dumps({'archive':archive,'lxaf_unchanged':report['sha256']},ensure_ascii=False));return
    avatars=list(enumerate(AVATARS if not args.only_embedded else AVATARS[:2]))
    clips=[];payloads=[];source_records=[];all_frames={};kept_buffers=[]
    (ROOT/'tmp').mkdir(exist_ok=True)
    # Windows keeps a ctypes-loaded DLL open until this Python process exits.
    with tempfile.TemporaryDirectory(prefix='lingxi-tf-render-',dir=ROOT/'tmp',ignore_cleanup_errors=True) as temp:
        renderer=compile_renderer(Path(temp))
        for avatar,(key,label) in avatars:
            if avatar>=2:
                path=FW/f'assets/tf-v1/{key}-poses.png'
                colors,alpha,record=load_generated_atlas(path);kept_buffers.extend([colors,alpha]);source_records.append(record)
                if renderer.tf_set_avatar(avatar,colors,alpha)!=1:raise RuntimeError('Could not bind texture')
            else:
                for filename in ([FW/'main/ui_kangaroo.c',FW/'main/ui_badge.c'] if avatar==0 else [FW/'main/ui_mascot.c']):
                    source_records.append({'source':str(filename.relative_to(ROOT)).replace('\\','/'),'sha256':hashlib.sha256(filename.read_bytes()).hexdigest()})
            for state,name in enumerate(STATE_NAMES):
                count=FRAME_COUNTS[state];frames=[];buf=(ctypes.c_uint8*FRAME_BYTES)()
                for n in range(count):
                    if renderer.tf_render_frame(buf,avatar,state,n,count)!=1:raise RuntimeError('Renderer rejected frame')
                    frames.append(bytes(buf))
                if len(set(hashlib.sha256(frame).digest() for frame in frames))<4:raise AssertionError('Static or broken animation')
                payload=b''.join(frames);payloads.append(payload);all_frames[(avatar,state)]=frames
                clips.append({'avatar_id':avatar,'state_id':state,'flags':0 if state==5 else 1,'frames':count,'frame_ms':FRAME_MS,'bytes':len(payload),'crc32':zlib.crc32(payload)&0xffffffff})
                images=[preview_frame(frame,avatar) for frame in frames]
                palette=images[0].quantize(colors=255,method=Image.Quantize.MEDIANCUT)
                indexed=[image.quantize(palette=palette,dither=Image.Dither.NONE) for image in images]
                gif_options={'loop':0} if state!=5 else {}
                indexed[0].save(out/f'previews/{key}-{name}.gif',save_all=True,append_images=indexed[1:],duration=FRAME_MS,optimize=False,disposal=2,**gif_options)
                print(f'{key}/{name}: {count} frames')
    count=len(clips);offset=64+count*32;index=bytearray()
    for clip,payload in zip(clips,payloads):
        index.extend(INDEX.pack(clip['avatar_id'],clip['state_id'],clip['flags'],clip['frames'],FRAME_MS,offset,len(payload),clip['crc32'],b'\0'*12));offset+=len(payload)
    body=bytes(index)+b''.join(payloads)
    packed=HEADER.pack(b'LXAF',1,64,128,128,1,count,64,64+count*32,64+len(body),0,hashlib.sha256(body).digest())+body
    report=validate_pack(packed);validate_negative_cases(packed)
    package=out/'lingxi-animations-v1.lxaf';package.write_bytes(packed)
    report.update({'filename':package.name,'sha256':hashlib.sha256(packed).hexdigest(),'bytes':len(packed),'nominal_fps':12,'actual_fps':round(1000/FRAME_MS,5),'frame_bytes':FRAME_BYTES,'source_art':source_records,'notes':['预渲染3D风格二维动画；不是真实3D引擎。','speaking为实际开口/闭口表情与小挥手循环，不承诺音素口型同步。','庆祝clip为一次动作，其他状态循环。','预览逐帧来自同一LXAF像素，不使用替代示意动画。']})
    (out/'pack-report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf8')
    # A true-size contact sheet makes all state poses reviewable together.
    sheet=Image.new('RGB',(6*168+24,len(avatars)*188+50),'#f7f6fc');draw=ImageDraw.Draw(sheet)
    try:font=ImageFont.truetype('C:/Windows/Fonts/msyh.ttc',14)
    except OSError:font=ImageFont.load_default()
    for state,label in enumerate(STATE_LABELS):draw.text((24+state*168,13),label,font=font,fill='#77728a')
    for avatar,(key,label) in avatars:
        for state in range(6):
            frames=all_frames[(avatar,state)];image=preview_frame(frames[len(frames)//3],avatar,size=152)
            x=18+state*168;y=48+avatar*188;sheet.paste(image,(x,y));draw.text((x,y+154),label if state==0 else f'{len(frames)}帧 · {len(frames)*FRAME_MS/1000:.2f}s',font=font,fill='#9a91ae')
    sheet.save(out/'previews/contact-sheet.png')
    write_resource_archive(out,report)
    write_manifest(out,report)
    print(json.dumps({'pack':str(package),'bytes':len(packed),'sha256':report['sha256'],'clips':count,'frames':sum(c['frames'] for c in clips),'verified_negative_cases':5},ensure_ascii=False))

if __name__=='__main__':main()
