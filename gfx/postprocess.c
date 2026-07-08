#include <windows.h>
#include <GL/gl.h>
#include <math.h>
#include "postprocess.h"

/* --- entry point GL2 caricati a runtime --- */
typedef char GLcharx;
typedef GLuint (WINAPI *PFNGLCREATESHADER)(GLenum);
typedef void   (WINAPI *PFNGLSHADERSOURCE)(GLuint, GLsizei, const GLcharx* const*, const GLint*);
typedef void   (WINAPI *PFNGLCOMPILESHADER)(GLuint);
typedef GLuint (WINAPI *PFNGLCREATEPROGRAM)(void);
typedef void   (WINAPI *PFNGLATTACHSHADER)(GLuint, GLuint);
typedef void   (WINAPI *PFNGLLINKPROGRAM)(GLuint);
typedef void   (WINAPI *PFNGLUSEPROGRAM)(GLuint);
typedef GLint  (WINAPI *PFNGLGETUNIFORMLOCATION)(GLuint, const GLcharx*);
typedef void   (WINAPI *PFNGLUNIFORM1F)(GLint, GLfloat);
typedef void   (WINAPI *PFNGLUNIFORM2F)(GLint, GLfloat, GLfloat);
typedef void   (WINAPI *PFNGLUNIFORM3F)(GLint, GLfloat, GLfloat, GLfloat);
typedef void   (WINAPI *PFNGLUNIFORM1I)(GLint, GLint);
typedef void   (WINAPI *PFNGLGETSHADERIV)(GLuint, GLenum, GLint*);
typedef void   (WINAPI *PFNGLGETPROGRAMIV)(GLuint, GLenum, GLint*);

static PFNGLCREATESHADER   pglCreateShader;
static PFNGLSHADERSOURCE   pglShaderSource;
static PFNGLCOMPILESHADER  pglCompileShader;
static PFNGLCREATEPROGRAM  pglCreateProgram;
static PFNGLATTACHSHADER   pglAttachShader;
static PFNGLLINKPROGRAM    pglLinkProgram;
static PFNGLUSEPROGRAM     pglUseProgram;
static PFNGLGETUNIFORMLOCATION pglGetUniformLocation;
static PFNGLUNIFORM1F      pglUniform1f;
static PFNGLUNIFORM2F      pglUniform2f;
static PFNGLUNIFORM3F      pglUniform3f;
static PFNGLUNIFORM1I      pglUniform1i;
static PFNGLGETSHADERIV    pglGetShaderiv;
static PFNGLGETPROGRAMIV   pglGetProgramiv;

#ifndef GL_FRAGMENT_SHADER
#define GL_FRAGMENT_SHADER 0x8B30
#endif
#ifndef GL_COMPILE_STATUS
#define GL_COMPILE_STATUS  0x8B81
#endif
#ifndef GL_LINK_STATUS
#define GL_LINK_STATUS     0x8B82
#endif
#ifndef GL_CLAMP_TO_EDGE
#define GL_CLAMP_TO_EDGE   0x812F
#endif

static const char *FRAG_SRC =
"uniform sampler2D tex;\n"
"uniform vec3 tint; uniform float strength;\n"
"uniform float desat; uniform float vignette;\n"
"uniform vec2 res;\n"
"uniform vec3 flash; uniform float flash_i;\n"
"uniform float shake; uniform vec2 shake_off;\n"
"uniform vec3 bloom_c; uniform float bloom_i;\n"
"uniform vec3 vig_tint; uniform float fade;\n"
"void main(){\n"
"  vec2 uv = gl_FragCoord.xy / res;\n"
"  vec2 uv2 = (uv - 0.5) * (1.0 - 0.05*shake) + 0.5 + shake_off;\n"
"  vec3 c = texture2D(tex, uv2).rgb;\n"
"  float l = dot(c, vec3(0.299,0.587,0.114));\n"
"  c = mix(c, vec3(l), desat);\n"
"  c = mix(c, tint, strength);\n"
"  c += flash * flash_i;\n"
"  c += bloom_c * bloom_i * smoothstep(0.4, 1.0, l);\n"
"  float d = distance(uv, vec2(0.5));\n"
"  float vg = vignette * smoothstep(0.35, 0.75, d);\n"
"  c = mix(c, vig_tint, vg);\n"
"  c = mix(c, vec3(0.0), fade);\n"
"  gl_FragColor = vec4(c, 1.0);\n"
"}\n";

