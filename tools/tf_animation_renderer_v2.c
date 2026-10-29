/* Offline 2-D texture rig. Immutable 512px artist poses; no whole-pose dissolve.
 * Every state has a single body texture, continuously deformed around local
 * head/ear/arm/tail pivots. No image generation, repainting, LCD or audio IO.
 */
#include <math.h>
#include <stdint.h>
#include <stddef.h>

#define SIDE 512
#define PI 3.14159265358979323846f
static const uint8_t *textures[5];
static const uint8_t *badge;
static int badge_side;
static float badge_centers[6][2]={{274,366},{270,366},{261,370},{278,358},{253,345},{257,349}};
static float badge_width=111;
typedef struct { float r,g,b,a; } px_t;
static float clamp(float v,float a,float b){return v<a?a:v>b?b:v;}
static float ease(float x){x=clamp(x,0,1);return x*x*(3-2*x);}
static float support(float x,float y,float cx,float cy,float rx,float ry)
{float xx=(x-cx)/rx,yy=(y-cy)/ry,d=1-xx*xx-yy*yy;return d>0?d*d:0;}
static float pulse(float t,float start,float width)
{float q=(t-start)/width;if(q<=0||q>=1)return 0;return sinf(q*PI);}
static px_t empty(void){px_t p={0,0,0,0};return p;}
int tf2_set_avatar(int avatar,const uint8_t *rgba)
{if(avatar<0||avatar>4||!rgba)return 0;textures[avatar]=rgba;return 1;}
int tf2_set_badge(const uint8_t *rgba,int size)
{if(!rgba||size<16||size>1024)return 0;badge=rgba;badge_side=size;return 1;}
static px_t texel(int avatar,int pose,int x,int y)
{
    if(x<0||x>=SIDE||y<0||y>=SIDE)return empty();
    const uint8_t *p=textures[avatar]+((pose*SIDE+y)*SIDE+x)*4;
    float a=p[3]/255.f;px_t out={p[0]*a,p[1]*a,p[2]*a,a};
    if(avatar==0&&badge){
        float bx=(x-badge_centers[pose][0])/badge_width+.5f,by=(y-badge_centers[pose][1])/badge_width+.5f;
        /* Blue furry paws remain in front of an embroidered chest patch. */
        int blue_paw=p[2]>p[0]*1.15f&&p[2]>p[1]*1.10f;
        if(bx>=0&&bx<1&&by>=0&&by<1&&!blue_paw){
            const uint8_t *b=badge+((int)(by*badge_side)*badge_side+(int)(bx*badge_side))*4;
            float ba=b[3]/255.f;out.r=b[0]*ba+out.r*(1-ba);out.g=b[1]*ba+out.g*(1-ba);
            out.b=b[2]*ba+out.b*(1-ba);out.a=ba+out.a*(1-ba);
        }
    }
    return out;
}
static px_t mix(px_t a,px_t b,float t)
{px_t p={a.r+(b.r-a.r)*t,a.g+(b.g-a.g)*t,a.b+(b.b-a.b)*t,a.a+(b.a-a.a)*t};return p;}
static px_t sample(int avatar,int pose,float u,float v)
{
    int x=(int)floorf(u),y=(int)floorf(v);float fx=u-x,fy=v-y;
    return mix(mix(texel(avatar,pose,x,y),texel(avatar,pose,x+1,y),fx),
               mix(texel(avatar,pose,x,y+1),texel(avatar,pose,x+1,y+1),fx),fy);
}
/* Artist eye landmarks in the original atlas cells. Only the eye-sized
 * neighborhood deforms; cheeks, ears, nose and body cannot double-expose. */
