// MKW_FPS=auto: the present interval (1-4: 60, 30, 20, 15 fps) from the time the game measured for each frame (its
// frame object's [+0x128], game.c). The game's own choice stops at 2: below 30 fps the race ran in slow motion
// (0.75-0.83x on the Radeon 660M at 36 ms a frame). Its rule (acc += measured - interval * 16.7 ms, capped at
// +-66.7 ms, interval = acc / 16.7 + 1) taken to 4 would cycle 2, 3, 4 on a steady 36 ms frame, each step undoing the
// last; so this one has hysteresis: up when the frames no longer fit the interval (the two triggers below); down only
// when the median of the last two seconds fits a lower interval with 15 % to spare.
#include <string.h>

#include "host.h"

#define PERIOD_MS (1000.0 / 60.0)
#define UP_FRAMES 8
#define DOWN_MARGIN 0.85   // lat4: race frames of 25-40 ms moved it 2 <-> 3 every few seconds with 0.92 over 1 s
#define DOWN_SECONDS 2
#define HOLD_MIN_S 5
#define HOLD_MAX_S 60
#define PINGPONG_S 10
#define UP_MARGIN 1.08   // gp15b: 50-54 ms spikes at interval 3 moved it to 4 one or two times every 5 s
// Up has two triggers. Quick: the median of the last 8 frames 25 % past the interval (QUICK_MARGIN), to the interval
// they fit with UP_MARGIN. Slow: the median of the real periods of the last two seconds 5 % past it (SLOW_UP_MARGIN),
// and the last 8 frames too, to no interval past the one those fit (after a stall the two seconds still hold it).
// fan_auto (Steam Deck GP, working fan): at 30 fps the game measured 33-41 ms while the real period held 33.3 ms
// (fixed 30 ran at 0.99x, 29.2 fps); 8 frames 8 % past undid each probe to 30 within a second.
#define QUICK_MARGIN 1.25
#define SLOW_UP_MARGIN 1.05
// A stall: frames past twice what the slowest interval holds (133 ms), which no interval fits (a CPU held at a low
// clock, a load), after frames that fitted the interval. It moves nothing for up to STALL_MAX_S: mp1/mp2 (Steam Deck,
// 2 players, interval 3) went to 4 on each stall of 300 ms frames and held it, doubled on each return, so the race ran
// at 15 fps between them where 20 held at full speed. Longer than that, it is the machine's speed and counts as any
// frame.
// A probe: at 20 or 15 fps, an interval that the down rule has not left for PROBE_S seconds, one step down when the median of
// the last two seconds fits the lower interval within 10 % of it (PROBE_MARGIN). The game's measure follows the
// interval it runs at: at 20 fps the Steam Deck's CPU and GPU idle half the frame and drop their clocks, its frames
// measure 30-37 ms and the down rule (28.3 ms) never holds, while a fixed 30 ran the same race at 0.94-1.01x. The up
// rule undoes a probe that does not hold (within 8 frames or two seconds), and the hold that follows doubles each
// time (to 60 s).
#define PROBE_S 10
#define PROBE_MARGIN 1.1   // auto1 (Steam Deck GP at interval 3): measured 32-44 ms a 5 s window, mostly 33-36
#define PROBE_FROM 2   // not to 60 fps: the game's measure there can be far under the real period (lat5)
#define STALL_FACTOR 2.0
#define STALL_MAX_S 20

static double median_of(const FpsAuto *a, const double *h, unsigned count) {
    double v[FPS_AUTO_HIST];
    unsigned n = count < a->n ? count : a->n;
    for (unsigned i = 0; i < n; i++) v[i] = h[(a->head + FPS_AUTO_HIST - 1 - i) % FPS_AUTO_HIST];
    for (unsigned i = 1; i < n; i++)   // insertion sort: at most 60 values
        for (unsigned j = i; j > 0 && v[j - 1] > v[j]; j--) {
            double t = v[j];
            v[j] = v[j - 1], v[j - 1] = t;
        }
    return n ? v[n / 2] : 0.0;
}

static double median(const FpsAuto *a, unsigned count) { return median_of(a, a->hist, count); }

