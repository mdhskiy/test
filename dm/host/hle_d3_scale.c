// D3 v1441792: drive the game's own VariableResRWindowData, after its native
// timing update. The original viewport, postprocess UVs and upscaler consume
// flPercent together on the following frame. No allocations, shader changes,
// output crop changes or operation-mode switches occur at a scale transition.
#include "hle.h"
#include "dm_d3_scale_ctl.h"
#include "dm_d3_view.h"
#include <stdatomic.h>

extern int dm_focus_now(void), dm_thermal_now(void);
extern uint64_t dm_focus_in_since(void);
extern int mtl_d3_loading_recent(void);

static module_t *g_d3_main;
static _Atomic int g_d3_ready, g_d3_playing, g_d3_level;
static _Atomic uint64_t g_d3_seen;
static _Atomic uint64_t g_d3_view;

unsigned dm_d3_view_state(uint64_t frame) {
    return d3_view_state(atomic_load(&g_d3_view), frame);
}
static int g_d3_on, g_d3_trace;
static float g_d3_fixed;
static struct { uint64_t frame; float scale; } g_d3_script[16];
static int g_d3_script_n;

static float d3_scale_value(int level) { return 1.0f - .1f * level; }

static void d3_scale_init(void) {
    const char *build = "2607a74f5df7754cc0357b5df7e49693";
    if (strcmp(DM_GAME_D3_RES_BUILD, build)) return;
    for (int i = 0; i < g_nmod; i++)
        if (!strcmp(g_mod[i].name, "main") && !strcmp(g_mod[i].build_id, build) && g_mod[i].size > 0x1905630)
            g_d3_main = &g_mod[i];
    if (!g_d3_main || !gate_obs_present(OBS_D3_SCALE)) return;
    const char *e = getenv("DM_D3_DYN"); g_d3_on = !(e && !strcmp(e, "0"));
    e = getenv("DM_D3_SCALE_TRACE"); g_d3_trace = e && !strcmp(e, "1");
    e = getenv("DM_D3_SCALE");
    if (e) { char *end; g_d3_fixed = strtof(e, &end);
        if (end == e || *end || !(g_d3_fixed >= .7f && g_d3_fixed <= 1.f)) die("DM_D3_SCALE requires 0.70..1.00"); }
    e = getenv("DM_D3_SCALE_SCRIPT");
    if (e) {
        char *copy = strdup(e), *save = NULL;
        for (char *t = strtok_r(copy, ",", &save); t; t = strtok_r(NULL, ",", &save)) {
            unsigned long long f; float s; char tail;
            if (g_d3_script_n == 16 || sscanf(t, "%llu:%f%c", &f, &s, &tail) != 2 || !(s >= .7f && s <= 1.f) ||
                (g_d3_script_n && f <= g_d3_script[g_d3_script_n - 1].frame)) die("Invalid DM_D3_SCALE_SCRIPT");
            g_d3_script[g_d3_script_n].frame = f; g_d3_script[g_d3_script_n++].scale = s;
        }
        free(copy);
    }
    LOG("D3 adaptive scale: %s; native scene scale 1.00/0.90/0.80/0.70, thermal fair/serious caps 0.80/0.70, fixed=%.2f script=%d",
        g_d3_on ? "on" : "off", g_d3_fixed, g_d3_script_n);
    atomic_store(&g_d3_ready, 1);
}