static float eyes[5][6][4]={
 {{257,151,318,164},{213,153,289,170},{177,146,236,160},{250,154,307,172},{245,161,307,178},{225,161,288,173}},
 {{207,254,338,245},{201,266,322,254},{239,230,358,219},{230,237,347,210},{197,239,323,223},{210,253,338,247}},
 {{214,210,323,177},{220,224,331,195},{242,222,354,184},{236,209,352,169},{241,198,353,160},{243,212,355,175}},
 {{194,183,327,145},{184,189,333,156},{194,192,328,151},{195,161,325,118},{194,165,326,116},{194,179,325,143}},
 {{167,209,295,242},{163,223,303,258},{166,207,292,247},{165,184,286,229},{169,168,303,210},{177,175,302,218}}
};
int tf2_set_landmarks(int avatar,const float *eye_positions,const float *centers,float width)
{
    if(avatar<0||avatar>4||!eye_positions)return 0;
    for(int pose=0;pose<6;++pose)for(int n=0;n<4;++n)eyes[avatar][pose][n]=eye_positions[pose*4+n];
    if(avatar==0&&centers){for(int i=0;i<6;++i)for(int j=0;j<2;++j)badge_centers[i][j]=centers[i*2+j];badge_width=width;}
    return 1;
}

int tf2_render(uint8_t *out,int avatar,int state,int frame,int frames,int size)
{
    if(!out||avatar<0||avatar>4||state<0||state>5||frame<0||frame>=frames||frames<2||size<64||size>1024||!textures[avatar])return 0;
    static const int poses[6]={0,2,3,4,5,4};
    int pose=poses[state];float t=frame/(float)(state==5?frames-1:frames),p=2*PI*t;
    float breath=sinf(p),head_angle=.022f*sinf(p+.35f),head_y=1.4f*sinf(p+.4f);
    float body_scale=.008f*breath,hand_angle=0,tail_angle=.03f*sinf(p-.7f);
    float ear_flex=3.8f*sinf(p-.8f),global_y=0,global_x=0,global_scale=1;
    float blink=powf(pulse(t,.34f,.055f),1.5f);
    if(state==1){
        head_angle=.045f*sinf(p)*.8f;head_y=-3*ease(pulse(t,.03f,.88f));
        ear_flex=5.5f*sinf(p+.2f);hand_angle=.035f*sinf(p*2);
        blink=powf(pulse(t,.68f,.06f),1.5f);
    }else if(state==2){
        head_angle=-.038f*sinf(p)*.8f;head_y=-2.4f*(1-cosf(p));
        hand_angle=.05f*sinf(p*2-.2f);ear_flex=3.5f*sinf(p+.8f);
        blink=powf(pulse(t,.56f,.055f),1.5f);
    }else if(state==3){
        head_angle=.023f*sinf(p*3)+.008f*sinf(p*5);head_y=2.1f*sinf(p*3-.4f);
        hand_angle=.16f*sinf(p*2)*(.45f+.55f*ease(pulse(t,.02f,.94f)));
        ear_flex=3.4f*sinf(p*2-1);body_scale=.009f*sinf(p*2);
        blink=powf(pulse(t,.71f,.05f),1.5f);
    }else if(state==4){
        head_angle=.032f*sinf(p);head_y=1.5f*sinf(p-.2f);
        hand_angle=.045f*sinf(p-.7f);tail_angle=.025f*sinf(p-.8f);
        blink=powf(pulse(t,.43f,.09f),1.5f);
    }else if(state==5){
        float anticipation=pulse(t,.02f,.17f),jump=pulse(t,.18f,.42f),settle=pulse(t,.61f,.25f);
        head_y=0;global_y=7*anticipation-24*jump+3*settle;global_scale=1-.018f*anticipation+.018f*jump;
        body_scale=-.025f*anticipation+.018f*jump-.01f*settle;
        hand_angle=.20f*sinf(p*3)*ease(pulse(t,.02f,.93f));head_angle=.04f*sinf(p*2)*jump;
        ear_flex=6.5f*sinf(p*2-.5f)*jump;tail_angle=.06f*sinf(p-.4f)*jump;
        blink=powf(pulse(t,.78f,.08f),1.5f);
    }
    float ear_limit=avatar==0?170:avatar==1?150:135;
    float head_limit=avatar==0?300:avatar==1?345:avatar==4?338:335;
    float hand_x=avatar==0?150:avatar==1?368:avatar==2?410:avatar==3?384:370;
    float hand_y=avatar==0?245:avatar==1?320:avatar==2?320:avatar==3?307:315;
    float tail_x=avatar==0?455:avatar==2?90:avatar==3?445:avatar==4?415:440;
    float unit=512.f/size;
    for(int y=0;y<size;++y)for(int x=0;x<size;++x){
        float ox=(x+.5f)*unit,oy=(y+.5f)*unit;
        float u=(ox-256-global_x)/(.96f*global_scale)+256;
        float v=(oy-488-global_y)/(.96f*global_scale)+500;
        /* Feet remain planted. The torso breath is phase-shifted from the
         * head, so it feels like a soft toy with weight, not a floating card. */
        float chest=support(u,v,275,370,180,135);u=275+(u-275)/(1+body_scale*chest);
        v-=3.5f*body_scale*100*chest;
        float hw=ease((head_limit-v)/95.f),a=head_angle*hw;
        float ca=cosf(a),sa=sinf(a),hx=u-270,hy=v-(head_limit+5);
        u=270+hx*ca+hy*sa;v=head_limit+5-hx*sa+hy*ca-head_y*hw;
        float ew=ease((ear_limit-v)/100.f);u-=ear_flex*ew*(u-270)/180.f;
        float arm=support(u,v,hand_x,hand_y,90,140),aa=hand_angle*arm;
        ca=cosf(aa);sa=sinf(aa);hx=u-hand_x;hy=v-(hand_y+85);
        u=hand_x+hx*ca+hy*sa;v=hand_y+85-hx*sa+hy*ca;
        float tw=support(u,v,tail_x,385,100,120);u-=tail_angle*70*tw;v-=tail_angle*35*tw;
        /* Gently flex the existing open mouth around its lower-lip pivot. */
        if(state==3||state==5){
            float mx=avatar==0?267:avatar==1?266:avatar==2?296:avatar==3?278:274;
            float my=avatar==0?244:avatar==1?296:avatar==2?249:avatar==3?264:270;
            float mouth=support(u,v,mx,my,48,35);
            float talk=.12f*sinf(p*5)+.07f*sinf(p*3+.5f);
            v=my+(v-my)/(1+talk*mouth);
        }
        px_t q=sample(avatar,pose,u,v);
        /* Local artist-rendered eyelid patches replace the complete eye
         * footprint for a short natural blink. No white-eye compression and
         * no full-body pose blend. Fur outside the eye region never changes. */
        if(blink>.001f&&!(avatar==1&&pose==4)){
            float closure=ease(blink*1.8f);
            for(int eye=0;eye<2;++eye){
                float ex=eyes[avatar][pose][eye*2],ey=eyes[avatar][pose][eye*2+1];
                float rx=avatar==0?35:avatar==1?58:avatar==2?54:47;
                float ry=avatar==0?32:avatar==1?55:avatar==2?48:44;
                float dx=(u-ex)/rx,dy=(v-ey)/ry,d=dx*dx+dy*dy;
                float mask=1-ease((d-.72f)/.28f);
                if(mask>0){
                    float cx=eyes[avatar][1][eye*2],cy=eyes[avatar][1][eye*2+1];
                    /* Eyelid sweeps spatially across the pupil. It covers
                     * registered texture instead of making the iris gray. */
                    float boundary=ey-ry+2*ry*closure;
                    float cover=ease((boundary-v+1.5f)/3.f);
                    q=mix(q,sample(avatar,1,cx+u-ex,cy+v-ey),cover*mask);
                }
            }
        }
        int i=(y*size+x)*4;
        if(q.a<=.01f){out[i]=out[i+1]=out[i+2]=out[i+3]=0;continue;}
        out[i]=(uint8_t)clamp(q.r/q.a+.5f,0,255);out[i+1]=(uint8_t)clamp(q.g/q.a+.5f,0,255);
        out[i+2]=(uint8_t)clamp(q.b/q.a+.5f,0,255);out[i+3]=(uint8_t)clamp(q.a*255+.5f,0,255);
    }
    return 1;
}