/* Bit di GfxState.flags (devono combaciare con FLAG_UNSTABLE/FLAG_HP_LOW in gfx_state.py). */
#define FLAG_UNSTABLE 1u
#define FLAG_HP_LOW   2u

static int g_ready = -1;   /* -1 unknown, 0 failed, 1 ok */
static int g_disabled = 0;      /* 1 = self-disabled after repeated GL errors -> passthrough */
static int g_error_streak = 0;  /* consecutive frames with a lingering GL error */
#define PP_MAX_ERROR_STREAK 60
static GLuint g_prog = 0, g_tex = 0;
static GLint u_tint, u_strength, u_desat, u_vignette, u_res, u_tex;
static GLint u_flash, u_flash_i, u_shake, u_shake_off, u_bloom_c, u_bloom_i;
static GLint u_vig_tint, u_fade;

/* --- Envelope / dt tracking per la "juice" degli eventi (Task 8) --- */
static LARGE_INTEGER g_freq, g_last; static int g_clock = 0;
static unsigned last_flash_seq = 0, last_shake_seq = 0, last_bloom_seq = 0;
static float env_flash = 0.0f, env_shake = 0.0f, env_bloom = 0.0f;   /* 0..1 decaying */
static float flash_col[3] = {0.0f, 0.0f, 0.0f}, bloom_col[3] = {0.0f, 0.0f, 0.0f};

static float tick_dt(void) {
    if (!g_clock) {
        QueryPerformanceFrequency(&g_freq);
        QueryPerformanceCounter(&g_last);
        g_clock = 1;
        return 0.016f;
    }
    LARGE_INTEGER now; QueryPerformanceCounter(&now);
    float dt = (float)(now.QuadPart - g_last.QuadPart) / (float)g_freq.QuadPart;
    g_last = now;
    if (dt > 0.1f) dt = 0.1f;
    if (dt < 0.0f) dt = 0.0f;
    return dt;
}

static void decay(float *e, float dt, float rate) {
    *e -= dt * rate;
    if (*e < 0.0f) *e = 0.0f;
}

/* Crossfade: valori "correnti" che rincorrono il target dello stato condiviso
   con un lerp per frame (k=0.08 ~= 1s a 60fps), cosi' i grade non scattano. */
static float cur_tint[3] = {0.0f, 0.0f, 0.0f};
static float cur_strength = 0.0f, cur_desat = 0.0f, cur_vignette = 0.0f;
static float cur_vig_tint[3] = {0.0f, 0.0f, 0.0f};
static float cur_fade = 0.0f;
static float g_time = 0.0f;   /* accumulatore tempo per le modulazioni sinusoidali (Task 9) */
static float lerp(float a, float b, float k) { return a + (b - a) * k; }

#define LOAD(var,type,name) var=(type)wglGetProcAddress(name); if(!var) return 0;

static int load_entrypoints(void) {
    LOAD(pglCreateShader, PFNGLCREATESHADER, "glCreateShader");
    LOAD(pglShaderSource, PFNGLSHADERSOURCE, "glShaderSource");
    LOAD(pglCompileShader, PFNGLCOMPILESHADER, "glCompileShader");
    LOAD(pglCreateProgram, PFNGLCREATEPROGRAM, "glCreateProgram");
    LOAD(pglAttachShader, PFNGLATTACHSHADER, "glAttachShader");
    LOAD(pglLinkProgram, PFNGLLINKPROGRAM, "glLinkProgram");
    LOAD(pglUseProgram, PFNGLUSEPROGRAM, "glUseProgram");
    LOAD(pglGetUniformLocation, PFNGLGETUNIFORMLOCATION, "glGetUniformLocation");
    LOAD(pglUniform1f, PFNGLUNIFORM1F, "glUniform1f");
    LOAD(pglUniform2f, PFNGLUNIFORM2F, "glUniform2f");
    LOAD(pglUniform3f, PFNGLUNIFORM3F, "glUniform3f");
    LOAD(pglUniform1i, PFNGLUNIFORM1I, "glUniform1i");
    LOAD(pglGetShaderiv, PFNGLGETSHADERIV, "glGetShaderiv");
    LOAD(pglGetProgramiv, PFNGLGETPROGRAMIV, "glGetProgramiv");
    return 1;
}

/* Lazy init: compila lo shader, linka il programma, crea la texture di
   cattura. Ritorna 0 su QUALSIASI fallimento -> pp_draw diventa passthrough
   (nessun crash, nessun effetto). Risultato cacheato: eseguito una sola volta. */
