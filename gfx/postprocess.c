#include <windows.h>
#include <GL/gl.h>
#include <math.h>
#include "postprocess.h"

/* Grade struct-driven: tinta * (grade_strength * master_intensity) +
   vignette radiale (TRIANGLE_FAN, centro trasparente -> bordo scuro).
   Nessuna cattura framebuffer, nessuno shader — solo overlay immediate-mode.
   Salva/ripristina rigorosamente lo stato GL per non corrompere DCSS. */
void pp_draw(const GfxState *st, int w, int h) {
    if (!st || !st->master_enable || w <= 0 || h <= 0) return;
    float mi = st->master_intensity;

    glPushAttrib(GL_ALL_ATTRIB_BITS);
    glMatrixMode(GL_PROJECTION); glPushMatrix(); glLoadIdentity();
    glOrtho(0, 1, 0, 1, -1, 1);
    glMatrixMode(GL_MODELVIEW);  glPushMatrix(); glLoadIdentity();
    glDisable(GL_DEPTH_TEST); glDisable(GL_TEXTURE_2D); glDisable(GL_LIGHTING);
    glEnable(GL_BLEND);

    /* Tinta: colore * strength su blending alpha. */
    float a = st->grade_strength * mi;
    if (a > 0.0f) {
        glBlendFunc(GL_SRC_ALPHA, GL_ONE_MINUS_SRC_ALPHA);
        glColor4f(st->tint_r, st->tint_g, st->tint_b, a);
        glBegin(GL_QUADS);
            glVertex2f(0,0); glVertex2f(1,0); glVertex2f(1,1); glVertex2f(0,1);
        glEnd();
    }

    /* Vignette: quad radiale scuro ai bordi (approssimazione a fan). */
    float vg = st->vignette * mi;
    if (vg > 0.0f) {
        glBlendFunc(GL_SRC_ALPHA, GL_ONE_MINUS_SRC_ALPHA);
        glBegin(GL_TRIANGLE_FAN);
            glColor4f(0,0,0,0.0f); glVertex2f(0.5f, 0.5f);       /* centro trasparente */
            glColor4f(0,0,0,vg);
            for (int i = 0; i <= 24; i++) {
                float t = (float)i / 24.0f * 6.2831853f;
                glVertex2f(0.5f + 0.75f*cosf(t), 0.5f + 0.75f*sinf(t));
            }
        glEnd();
    }

    glMatrixMode(GL_PROJECTION); glPopMatrix();
    glMatrixMode(GL_MODELVIEW);  glPopMatrix();
    glPopAttrib();
}
