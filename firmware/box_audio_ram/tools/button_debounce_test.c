#include <stdio.h>
#include <string.h>
#include "../main/button_debounce.h"
static int errors;
static void expect(button_debounce_t *b,bool down,bool allowed,uint32_t now,button_event_t wanted,const char *name)
{
    button_event_t event=button_debounce_update(b,down,allowed,now);
    if(event!=wanted){fprintf(stderr,"FAIL %s at %lu: got %d wanted %d\n",name,(unsigned long)now,event,wanted);++errors;}
}
static void released(button_debounce_t *b){memset(b,0,sizeof(*b));expect(b,false,true,30,BUTTON_NONE,"arm released");}
int main(void)
{
    button_debounce_t b;released(&b);
    expect(&b,true,true,100,BUTTON_NONE,"press edge");
    expect(&b,false,true,105,BUTTON_NONE,"bounce up");
    expect(&b,true,true,110,BUTTON_NONE,"bounce down");
    expect(&b,true,true,139,BUTTON_NONE,"29 ms is insufficient");
    expect(&b,true,true,140,BUTTON_NONE,"30 ms confirms down");
    expect(&b,false,true,200,BUTTON_NONE,"short never fires before released");
    expect(&b,false,true,229,BUTTON_NONE,"release still debouncing");
    expect(&b,false,true,230,BUTTON_SHORT,"release fires one short");
    expect(&b,false,true,500,BUTTON_NONE,"no repeat after release");
    released(&b);
    expect(&b,true,true,100,BUTTON_NONE,"long press edge");
    expect(&b,true,true,130,BUTTON_NONE,"long press confirmed");
    expect(&b,true,true,899,BUTTON_NONE,"799 ms insufficient");
    expect(&b,true,true,900,BUTTON_LONG,"800 ms fires long");
    expect(&b,true,true,3000,BUTTON_NONE,"held long does not repeat");
    expect(&b,false,true,3100,BUTTON_NONE,"long release edge");
    expect(&b,false,true,3130,BUTTON_NONE,"long release never fires short");
    for(unsigned mode=0;mode<2;++mode){
        released(&b);
        expect(&b,true,false,100,BUTTON_NONE,mode?"recording blocks press":"install blocks press");
        expect(&b,true,false,1200,BUTTON_NONE,"blocked hold");
        expect(&b,true,true,1300,BUTTON_NONE,"unblock while held");
        expect(&b,true,true,2400,BUTTON_NONE,"suppressed hold stays suppressed");
        expect(&b,false,true,2500,BUTTON_NONE,"suppressed release edge");
        expect(&b,false,true,2530,BUTTON_NONE,"suppressed release rearms only");
        expect(&b,true,true,2600,BUTTON_NONE,"new press after suppression");
        expect(&b,true,true,2630,BUTTON_NONE,"new press confirmed");
        expect(&b,false,true,2700,BUTTON_NONE,"new release edge");
        expect(&b,false,true,2730,BUTTON_SHORT,"new clean press allowed");
    }
    released(&b);
    uint32_t start=UINT32_MAX-100;
    expect(&b,true,true,start,BUTTON_NONE,"timestamp wrap edge");
    expect(&b,true,true,start+30,BUTTON_NONE,"timestamp wrap stable");
    expect(&b,true,true,start+799,BUTTON_NONE,"timestamp wrap before long");
    expect(&b,true,true,start+800,BUTTON_LONG,"timestamp wrap long exact");
    if(errors)return 1;
    puts("PASS: 30 ms debounce, release-only short, 800 ms one-shot long, held suppression, install/recording lockout, rearm, uint32 wrap");return 0;
}