int pp_init(void) {
    if (g_ready >= 0) return g_ready;
    g_ready = 0;
    if (!load_entrypoints()) return 0;

    GLuint fs = pglCreateShader(GL_FRAGMENT_SHADER);
    if (!fs) return 0;
    pglShaderSource(fs, 1, &FRAG_SRC, NULL);
    pglCompileShader(fs);
    GLint ok = 0;
    pglGetShaderiv(fs, GL_COMPILE_STATUS, &ok);
    if (!ok) return 0;

    g_prog = pglCreateProgram();
    if (!g_prog) return 0;
    pglAttachShader(g_prog, fs);
    pglLinkProgram(g_prog);
    GLint linked = 0;
    pglGetProgramiv(g_prog, GL_LINK_STATUS, &linked);
    if (!linked) return 0;
    pglUseProgram(g_prog);
    u_tint = pglGetUniformLocation(g_prog, "tint");
    u_strength = pglGetUniformLocation(g_prog, "strength");
    u_desat = pglGetUniformLocation(g_prog, "desat");
    u_vignette = pglGetUniformLocation(g_prog, "vignette");
    u_res = pglGetUniformLocation(g_prog, "res");
    u_tex = pglGetUniformLocation(g_prog, "tex");
    u_flash = pglGetUniformLocation(g_prog, "flash");
    u_flash_i = pglGetUniformLocation(g_prog, "flash_i");
    u_shake = pglGetUniformLocation(g_prog, "shake");
    u_shake_off = pglGetUniformLocation(g_prog, "shake_off");
    u_bloom_c = pglGetUniformLocation(g_prog, "bloom_c");
    u_bloom_i = pglGetUniformLocation(g_prog, "bloom_i");
    u_vig_tint = pglGetUniformLocation(g_prog, "vig_tint");
    u_fade = pglGetUniformLocation(g_prog, "fade");
    pglUseProgram(0);

    glGenTextures(1, &g_tex);
    g_ready = 1;
    return 1;
}

/* Cattura il back buffer in una texture e applica tint*desaturazione*vignetta
   in un unico pass a schermo intero via fragment shader.
   Salva/ripristina rigorosamente lo stato GL per non corrompere DCSS. */
