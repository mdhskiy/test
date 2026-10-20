// iOS front end (the iOS implementation of front.h): a Metal view covering the whole screen + a full-screen virtual gamepad layer (DmGamepad.m, controls drawn over the picture).
// The game is told the screen's own pixels (front_game_res), so it renders at the screen's aspect ratio and the picture fills it with no black bars and no stretching.
// The host runs on the big-stack thread started by main.m; front_run runs the guest directly on the calling thread.
#import <UIKit/UIKit.h>
#import <QuartzCore/CAMetalLayer.h>
#import <Metal/Metal.h>
#import <AVFAudio/AVFAudio.h>
#include <errno.h>
#include "front.h"
#include "hle.h"
#include "dm.h"

UIView *dm_gamepad_view(CGRect frame);
void dm_gamepad_reset(void);
void front_ios_boot(void);
int front_ios_boot_ok(void);

static CAMetalLayer *g_layer;
static void front_ios_power_watch(void);

@interface DmGameView : UIView
@end
@implementation DmGameView
+ (Class)layerClass { return CAMetalLayer.class; }
- (instancetype)initWithFrame:(CGRect)f {
    if ((self = [super initWithFrame:f])) {
        CAMetalLayer *l = (CAMetalLayer *)self.layer;
        l.device = MTLCreateSystemDefaultDevice(); l.pixelFormat = MTLPixelFormatBGRA8Unorm;
        l.contentsScale = UIScreen.mainScreen.nativeScale; l.framebufferOnly = NO; l.opaque = YES;
        self.backgroundColor = UIColor.blackColor;
    }
    return self;
}
- (void)layoutSubviews {
    [super layoutSubviews];
    CAMetalLayer *l = (CAMetalLayer *)self.layer;
    l.drawableSize = CGSizeMake(self.bounds.size.width * l.contentsScale, self.bounds.size.height * l.contentsScale);
}
@end

@interface DmRootVC : UIViewController
@property (nonatomic, strong) DmGameView *game;
@property (nonatomic, strong) UIView *pad;
@end
@implementation DmRootVC
- (void)viewDidLoad {
    [super viewDidLoad];
    self.view.backgroundColor = UIColor.blackColor;
    front_ios_power_watch();
    if (!front_ios_boot_ok()) {   // No game files: show a hint and do not start the host
        UILabel *lb = [[UILabel alloc] initWithFrame:CGRectInset(self.view.bounds, 40, 40)];
        lb.autoresizingMask = UIViewAutoresizingFlexibleWidth | UIViewAutoresizingFlexibleHeight;
        lb.numberOfLines = 0; lb.textAlignment = NSTextAlignmentCenter; lb.textColor = UIColor.whiteColor;
        lb.text = @"Game files not found.\nPut the RomFS folder into this App's Documents as \"romfs\" (Files app), then restart.\n\n没找到游戏文件：把 RomFS 文件夹以 romfs 为名放进本 App 的「文稿」后重开。";
        [self.view addSubview:lb]; return;
    }
    self.game = [[DmGameView alloc] initWithFrame:self.view.bounds];
    [self.view addSubview:self.game];
    g_layer = (CAMetalLayer *)self.game.layer;
    self.pad = dm_gamepad_view(self.view.bounds);
    self.pad.autoresizingMask = UIViewAutoresizingFlexibleWidth | UIViewAutoresizingFlexibleHeight;
    [self.view addSubview:self.pad];
}
- (void)viewDidLayoutSubviews {
    [super viewDidLayoutSubviews];
    if (!self.game) return;
    // The whole screen: the game renders at the screen's aspect ratio (front_game_res), so filling it neither stretches the
    // picture nor leaves a bar. It used to be fitted to 16:9 and centred, which put a black bar on each side of any wider
    // phone (a 17 Pro Max is 2868x1320, 2.17:1, so 522 of its 2868 columns were black).
    self.game.frame = self.view.bounds;
}
- (void)viewDidAppear:(BOOL)a { [super viewDidAppear:a]; front_ios_boot(); }
- (BOOL)prefersHomeIndicatorAutoHidden { return YES; }
- (UIRectEdge)preferredScreenEdgesDeferringSystemGestures { return UIRectEdgeAll; }   // Edge gestures need two swipes, to avoid accidental exits
- (BOOL)prefersStatusBarHidden { return YES; }
- (UIInterfaceOrientationMask)supportedInterfaceOrientations { return UIInterfaceOrientationMaskLandscape; }
@end
UIViewController *front_ios_root(void) { return [DmRootVC new]; }

