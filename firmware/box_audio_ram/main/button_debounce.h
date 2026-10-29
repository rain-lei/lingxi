#pragma once
#include <stdbool.h>
#include <stdint.h>

typedef struct {
    bool raw_down, stable_down, armed, long_sent;
    uint32_t changed_ms, pressed_ms;
} button_debounce_t;
typedef enum { BUTTON_NONE, BUTTON_SHORT, BUTTON_LONG } button_event_t;

/* Pure timestamp state machine: no delay, task, GPIO, allocation or IO.
   Suppressed inputs must settle released before another press is accepted. */
static inline button_event_t button_debounce_update(button_debounce_t *b,bool down,bool allowed,uint32_t now)
{
    if(!allowed){
        b->raw_down=b->stable_down=down;b->armed=false;b->long_sent=true;b->changed_ms=now;
        return BUTTON_NONE;
    }
    if(down!=b->raw_down){b->raw_down=down;b->changed_ms=now;}
    if(now-b->changed_ms<30)return BUTTON_NONE;
    if(b->stable_down!=b->raw_down){
        b->stable_down=b->raw_down;
        if(b->stable_down){b->pressed_ms=b->changed_ms;b->long_sent=false;}
        else{
            bool short_press=b->armed && !b->long_sent;
            b->armed=true;b->long_sent=false;
            return short_press?BUTTON_SHORT:BUTTON_NONE;
        }
    }
    if(!b->stable_down){b->armed=true;return BUTTON_NONE;}
    if(b->armed && b->raw_down && !b->long_sent && now-b->pressed_ms>=800){
        b->long_sent=true;return BUTTON_LONG;
    }
    return BUTTON_NONE;
}
