// Uniform cover for artwork authored in a centered 16:9 canvas. Text uses its
// original viewport; only profile-identified background textures use this one.
#pragma once
#include <math.h>
static inline double nvn_loading_art_scale(double w, double h) {
    if (!isfinite(w) || !isfinite(h) || w <= 0 || h <= 0) return 1;
    // Round inward by less than one pixel, covering the integer-rounded art edge.
    double art_w = floor(h * 16.0 / 9.0);
    return art_w >= 1 && w > art_w ? w / art_w : 1;
}
