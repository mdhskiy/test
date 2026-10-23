#include "../dm_d3_view.h"
#include <assert.h>
#include <stdio.h>

int main(void) {
    assert(d3_view_state(0, 100) == D3_VIEW_UNKNOWN);
    uint64_t menu = d3_view_snapshot(850, 1, 0, 0);
    assert(d3_view_state(menu, 850) == D3_VIEW_FRONTEND);
    assert(d3_view_state(menu, 852) == D3_VIEW_FRONTEND);
    assert(d3_view_state(menu, 853) == D3_VIEW_UNKNOWN);
    assert(d3_view_state(menu, 849) == D3_VIEW_UNKNOWN);
    assert(d3_view_state(d3_view_snapshot(850, 0, 0, 0), 850) == D3_VIEW_UNKNOWN);
    assert(d3_view_state(d3_view_snapshot(850, 1, 1, 0), 850) == D3_VIEW_GAME);
    assert(d3_view_state(d3_view_snapshot(850, 1, 0, 1), 850) == D3_VIEW_UNKNOWN);
    assert(d3_view_state(d3_view_snapshot(850, 1, 1, 1), 850) == D3_VIEW_UNKNOWN);
    // Frontend seams measured on 2040x940: left 120, right 1890.
    double k = d3_view_cover(2040, 940);
    assert(k > 1.22 && k < 1.23);
    assert(d3_view_point(120, 1020, k) < 0);
    assert(d3_view_point(1890, 1020, k) > 2040);
    assert(d3_view_cover(1920,1080) == 1);
    assert(d3_view_cover(1024,768) == 1);
    assert(d3_view_cover(NAN,940) == 1);
    // Both viewport signs preserve the chosen ground-contact anchor.
    double a = 940 * .67;
    assert(d3_view_point(a, a, k) == a);
    assert(fabs(d3_view_point(940-a, 940-a, k) - (940-a)) < 1e-9);
    // 10% whole-frame zoom is uniform and centered; 4.55% lost per side.
    assert(fabs(d3_view_point(0, 1020, 1.1) + 102) < 1e-9);
    assert(fabs(d3_view_point(940, 470, 1.1) - 987) < 1e-9);
    puts("D3 view state and framing checks passed");
}
