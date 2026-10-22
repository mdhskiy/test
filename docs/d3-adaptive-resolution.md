# D3 adaptive scene resolution

The D3 v1441792 host uses actual presentation intervals and iOS thermal state
to drive the game's existing variable-resolution viewport/upscale path. It
does not resize the output, reallocate textures, change operation mode, or
change shaders. A 2346x1080 output is the ceiling, not a claim that every 3D
frame is rendered at that resolution or at the phone's native panel size.

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
postprocessing 410x189, and the final UI/output pass still 2346x1080. Complete
images at 100/90/80/70% remained aligned. Automatic policy and complete
regression results still require the corrected gameplay gate on device.

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
