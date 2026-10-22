#include <assert.h>
#include "../nvn/nvn_exit_guard.h"
int main(void) {
    nvn_exit_guard s = {0};
    assert(!nvn_exit_guard_step(&s, 0, 0, 0));
    assert(nvn_exit_guard_step(&s, 1, 0, 10));
    assert(!nvn_exit_guard_step(&s, 1, 1, 20));
    assert(!nvn_exit_guard_step(&s, 1, 0, 30)); // A persistent reason cannot re-arm.
    assert(!nvn_exit_guard_step(&s, 0, 0, 40));
    assert(nvn_exit_guard_step(&s, 1, 0, 50)); // Another quit after re-entry.
    assert(!nvn_exit_guard_step(&s, 0, 0, 60)); // Cancel or unreadable state.
    assert(nvn_exit_guard_step(&s, 1, 0, 70));
    assert(!nvn_exit_guard_step(&s, 1, 0, 250000070));
    assert(!nvn_exit_guard_step(&s, 1, 0, 260000070)); // No repeated timeout stalls.
    assert(!nvn_exit_guard_step(&s, 0, 0, 270000070));
    assert(!nvn_exit_guard_step(&s, 1, 1, 280000070)); // Loading was ready immediately.
    return 0;
}
