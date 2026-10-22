#include "../nvn/nvn_loading_art.h"
#include <assert.h>
#include <stdio.h>

int main(void) {
    assert(nvn_loading_art_scale(1920, 1080) == 1);
    assert(nvn_loading_art_scale(1024, 768) == 1);
    assert(nvn_loading_art_scale(NAN, 816) == 1);
    assert(nvn_loading_art_scale(1776, 0) == 1);
    double s = nvn_loading_art_scale(1776, 816);
    // Measured loading-art vertices: outer edges x=162 and x=1613, y=0..816.
    // Both edges must cover the render target; one scale preserves proportions.
    assert(s > 1.22 && s < 1.23);
    assert(888 + (162 - 888) * s <= 0);
    assert(888 + (1613 - 888) * s >= 1776);
    assert(408 - 408 * s < 0 && 408 + 408 * s > 816);
    // Lower-left origin uses a negative viewport height. Center stays invariant.
    double y = 408 + (816 - 408) * s, h = -816 * s;
    assert(fabs(y + h / 2 - 408) < 1e-9);
    puts("loading artwork viewport checks passed");
}
