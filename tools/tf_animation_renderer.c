/* Host-only sprite animation renderer. Source textures remain immutable.
 * This is deliberately separate from ESP32 display ownership and audio tasks.
 * All visible poses come from the six supplied, artist-rendered textures.
 */
#include <math.h>
#include <stdint.h>
#include <string.h>
#include "ui_mascot.h"
#include "ui_kangaroo.h"
#include "ui_badge.h"

#define SIZE 128
#define POSES 6
#define AVATARS 5
#define PI 3.14159265358979323846f
typedef struct { float r,g,b,a; } rgba_t;
static const uint16_t *colors[AVATARS] = { &ui_kangaroo_rgb565[0][0], &ui_mascot_rgb565[0][0], 0,0,0 };
static const uint8_t *alphas[AVATARS] = { &ui_kangaroo_alpha[0][0], &ui_mascot_alpha[0][0], 0,0,0 };
static float limit(float v,float lo,float hi){return v<lo?lo:v>hi?hi:v;}
static float smooth(float x){x=limit(x,0,1);return x*x*(3-2*x);}
static rgba_t zero(void){rgba_t p={0,0,0,0};return p;}
static rgba_t read_texel(int avatar,int pose,int x,int y)
{
    if(x<0||x>=SIZE||y<0||y>=SIZE||!colors[avatar]||!alphas[avatar])return zero();
    int i=pose*SIZE*SIZE+y*SIZE+x;
    float a=alphas[avatar][i]/255.f;
    uint16_t c=colors[avatar][i];
    rgba_t p={((c>>11)*255.f/31)*a,(((c>>5)&63)*255.f/63)*a,((c&31)*255.f/31)*a,a};
    if(avatar==0){
        int bx=x-ui_kangaroo_badge_centers[pose][0]+UI_BADGE_SIZE/2;
        int by=y-ui_kangaroo_badge_centers[pose][1]+UI_BADGE_SIZE/2;
        if(bx>=0&&bx<UI_BADGE_SIZE&&by>=0&&by<UI_BADGE_SIZE){
            int j=by*UI_BADGE_SIZE+bx;float ba=ui_badge_alpha[j]/255.f;
            uint16_t bc=ui_badge_rgb565[j];
            p.r=(bc>>11)*255.f/31*ba+p.r*(1-ba);
            p.g=((bc>>5)&63)*255.f/63*ba+p.g*(1-ba);
            p.b=(bc&31)*255.f/31*ba+p.b*(1-ba);
            p.a=ba+p.a*(1-ba);
        }
    }
    return p;
}
static rgba_t lerp(rgba_t a,rgba_t b,float t)
{rgba_t p={a.r+(b.r-a.r)*t,a.g+(b.g-a.g)*t,a.b+(b.b-a.b)*t,a.a+(b.a-a.a)*t};return p;}
static rgba_t sample(int avatar,int pose,float x,float y)
{
    int x0=(int)floorf(x),y0=(int)floorf(y);float fx=x-x0,fy=y-y0;
    return lerp(lerp(read_texel(avatar,pose,x0,y0),read_texel(avatar,pose,x0+1,y0),fx),
                lerp(read_texel(avatar,pose,x0,y0+1),read_texel(avatar,pose,x0+1,y0+1),fx),fy);
}
int tf_set_avatar(int avatar,const uint16_t *rgb565,const uint8_t *alpha)
{if(avatar<2||avatar>=AVATARS||!rgb565||!alpha)return 0;colors[avatar]=rgb565;alphas[avatar]=alpha;return 1;}

/* Every state includes genuine expression/gesture poses, as well as the
 * small continuous transforms. Speaking is an expressive preset loop,
 * not phoneme-accurate or automatically synchronized to a TTS waveform. */
static void pose_at(int state,float t,int *a,int *b,float *blend)
{
    *a=*b=0;*blend=0;
    if(state==0){
        float blink=0;
        if(t>.29f&&t<.40f)blink=sinf((t-.29f)/.11f*PI);
        if(t>.73f&&t<.79f)blink=sinf((t-.73f)/.06f*PI);
        *b=1;*blend=smooth(blink);
    }else if(state==1||state==2||state==4){
        int pose=state==1?2:state==2?3:5;
        *b=pose;*blend=smooth(fminf(t/.15f,(1-t)/.15f));
    }else if(state==3){
        float cycle=fmodf(t*2.f,1.f);
        *b=4;
        /* Two small conversational waves, with an actual closed-mouth
         * idle pose between open-mouth happy poses. */
        *blend=smooth(fminf(cycle/.16f,(1-cycle)/.16f));
    }else if(state==5){
        if(t<.72f){*b=4;*blend=smooth(fminf(t/.15f,(.80f-t)/.18f));}
        else{*b=1;*blend=sinf((t-.72f)/.28f*PI)*.70f;}
    }
}
int tf_render_frame(uint8_t *out,int avatar,int state,int frame,int count)
{
    if(!out||avatar<0||avatar>=AVATARS||state<0||state>5||frame<0||frame>=count||count<2||!colors[avatar])return 0;
    const float t=frame/(float)count, phase=2*PI*t;
    int pa,pb;float blend;pose_at(state,t,&pa,&pb,&blend);
    float sx=.935f,sy=.935f,dy=-.7f*(1-cosf(phase)),dx=.5f*sinf(phase),angle=.006f*sinf(phase);
    if(state==0){sy+=.009f*sinf(phase);}
    if(state==1){angle=.017f*sinf(phase);dy=-1.1f*(1-cosf(phase));}
    if(state==2){angle=-.012f*sinf(phase);dx=.75f*sinf(phase);}
    if(state==3){angle=.018f*sinf(phase*2);dy=-1.0f*(1-cosf(phase*2));}
    if(state==4){angle=.009f*sinf(phase);dy=-.65f*(1-cosf(phase));}
    if(state==5){float hop=sinf(PI*t);dy=-5.5f*hop;sx+=.025f*hop;sy+=.025f*hop;angle=.055f*sinf(phase*2)*hop;}
    float co=cosf(angle),si=sinf(angle);
    for(int y=0;y<SIZE;y++)for(int x=0;x<SIZE;x++){
        float xx=x-64-dx,yy=y-123-dy;
        float u=(xx*co+yy*si)/sx+64,v=(-xx*si+yy*co)/sy+123;
        /* A tiny soft ear/leaf flex; the face and badge never get warped. */
        if(v<35)u-=.40f*sinf(phase+v*.04f)*(35-v)/35;
        rgba_t p=lerp(sample(avatar,pa,u,v),sample(avatar,pb,u,v),blend);
        int alpha=(int)floorf(limit(p.a,0,1)*255+.5f);
        uint16_t c=0;
        if(alpha>8&&p.a>0){
            unsigned r=(unsigned)floorf(limit(p.r/p.a,0,255)+.5f);
            unsigned g=(unsigned)floorf(limit(p.g/p.a,0,255)+.5f);
            unsigned b=(unsigned)floorf(limit(p.b/p.a,0,255)+.5f);
            c=(uint16_t)(((r>>3)<<11)|((g>>2)<<5)|(b>>3));
        }else alpha=0;
        int o=(y*SIZE+x)*3;out[o]=(uint8_t)c;out[o+1]=(uint8_t)(c>>8);out[o+2]=(uint8_t)alpha;
    }
    return 1;
}
