#include "../dm_d3_scale_ctl.h"
#include <assert.h>
#include <stdio.h>

static uint64_t clock_ns = 20 * D3S_SEC;
static void feed(d3_scale_ctl *c, int frames, int every, int thermal) {
    for (int i = 0; i < frames; i++) {
        double iv = every && i % every == 0 ? 1000.0 / 30 : 1000.0 / 60;
        clock_ns += (uint64_t)(iv * 1e6 + .5);
        d3_scale_step(c, iv, clock_ns, thermal);
    }
}
int main(void) {
    d3_scale_ctl c = {0};
    feed(&c, 7200, 0, 0); assert(c.level == 0);
    feed(&c, 120, 10, 0); assert(c.level == 1); // Frequent misses react within 2s.
    int level = c.level; feed(&c, 60, 1, 0); assert(c.level == level); // Settle hold.
    feed(&c, 1800, 10, 0); assert(c.level == 3); // Bounded floor under overload.
    feed(&c, 60 * 45, 0, 0); assert(c.level == 3); // No early recovery.
    feed(&c, 60 * 20, 0, 0); assert(c.level == 2);
    feed(&c, 120, 10, 0); // May still be in the 3s settle hold.
    feed(&c, 240, 10, 0); assert(c.level == 3 && c.need_good == 60);
    feed(&c, 60 * 90, 0, 0); assert(c.level == 3);
    feed(&c, 60 * 35, 0, 0); assert(c.level == 2);

    c = (d3_scale_ctl){0};
    d3_scale_hold(&c, clock_ns, 10 * D3S_SEC);
    d3_scale_step(&c, 0, clock_ns, 1); assert(c.level == 2); // Early protection during warmup/no readings.
    feed(&c, 60 * 150, 0, 1); assert(c.level == 2 && c.good == 0);
    feed(&c, 60 * 59, 0, 0); assert(c.level == 2); // Cooling does not immediately raise.
    feed(&c, 60 * 3, 0, 0); assert(c.level == 1);
    d3_scale_step(&c, 0, clock_ns, 2); assert(c.level == 3); // Serious need not wait for critical.
    d3_scale_step(&c, 0, clock_ns, 3); assert(c.level == 3);

    c = (d3_scale_ctl){.level = 3};
    feed(&c, 60 * 150 + 60, 0, 2);
    assert(c.level == 3 && c.good == 0); // No 70% -> 80% recovery while serious.
    feed(&c, 60 * 150 + 60, 0, 1); assert(c.level == 3 && c.good == 0); // Cooling to fair still blocks recovery.
    feed(&c, 60 * 59, 0, 0); assert(c.level == 3); // Partial hot window grants no credit.
    feed(&c, 60, 0, 0); assert(c.level == 2);

    c = (d3_scale_ctl){.level = 3};
    feed(&c, 60 * 58, 0, 0); assert(c.good == 29);
    d3_scale_step(&c, 0, clock_ns, 2); assert(c.good == 0); // Heat clears prior credit even without samples.
    feed(&c, 60 * 59, 0, 0); assert(c.level == 3);
    feed(&c, 60, 0, 0); assert(c.level == 2);

    c = (d3_scale_ctl){.level = 3, .need_good = 60};
    feed(&c, 60 * 150, 0, 2); assert(c.level == 3 && c.good == 0);
    feed(&c, 60 * 119, 0, -1); assert(c.level == 3); // Unknown desktop thermal state allows normal recovery.
    feed(&c, 60, 0, -1); assert(c.level == 2); // Failed recovery still needs 120s after cooling.

    c = (d3_scale_ctl){.level = 2};
    feed(&c, 120, 10, 1); assert(c.level == 3); // Thermal recovery gate does not block load-driven descent.

    c = (d3_scale_ctl){0};
    feed(&c, 600, 60, 0); assert(c.level == 1); // Sparse sustained misses: ten-second criterion.
    c = (d3_scale_ctl){0};
    feed(&c, 600, 120, 0); assert(c.level == 0); // One miss per 2s does not thrash.
    d3_scale_hold(&c, clock_ns, 10 * D3S_SEC);
    feed(&c, 120, 1, 0); assert(c.level == 0); // Loading/resume hold ignores samples.
    clock_ns += 20 * D3S_SEC;
    for (int i = 0; i < 120; i++) { clock_ns += D3S_SEC / 60; d3_scale_step(&c, -1, clock_ns, 0); }
    assert(c.level == 1); // Discarded presents are not silently ignored.
    unsigned n = c.n;
    d3_scale_step(&c, NAN, clock_ns, 0); d3_scale_step(&c, 0, clock_ns, 0); assert(c.n == n);
    puts("D3 adaptive scale policy passed");
}
