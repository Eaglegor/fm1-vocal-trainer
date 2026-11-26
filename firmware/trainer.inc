/* SPDX-License-Identifier: GPL-3.0-only WITH GPL-3.0-linking-exception */
/* Included in screen.c so the trainer uses the existing banded LCD renderer. */
static volatile unsigned voice_code;
static volatile uint32_t voice_time;
static volatile unsigned target_code, score_code;

struct practice_step { uint16_t start, end; uint8_t target, harmony; };
struct practice_routine { const char *label; const struct practice_step *steps; uint16_t count, duration; };
#include "practice_bank.inc"

static unsigned routine, root_note = 60, practice_bpm = 90;
static unsigned running, step_index, sounding, guide_channel, guide_target, guide_harmony;
static unsigned session_score, previous_voice;
static uint32_t origin, cue_end, good_time, last_position, voice_valid_until;

static void trainer_release(void)
{
    if (sounding) {
        post(0x80 + guide_channel, guide_target, 0, 3);
        if (guide_harmony < 128) post(0x80 + guide_channel, guide_harmony, 0, 3);
    }
    sounding = 0;
}

static void trainer_stop(void)
{
    trainer_release();
    running = 0;
}

static void trainer_sound(unsigned target, unsigned harmony)
{
    guide_target = target;
    guide_harmony = harmony;
    sounding = 1;
    if (!post(0x90 + guide_channel, target, 80, 3) ||
        (harmony < 128 && !post(0x90 + guide_channel, harmony, 72, 3)))
        trainer_stop();
}

static unsigned trainer_controls(struct fm1_controls *c, unsigned pressed, uint32_t now)
{
    int change = c->encoders[2], transpose = c->encoders[3], tempo = c->encoders[4];
    c->encoders[2] = c->encoders[3] = c->encoders[4] = 0;
    if (!running && (change || transpose || tempo)) {
        routine = clamp((int)routine + change, 0, sizeof routines / sizeof routines[0] - 1);
        root_note = clamp((int)root_note + transpose, 36, 84);
        practice_bpm = clamp((int)practice_bpm + tempo, 30, 240);
        session_score = 0;
    }
    if (!(pressed & BUTTON(PLAY))) return 0;
    if (running) trainer_stop();
    else if (routine) {
        guide_channel = groove_midi_input_channel(track);
        step_index = good_time = session_score = last_position = previous_voice = 0;
        unsigned beat = 60000 / practice_bpm;
        cue_end = now + beat;
        origin = cue_end + beat;
        running = 1;
        trainer_sound(root_note, root_note + 7);
    }
    return 1;
}

static void trainer_tick(uint32_t now)
{
    if (!running) return;
    if (running == 1) {
        if ((int32_t)(now - cue_end) < 0) return;
        trainer_release();
        running = 2;
    }
    if ((int32_t)(now - origin) < 0) return;
    const struct practice_routine *r = &routines[routine];
    const struct practice_step *s = &r->steps[step_index];
    uint32_t position = (now - origin) * practice_bpm / 1200;
    if (sounding && previous_voice) {
        int error = (int)previous_voice - 1 - (int)guide_target * 100;
        uint32_t end = position < s->end ? position : s->end;
        if (end > voice_valid_until) end = voice_valid_until;
        if (error >= -50 && error <= 50 && end > last_position)
            good_time += end - last_position;
    }
    while (position >= s->end) {
        trainer_release();
        if (++step_index == r->count) {
            running = 0;
            session_score = 1 + (100 * good_time + r->duration / 2) / r->duration;
            return;
        }
        s = &r->steps[step_index];
    }
    if (!sounding && position >= s->start) {
        trainer_sound(clamp((int)s->target + (int)root_note - 60, 0, 127),
                      s->harmony == 255 ? 255 : clamp((int)s->harmony + (int)root_note - 60, 0, 127));
    }
    uint32_t age = now - voice_time;
    previous_voice = age < 120 ? voice_code : 0;
    voice_valid_until = position + (age < 120 ? (120 - age) * practice_bpm / 1200 : 0);
    last_position = position;
}

int trainer_receive(unsigned source, const uint8_t *m, size_t n)
{
    if (source != FM1_MIDI_USB || n != 3) return 0;
    if (m[0] == 0xef) {
        voice_code = m[1] | ((unsigned)m[2] << 7);
        voice_time = fm1_millis();
        return 1;
    }
    if (m[0] == 0xbf && m[1] == 20) {
        target_code = m[2];
        score_code = 0;
        return 1;
    }
    if (m[0] == 0xbf && m[1] == 21) {
        score_code = m[2];
        return 1;
    }
    return 0;
}

static void trainer_draw(void)
{
    unsigned voice = fm1_millis() - voice_time <= 400 ? voice_code : 0;
    unsigned reference = routine ? (sounding && running == 2 ? guide_target + 1 : 0) : target_code;
    unsigned score = routine ? session_score : score_code, key = 255;
    for (unsigned i = 0; i < 27; ++i)
        if (key_note[i] != 255) key = key_note[i];
    unsigned config = routine | (root_note << 4) | (practice_bpm << 12) | (running << 20);
    if (cache->title_cache != config) {
        cache->title_cache = config;
        paint_fill(0, 0, 240, 56, BACK);
        text(8, 6, routines[routine].label, 2, ACCENT, BACK);
        char root[12]; note_name(root_note, root);
        text(8, 32, "K2 ROOT", 1, DIM, BACK);
        text(56, 32, root, 1, TEXT, BACK);
        text(104, 32, "K3 BPM", 1, DIM, BACK);
        number(154, 32, practice_bpm, 1, 1, TEXT, BACK);
        paint_fill(8, 221, 220, 9, BACK);
        text(8, 221, running ? "PLAY STOP" : "K1 ROUTINE   PLAY START", 1, ACCENT, BACK);
    }
    unsigned values[4] = {key, voice, reference, score};
    const char *labels[4] = {"KEY", "VOICE", "TARGET", "SCORE"};
    for (unsigned i = 0; i < 4; ++i) {
        if (cache->row_cache[i] == values[i]) continue;
        cache->row_cache[i] = values[i];
        unsigned y = 62 + i * 39;
        paint_fill(6, y, 228, 28, BACK);
        text(10, y, labels[i], 1, DIM, BACK);
        char name[12] = "--";
        if (i == 0 && key < 128) note_name(key, name);
        if (i == 1 && voice) {
            int cents = (int)voice - 1;
            unsigned nearest = (cents + 50) / 100;
            note_name(nearest, name);
            number(132, y, cents - 100 * (int)nearest, 1, 2, AMBER, BACK);
            text(182, y, "CT", 1, DIM, BACK);
        }
        if (i == 2 && reference) note_name(reference - 1, name);
        if (i == 3 && score) decimal(name, score - 1, 1);
        text(66, y, name, 2, TEXT, BACK);
    }
}
