/* Windows independent verifier of the same portable parser used on ESP32.
 * gcc -std=c11 -O2 -Wall -Wextra -Werror tools/lxff_verify.c main/lxff_format.c -lbcrypt -o lxff_verify.exe
 */
#include <windows.h>
#include <bcrypt.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include "../main/lxff_format.h"
static int failures;
static void require(bool condition,const char *name)
{if(!condition){fprintf(stderr,"FAIL: %s\n",name);failures++;}}
static void put32(uint8_t *p,uint32_t v){for(unsigned i=0;i<4;i++)p[i]=v>>(8*i);}
int main(int argc,char **argv)
{
    if(argc!=2){fprintf(stderr,"Usage: lxff_verify FILE\n");return 2;}
    FILE *f=fopen(argv[1],"rb");if(!f){perror(argv[1]);return 2;}
    fseek(f,0,SEEK_END);long bytes=ftell(f);rewind(f);
    if(bytes<320 || (unsigned long)bytes>LXFF_MAX_FILE_BYTES){fclose(f);return 1;}
    uint8_t *raw=malloc(bytes);if(!raw){fclose(f);return 2;}
    if(fread(raw,1,bytes,f)!=(size_t)bytes){fclose(f);free(raw);return 1;}fclose(f);
    lxff_info_t info;require(lxff_parse(raw,raw+64,256,bytes,&info),"valid pack metadata");
    if(failures){free(raw);return 1;}
    BCRYPT_ALG_HANDLE alg=NULL;BCRYPT_HASH_HANDLE hash=NULL;uint8_t digest[32];
    require(!BCryptOpenAlgorithmProvider(&alg,BCRYPT_SHA256_ALGORITHM,NULL,0),"SHA provider");
    require(!BCryptCreateHash(alg,&hash,NULL,0,NULL,0,0),"SHA init");
    require(!BCryptHashData(hash,raw+64,bytes-64,0),"SHA body");
    require(!BCryptFinishHash(hash,digest,32,0) && !memcmp(digest,info.sha256,32),"SHA digest");
    BCryptDestroyHash(hash);BCryptCloseAlgorithmProvider(alg,0);
    for(unsigned i=0;i<4;i++){
        lxff_font_t *font=&info.fonts[i];
        lxff_view_t view={.glyphs=raw+font->glyph_offset,.alpha=raw+font->alpha_offset,.font=*font};
        uint32_t crc=lxff_crc32_update(0xffffffffu,view.glyphs,font->glyph_bytes+font->alpha_bytes)^0xffffffffu;
        require(crc==font->crc32,"per-font CRC");require(lxff_validate_view(&view),"strict glyph validation");
        lxff_glyph_t g,q;
        require(lxff_glyph(&view,0x4e2d,&g) && g.codepoint==0x4e2d && g.advance==20,"Chinese glyph lookup");
        require(lxff_glyph(&view,0x10ffff,&q) && q.codepoint=='?',"unknown glyph fallback");
        for(unsigned a=32;a<127;a++)require(lxff_glyph(&view,a,&g) && g.codepoint==a,"complete ASCII coverage");
        uint8_t saved=((uint8_t*)view.glyphs)[4];((uint8_t*)view.glyphs)[4]=255;
        require(!lxff_validate_view(&view),"reject corrupt first glyph offset");((uint8_t*)view.glyphs)[4]=saved;
        saved=((uint8_t*)view.glyphs)[9];((uint8_t*)view.glyphs)[9]=255;
        require(!lxff_validate_view(&view),"reject glyph height overflow");((uint8_t*)view.glyphs)[9]=saved;
        printf("tone=%u %s glyphs=%lu cache=%lu bytes; valid\n",i,font->name,(unsigned long)font->glyph_count,(unsigned long)(font->glyph_bytes+font->alpha_bytes));
    }
    uint8_t h[64],index[256];memcpy(h,raw,64);memcpy(index,raw+64,256);
    h[12]=255;require(!lxff_parse(h,index,256,bytes,&info),"reject invalid font count");memcpy(h,raw,64);
    h[24]=1;require(!lxff_parse(h,index,256,bytes,&info),"reject reserved header flags");memcpy(h,raw,64);
    require(!lxff_parse(h,index,255,bytes,&info),"reject truncated index");
    require(!lxff_parse(h,index,256,bytes-1,&info),"reject truncated file");
    put32(index+16,0xfffffff0u);require(!lxff_parse(h,index,256,bytes,&info),"reject overflowing alpha offset");memcpy(index,raw+64,256);
    put32(index+8,321);require(!lxff_parse(h,index,256,bytes,&info),"reject glyph range gap");memcpy(index,raw+64,256);
    index[64]=0;require(!lxff_parse(h,index,256,bytes,&info),"reject duplicate tone id");
    require(lxff_tone_id("warm")==0 && lxff_tone_id("calm")==1 && lxff_tone_id("cheerful")==2 && lxff_tone_id("direct")==3,"tone mapping");
    printf("%s: independent SHA256, four CRC32, all glyphs and negative boundary tests\n",failures?"FAIL":"PASS");
    free(raw);return failures?1:0;
}
