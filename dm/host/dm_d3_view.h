// D3 view policy: keep state and its observation frame in one atomic snapshot.
#pragma once
#include <stdint.h>
#include <math.h>

enum { D3_VIEW_UNKNOWN, D3_VIEW_FRONTEND, D3_VIEW_GAME };
static inline uint64_t d3_view_snapshot(uint64_t frame, int valid, unsigned type, unsigned pending) {
    unsigned state = !valid || pending ? D3_VIEW_UNKNOWN : type ? D3_VIEW_GAME : D3_VIEW_FRONTEND;
    return ((frame + 1) << 2) | state;
}
static inline unsigned d3_view_state(uint64_t snapshot, uint64_t frame) {
    uint64_t seen = snapshot >> 2;
    if (!seen || frame + 1 < seen || frame + 1 - seen > 2) return D3_VIEW_UNKNOWN;
    return snapshot & 3;
}
static inline double d3_view_cover(double w, double h) {
    if (!isfinite(w) || !isfinite(h) || w <= 0 || h <= 0) return 1;
    return fmax(1, w / h / (16.0 / 9.0));
}
static inline double d3_view_point(double point, double anchor, double scale) {
    return anchor + (point - anchor) * scale;
}
