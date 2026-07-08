#include <windows.h>
#include <GL/gl.h>
#include "postprocess.h"

/* Passo minimale: quad fullscreen semitrasparente rosso in blending.
   Nessuna cattura framebuffer, nessuno shader — solo prova di pipeline.
   Salva/ripristina rigorosamente lo stato GL per non corrompere DCSS. */
void pp_draw_overlay(int w, int h) {
    if (w <= 0 || h <= 0) return;

    glPushAttrib(GL_ALL_ATTRIB_BITS);
    glMatrixMode(GL_PROJECTION); glPushMatrix(); glLoadIdentity();
    glOrtho(0, 1, 0, 1, -1, 1);
    glMatrixMode(GL_MODELVIEW);  glPushMatrix(); glLoadIdentity();

    glDisable(GL_DEPTH_TEST);
    glDisable(GL_TEXTURE_2D);
    glDisable(GL_LIGHTING);
    glEnable(GL_BLEND);
    glBlendFunc(GL_SRC_ALPHA, GL_ONE_MINUS_SRC_ALPHA);

    glColor4f(1.0f, 0.0f, 0.0f, 0.20f);   /* rosso 20% */
    glBegin(GL_QUADS);
        glVertex2f(0, 0); glVertex2f(1, 0);
        glVertex2f(1, 1); glVertex2f(0, 1);
    glEnd();

    glMatrixMode(GL_PROJECTION); glPopMatrix();
    glMatrixMode(GL_MODELVIEW);  glPopMatrix();
    glPopAttrib();
}
