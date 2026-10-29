#include "lxff_format.h"
#include <string.h>
static uint16_t le16(const uint8_t *p) { return p[0] | (uint16_t)p[1] << 8; }
static uint32_t le32(const uint8_t *p) { return le16(p) | (uint32_t)le16(p+2) << 16; }
unsigned lxff_tone_id(const char *tone)
{ return tone && !strcmp(tone,"calm") ? 1 : tone && !strcmp(tone,"cheerful") ? 2 : tone && !strcmp(tone,"direct") ? 3 : 0; }
uint32_t lxff_crc32_update(uint32_t crc,const uint8_t *data,size_t n)
{ while(n--){crc^=*data++;for(unsigned b=0;b<8;b++)crc=(crc>>1)^((crc&1)?0xedb88320u:0);}return crc; }
bool lxff_parse(const uint8_t h[64],const uint8_t *index,size_t n,uint32_t size,lxff_info_t *out)
{
    if(!h || !index || !out || size<320 || size>LXFF_MAX_FILE_BYTES || n!=256 ||
       memcmp(h,"LXFF",4) || le16(h+4)!=1 || le16(h+6)!=64 || le32(h+8)!=size ||
       le16(h+12)!=4 || le16(h+14)!=12 || le32(h+16)!=64 || le32(h+20))return false;
    for(unsigned i=24;i<32;i++)if(h[i])return false;
    memset(out,0,sizeof(*out));out->total_bytes=size;memcpy(out->sha256,h+32,32);
    uint32_t previous=320;
    for(unsigned i=0;i<4;i++){
        const uint8_t *p=index+i*64;lxff_font_t *f=&out->fonts[i];
        f->tone=p[0];f->pixel_size=p[1];f->line_height=p[2];f->alpha_bits=p[3];
        f->glyph_count=le32(p+4);f->glyph_offset=le32(p+8);f->glyph_bytes=le32(p+12);
        f->alpha_offset=le32(p+16);f->alpha_bytes=le32(p+20);f->crc32=le32(p+24);
        memcpy(f->name,p+32,32);f->name[32]=0;
        if(f->tone!=i || f->pixel_size!=20 || f->line_height!=26 || f->alpha_bits!=2 ||
           f->glyph_count<6858 || f->glyph_count>12000 || f->glyph_bytes!=f->glyph_count*12 ||
           f->glyph_offset!=previous || f->alpha_offset!=(uint64_t)f->glyph_offset+f->glyph_bytes ||
           (uint64_t)f->alpha_offset+f->alpha_bytes>size || !f->alpha_bytes ||
           (uint64_t)f->glyph_bytes+f->alpha_bytes>LXFF_MAX_CACHE_BYTES || le32(p+28))return false;
        previous=f->alpha_offset+f->alpha_bytes;
    }
    return previous==size;
}
static void unpack(const uint8_t *p,lxff_glyph_t *g)
{g->codepoint=le32(p);g->offset=le32(p+4);g->width=p[8];g->height=p[9];g->advance=p[10];g->bearing_x=(int8_t)p[11];}
bool lxff_validate_view(const lxff_view_t *v)
{
    if(!v || !v->glyphs || !v->alpha)return false;
    uint32_t code=0,offset=0;bool question=false;
    for(uint32_t i=0;i<v->font.glyph_count;i++){
        lxff_glyph_t g;unpack(v->glyphs+i*12,&g);
        uint32_t bytes=((uint32_t)g.width*g.height+3)/4;
        if(g.codepoint<=code || g.codepoint>0x10ffff || (g.codepoint>=0xd800 && g.codepoint<=0xdfff) ||
           !g.width || g.width>32 || g.height!=26 || !g.advance || g.advance>32 ||
           g.bearing_x < -8 || g.bearing_x > 8 || g.offset!=offset ||
           (uint64_t)g.offset+bytes>v->font.alpha_bytes)return false;
        if(g.codepoint=='?')question=true;
        code=g.codepoint;offset+=bytes;
    }
    return question && offset==v->font.alpha_bytes;
}
bool lxff_glyph(const lxff_view_t *v,uint32_t code,lxff_glyph_t *out)
{
    if(!v || !out || !v->glyphs || !v->alpha)return false;
    uint32_t lo=0,hi=v->font.glyph_count;
    while(lo<hi){uint32_t mid=lo+(hi-lo)/2;if(le32(v->glyphs+mid*12)<code)lo=mid+1;else hi=mid;}
    if(lo<v->font.glyph_count && le32(v->glyphs+lo*12)==code){unpack(v->glyphs+lo*12,out);return true;}
    return code!='?' && lxff_glyph(v,'?',out);
}