static int fitting(double ms, double margin) {   // the smallest interval a frame of ms fits in
    for (int iv = 1; iv < FPS_AUTO_MAX; iv++)
        if (ms <= iv * PERIOD_MS * margin) return iv;
    return FPS_AUTO_MAX;
}

void fps_auto_reset(FpsAuto *a) {
    memset(a, 0, sizeof *a);
    a->iv = 1;
}

static double median_real(const FpsAuto *a) {   // the last UP_FRAMES real periods
    double v[UP_FRAMES];
    for (unsigned i = 0; i < UP_FRAMES; i++) v[i] = a->real[i];
    for (unsigned i = 1; i < UP_FRAMES; i++)
        for (unsigned j = i; j > 0 && v[j - 1] > v[j]; j--) {
            double t = v[j];
            v[j] = v[j - 1], v[j - 1] = t;
        }
    return v[UP_FRAMES / 2];
}

// measured_ms: the game's own measure of the frame; real_ms: the time since the last frame began (0 unknown). Up on
// the larger of the two: the game's measure can stay under the real period (lat5: 3 -> 1 on 8.7 ms frames before the
// start, then the race at 0.79x at interval 1). Down one step at a time; after an up, no down for hold_s seconds,
// doubled (to 60) when the up undid a down of the last 10 s.
int fps_auto_step(FpsAuto *a, double measured_ms, double real_ms) {
    a->hist[a->head] = measured_ms;
    a->rhist[a->head] = real_ms > 0 ? real_ms : measured_ms;
    a->head = (a->head + 1) % FPS_AUTO_HIST;
    a->real[a->n_real++ % UP_FRAMES] = real_ms;
    if (a->n < FPS_AUTO_HIST) a->n++;
    a->since++;
    if (a->hold) a->hold--;
    if (!a->hold_s) a->hold_s = HOLD_MIN_S;
    unsigned window = DOWN_SECONDS * 60 / (unsigned)a->iv;   // two seconds of frames at this interval
    if (a->since >= UP_FRAMES && a->n >= UP_FRAMES) {
        double m = median(a, UP_FRAMES), r = a->n_real >= UP_FRAMES ? median_real(a) : 0, v = m > r ? m : r;
        int stalled = a->fits && v > FPS_AUTO_MAX * PERIOD_MS * STALL_FACTOR;
        a->stall_ms = stalled ? a->stall_ms + (real_ms > measured_ms ? real_ms : measured_ms) : 0;
        int quick = fitting(v, QUICK_MARGIN) > a->iv ? fitting(v, UP_MARGIN) : a->iv;
        int slow = a->iv, last = fitting(v, SLOW_UP_MARGIN);
        if (a->since >= window && a->n >= window && last > a->iv) {
            slow = fitting(median_of(a, a->rhist, window), SLOW_UP_MARGIN);
            if (slow > last) slow = last;
        }
        int up = stalled && a->stall_ms < STALL_MAX_S * 1000.0 ? a->iv : quick > a->iv ? quick : slow;
        if (!stalled) a->fits = up <= a->iv;
        if (up > a->iv) {
            int undid_down = a->downed && a->since < (unsigned)(PINGPONG_S * 60 / a->iv);
            a->hold_s = undid_down ? (a->hold_s * 2 > HOLD_MAX_S ? HOLD_MAX_S : a->hold_s * 2) : HOLD_MIN_S;
            a->iv = up, a->since = 0, a->downed = 0;
            a->hold = (unsigned)(a->hold_s * 60 / a->iv);
            return a->iv;
        }
    }
    if (a->iv > 1 && !a->hold && a->since >= window && a->n >= window) {
        // one step at a time: the game's measure can be far under the frame's real cost (lat6: 9 ms at interval 4,
        // 66 ms frames), so a step down is a trial the real period confirms or undoes within 8 frames
        double m = median(a, window);
        int probe = a->iv > PROBE_FROM && a->since >= (unsigned)(PROBE_S * 60 / a->iv) && fitting(m, PROBE_MARGIN) < a->iv;
        if (fitting(m, DOWN_MARGIN) < a->iv || probe) a->iv--, a->since = 0, a->downed = 1, a->probes += probe;
    }
    return a->iv;
}
