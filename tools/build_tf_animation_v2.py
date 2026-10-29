"""Produce native 512px/20fps web animation and a separate 128px LXAF card pack.

The C rig samples artist-rendered textures. Python handles immutable atlas
framing, downsampling, encoding and checksums; it never draws facial features.
"""
from __future__ import annotations
import argparse
import ctypes
from datetime import datetime, timezone
import hashlib
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import zlib
import zipfile
import numpy as np
from PIL import Image, ImageDraw, ImageFont

ROOT=Path(__file__).resolve().parents[1]
FW=ROOT/'firmware/box_audio_ram'
sys.path.insert(0,str(ROOT/'tools'))
from build_tf_animation_pack import HEADER, INDEX, validate_pack, validate_negative_cases
sys.path.insert(0,str(FW/'tools'))
from pack_mascot import largest_component,suspicious_checkerboard

AVATARS=(('kangaroo','蓝蓝'),('robot','小犀'),('cat','奶泡'),('otter','团团'),('sprout','芽芽'))
STATES=('idle','listening','thinking','speaking','comfort','celebrate')
LABELS=('待机眨眼','认真倾听','想一想','开口回应','温柔安慰','完成庆祝')
DURATIONS=(4000,3000,3500,3000,4000,3000)
BOARD_MS=83
WEB_MS=50
FRAME_BYTES=128*128*3
SOURCES=(FW/'assets/mascot-v3/kangaroo-concept.png',FW/'assets/mascot-v2/xiaoxi-3d-concept-v2.png',*(FW/f'assets/tf-v1/{key}-poses.png' for key in ('cat','otter','sprout')))
EYES=(
 ((250,151,322,164),(218,154,291,170),(190,153,256,165),(253,139,313,160),(229,135,290,151),(209,143,268,164)),
 ((207,254,338,245),(201,266,322,254),(239,230,358,219),(230,237,347,210),(197,239,323,223),(210,253,338,247)),
 ((214,210,323,177),(220,224,331,195),(242,222,354,184),(236,209,352,169),(241,198,353,160),(243,212,355,175)),
 ((194,183,327,145),(184,189,333,156),(194,192,328,151),(195,161,325,118),(194,165,326,116),(194,179,325,143)),
 ((167,209,295,242),(163,223,303,258),(166,207,292,247),(165,184,286,229),(169,168,303,210),(177,175,302,218)),
)
BADGE_CENTERS=((278,370),(274,370),(259,370),(276,365),(260,350),(263,315))

def sha(path):return hashlib.sha256(path.read_bytes()).hexdigest()
def compile_rig(temp):
    library=Path(temp)/('tf_animation_v2.dll' if sys.platform=='win32' else 'tf_animation_v2.so')
    subprocess.run(['gcc','-std=c11','-O3','-Wall','-Wextra','-Werror','-shared',str(ROOT/'tools/tf_animation_renderer_v2.c'),'-o',str(library),'-lm'],check=True)
    rig=ctypes.CDLL(str(library));ptr=ctypes.POINTER(ctypes.c_uint8)
    rig.tf2_set_avatar.argtypes=[ctypes.c_int,ptr];rig.tf2_set_avatar.restype=ctypes.c_int
    rig.tf2_set_badge.argtypes=[ptr,ctypes.c_int];rig.tf2_set_badge.restype=ctypes.c_int
    rig.tf2_set_landmarks.argtypes=[ctypes.c_int,ctypes.POINTER(ctypes.c_float),ctypes.POINTER(ctypes.c_float),ctypes.c_float];rig.tf2_set_landmarks.restype=ctypes.c_int
    rig.tf2_render.argtypes=[ptr,ctypes.c_int,ctypes.c_int,ctypes.c_int,ctypes.c_int,ctypes.c_int];rig.tf2_render.restype=ctypes.c_int
    return rig

