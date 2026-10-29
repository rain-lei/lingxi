/* Independent Windows host verifier: native C format reader + Windows SHA256.
   gcc -std=c11 -O2 -Wall -Wextra -Werror tools/lxaf_verify.c main/lxaf_format.c -lbcrypt -o lxaf_verify.exe
   lxaf_verify.exe --self-test | lxaf_verify.exe path/to/animations-v1.lxaf */
#include <windows.h>
#include <bcrypt.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include "../main/lxaf_format.h"

static int verify(const char *path)
{
    FILE *file=fopen(path,"rb");if(!file){perror(path);return 1;}
    uint8_t header[64],index[LXAF_MAX_CLIPS*32],buffer[8192],digest[32];
    lxaf_info_t info;int result=1;BCRYPT_ALG_HANDLE algorithm=NULL;BCRYPT_HASH_HANDLE hash=NULL;
    if(fseek(file,0,SEEK_END))goto done;
    long size=ftell(file);if(size<64 || (unsigned long)size>LXAF_MAX_FILE_BYTES || fseek(file,0,SEEK_SET))goto done;
    if(fread(header,1,64,file)!=64)goto done;
    unsigned count=header[14]|(unsigned)header[15]<<8;
    if(!count || count>LXAF_MAX_CLIPS || fread(index,32,count,file)!=count ||
       !lxaf_parse(header,index,count*32,(uint32_t)size,&info)){fprintf(stderr,"Invalid LXAF metadata\n");goto done;}
    if(BCryptOpenAlgorithmProvider(&algorithm,BCRYPT_SHA256_ALGORITHM,NULL,0) ||
       BCryptCreateHash(algorithm,&hash,NULL,0,NULL,0,0) || BCryptHashData(hash,index,count*32,0))goto done;
    uint32_t crc[LXAF_MAX_CLIPS];for(unsigned i=0;i<count;++i)crc[i]=0xffffffffu;
    uint32_t offset=info.data_offset;
    while(offset<(uint32_t)size){
        size_t bytes=(uint32_t)size-offset;if(bytes>sizeof(buffer))bytes=sizeof(buffer);
        if(fread(buffer,1,bytes,file)!=bytes || BCryptHashData(hash,buffer,(ULONG)bytes,0))goto done;
        for(unsigned i=0;i<count;++i){
            lxaf_clip_t *clip=&info.clips[i];
            uint32_t first=offset>clip->offset?offset:clip->offset;
            uint32_t last=offset+bytes<clip->offset+clip->bytes?offset+bytes:clip->offset+clip->bytes;
            if(last>first)crc[i]=lxaf_crc32_update(crc[i],buffer+first-offset,last-first);
        }
        offset+=(uint32_t)bytes;
    }
    if(BCryptFinishHash(hash,digest,sizeof(digest),0) || memcmp(digest,info.sha256,32)){
        fprintf(stderr,"SHA256 mismatch\n");goto done;
    }
    for(unsigned i=0;i<count;++i){
        lxaf_clip_t *clip=&info.clips[i];
        if((crc[i]^0xffffffffu)!=clip->crc32){fprintf(stderr,"CRC32 mismatch at clip %u\n",i);goto done;}
        uint8_t *payload=malloc(clip->bytes),*frame=malloc(LXAF_FRAME_BYTES);
        if(!payload || !frame){free(payload);free(frame);goto done;}
        bool valid=!fseek(file,clip->offset,SEEK_SET) && fread(payload,1,clip->bytes,file)==clip->bytes &&
            lxaf_validate_clip(clip,payload,clip->bytes);
        for(unsigned n=0;valid && n<clip->frames;++n)
            valid=lxaf_decode_frame(clip,payload,clip->bytes,n,frame,LXAF_FRAME_BYTES);
        free(payload);free(frame);
        if(!valid){fprintf(stderr,"Frame decode failed at clip %u\n",i);goto done;}
    }
    printf("OK: version %u; %ld bytes; %u clips; SHA256, all CRC32, every frame decode verified\n",info.version,size,count);
    for(unsigned i=0;i<count;++i)printf("avatar=%u state=%u frames=%u frame_ms=%u loop=%u\n",
        info.clips[i].avatar,info.clips[i].state,info.clips[i].frames,info.clips[i].frame_ms,info.clips[i].flags&1u);
    result=0;
done:
    if(hash)BCryptDestroyHash(hash);
    if(algorithm)BCryptCloseAlgorithmProvider(algorithm,0);
    fclose(file);return result;
}
static void set16(uint8_t *p,unsigned v){p[0]=v;p[1]=v>>8;}
static void set32(uint8_t *p,uint32_t v){for(unsigned i=0;i<4;++i)p[i]=v>>(i*8);}
static int self_test(void)
{
    uint8_t h[64]={0},indices[64]={0};lxaf_info_t info;
    memcpy(h,"LXAF",4);set16(h+4,1);set16(h+6,64);set16(h+8,128);set16(h+10,128);
    set16(h+12,1);set16(h+14,2);set32(h+16,64);set32(h+20,128);set32(h+24,128+2*LXAF_FRAME_BYTES);h[32]=1;
    for(unsigned i=0;i<2;++i){uint8_t *p=indices+i*32;p[1]=i;set16(p+4,1);set16(p+6,83);set32(p+8,128+i*LXAF_FRAME_BYTES);set32(p+12,LXAF_FRAME_BYTES);}
    uint32_t size=128+2*LXAF_FRAME_BYTES;
    if(!lxaf_parse(h,indices,64,size,&info))return 1;
    indices[33]=0;if(lxaf_parse(h,indices,64,size,&info))return 2;indices[33]=1;
    set32(indices+40,128);if(lxaf_parse(h,indices,64,size,&info))return 3;
    set32(indices+40,0xfffffff0u);if(lxaf_parse(h,indices,64,size,&info))return 4;
    set32(indices+40,128+LXAF_FRAME_BYTES);set16(indices+36,97);if(lxaf_parse(h,indices,64,size,&info))return 5;
    set16(indices+36,1);indices[52]=1;if(lxaf_parse(h,indices,64,size,&info))return 6;
    indices[52]=0;if(lxaf_parse(h,indices,63,size,&info) || lxaf_parse(h,indices,64,size-1,&info))return 7;
    if((lxaf_crc32_update(0xffffffffu,(const uint8_t*)"123456789",9)^0xffffffffu)!=0xcbf43926u)return 8;
    uint8_t packed[520]={0},decoded[LXAF_FRAME_BYTES];
    set32(packed,8);set32(packed+4,512);
    for(unsigned n=0;n<128;++n){packed[8+n*4]=255;packed[9+n*4]=12;packed[10+n*4]=34;packed[11+n*4]=255;}
    lxaf_clip_t clip={.flags=LXAF_FLAG_RLE3,.frames=1,.frame_ms=50,.bytes=sizeof(packed)};
    if(!lxaf_validate_clip(&clip,packed,sizeof(packed)) || !lxaf_decode_frame(&clip,packed,sizeof(packed),0,decoded,sizeof(decoded)))return 9;
    for(unsigned n=0;n<LXAF_FRAME_BYTES;n+=3)if(decoded[n]!=12 || decoded[n+1]!=34 || decoded[n+2]!=255)return 10;
    if(lxaf_decode_frame(&clip,packed,sizeof(packed),1,decoded,sizeof(decoded)) ||
       lxaf_decode_frame(&clip,packed,sizeof(packed),0,decoded,sizeof(decoded)-1) ||
       lxaf_validate_clip(&clip,packed,sizeof(packed)-1))return 11;
    set32(packed,7);if(lxaf_validate_clip(&clip,packed,sizeof(packed)))return 12;
    set32(packed,8);packed[8]=254;if(lxaf_validate_clip(&clip,packed,sizeof(packed)))return 13;
    puts("OK: metadata bounds/duplicates, CRC32 known vector, RLE3 full decode/truncation/directory/output rejection");return 0;
}
int main(int argc,char **argv)
{
    if(argc==2 && !strcmp(argv[1],"--self-test"))return self_test();
    if(argc!=2){fprintf(stderr,"Usage: lxaf_verify.exe --self-test | package.lxaf\n");return 2;}
    return verify(argv[1]);
}
