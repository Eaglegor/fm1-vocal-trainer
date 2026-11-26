/* Host test of the panel routines. Build with cc tests/panel.c -o panel-test. */
#include <assert.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>

struct fm1_controls { int encoders[7]; };
enum { PLAY, FM1_MIDI_USB, ACCENT, BACK, TEXT, DIM, AMBER };
#define BUTTON(b) (1U << (b))
static unsigned track;
static uint32_t clock_ms;
static int held[128], attacks;
static uint32_t fm1_millis(void) { return clock_ms; }
static unsigned groove_midi_input_channel(unsigned t) { return t; }
static int clamp(int n, int lo, int hi) { return n < lo ? lo : n > hi ? hi : n; }
static int post(unsigned status, unsigned note, unsigned velocity, unsigned len)
{
    assert(note < 128 && len == 3);
    if ((status & 0xf0) == 0x90) { assert(velocity); ++attacks; ++held[note]; }
    else { assert(held[note] == 1); --held[note]; }
    return 1;
}
static struct { unsigned title_cache, row_cache[8]; } screen_cache, *cache = &screen_cache;
static uint8_t key_note[27];
#define paint_fill(...) ((void)0)
#define text(...) ((void)0)
#define number(...) ((void)0)
#define decimal(...) ((void)0)
#define note_name(...) ((void)0)
#include "../firmware/trainer.inc"

static void check_session(unsigned selection, int sing, int expected_score)
{
    struct fm1_controls c = {0};
    c.encoders[2] = (int)selection - (int)routine;
    trainer_controls(&c, BUTTON(PLAY), clock_ms);
    assert(running && sounding && held[root_note] && held[root_note + 7]);
    trainer_tick(cue_end - 1);
    assert(held[root_note] && held[root_note + 7]);
    trainer_tick(cue_end);
    assert(!sounding && !held[root_note] && !held[root_note + 7]);
    trainer_tick(origin - 1);
    assert(!sounding && !good_time);
    clock_ms = origin;
    attacks = 0;
    unsigned start = clock_ms;
    while (running && clock_ms - start < 20000) {
        const struct practice_step *s = &routines[routine].steps[step_index];
        unsigned code = sing ? 1 + 100 * (s->target + root_note - 60) : 0;
        uint8_t packet[] = {0xef, code & 127, code >> 7};
        trainer_receive(FM1_MIDI_USB, packet, 3);
        trainer_tick(clock_ms++);
    }
    assert(!running && !sounding && attacks >= (int)routines[routine].count);
    assert((int)session_score - 1 >= expected_score - 1 && (int)session_score - 1 <= expected_score);
    for (int i = 0; i < 128; ++i) assert(!held[i]);
}

int main(void)
{
    for (unsigned i = 1; i < sizeof routines / sizeof routines[0]; ++i) check_session(i, 1, 100);
    check_session(6, 0, 0);
    struct fm1_controls c = {0};
    c.encoders[2] = -1;
    c.encoders[3] = -5;
    trainer_controls(&c, BUTTON(PLAY), clock_ms);
    assert(held[55] && held[62]);
    trainer_controls(&c, BUTTON(PLAY), clock_ms);
    assert(!running && !held[55] && !held[62]);
    trainer_controls(&c, BUTTON(PLAY), clock_ms);
    clock_ms = origin;
    trainer_tick(clock_ms);
    assert(held[55] && held[62]);
    trainer_controls(&c, BUTTON(PLAY), clock_ms);
    assert(!running && !held[55] && !held[62]);
    puts("All panel routines, scores and dyad stop passed.");
}