void pp_draw(const GfxState *st, int w, int h) {
    if (g_disabled) return;                 /* self-disabled: passthrough permanente */
    if (!st || !st->master_enable || w <= 0 || h <= 0) return;
    if (!pp_init()) return;                 /* fallback: nessun effetto */
    float mi = st->master_intensity;

    /* Rileva nuovi eventi via seq-counter e arma le envelope; poi decadono
       nel tempo (dt reale via QueryPerformanceCounter). */
    float dt = tick_dt();
    g_time += dt;
    if (st->flash_seq != last_flash_seq) {
        last_flash_seq = st->flash_seq;
        env_flash = st->flash_intensity;
        flash_col[0] = st->flash_r; flash_col[1] = st->flash_g; flash_col[2] = st->flash_b;
    }
    if (st->shake_seq != last_shake_seq) {
        last_shake_seq = st->shake_seq;
        env_shake = st->shake_intensity;
    }
    if (st->bloom_seq != last_bloom_seq) {
        last_bloom_seq = st->bloom_seq;
        env_bloom = st->bloom_intensity;
        bloom_col[0] = st->bloom_r; bloom_col[1] = st->bloom_g; bloom_col[2] = st->bloom_b;
    }
    decay(&env_flash, dt, 3.0f);   /* ~0.3s */
    decay(&env_shake, dt, 4.0f);   /* ~0.25s */
    decay(&env_bloom, dt, 2.0f);   /* ~0.5s */

    glPushAttrib(GL_ALL_ATTRIB_BITS);
    glMatrixMode(GL_PROJECTION); glPushMatrix(); glLoadIdentity(); glOrtho(0, 1, 0, 1, -1, 1);
    glMatrixMode(GL_MODELVIEW);  glPushMatrix(); glLoadIdentity();
    glDisable(GL_DEPTH_TEST); glDisable(GL_LIGHTING); glDisable(GL_BLEND);
    glEnable(GL_TEXTURE_2D);

    /* Cattura il back buffer nella texture. */
    glBindTexture(GL_TEXTURE_2D, g_tex);
    glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MIN_FILTER, GL_LINEAR);
    glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MAG_FILTER, GL_LINEAR);
    glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_WRAP_S, GL_CLAMP_TO_EDGE);
    glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_WRAP_T, GL_CLAMP_TO_EDGE);
    glCopyTexImage2D(GL_TEXTURE_2D, 0, GL_RGB, 0, 0, w, h, 0);

    {
        float k = 0.08f;   /* ~1s di crossfade a 60fps */
        cur_tint[0] = lerp(cur_tint[0], st->tint_r, k);
        cur_tint[1] = lerp(cur_tint[1], st->tint_g, k);
        cur_tint[2] = lerp(cur_tint[2], st->tint_b, k);
        cur_strength = lerp(cur_strength, st->grade_strength * mi, k);
        cur_desat = lerp(cur_desat, st->desaturate * mi, k);
        cur_vignette = lerp(cur_vignette, st->vignette * mi, k);
        cur_vig_tint[0] = lerp(cur_vig_tint[0], st->vignette_tint_r, k);
        cur_vig_tint[1] = lerp(cur_vig_tint[1], st->vignette_tint_g, k);
        cur_vig_tint[2] = lerp(cur_vig_tint[2], st->vignette_tint_b, k);
        cur_fade = lerp(cur_fade, st->fade_black, k);
    }

    /* Modulazioni sinusoidali "danger signal" (Task 9): instabilita' di
       zona (Abyss/Pan) fa pulsare lentamente il grading; HP bassa fa
       pulsare la vignetta rossa piu' rapidamente. */
    float strength_mod = (st->flags & FLAG_UNSTABLE)
        ? (1.0f + 0.25f * sinf(g_time * 1.5f)) : 1.0f;
    float vignette_mod = (st->flags & FLAG_HP_LOW)
        ? (1.0f + 0.25f * sinf(g_time * 4.0f)) : 1.0f;

    /* Offset di shake: jitter per-frame usando il perf-counter come fase
       (deterministico rispetto al tempo, non serve rand()). */
    float shake_phase = (float)(g_last.QuadPart % 1000000) * 0.001f;
    float sx = env_shake * mi * 0.02f * sinf(shake_phase * 13.0f);
    float sy = env_shake * mi * 0.02f * cosf(shake_phase * 17.0f);

    pglUseProgram(g_prog);
    pglUniform1i(u_tex, 0);
    pglUniform3f(u_tint, cur_tint[0], cur_tint[1], cur_tint[2]);
    pglUniform1f(u_strength, cur_strength * strength_mod);
    pglUniform1f(u_desat, cur_desat);
    pglUniform1f(u_vignette, cur_vignette * vignette_mod);
    pglUniform2f(u_res, (float)w, (float)h);
    pglUniform3f(u_flash, flash_col[0], flash_col[1], flash_col[2]);
    pglUniform1f(u_flash_i, env_flash * mi);
    pglUniform1f(u_shake, env_shake * mi);
    pglUniform2f(u_shake_off, sx, sy);
    pglUniform3f(u_bloom_c, bloom_col[0], bloom_col[1], bloom_col[2]);
    pglUniform1f(u_bloom_i, env_bloom * mi);
    pglUniform3f(u_vig_tint, cur_vig_tint[0], cur_vig_tint[1], cur_vig_tint[2]);
    pglUniform1f(u_fade, cur_fade);

    glBegin(GL_QUADS);
        glTexCoord2f(0, 0); glVertex2f(0, 0);
        glTexCoord2f(1, 0); glVertex2f(1, 0);
        glTexCoord2f(1, 1); glVertex2f(1, 1);
        glTexCoord2f(0, 1); glVertex2f(0, 1);
    glEnd();
    pglUseProgram(0);

    glMatrixMode(GL_PROJECTION); glPopMatrix();
    glMatrixMode(GL_MODELVIEW);  glPopMatrix();
    glPopAttrib();

    /* Drena eventuali errori GL DOPO il ripristino dello stato, cosi' la
       drain stessa non perturba il rendering. Se un errore persiste per
       N frame consecutivi, il driver/lo stato e' probabilmente in una
       condizione anomala: ci auto-disabilitiamo in modo permanente e
       torniamo passthrough per tutti i frame successivi (mai crash). */
    {
        int frame_had_error = 0;
        GLenum err;
        while ((err = glGetError()) != GL_NO_ERROR) {
            frame_had_error = 1;
        }
        if (frame_had_error) {
            g_error_streak++;
            if (g_error_streak >= PP_MAX_ERROR_STREAK) {
                g_disabled = 1;
                OutputDebugStringA("dcss-gfx: postprocess self-disabled after repeated GL errors; falling back to passthrough\n");
            }
        } else {
            g_error_streak = 0;
        }
    }
}