// Thermal state and screen brightness for the power and present rows every 300 frames (hle_nvn.c; its weak defaults return -1 on the Mac). thermalState: 0 nominal, 1 fair, 2 serious, 3 critical.
// Brightness is read on the main thread at start and on each change; every change of the thermal state is logged with the time since launch
static _Atomic double g_brightness = -1;
int dm_thermal_now(void) { return (int)NSProcessInfo.processInfo.thermalState; }
double dm_brightness_now(void) { return g_brightness; }
static void front_ios_power_watch(void) {
    g_brightness = UIScreen.mainScreen.brightness;
    [NSNotificationCenter.defaultCenter addObserverForName:UIScreenBrightnessDidChangeNotification object:nil queue:NSOperationQueue.mainQueue usingBlock:^(NSNotification *n) { (void)n; g_brightness = UIScreen.mainScreen.brightness; }];
    [NSNotificationCenter.defaultCenter addObserverForName:NSProcessInfoThermalStateDidChangeNotification object:nil queue:nil usingBlock:^(NSNotification *n) {
        (void)n; LOG("前端：温控状态 → %d（启动后 %.0f s）", dm_thermal_now(), (now_ns() - g_t0_ns) / 1e9); }];
    LOG("前端：温控状态 %d，亮度 %.2f", dm_thermal_now(), g_brightness);
}

void *front_metal_layer(void) { return (__bridge void *)g_layer; }
// The render resolution the game is told (dm_game_res → the rewriter's KRES0 / KRES1 parameter slots, thread.c guest_thread_init):
// the screen's own pixels, so the picture fills it at the screen's aspect ratio. The Switch's 16:9 constants (1600x900 docked)
// are what "not fullscreen" was: a 2.17:1 phone got a black bar on each side, and the picture was scaled up into a larger area.
//   DM_GAME_RES=<width>x<height>  sets it directly (docked)
//   DM_GAME_RES_SCALE=<0.25-1>    scales the screen's size: the one knob for GPU cost. At 1.0 a 17 Pro Max renders 2868x1320,
//                                 2.6x the pixels of 1600x900; 0.8 is 2294x1056, 0.7 is 2008x924.
// Both are also read from Documents/env.txt, so the scale can be changed on the phone without rebuilding the app.
// Handheld is 0.8 of docked, as the original 1280x720 was of 1600x900. KASPECT / KASPECTUI follow from these (thread.c), so
// the game's UI is told the screen is wider than 16:9. Keep the screen's aspect ratio when overriding, or the picture stretches.
static int g_res_w, g_res_h;
static void game_res_init(void) {
    CGRect nb = UIScreen.mainScreen.nativeBounds;      // device pixels, always in the portrait-up orientation
    CGFloat sw = MAX(nb.size.width, nb.size.height), sh = MIN(nb.size.width, nb.size.height);   // the app is landscape-only
    CGFloat w = sw, h = sh;
    const char *e = getenv("DM_GAME_RES"); unsigned ew, eh;
    if (e && sscanf(e, "%ux%u", &ew, &eh) == 2 && ew >= 640 && eh >= 360) { w = ew; h = eh; }
    else { const char *s = getenv("DM_GAME_RES_SCALE"); if (s) { char *end; float f = strtof(s, &end);
        if (end != s && !*end && f >= 0.25f && f <= 1.0f) { w = (int)(sw * f); h = (int)(sh * f); } } }
    g_res_w = ((int)w) & ~3; g_res_h = ((int)h) & ~3;   // a multiple of 4, as the original constants were
    LOG("前端：屏幕 %.0fx%.0f 像素，游戏渲染 %dx%d（DM_GAME_RES / DM_GAME_RES_SCALE 可改，也可写进 Documents/env.txt）", sw, sh, g_res_w, g_res_h);
}
uint64_t front_game_res(int docked) {
    static dispatch_once_t once; dispatch_once(&once, ^{ game_res_init(); });
    if (docked) return (uint64_t)g_res_h << 32 | (uint64_t)g_res_w;
    int w = (g_res_w * 4 / 5) & ~3, h = (g_res_h * 4 / 5) & ~3;
    return (uint64_t)h << 32 | (uint64_t)w;
}
void front_run(void (*guest)(void)) { guest(); }   // Already on main.m's big-stack thread

// Software keyboard: show a UIAlertController on the main thread, the calling thread waits for the result
int front_text_input(const char *title, const char *sub, const char *guide, const char *initial, int max_chars, char *out, int out_cap) {
    (void)max_chars;
    if (!g_layer) return -1;
    __block int r = 0; __block NSString *text = nil;
    dispatch_semaphore_t done = dispatch_semaphore_create(0);
    NSString *t = title && *title ? @(title) : @"", *m = [NSString stringWithFormat:@"%s%s%s", sub ? sub : "", sub && *sub && guide && *guide ? "\n" : "", guide ? guide : ""];
    NSString *init = initial ? @(initial) : @"", *ph = guide ? @(guide) : @"";
    dispatch_async(dispatch_get_main_queue(), ^{
        UIAlertController *ac = [UIAlertController alertControllerWithTitle:t message:m preferredStyle:UIAlertControllerStyleAlert];
        [ac addTextFieldWithConfigurationHandler:^(UITextField *f) { f.text = init; f.placeholder = ph; }];
        [ac addAction:[UIAlertAction actionWithTitle:@"OK" style:UIAlertActionStyleDefault handler:^(UIAlertAction *x) { (void)x; r = 1; text = ac.textFields.firstObject.text; dispatch_semaphore_signal(done); }]];
        [ac addAction:[UIAlertAction actionWithTitle:@"Cancel" style:UIAlertActionStyleCancel handler:^(UIAlertAction *x) { (void)x; dispatch_semaphore_signal(done); }]];
        UIViewController *vc = nil;
        for (UIScene *s in UIApplication.sharedApplication.connectedScenes) if ([s isKindOfClass:UIWindowScene.class]) for (UIWindow *w in ((UIWindowScene *)s).windows) if (w.isKeyWindow) vc = w.rootViewController;
        if (!vc) { dispatch_semaphore_signal(done); return; }
        [vc presentViewController:ac animated:YES completion:nil];
    });
    guest_clock_freeze_for(2, 1);
    dispatch_semaphore_wait(done, DISPATCH_TIME_FOREVER);
    guest_clock_freeze_for(2, 0);
    if (!r) return 0;
    snprintf(out, out_cap, "%s", text.UTF8String ? text.UTF8String : "");
    return 1;
}

