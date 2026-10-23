// D3 presentation-driven resolution policy. No guest or platform dependencies.
#ifndef DM_D3_SCALE_CTL_H
#define DM_D3_SCALE_CTL_H
#include <stdint.h>
#include <string.h>
#include <math.h>

#define D3S_SEC UINT64_C(1000000000)
typedef struct {
    int level, good, need_good, nw, reason, hot;
    uint64_t hold_until, last_up;
    double ms, rate2, rate10;
    unsigned n, drops;
    unsigned wn[5], wd[5];
} d3_scale_ctl;

static inline void d3_scale_hold(d3_scale_ctl *c, uint64_t now, uint64_t duration) {
    if (now + duration > c->hold_until) c->hold_until = now + duration;
    c->ms = 0; c->n = c->drops = 0; c->nw = c->good = 0;
}

// 0=configured output ceiling, 1=90%, 2=80%, 3=70% (linear dimensions).
// Fair thermal pressure caps at 80%, serious/critical at 70%; actual drops
// can lower further before those thermal limits are reached.
// Two-second windows: >5% drops in one window or >1% in ten seconds lowers
// one level. Three seconds settle after a change. Recovery requires 60 clean
// seconds; a failed recovery extends that to 120 seconds. Any reported
// thermal pressure prohibits recovery; nominal starts a fresh clean period.
static inline int d3_scale_step(d3_scale_ctl *c, double iv, uint64_t now, int thermal) {
    c->reason = 0;
    if (thermal >= 1) c->good = 0;
    else if (c->hot) {
        // Do not count a partial hot window toward recovery after cooling.
        // Retain completed miss windows so cooling cannot hide load pressure.
        c->ms = 0; c->n = c->drops = 0;
    }
    c->hot = thermal >= 1;
    int floor = thermal >= 2 ? 3 : thermal == 1 ? 2 : 0;
    if (c->level < floor) {
        c->level = floor; c->reason = 1;
        d3_scale_hold(c, now, 3 * D3S_SEC); return c->level;
    }
    if (now < c->hold_until || !isfinite(iv) || iv == 0) return c->level;
    const double period = 1000.0 / 60.0;
    c->n++; if (iv < 0 || iv > period * 1.5) c->drops++;
    c->ms += iv > 0 ? iv : period;
    if (c->ms + 1e-6 < 2000) return c->level;
    memmove(c->wn + 1, c->wn, 4 * sizeof c->wn[0]);
    memmove(c->wd + 1, c->wd, 4 * sizeof c->wd[0]);
    c->wn[0] = c->n; c->wd[0] = c->drops; if (c->nw < 5) c->nw++;
    unsigned n = 0, d = 0;
    for (int i = 0; i < c->nw; i++) { n += c->wn[i]; d += c->wd[i]; }
    c->rate2 = (double)c->drops / c->n; c->rate10 = (double)d / n;
    int clean = !c->drops; c->ms = 0; c->n = c->drops = 0;
    if (c->level < 3 && (c->rate2 > .05 || (c->nw == 5 && c->rate10 > .01))) {
        if (c->last_up && now - c->last_up < 15 * D3S_SEC) c->need_good = 60;
        c->level++; c->reason = 2; d3_scale_hold(c, now, 3 * D3S_SEC);
    } else if (c->hot || !clean || c->level <= floor) c->good = 0;
    else if (++c->good >= (c->need_good ? c->need_good : 30) && c->level) {
        c->level--; c->last_up = now; c->need_good = 0; c->reason = 3;
        d3_scale_hold(c, now, 3 * D3S_SEC);
    }
    return c->level;
}
#endif
