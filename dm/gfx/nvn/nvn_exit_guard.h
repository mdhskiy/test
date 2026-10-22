// Keep the last presented menu while a confirmed quit prepares its first loading
// frame. The caller supplies game state; no button, image-color or timing guess
// is used to infer a quit. Fail open on missing state, cancellation or timeout.
#pragma once
#include <stdint.h>
typedef struct { int request, waiting; uint64_t start; } nvn_exit_guard;
static inline int nvn_exit_guard_step(nvn_exit_guard *s, int request, int loading, uint64_t now_ns) {
    if (request && !s->request) { s->waiting = 1; s->start = now_ns; }
    s->request = request;
    if (!request || loading || now_ns - s->start >= 250000000ull) s->waiting = 0;
    return s->waiting;
}
