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
static float badge_centers[10][2]={{274,366},{270,366},{261,370},{278,358},{253,345},{257,349}};
static float badge_width=111;
static float badge_widths[10];
typedef struct { float r,g,b,a; } px_t;
static float clamp(float v,float a,float b){return v<a?a:v>b?b:v;}
static float ease(float x){x=clamp(x,0,1);return x*x*(3-2*x);}
static float support(float x,float y,float cx,float cy,float rx,float ry)
{float xx=(x-cx)/rx,yy=(y-cy)/ry,d=1-xx*xx-yy*yy;return d>0?d*d:0;}
static float pulse(float t,float start,float width)
{float q=(t-start)/width;if(q<=0||q>=1)return 0;return sinf(q*PI);}
static px_t empty(void){px_t p={0,0,0,0};return p;}
int tf3_set_avatar(int avatar,const uint8_t *rgba)
{if(avatar<0||avatar>4||!rgba)return 0;textures[avatar]=rgba;return 1;}
int tf3_set_badge(const uint8_t *rgba,int size)
{if(!rgba||size<16||size>1024)return 0;badge=rgba;badge_side=size;return 1;}
static px_t texel(int avatar,int pose,int x,int y)
{
    if(x<0||x>=SIDE||y<0||y>=SIDE)return empty();
    const uint8_t *p=textures[avatar]+((pose*SIDE+y)*SIDE+x)*4;
    float a=p[3]/255.f;px_t out={p[0]*a,p[1]*a,p[2]*a,a};
    if(avatar==0&&badge){
        float bw=badge_widths[pose]>0?badge_widths[pose]:badge_width;
        float bx=(x-badge_centers[pose][0])/bw+.5f,by=(y-badge_centers[pose][1])/bw+.5f;
        /* Blue furry paws remain in front of an embroidered chest patch. */
        int blue_paw=p[2]>p[0]*1.15f&&p[2]>p[1]*1.10f;
        if(bx>=0&&bx<1&&by>=0&&by<1&&!blue_paw){
            const uint8_t *b=badge+((int)(by*badge_side)*badge_side+(int)(bx*badge_side))*4;
            float ba=b[3]/255.f;
            /* A chest patch may tint existing body pixels, never expand the
               character silhouette into transparent background. */
            out.r=(b[0]*ba+p[0]*(1-ba))*a;out.g=(b[1]*ba+p[1]*(1-ba))*a;
            out.b=(b[2]*ba+p[2]*(1-ba))*a;out.a=a;
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
static float eyes[5][10][4]={
 {{257,151,318,164},{213,153,289,170},{177,146,236,160},{250,154,307,172},{245,161,307,178},{225,161,288,173}},
 {{207,254,338,245},{201,266,322,254},{239,230,358,219},{230,237,347,210},{197,239,323,223},{210,253,338,247}},
 {{214,210,323,177},{220,224,331,195},{242,222,354,184},{236,209,352,169},{241,198,353,160},{243,212,355,175}},
 {{194,183,327,145},{184,189,333,156},{194,192,328,151},{195,161,325,118},{194,165,326,116},{194,179,325,143}},
 {{167,209,295,242},{163,223,303,258},{166,207,292,247},{165,184,286,229},{169,168,303,210},{177,175,302,218}}
};
int tf3_set_landmarks(int avatar,const float *eye_positions,const float *centers,float width)
{
    if(avatar<0||avatar>4||!eye_positions)return 0;
    for(int pose=0;pose<10;++pose)for(int n=0;n<4;++n)eyes[avatar][pose][n]=eye_positions[pose*4+n];
    if(avatar==0&&centers){for(int i=0;i<10;++i)for(int j=0;j<2;++j)badge_centers[i][j]=centers[i*2+j];badge_width=width;}
    return 1;
}

int tf3_set_badge_widths(const float *widths)
{if(!widths)return 0;for(int i=0;i<10;++i)badge_widths[i]=widths[i];return 1;}


/* Limb regions are authored in the canonical 512 px cells produced by
 * load_atlas/extra_art, not in the unnormalised artist contact sheet.  The
 * polygon follows the visible arm and has transparent padding; the circular
 * shoulder transition is the only skinned part of an otherwise rigid limb.
 * In particular it cannot select the feet, chest patch or the whole canvas. */
typedef struct { float x,y; } point_t;
typedef struct { float x,y,root; int count; point_t edge[10]; } joint_t;
typedef struct {
    float head_angle,head_y,hand_angle,second_angle,ear_flex,blink;
    float mouth_x,mouth_y,mouth_rx,mouth_ry,mouth_amplitude;
} motion_profile_t;
static const joint_t no_joint={0,0,0,0,{{0,0}}};
static float polygon_mask(float x,float y,const joint_t *j)
{
    if(!j->count)return 0;
    int inside=0;float nearest=1e9f;
    for(int n=0,k=j->count-1;n<j->count;k=n++){
        float ax=j->edge[k].x,ay=j->edge[k].y,bx=j->edge[n].x,by=j->edge[n].y;
        if(((ay>y)!=(by>y))&&(x<(bx-ax)*(y-ay)/(by-ay)+ax))inside=!inside;
        float dx=bx-ax,dy=by-ay;
        float t=clamp(((x-ax)*dx+(y-ay)*dy)/(dx*dx+dy*dy),0,1);
        float ex=x-ax-t*dx,ey=y-ay-t*dy,d=ex*ex+ey*ey;
        if(d<nearest)nearest=d;
    }
    return inside?ease(sqrtf(nearest)/12.f):0;
}
/* Otter and sprout keep the head, book/belly and feet unskinned.  Their
 * greeting uses a wrist/forearm pivot; celebration and stretch use the
 * shoulder.  Shared artwork therefore has genuinely different gestures. */
static joint_t otter_sprout_joint(int avatar,int pose,int second)
{
    if(avatar==3){
        if(pose==4||pose==6||pose==9){
            /* The supporting paw may flex, but the blue book stays fixed. */
            if(second)return (joint_t){133,299,24,8,{{117,275},{160,275},{192,291},{212,311},{202,341},{166,351},{132,334},{112,307}}};
            if(pose==6)return (joint_t){351,278,27,10,{{372,163},{449,160},{475,200},{460,260},{420,278},{360,312},{328,323},{317,293},{338,265},{370,217}}};
            return (joint_t){335,302,34,10,{{372,163},{449,160},{475,200},{460,260},{420,278},{360,312},{328,323},{317,293},{338,265},{370,217}}};
        }
        if(pose==5)return second?(joint_t){333,310,25,8,{{320,279},{355,272},{382,286},{390,312},{371,340},{341,350},{311,329},{306,303}}}:(joint_t){145,310,25,8,{{118,274},{151,273},{180,292},{185,319},{168,343},{134,349},{110,328},{107,301}}};
        if(pose==3||pose==7){
            if(second)return no_joint;
            return (joint_t){151,313,30,9,{{173,257},{209,224},{238,217},{256,231},{251,259},{223,286},{192,316},{155,337},{133,319}}};
        }
        if(pose==2){
            if(second)return no_joint;
            return (joint_t){133,292,28,8,{{102,189},{127,182},{149,201},{148,241},{164,274},{153,307},{120,307},{100,265}}};
        }
        if(pose==0||pose==1||pose==8){
            if(second)return no_joint;
            return (joint_t){133,304,24,7,{{115,277},{153,279},{182,294},{203,315},{193,343},{151,349},{115,326}}};
        }
    }
    if(avatar==4){
        if(pose==4||pose==6||pose==9){
            if(second)return (joint_t){281,338,28,8,{{266,315},{293,313},{310,344},{306,382},{283,413},{256,411},{255,376},{261,348}}};
            if(pose==6)return (joint_t){136,303,27,10,{{32,219},{106,220},{111,240},{121,262},{151,287},{177,309},{166,343},{117,339},{58,309},{28,293}}};
            return (joint_t){159,319,31,10,{{32,219},{106,220},{111,240},{121,262},{151,287},{177,309},{166,343},{117,339},{58,309},{28,293}}};
        }
        if(pose==5)return second?(joint_t){270,335,25,8,{{245,306},{280,305},{301,325},{307,353},{286,375},{254,377},{232,357},{234,330}}}:(joint_t){145,328,25,8,{{113,291},{145,296},{171,320},{174,346},{153,366},{121,364},{101,346},{100,318}}};
        if(pose==3||pose==7){
            if(second)return no_joint;
            return (joint_t){157,341,29,8,{{146,277},{174,268},{198,281},{206,308},{193,343},{175,365},{145,365},{132,337}}};
        }
        if(pose==2){
            if(second)return no_joint;
            return (joint_t){285,341,28,8,{{280,274},{309,267},{330,290},{325,320},{311,350},{285,365},{264,347},{268,313}}};
        }
    }
    return no_joint;
}
/* Robot and cat hands sit beside the face or on the chest, rather than at
 * the generic atlas coordinates.  Author each visible limb in canonical
 * space so a wave cannot pick up the cheek, scarf, display or planted feet. */
static joint_t robot_cat_joint(int avatar,int pose,int second)
{
    if(avatar==1){
        if(pose==4||pose==6||pose==9){
            if(!second)return (joint_t){342,348,26,10,{{351,284},{369,271},{407,270},{448,286},{458,328},{411,364},{351,382},{325,356},{336,323},{346,310}}};
            return (joint_t){193,355,24,8,{{170,346},{191,345},{203,367},{197,398},{174,424},{145,418},{132,393},{145,365}}};
        }
        if(pose==5){
            if(!second)return (joint_t){206,356,24,8,{{208,336},{233,322},{262,319},{278,341},{268,370},{243,389},{214,387},{187,366}}};
            return (joint_t){330,355,24,8,{{276,319},{300,320},{326,335},{349,353},{341,380},{312,389},{281,374},{267,344}}};
        }
        if(pose==2){
            if(!second)return (joint_t){197,347,27,8,{{141,283},{164,272},{191,282},{198,306},{219,340},{203,370},{169,366},{143,334}}};
            return (joint_t){340,348,24,7,{{333,336},{356,339},{381,364},{395,387},{380,412},{352,415},{335,386}}};
        }
        if(pose==3||pose==7){
            if(!second)return (joint_t){215,350,24,8,{{229,310},{253,296},{280,305},{292,327},{274,354},{251,374},{217,377},{192,355}}};
            return (joint_t){339,356,24,7,{{286,333},{314,332},{342,339},{359,360},{348,386},{315,389},{284,371}}};
        }
        if(pose==0||pose==1||pose==8){
            if(!second)return (joint_t){187,358,25,7,{{164,352},{189,349},{205,374},{202,405},{178,428},{151,423},{137,391}}};
            return (joint_t){338,355,25,7,{{326,347},{349,347},{376,371},{393,398},{376,425},{348,424},{331,393}}};
        }
    }
    if(avatar==2){
        if(pose==4||pose==6||pose==9){
            if(!second)return (joint_t){369,319,25,10,{{389,230},{409,220},{447,225},{471,254},{466,291},{435,326},{389,348},{357,329},{357,285},{373,254}}};
            /* The planted front paws stay still; the resting tail supplies
             * the small secondary gesture, outside the legs and scarf. */
            return (joint_t){157,419,28,8,{{57,316},{94,296},{132,302},{156,337},{158,374},{179,412},{160,445},{117,434}}};
        }
        if(pose==5){
            if(!second)return (joint_t){270,359,26,9,{{206,314},{235,299},{268,304},{289,323},{294,347},{276,371},{246,379},{218,365},{201,341}}};
            return (joint_t){371,359,26,9,{{373,315},{402,300},{435,304},{457,327},{456,350},{435,369},{407,377},{379,366},{360,342}}};
        }
        if(pose==2){
            if(!second)return (joint_t){184,319,28,9,{{121,228},{146,216},{168,229},{181,258},{190,285},{202,316},{183,340},{155,327},{131,278}}};
            return (joint_t){147,417,29,8,{{53,319},{90,298},{123,303},{148,333},{152,374},{168,414},{145,444},{107,429}}};
        }
        if(pose==3||pose==7){
            if(!second)return (joint_t){344,345,26,8,{{300,268},{320,256},{345,263},{360,287},{370,327},{359,358},{332,367},{309,338}}};
            return (joint_t){150,419,28,8,{{50,317},{87,297},{124,304},{148,333},{154,372},{170,414},{147,445},{109,431}}};
        }
        if(pose==0||pose==1||pose==8){
            if(!second)return no_joint;
            return (joint_t){145,419,28,8,{{49,319},{85,301},{121,306},{147,337},{151,373},{166,413},{145,445},{106,431}}};
        }
    }
    return no_joint;
}
/* Integrate a smooth local angular velocity field backwards.  A direct
 * angle*mask inverse can have several roots near a narrow mask edge and
 * switch branches, slicing a paw into a straight edge.  Small midpoint
 * steps preserve the continuous socket and the complete paw silhouette. */
static void joint_map_flow(float *x,float *y,const joint_t *j,float angle)
{
    if(!j->count||fabsf(angle)<.00001f)return;
    float left=j->edge[0].x,right=left,top=j->edge[0].y,bottom=top;
    for(int n=1;n<j->count;++n){left=fminf(left,j->edge[n].x);right=fmaxf(right,j->edge[n].x);top=fminf(top,j->edge[n].y);bottom=fmaxf(bottom,j->edge[n].y);}
    if(*x<=left||*x>=right||*y<=top||*y>=bottom)return;
    if(polygon_mask(*x,*y,j)<.000001f)return;
    float dx=*x-j->x,dy=*y-j->y;
    float amount=-angle*ease((hypotf(dx,dy)-8.f)/j->root)/12.f;
    if(fabsf(amount)<.000001f)return;
    for(int n=0;n<12;++n){
        float first=amount*polygon_mask(j->x+dx,j->y+dy,j)*.5f;
        float ca=cosf(first),sa=sinf(first);
        float midx=dx*ca-dy*sa,midy=dx*sa+dy*ca;
        float step=amount*polygon_mask(j->x+midx,j->y+midy,j);
        ca=cosf(step);sa=sinf(step);
        float nextx=dx*ca-dy*sa;
        dy=dx*sa+dy*ca;dx=nextx;
    }
    *x=j->x+dx;*y=j->y+dy;
}

static joint_t joint_for(int avatar,int pose,int second)
{
    if(avatar==1||avatar==2)return robot_cat_joint(avatar,pose,second);
    if(avatar==3||avatar==4)return otter_sprout_joint(avatar,pose,second);
    if(avatar==0){
        if(pose==6&&!second)return (joint_t){182,290,38,10,{{8,145},{128,145},{143,202},{143,247},{160,273},{193,287},{206,315},{172,333},{105,329},{8,300}}};
        if(pose==9){
            if(!second)return (joint_t){172,284,38,10,{{43,110},{128,104},{147,153},{134,194},{127,218},{140,245},{177,276},{181,307},{129,307},{62,202}}};
            return (joint_t){303,285,38,9,{{303,267},{355,220},{356,182},{370,165},{402,154},{431,180},{425,214},{357,286},{309,315}}};
        }
        /* This artist pose has a lower, leftward cheek than greeting.  Keep
         * its inner socket outside that cheek while retaining transparent
         * padding around the complete paw sweep. */
        if(pose==4&&!second)return (joint_t){181,291,35,10,{{8,165},{111,165},{118,208},{123,239},{140,266},{181,287},{205,316},{171,334},{104,329},{8,300}}};
        if(pose==5){
            if(!second)return (joint_t){126,309,30,7,{{98,282},{141,282},{158,321},{208,353},{199,401},{147,396},{104,346}}};
            return (joint_t){298,307,30,7,{{281,286},{324,292},{327,343},{282,391},{223,400},{213,355},{268,326}}};
        }
        if(pose==2&&!second)return (joint_t){336,275,30,7,{{314,193},{348,185},{379,218},{386,277},{346,304},{319,282},{307,236}}};
        if(pose==3&&!second)return (joint_t){165,321,30,7,{{139,251},{181,249},{194,283},{184,327},{150,351},{127,321},{124,286}}};
        return no_joint;
    }
    /* Other four characters reuse their raised-paw artist pose for greeting
       and stretch.  Their hands are on different sides of the screen. */
    if(pose==4||pose==6||pose==9){
        if(second)return no_joint;
        if(avatar==1)return (joint_t){352,356,25,7,{{362,272},{410,264},{437,294},{431,335},{383,365},{349,375},{342,340}}};
        if(avatar==2)return (joint_t){343,337,29,7,{{365,218},{418,215},{444,252},{426,299},{381,340},{339,356},{331,313}}};
        if(avatar==3)return (joint_t){335,302,30,7,{{365,189},{413,184},{442,213},{428,254},{380,298},{333,326},{320,279}}};
        if(avatar==4)return (joint_t){159,319,26,7,{{79,227},{129,222},{153,254},{171,291},{183,329},{137,345},{87,298}}};
    }
    /* The comforting pose has both paws together.  Keep their motion tiny
       and preserve the book/screen/torso underneath rather than moving it. */
    if(pose==5){
        if(avatar==1)return second?(joint_t){306,352,24,6,{{264,326},{303,321},{334,344},{333,377},{293,384},{267,365}}}:(joint_t){203,350,24,6,{{181,324},{219,321},{246,338},{244,370},{207,383},{178,362}}};
        if(avatar==2)return second?(joint_t){321,327,24,6,{{294,296},{336,290},{363,311},{361,345},{318,357},{291,334}}}:(joint_t){171,334,24,6,{{137,294},{181,293},{201,315},{193,346},{154,356},{133,333}}};
        if(avatar==3)return second?(joint_t){343,315,24,6,{{306,279},{350,270},{378,293},{371,331},{333,345},{305,320}}}:(joint_t){148,310,24,6,{{113,271},{158,270},{181,293},{174,331},{135,341},{109,312}}};
        if(avatar==4)return second?(joint_t){278,347,24,6,{{254,315},{290,314},{313,341},{301,373},{265,376},{245,350}}}:(joint_t){140,335,24,6,{{112,302},{153,303},{174,330},{160,362},{122,365},{104,337}}};
    }
    return no_joint;
}

static void tune_robot_cat_motion(int avatar,int state,float t,float p,motion_profile_t *motion)
{
    if(avatar!=1&&avatar!=2)return;
    /* In a big-headed character even a small head rotation dominates the
     * entire picture.  Keep its face, torso and feet stationary; articulate
     * the independently drawn paws, eye lids and the cat's tail instead. */
    motion->head_angle=0;motion->head_y=0;motion->ear_flex=0;
    motion->hand_angle=0;motion->second_angle=0;
    float wave=.5f-.5f*cosf(3*p);
    float phrase=ease(pulse(t,.025f,.95f));
    if(state==0){
        motion->hand_angle=avatar==1?.018f*sinf(p):0;
        motion->second_angle=(avatar==1?-.018f:.022f)*sinf(p);
    }else if(state==1){
        motion->hand_angle=(avatar==1?-.075f:-.065f)*(.5f-.5f*cosf(2*p));
        motion->second_angle=(avatar==1?.012f:.022f)*sinf(p);
        if(avatar==2)motion->ear_flex=.65f*sinf(2*p);
    }else if(state==2){
        motion->hand_angle=(avatar==1?.10f:.065f)*(.5f-.5f*cosf(p));
        motion->second_angle=(avatar==1?-.035f:.024f)*sinf(p);
    }else if(state==3){
        /* Conversational beats are slower and smaller than a greeting. */
        motion->hand_angle=(avatar==1?.15f:.16f)*(.5f-.5f*cosf(2*p));
        motion->second_angle=(avatar==1?-.035f:.018f)*sinf(p);
        motion->mouth_x=avatar==1?260:294;
        motion->mouth_y=avatar==1?270:238;
        motion->mouth_rx=avatar==1?27:30;
        motion->mouth_ry=avatar==1?25:28;
        motion->mouth_amplitude=.13f*sinf(5*p)+.045f*sinf(3*p);
    }else if(state==4){
        /* Two independent comforting palms, not the old chest-sized mask. */
        motion->hand_angle=(avatar==1?.065f:-.085f)*sinf(p);
        motion->second_angle=(avatar==1?-.065f:.085f)*sinf(p);
    }else if(state==5){
        /* A bouncy right-paw cheer plus a small secondary hand/tail beat. */
        motion->hand_angle=(avatar==1?.28f:.25f)*wave*phrase;
        motion->second_angle=(avatar==1?.15f:.07f)*sinf(2*p)*phrase;
        if(avatar==2)motion->ear_flex=.7f*sinf(2*p)*phrase;
    }else if(state==6){
        /* Three visible wrist/forearm arcs, with a clean rest at both ends. */
        motion->hand_angle=(avatar==1?.30f:.28f)*wave*phrase;
        motion->second_angle=(avatar==1?.055f:.045f)*sinf(p)*phrase;
    }else if(state==7){
        motion->hand_angle=(avatar==1?.025f:.024f)*sinf(p);
        motion->second_angle=(avatar==1?-.012f:.018f)*sinf(p);
    }else if(state==8){
        motion->hand_angle=avatar==1?.012f*sinf(p):0;
        motion->second_angle=(avatar==1?-.012f:.012f)*sinf(p);
        motion->blink=0;
        if(avatar==2)motion->ear_flex=.35f*sinf(p);
    }else if(state==9){
        /* One slow outward extension and return; deliberately unlike the
         * three-beat wave, while both planted feet retain their coordinates. */
        float reach=ease(pulse(t,.06f,.88f));
        motion->hand_angle=(avatar==1?.28f:.25f)*reach;
        motion->second_angle=(avatar==1?.23f:.075f)*reach;
        motion->blink=0;
    }
}
static void tune_otter_sprout_motion(int avatar,int state,float t,float p,motion_profile_t *motion)
{
    if(avatar!=3&&avatar!=4)return;
    /* The face and its surrounding space never rock.  Motion is confined
       to the authored paw sockets, eyelids, mouth and sprout leaves. */
    motion->head_angle=0;motion->head_y=0;
    motion->hand_angle=0;motion->second_angle=0;motion->ear_flex=0;
    float direction=avatar==3?1.f:-1.f;
    if(state==0){
        motion->hand_angle=avatar==3?.018f*sinf(p):0;
        motion->ear_flex=avatar==4?1.8f*sinf(p):0;
    }else if(state==1){
        motion->hand_angle=.045f*sinf(p)*sinf(p);
        motion->ear_flex=avatar==4?1.1f*sinf(p):0;
    }else if(state==2){
        motion->hand_angle=(avatar==3?-.055f:.065f)*sinf(p)*sinf(p);
        motion->ear_flex=avatar==4?.9f*sinf(p):0;
    }else if(state==3){
        motion->hand_angle=direction*(.06f+.10f*sinf(p*2))*sinf(p)*sinf(p);
        /* Correct the mouth anchor to the mouth, never the cheek/neck. */
        motion->mouth_x=avatar==3?252:209;motion->mouth_y=avatar==3?210:259;
        motion->mouth_rx=avatar==3?31:36;motion->mouth_ry=avatar==3?23:24;
        motion->mouth_amplitude=.12f*sinf(p*5)+.04f*sinf(p*3);
    }else if(state==4){
        float offer=sinf(p)*sinf(p);
        motion->hand_angle=(avatar==3?-.13f:.16f)*offer;
        motion->second_angle=(avatar==3?.13f:-.16f)*offer;
    }else if(state==5){
        /* Two cheerful forearm pumps, with the other paw answering. */
        float envelope=ease(t/.12f)*(1-ease((t-.78f)/.22f));
        float pump=.5f-.5f*cosf(p*2);
        motion->hand_angle=direction*.43f*pump*envelope;
        motion->second_angle=-direction*(avatar==3?.045f:.20f)*pump*envelope;
        motion->ear_flex=avatar==4?2.8f*sinf(p*2)*envelope:0;
    }else if(state==6){
        /* Three clear wrist waves.  Elbow, book, belly and feet stay put. */
        float envelope=ease(t/.10f)*(1-ease((t-.82f)/.18f));
        motion->hand_angle=direction*(avatar==3?.58f:.44f)*(.5f-.5f*cosf(p*3))*envelope;
        motion->second_angle=0;
    }else if(state==7){
        motion->hand_angle=(avatar==3?-.024f:.025f)*sinf(p)*sinf(p);
    }else if(state==8){
        motion->blink=0;motion->ear_flex=avatar==4?.55f*sinf(p):0;
    }else if(state==9){
        /* A slow reach, relaxed hold and return, distinct from waving. */
        float reach=ease((t-.06f)/.28f)*(1-ease((t-.70f)/.24f));
        motion->hand_angle=-direction*.24f*reach;
        motion->second_angle=avatar==4?.16f*reach:0;
        motion->ear_flex=avatar==4?1.6f*sinf(p)*reach:0;
        motion->blink=0;
    }
}

int tf3_render(uint8_t *out,int avatar,int state,int frame,int frames,int size)
{
    if(!out||avatar<0||avatar>4||state<0||state>9||frame<0||frame>=frames||frames<2||size<64||size>1024||!textures[avatar])return 0;
    static const int poses[10]={0,2,3,4,5,4,6,7,8,9};
    int pose=poses[state];float t=frame/(float)((state==5||state==6||state==9)?frames-1:frames),p=2*PI*t;
    float head_angle=0,head_y=0,hand_angle=0,second_angle=0,ear_flex=0;
    float blink=powf(pulse(t,.34f,.055f),1.5f);
    /* No global translation, zoom, torso warp or camera wobble.  Feet and
       chest stay at the exact same canvas coordinates in every frame. */
    if(state==0){head_angle=.006f*sinf(p);ear_flex=1.2f*sinf(p);}
    else if(state==1){head_angle=.012f*sinf(p);head_y=-.8f*sinf(p);hand_angle=.025f*sinf(p*2);blink=powf(pulse(t,.68f,.06f),1.5f);}
    else if(state==2){head_angle=-.009f*sinf(p);hand_angle=.035f*sinf(p*1.5f);blink=powf(pulse(t,.56f,.055f),1.5f);}
    else if(state==3){hand_angle=.12f*sinf(p*2);blink=powf(pulse(t,.71f,.05f),1.5f);}
    else if(state==4){hand_angle=.065f*sinf(p);second_angle=-.065f*sinf(p);blink=powf(pulse(t,.43f,.09f),1.5f);}
    else if(state==5){float e=ease(pulse(t,.02f,.94f));hand_angle=((avatar==0?-.18f:avatar==4?-.32f:.26f)*(.5f-.5f*cosf(p*3)))*e;ear_flex=2.2f*sinf(p*2)*e;blink=powf(pulse(t,.78f,.08f),1.5f);}
    else if(state==6){float e=ease(pulse(t,.02f,.94f));hand_angle=((avatar==0||avatar==4?-.40f:.32f)*(.5f-.5f*cosf(p*3)))*e;blink=powf(pulse(t,.75f,.065f),1.5f);}
    else if(state==7){head_angle=.004f*sinf(p);blink=powf(pulse(t,.64f,.06f),1.5f);}
    else if(state==8){head_angle=.005f*sinf(p);ear_flex=.7f*sinf(p);blink=0;}
    else if(state==9){float e=ease(pulse(t,.06f,.86f));hand_angle=-.14f*e;second_angle=.14f*e;ear_flex=1.4f*sinf(p)*e;blink=0;}
    motion_profile_t motion={head_angle,head_y,hand_angle,second_angle,ear_flex,blink,
        avatar==0?267:avatar==1?266:avatar==2?296:avatar==3?278:274,
        avatar==0?244:avatar==1?296:avatar==2?249:avatar==3?264:270,
        42,27,.09f*sinf(p*5)+.04f*sinf(p*3)};
    tune_robot_cat_motion(avatar,state,t,p,&motion);
    tune_otter_sprout_motion(avatar,state,t,p,&motion);
    head_angle=motion.head_angle;head_y=motion.head_y;hand_angle=motion.hand_angle;
    second_angle=motion.second_angle;ear_flex=motion.ear_flex;blink=motion.blink;
    float head_limit=avatar==0?277:avatar==1?330:avatar==4?310:avatar==2?290:273;
    float ear_limit=avatar==0?124:avatar==1?130:avatar==4?110:125;
    joint_t arm=joint_for(avatar,pose,0),arm2=joint_for(avatar,pose,1);
    float unit=512.f/size;
    for(int y=0;y<size;++y)for(int x=0;x<size;++x){
        float ox=(x+.5f)*unit,oy=(y+.5f)*unit;
        /* Constant framing, shared by every clip and phase. */
        float u=(ox-256)/.96f+256,v=(oy-488)/.96f+500;
        joint_map_flow(&u,&v,&arm,hand_angle);joint_map_flow(&u,&v,&arm2,second_angle);
        float hw=ease((head_limit-v)/75.f),a=head_angle*hw;
        float ca=cosf(a),sa=sinf(a),hx=u-270,hy=v-head_limit;
        u=270+hx*ca+hy*sa;v=head_limit-hx*sa+hy*ca-head_y*hw;
        float ew=ease((ear_limit-v)/70.f);u-=ear_flex*ew*(u-270)/180.f;
        if(state==3){
            float mx=motion.mouth_x,my=motion.mouth_y;
            float mouth=support(u,v,mx,my,motion.mouth_rx,motion.mouth_ry),talk=motion.mouth_amplitude;
            v=my+(v-my)/(1+talk*mouth);
        }
        px_t q=sample(avatar,pose,u,v);
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