// Save write failed (most likely the phone's storage is full): show a notice on the main thread without blocking the game (as d2r-mobile does). hle_fs.c calls this when a save transaction is refused or a mount has to fall back to read-only;
// the iOS front end used not to implement it, so there was only a log line and the player never learned that progress was not being saved
void front_save_failed(int err) {
    LOG("前端：存档写失败 errno=%d，提示玩家", err);
    dispatch_async(dispatch_get_main_queue(), ^{
        UIViewController *vc = nil;
        for (UIScene *s in UIApplication.sharedApplication.connectedScenes) if ([s isKindOfClass:UIWindowScene.class]) for (UIWindow *w in ((UIWindowScene *)s).windows) if (w.isKeyWindow) vc = w.rootViewController;
        while (vc.presentedViewController) vc = vc.presentedViewController;
        if (!vc) { LOG("【红】前端：存档失败提示没有窗口 errno=%d", err); return; }
        NSString *m = err == ENOSPC ? @"存储空间不足，进度没有存上。请清理空间后再存档。\nStorage is full, so progress was not saved. Free up space and save again."
                                    : [NSString stringWithFormat:@"存档写入失败（errno %d），进度没有存上。\nSaving failed (errno %d); progress was not saved.", err, err];
        UIAlertController *a = [UIAlertController alertControllerWithTitle:@"存档失败 / Save failed" message:m preferredStyle:UIAlertControllerStyleAlert];
        [a addAction:[UIAlertAction actionWithTitle:@"OK" style:UIAlertActionStyleDefault handler:nil]];
        [vc presentViewController:a animated:YES completion:nil];
    });
}

// Audio session: the frames RemoteIO asks for in each callback follow the I/O buffer duration, about 21 ms by default on iOS (1024 frames at 48 kHz). The game keeps only 4 blocks × 5 ms = 20 ms in flight,
// so every callback came up 1.3 ms short and was zero-filled, about 47 gaps per second (crackling; reproducible on the Mac by forcing 1024-frame callbacks: 1999 underruns in 2000 callbacks). Ask for 5 ms and the system picks the nearest it supports;
// the category stays the default SoloAmbient (silent switch and interrupting other apps' audio behave as before). Set once at boot and again on return to the foreground (the system may reset it after an interruption)
void front_ios_audio_session(void) {
    AVAudioSession *s = AVAudioSession.sharedInstance; NSError *e = nil;
    if (![s setCategory:AVAudioSessionCategorySoloAmbient error:&e]) LOG("【红】音频会话类别设不上：%s", e.localizedDescription.UTF8String);
    [s setPreferredSampleRate:48000 error:nil];
    if (![s setPreferredIOBufferDuration:0.005 error:&e]) LOG("【红】音频会话 I/O 缓冲时长设不上：%s", e.localizedDescription.UTF8String);
    if (![s setActive:YES error:&e]) LOG("【红】音频会话激活失败：%s", e.localizedDescription.UTF8String);
    LOG("音频会话：采样率 %.0f Hz，I/O 缓冲 %.2f ms（要 5 ms）", s.sampleRate, s.IOBufferDuration * 1000);
}

// Scene lifecycle (called by SceneDelegate in main.m): 0 resign active, 1 enter background, 2 return to foreground, 3 become active. On entering background, freeze the guest clock and suspend after in-flight GPU work completes (submitting GPU work in background gets the process killed)
void front_ios_focus_event(int ev) {
    if (!g_layer) return;
    switch (ev) {
        case 0: dm_gamepad_reset(); dm_focus_set(2); break;
        case 1: dm_focus_set(3); dm_audio_suspend(1); guest_clock_freeze_for(1, 1); dm_gfx_suspend(1); break;
        case 2: dm_gfx_suspend(0); guest_clock_freeze_for(1, 0); front_ios_audio_session(); dm_audio_suspend(0); dm_focus_set(2); break;
        case 3: dm_focus_set(1); break;
    }
}
