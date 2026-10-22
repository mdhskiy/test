# D3 adaptive scene resolution

The D3 v1441792 host uses actual presentation intervals and iOS thermal state
to drive the game's existing variable-resolution viewport/upscale path. It
does not resize the output, reallocate textures, change operation mode, or
change shaders. The configured output is the ceiling, not a claim that every
3D frame is rendered at that resolution or at the phone's native panel size.
The v32 package uses 2040x940 after device testing found missing text at
2346x1080. The latter is not an accepted quality configuration. The narrower
configuration restores text without disabling the vertex binding cache;
the underlying high-resolution text problem remains unresolved.

The policy uses linear scale levels 1.00, 0.90, 0.80 and 0.70. Fair thermal
state limits scale to 0.80, serious or critical to 0.70. It lowers one level if more than
5% of presentations miss in a two-second window, or more than 1% miss over
ten seconds. A miss is a discarded presentation or an interval over 25 ms.
After a change it waits three seconds. Recovery requires 60 clean seconds;
a relapse within 15 seconds extends the next recovery to 120 clean seconds.
Any reported thermal pressure prohibits recovery, including 70% to 80%.
Returning to nominal starts a fresh clean period; hot frames grant no credit.
This acts before the serious state that was already uncomfortably hot in
device testing; the OS states are coarse and do not guarantee a surface temperature.
These are conservative policy choices, not thresholds validated in a dense
greater rift. CPU simulation and loading stalls are not fixed by resolution.

Menus, loading, stale render callbacks and background time do not accumulate
recovery evidence. Gameplay entry has a ten-second grace period and foreground
resume has a three-second grace period. Thermal limits still apply during
the gameplay grace period. Lower levels persist across loading.

## Audited native interface

Only build `2607a74f5df7754cc0357b5df7e49693` gets observation gate 21 at
`main+0x42d08`, immediately after the sole call to the native update at
`0x3cd10`. The rewriter asserts original word `f9400b48` before replacing it.
The original instruction, `ldr x8, [x26, #0x10]`, still runs afterwards.

`x26+0x20` is the current RWindow. Only the primary RWindow at `0x17de610`
(relocated GOT `0x114a870`) is controlled. Its `+0x2c0` points to
VariableResRWindowData; the host writes only `flPercent` at `+0x18` after the
native timing update. Full/half/quarter targets, viewport construction,
postprocessing coordinates and final upscale remain the game's code.
AppGlobals (GOT `0x114a840`) has its active CGame at `+0x10`. Both active and
playing pointers also exist in menus, as the v30 device probe showed. Native
GameIsStartUp (`0x4c7df0`) reads GameParams.type at `CGame+0x68+0x1c` and
compares it with zero. The gameplay gate uses nonzero type and no pending
GameParams (`CGame+0x428 == 0`); loading artwork supplies the transition mask.

The v30 device sweep confirmed scene viewport 1642x756 at 70%, quarter-size
postprocessing 410x189, and the final UI/output pass still 2346x1080. Scene
alignment passed, but this did not establish text correctness; v31 review
found the same missing text in older v29 captures. Disabling vertex binding
caching or overriding UI dimensions did not resolve it. Both 1776x816 and
2040x940 restored text in fresh launches on the same installed v31 binary.

The v31 device log confirmed menu type=0, gameplay type=1, pending=1 on quit,
and correct re-entry. A screenshot-free forced-scale moving route had no
presentation misses within 30 frames before to 60 frames after each of the
100/90/80/70/100% transitions. Misses elsewhere in that route still occurred;
this is neither a dense-combat nor a universal 60 FPS guarantee.

The installed v32 (host `7bfb8ef1188b`) passed loading, quit/cancel, inventory,
and re-entry checks at 2040x940 with complete text. At 80%, the pass dump showed
scene viewport 1632x752, quarter postprocess 408x188 and final output 2040x940.
The final screenshot-free opening-route/attack run kept the same foreground
process for approximately two minutes: 25 presentation windows reported zero
misses and p99 16.67 ms. Whole-device gauge SystemLoad averaged 4.406 W
(time-weighted 4.426 W), with a maximum sample of 5.349 W. Battery temperature
was 36.59–37.50 C; brightness was 0.30. Charging changed from active to inactive,
so neither thermal equilibrium nor a causal power-saving percentage follows.
Scale fell to 80% as thermal state entered fair and remained there without
recovery throughout the measurement. Final diagnostic options were removed
and the application was relaunched. Dense greater-rift combat remains untested.

## Diagnostics

- `DM_D3_DYN=0`: leave the native scale policy in control.
- `DM_D3_SCALE=0.70..1.00`: fixed scene scale, disables the adaptive policy.
- `DM_D3_SCALE_SCRIPT=1200:1,1500:0.9,1800:0.8,2100:0.7,2400:1`:
  force changes at frame boundaries, for visual/transition validation only.
- `DM_D3_SCALE_TRACE=1`: log the native/applied scale every 300 frames.
- `DM_NVN_PASSDUMP=N`: inspect actual Metal viewport/scissor dimensions for
  frame N. Texture allocation dimensions alone do not prove active resolution.

None of the fixed/scripted diagnostic options should be in a release env.txt.
The controller test is `dm/host/tests/t_d3_scale.c`; CI also runs the existing
display notification, loading-art and exit-guard tests. Screenshots and verbose
pass dumps are excluded from power and frame-pacing acceptance intervals.