static void d3_scale_after_update(const uint64_t *regs) {
    static int init;
    if (!init) { init = 1; d3_scale_init(); }
    if (!atomic_load(&g_d3_ready)) return;
    // Audited BL 0x42d04 -> 0x3cd10. x26 is the live RWindow manager;
    // [x26+0x20] is its current RWindow, [RWindow+0x2c0] the scale data.
    // Only the primary RWindow is controlled (GOT 0x114a870 -> 0x17de610).
    uintptr_t window = *(uintptr_t *)(regs[26] + 0x20);
    if (window != (uintptr_t)g_d3_main->base + 0x17de610) return;
    uint8_t *data = *(uint8_t **)(window + 0x2c0);
    if (!data) return;
    // The menu also owns a "playing" CGame, so pointer presence is not an
    // in-game test. Native GameIsStartUp at 0x4c7df0 compares GameParams.type
    // with zero (0x4c7e24: active+0x68; 0x4c7e3c: params+0x1c).
    // A queued GameParams at +0x428 marks an entry/exit already in progress.
    uintptr_t app = *(uintptr_t *)(g_d3_main->base + 0x114a840);
    uintptr_t game = app ? *(uintptr_t *)(app + 0x10) : 0;
    unsigned type = game ? *(uint32_t *)(game + 0x84) : 0;
    unsigned pending = game ? *(uint32_t *)(game + 0x428) : 1;
    int playing = game && type != 0 && pending == 0;
    uint64_t frame = dm_nvn_frame_count();
    atomic_store(&g_d3_view, d3_view_snapshot(frame, game != 0, type, pending));
    atomic_store(&g_d3_playing, playing); atomic_store(&g_d3_seen, frame + 1);
    if (!g_d3_on && !g_d3_fixed && !g_d3_script_n) return;
    float native = *(float *)(data + 0x18);
    float scale = playing ? d3_scale_value(atomic_load(&g_d3_level)) : 1.f;
    if (g_d3_fixed) scale = g_d3_fixed;
    for (int i = 0; i < g_d3_script_n && frame >= g_d3_script[i].frame; i++) scale = g_d3_script[i].scale;
    if (native != scale) { dm_guest_write_prepare(data + 0x18, 4); *(float *)(data + 0x18) = scale; }
    static float last = -1; static int was_playing = -1; static uint64_t logged;
    if (scale != last || playing != was_playing || (g_d3_trace && frame >= logged + 300)) {
        LOG("D3 scene scale frame=%llu playing=%d type=%u pending=%u native=%.3f applied=%.3f history_us=%u window=%p",
            (unsigned long long)frame, playing, type, pending, native, scale, *(uint32_t *)(data + 0x20), (void *)window);
        last = scale; was_playing = playing; logged = frame;
    }
}

// Called on the present thread, from the same actual timestamps as the FPS
// report. Only the atomic target crosses to the game's frame-boundary hook.
void dm_d3_scale_present(double iv) {
    if (!atomic_load(&g_d3_ready) || !g_d3_on || g_d3_fixed || g_d3_script_n) return;
    static d3_scale_ctl ctl; static int was_active; static uint64_t focus, thermal_at;
    static int thermal;
    uint64_t now = now_ns(), frame = dm_nvn_frame_count(), seen = atomic_load(&g_d3_seen);
    int active = dm_focus_now() == 1 && atomic_load(&g_d3_playing) && seen && frame + 1 <= seen + 2 && !mtl_d3_loading_recent();
    uint64_t resumed = dm_focus_in_since();
    if (resumed != focus) { focus = resumed; d3_scale_hold(&ctl, now, 3 * D3S_SEC); }
    if (!active) { was_active = 0; d3_scale_hold(&ctl, now, D3S_SEC); return; }
    if (!was_active) { was_active = 1; d3_scale_hold(&ctl, now, 10 * D3S_SEC); }
    if (!thermal_at || now - thermal_at >= D3S_SEC) { thermal_at = now; thermal = dm_thermal_now(); }
    int old = ctl.level, level = d3_scale_step(&ctl, iv, now, thermal);
    if (level != old) LOG("D3 adaptive scale frame=%llu level=%d scale=%.2f cause=%s thermal=%d drops2=%.2f%% drops10=%.2f%%",
        (unsigned long long)frame, level, d3_scale_value(level), ctl.reason == 1 ? "thermal" : ctl.reason == 2 ? "present" : "recovery",
        thermal, ctl.rate2 * 100, ctl.rate10 * 100);
    atomic_store(&g_d3_level, level);
}

__attribute__((constructor)) static void d3_scale_register(void) { gate_obs_set(OBS_D3_SCALE, d3_scale_after_update); }