def load_atlas(path,avatar,badge_anchors=None):
    source=Image.open(path).convert('RGBA');w,h=source.size
    if (w,h)!=(1536,1024):raise ValueError(f'Expected native 512px cells: {path}')
    frames=[];stats=[];boxes=[]
    for pose in range(6):
        column,row=pose%3,pose//3
        bounds=(max(0,column*512-40),max(0,row*512-30),min(w,(column+1)*512+85),min(h,(row+1)*512+30))
        cell=source.crop(bounds)
        if suspicious_checkerboard(cell):raise ValueError('Opaque checkerboard atlas')
        cell,record=largest_component(cell,32)
        cell.putalpha(cell.getchannel('A').point(lambda a:0 if a<=6 else a))
        virtual=Image.new('RGBA',(637,572));virtual.paste(cell,(bounds[0]-column*512+40,bounds[1]-row*512+30))
        box=virtual.getchannel('A').point(lambda a:255 if a>=32 else 0).getbbox()
        if not box:raise ValueError('Empty expanded atlas cell')
        frames.append(virtual);boxes.append(box);record['expanded_source_bounds']=bounds;stats.append(record)
    baseline=max(b[3] for b in boxes);baseline_offsets=[baseline-box[3] for box in boxes]
    for pose,dy in enumerate(baseline_offsets):
        if dy:
            aligned=Image.new('RGBA',(637,572));aligned.paste(frames[pose],(0,dy));frames[pose]=aligned
            box=boxes[pose];boxes[pose]=(box[0],box[1]+dy,box[2],box[3]+dy)
    union=(min(b[0] for b in boxes),min(b[1] for b in boxes),max(b[2] for b in boxes),max(b[3] for b in boxes))
    factor=min(440/(union[2]-union[0]),440/(union[3]-union[1]))
    target=(round((union[2]-union[0])*factor),round((union[3]-union[1])*factor))
    origin=((512-target[0])//2,476-target[1])
    canonical=[]
    for frame in frames:
        tile=Image.new('RGBA',(512,512));tile.paste(frame.crop(union).resize(target,Image.Resampling.LANCZOS),origin);canonical.append(tile.tobytes())
    def transform(point,pose):return (origin[0]+(point[0]+40-union[0])*factor,origin[1]+(point[1]+30+baseline_offsets[pose]-union[1])*factor)
    landmarks=[]
    for pose,positions in enumerate(EYES[avatar]):
        landmarks.extend(transform(positions[:2],pose));landmarks.extend(transform(positions[2:],pose))
    badge_centers=[value for pose,point in enumerate(BADGE_CENTERS if badge_anchors is None else badge_anchors) for value in transform(point,pose)]
    return ctypes.create_string_buffer(b''.join(canonical)),{'source':str(path.relative_to(ROOT)).replace('\\','/'),'sha256':sha(path),'native_size':list(source.size),'components':stats,'baseline_translation_px':baseline_offsets,'common_virtual_crop':union,'canonical_origin':origin,'canonical_art_size':target,'canonical_minimum_gutter':36},landmarks,badge_centers,111*factor

def encode_board(image):
    small=image.resize((128,128),Image.Resampling.LANCZOS)
    rgba=np.asarray(small,dtype=np.uint8)
    color=((rgba[:,:,0].astype(np.uint16)>>3)<<11)|((rgba[:,:,1].astype(np.uint16)>>2)<<5)|(rgba[:,:,2].astype(np.uint16)>>3)
    alpha=rgba[:,:,3].copy();alpha[alpha<=6]=0;color[alpha==0]=0
    result=np.empty((128,128,3),dtype=np.uint8)
    result[:,:,0]=color&255;result[:,:,1]=color>>8;result[:,:,2]=alpha
    return result.tobytes()

def decode_board(raw):
    packed=np.frombuffer(raw,dtype=np.uint8).reshape(128,128,3)
    color=packed[:,:,0].astype(np.uint16)|(packed[:,:,1].astype(np.uint16)<<8)
    rgba=np.empty((128,128,4),dtype=np.uint8)
    rgba[:,:,0]=(color>>11)*255//31;rgba[:,:,1]=((color>>5)&63)*255//63
    rgba[:,:,2]=(color&31)*255//31;rgba[:,:,3]=packed[:,:,2]
    return Image.fromarray(rgba,'RGBA')

def write_gif(frames,path,loop):
    images=[]
    for raw in frames:
        background=Image.new('RGBA',(128,128),'#eef3fc');background.alpha_composite(decode_board(raw));images.append(background.convert('RGB'))
    palette=images[0].quantize(colors=255,method=Image.Quantize.MEDIANCUT)
    indexed=[image.quantize(palette=palette,dither=Image.Dither.NONE) for image in images]
    options={'loop':0} if loop else {}
    indexed[0].save(path,save_all=True,append_images=indexed[1:],duration=BOARD_MS,optimize=False,disposal=2,**options)

def web_asset(frames,path,loop):
    # Keep full-color RGBA edges; never go through RGB565 or GIF palettes.
    # APNG uses OP_SOURCE so moved transparent edges clear the old frame.
    frames[0].save(path,format='PNG',save_all=True,append_images=frames[1:],duration=WEB_MS,loop=0 if loop else 1,disposal=0,blend=0,optimize=False,compress_level=6)
    with Image.open(path) as check:
        if check.size!=(512,512) or check.n_frames!=len(frames):raise ValueError('APNG frame count/size mismatch')
        check.seek(len(frames)//2)
        if check.convert('RGBA').getpixel((0,0))[3]!=0:raise ValueError('APNG alpha was lost')
        # Three decoded frames must reproduce original RGBA exactly, including
        # zero-alpha movement footprints. This catches disposal/codec residue.
    for index in (0,len(frames)//2,len(frames)-1):
        # Pillow 12.3 APNG backwards-seek can reuse a decompressor at the wrong
        # offset, so each independent integrity sample opens a fresh decoder.
        with Image.open(path) as check:
            check.seek(index)
            if check.convert('RGBA').tobytes()!=frames[index].tobytes():raise ValueError('APNG did not round-trip RGBA losslessly')

def file_meta(path,prefix):
    return {'url':prefix+'/'+path.name,'filename':path.name,'size_bytes':path.stat().st_size,'sha256':sha(path)}

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path,default=ROOT/'public/animations/v2')
    parser.add_argument('--samples',action='store_true',help='Render only blue idle/speaking, with no release manifest')
    parser.add_argument('--avatars',default='',help='Comma-separated subset; render/cache only, without final manifest')
    args=parser.parse_args();out=args.output.resolve();preview=out/'previews';preview.mkdir(parents=True,exist_ok=True)
    selected=set(args.avatars.split(',')) if args.avatars else {key for key,_ in AVATARS}
    if selected-{key for key,_ in AVATARS}:raise ValueError('Unknown avatar')
    cache=ROOT/'tmp/tf-v2-build-cache';cache.mkdir(parents=True,exist_ok=True)
    retained=[];source_records=[];clips=[];payloads=[];posters={};avatar_meta=[]
    with tempfile.TemporaryDirectory(prefix='tf-v2-',dir=ROOT/'tmp',ignore_cleanup_errors=True) as temp:
        rig=compile_rig(temp)
        badge=Image.open(FW/'assets/mascot-v3/dlut-badge.png').convert('RGBA').resize((256,256),Image.Resampling.LANCZOS)
        badge_buffer=ctypes.create_string_buffer(badge.tobytes());retained.append(badge_buffer)
        rig.tf2_set_badge(ctypes.cast(badge_buffer,ctypes.POINTER(ctypes.c_uint8)),256)
        for avatar,(key,name) in enumerate(AVATARS[:1] if args.samples else AVATARS):
            if key not in selected:continue
            candidates=(FW/f'assets/tf-v2/{key}-poses-v2-source.png',FW/f'assets/tf-v2/{key}-poses-v2.png')
            source=next((file for file in candidates if file.exists()),SOURCES[avatar])
            atlas,record,landmarks,centers,badge_width=load_atlas(source,avatar);retained.append(atlas);source_records.append(record)
            rig.tf2_set_avatar(avatar,ctypes.cast(atlas,ctypes.POINTER(ctypes.c_uint8)))
            positions=(ctypes.c_float*24)(*landmarks);badge_positions=(ctypes.c_float*12)(*centers)
            rig.tf2_set_landmarks(avatar,positions,badge_positions,badge_width)
            cache_key=hashlib.sha256((sha(ROOT/'tools/tf_animation_renderer_v2.c')+record['sha256']+sha(FW/'assets/mascot-v3/dlut-badge.png')+str(DURATIONS)+str(landmarks)+'apng-normalized-v2').encode()).hexdigest()
            avatar_clips=[]
            for state in ((0,3) if args.samples else range(6)):
                duration=DURATIONS[state];count=duration//WEB_MS
                stem=f'{key}-{STATES[state]}'
                cached_meta=cache/f'{stem}.json';cached_payload=cache/f'{stem}.bin'
                web=preview/f'{stem}-motion.png';poster=preview/f'{stem}-poster.png';gif=preview/f'{stem}.gif'
                if not args.samples and cached_meta.exists() and cached_payload.exists() and web.exists() and poster.exists() and gif.exists():
                    previous=json.loads(cached_meta.read_text(encoding='utf8'))
                    if previous['cache_key']==cache_key:
                        payload=cached_payload.read_bytes();clip=previous['clip'];meta=previous['meta']
                        if len(payload)==clip['bytes'] and zlib.crc32(payload)&0xffffffff==clip['crc32']:
                            payloads.append(payload);clips.append(clip);avatar_clips.append(meta);posters[(avatar,state)]=Image.open(poster).convert('RGBA')
                            print(f'{stem}: verified render cache reused',flush=True);continue
                frames=[];output=(ctypes.c_uint8*(512*512*4))()
                for frame in range(count):
                    if rig.tf2_render(output,avatar,state,frame,count,512)!=1:raise RuntimeError('Rig rejected frame')
                    frames.append(Image.frombytes('RGBA',(512,512),bytes(output)))
                web_asset(frames,web,state!=5)
                frames[0].save(poster)
                posters[(avatar,state)]=frames[0].copy()
                board_count=round(duration/BOARD_MS)
                board=[encode_board(frames[round(n*count/board_count)%count]) for n in range(board_count)]
                if len(set(hashlib.sha256(frame).digest() for frame in board))<board_count//2:raise ValueError('Insufficient unique frames')
                write_gif(board,gif,state!=5)
                payload=b''.join(board);payloads.append(payload)
                clips.append({'avatar_id':avatar,'state_id':state,'avatar':key,'state':STATES[state],'frames':board_count,'frame_ms':BOARD_MS,'flags':0 if state==5 else 1,'bytes':len(payload),'crc32':zlib.crc32(payload)&0xffffffff})
                avatar_clips.append({'id':STATES[state],'label':LABELS[state],'preview_url':f'/animations/v2/previews/{gif.name}','frame_count':board_count,'frame_ms':BOARD_MS,'duration_ms':board_count*BOARD_MS,'loop':state!=5,'web_preview_url':f'/animations/v2/previews/{web.name}','web_poster_url':f'/animations/v2/previews/{poster.name}','web_frame_count':count,'web_fps':20,'web_duration_ms':duration,'web_width':512,'web_height':512,'web_format':'apng','web_lossless':True,'badge_baked':avatar==0,'web_badge_baked':avatar==0,'board_badge_baked':avatar==0})
                cached_payload.write_bytes(payload)
                cached_meta.write_text(json.dumps({'cache_key':cache_key,'clip':clips[-1],'meta':avatar_clips[-1]},ensure_ascii=False),encoding='utf8')
                print(f'{stem}: web 512px/{count} frames, card 128px/{board_count} frames',flush=True)
            avatar_meta.append({'id':key,'avatar_id':avatar,'name':name,'badge_baked':avatar==0,'clips':avatar_clips})
        if args.avatars:
            print('Selected render/cache complete; no existing release changed.');return
        sheet=Image.new('RGB',(6*210+24,len(avatar_meta)*225+60),'#f3f1f9');draw=ImageDraw.Draw(sheet)
        try:font=ImageFont.truetype('C:/Windows/Fonts/msyh.ttc',16)
        except OSError:font=ImageFont.load_default()
        for state,label in enumerate(LABELS):draw.text((18+state*210,12),label,font=font,fill='#5b4f70')
        for (avatar,state),poster in posters.items():
            tile=poster.resize((200,200),Image.Resampling.LANCZOS)
            sheet.paste(tile,(12+state*210,42+avatar*225),tile)
            draw.text((20+state*210,243+avatar*225),AVATARS[avatar][1],font=font,fill='#675379')
        sheet.save(preview/'contact-sheet.png')
    if args.samples or args.avatars:
        print('Selected render/cache complete; no existing release changed.');return
    clip_count=len(clips);offset=64+clip_count*32;index=bytearray()
    for clip,payload in zip(clips,payloads):
        index.extend(INDEX.pack(clip['avatar_id'],clip['state_id'],clip['flags'],clip['frames'],BOARD_MS,offset,len(payload),clip['crc32'],b'\0'*12))
        clip['offset']=offset;offset+=len(payload)
    body=bytes(index)+b''.join(payloads)
    packed=HEADER.pack(b'LXAF',1,64,128,128,1,clip_count,64,64+clip_count*32,64+len(body),0,hashlib.sha256(body).digest())+body
    if len(packed)>64*1024*1024:raise ValueError('Pack exceeds reader 64MiB cap')
    report=validate_pack(packed);validate_negative_cases(packed)
    report.update({'filename':'lingxi-animations-v2.lxaf','bytes':len(packed),'sha256':hashlib.sha256(packed).hexdigest(),'web_frame_size':{'width':512,'height':512},'web_fps':20,'source_art':source_records,'board_frames':sum(c['frames'] for c in clips),'web_frames':sum(c['web_frame_count'] for avatar in avatar_meta for c in avatar['clips']),'no_whole_pose_dissolve':True})
    package=out/report['filename'];package.write_bytes(packed)
    (out/'pack-report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf8')
    archive=out/'lingxi-tf-animations-v2.zip'
    with zipfile.ZipFile(archive,'w',zipfile.ZIP_DEFLATED,compresslevel=6) as z:
        z.write(package,'lingxi/animations-v1.lxaf')
        z.write(out/'pack-report.json','lingxi/pack-report.json')
        z.write(ROOT/'docs/TF_ANIMATION_INSTALL_GUIDE_20261021.md','安装说明.md')
        for file in sorted(preview.iterdir()):
            if file.suffix.lower()=='.gif' or file.name=='contact-sheet.png':z.write(file,'previews/'+file.name)
        z.writestr('README-先读我.txt','灵犀 TF 动画 V2\n把 lingxi 文件夹复制到 FAT32 TF 卡根目录。卡内资源文件名仍为 animations-v1.lxaf，兼容已提供的TF固件。previews 文件夹是板端真实GIF和总览，无需放到卡。512px高清APNG可以另外下载高清离线包。\n')
    web_archive=out/'lingxi-hd-animations-v2.zip'
    with zipfile.ZipFile(web_archive,'w',zipfile.ZIP_DEFLATED,compresslevel=6) as z:
        for avatar in avatar_meta:
            for clip in avatar['clips']:
                for field in ('web_preview_url','web_poster_url'):
                    file=preview/clip[field].rsplit('/',1)[1];z.write(file,'previews/'+file.name)
        z.write(preview/'contact-sheet.png','previews/contact-sheet.png')
        z.writestr('README-高清预览.txt','灵犀高清动画 V2\npreviews/*-motion.png 是512×512/20fps透明无损APNG，可拖入现代浏览器播放；*-poster.png是同一动作静态封面。\n这是电脑高清观赏素材，不需要复制到TF卡。板子读取的LXAF请从动画工坊另下TF安装包。\n')
    manifest={'schema_version':1,'pack_id':'lingxi-tf-animations-v2','created_at':datetime.now(timezone.utc).isoformat(timespec='seconds'),'web_ready':True,'frame_size':{'width':128,'height':128},'fps':12,'frame_ms':83,'web_frame_size':{'width':512,'height':512},'web_fps':20,'pixel_format':'RGB565LE+alpha8 interleaved','hardware_verified':False,'download':file_meta(package,'/animations/v2'),'archive':file_meta(archive,'/animations/v2'),'web_archive':file_meta(web_archive,'/animations/v2'),'avatars':avatar_meta,'firmware':{'ready':False,'compiled':False,'hardware_verified':False},'notes':['高分辨率单姿态局部骨骼纹理形变，未使用整幅角色姿态淡化。','网页512RGBA/20fps与板端128RGB565/83ms独立编码；网页预览帧率不代表实板帧率。','说话表情与挥手为预置动画，不是音素同步；庆祝为一次动作。']}
    (out/'manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2)+'\n',encoding='utf8')
    print(json.dumps({'pack':str(package),'bytes':len(packed),'sha256':report['sha256'],'board_frames':report['board_frames'],'web_frames':report['web_frames'],'archive':manifest['archive']},ensure_ascii=False,indent=2))

if __name__=='__main__':main()
