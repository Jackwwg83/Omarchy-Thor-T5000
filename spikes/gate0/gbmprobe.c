// gbmprobe: exercise the GBM/EGL paths a wlroots- or aquamarine-style Wayland
// compositor needs, on one DRM node, without modesetting. Spike code for Gate 0a.
//
//   gbmprobe /dev/dri/renderD130
//
// Path A renders into a gbm_surface and locks its front buffer.
// Path B allocates a scanout buffer with modifiers, exports it as dma-buf,
// imports it as an EGLImage and renders into it through an FBO, then reads the
// pixel back. Path B is where Jetson Orin fails (GL_FRAMEBUFFER_INCOMPLETE_ATTACHMENT).
#include <EGL/egl.h>
#include <EGL/eglext.h>
#include <GLES2/gl2.h>
#include <GLES2/gl2ext.h>
#include <drm_fourcc.h>
#include <fcntl.h>
#include <gbm.h>
#include <inttypes.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>
#include <xf86drm.h>

static int fails;

static void check(int ok, const char *what) {
  printf("%s %s\n", ok ? "PASS" : "FAIL", what);
  if (!ok) fails++;
}

static int has_ext(const char *list, const char *ext) {
  size_t n = strlen(ext);
  for (const char *p = list; p && (p = strstr(p, ext)); p += n)
    if ((p == list || p[-1] == ' ') && (p[n] == ' ' || p[n] == '\0')) return 1;
  return 0;
}

#define PROC(type, name) type name = (type)eglGetProcAddress(#name)

static void list_egl_devices(void) {
  PROC(PFNEGLQUERYDEVICESEXTPROC, eglQueryDevicesEXT);
  PROC(PFNEGLQUERYDEVICESTRINGEXTPROC, eglQueryDeviceStringEXT);
  if (!eglQueryDevicesEXT || !eglQueryDeviceStringEXT) { check(0, "EGL device enumeration available"); return; }
  EGLDeviceEXT devs[16];
  EGLint n = 0;
  eglQueryDevicesEXT(16, devs, &n);
  printf("EGL devices: %d\n", n);
  for (EGLint i = 0; i < n; i++) {
    const char *file = eglQueryDeviceStringEXT(devs[i], EGL_DRM_DEVICE_FILE_EXT);
    const char *render = eglQueryDeviceStringEXT(devs[i], EGL_DRM_RENDER_NODE_FILE_EXT);
    printf("  device %d: drm=%s render=%s\n", i, file ? file : "-", render ? render : "-");
  }
}

static EGLConfig pick_config(EGLDisplay dpy, uint32_t format) {
  EGLint attrs[] = {EGL_SURFACE_TYPE, EGL_WINDOW_BIT, EGL_RED_SIZE, 8, EGL_GREEN_SIZE, 8,
                    EGL_BLUE_SIZE, 8, EGL_RENDERABLE_TYPE, EGL_OPENGL_ES2_BIT, EGL_NONE};
  EGLConfig cfgs[64];
  EGLint n = 0;
  if (!eglChooseConfig(dpy, attrs, cfgs, 64, &n)) return NULL;
  for (EGLint i = 0; i < n; i++) {
    EGLint visual = 0;
    eglGetConfigAttrib(dpy, cfgs[i], EGL_NATIVE_VISUAL_ID, &visual);
    if ((uint32_t)visual == format) return cfgs[i];
  }
  return NULL;
}

static void path_a(struct gbm_device *gbm, EGLDisplay dpy, EGLContext ctx, EGLConfig cfg) {
  struct gbm_surface *surf = gbm_surface_create(gbm, 1920, 1080, GBM_FORMAT_XRGB8888,
                                                GBM_BO_USE_SCANOUT | GBM_BO_USE_RENDERING);
  check(surf != NULL, "A: gbm_surface_create XRGB8888 scanout|rendering");
  if (!surf) return;
  PROC(PFNEGLCREATEPLATFORMWINDOWSURFACEEXTPROC, eglCreatePlatformWindowSurfaceEXT);
  EGLSurface es = eglCreatePlatformWindowSurfaceEXT(dpy, cfg, surf, NULL);
  check(es != EGL_NO_SURFACE, "A: eglCreatePlatformWindowSurface on gbm_surface");
  if (es == EGL_NO_SURFACE) { printf("   egl error 0x%x\n", eglGetError()); gbm_surface_destroy(surf); return; }
  check(eglMakeCurrent(dpy, es, es, ctx), "A: eglMakeCurrent window surface");
  glClearColor(1, 0, 0, 1);
  glClear(GL_COLOR_BUFFER_BIT);
  check(eglSwapBuffers(dpy, es), "A: eglSwapBuffers");
  struct gbm_bo *bo = gbm_surface_lock_front_buffer(surf);
  check(bo != NULL, "A: gbm_surface_lock_front_buffer");
  if (bo) {
    printf("   front buffer: format=0x%x modifier=0x%016" PRIx64 " stride=%u planes=%d\n", gbm_bo_get_format(bo),
           gbm_bo_get_modifier(bo), gbm_bo_get_stride(bo), gbm_bo_get_plane_count(bo));
    gbm_surface_release_buffer(surf, bo);
  }
  eglMakeCurrent(dpy, EGL_NO_SURFACE, EGL_NO_SURFACE, EGL_NO_CONTEXT);
  eglDestroySurface(dpy, es);
  gbm_surface_destroy(surf);
}

// Allocate with the given modifiers, import as EGLImage, render through an FBO, read back.
static void path_b(struct gbm_device *gbm, EGLDisplay dpy, EGLContext ctx, const uint64_t *mods, int nmods,
                   const char *label) {
  char what[160];
  struct gbm_bo *bo = gbm_bo_create_with_modifiers2(gbm, 1920, 1080, GBM_FORMAT_XRGB8888, mods, nmods,
                                                    GBM_BO_USE_SCANOUT | GBM_BO_USE_RENDERING);
  snprintf(what, sizeof what, "B[%s]: gbm_bo_create_with_modifiers2 scanout|rendering", label);
  check(bo != NULL, what);
  if (!bo) return;
  uint64_t mod = gbm_bo_get_modifier(bo);
  int fd = gbm_bo_get_fd(bo);
  printf("   bo: modifier=0x%016" PRIx64 " stride=%u offset=%u fd=%d\n", mod, gbm_bo_get_stride_for_plane(bo, 0),
         gbm_bo_get_offset(bo, 0), fd);
  snprintf(what, sizeof what, "B[%s]: export dma-buf fd", label);
  check(fd >= 0, what);
  if (fd < 0) { gbm_bo_destroy(bo); return; }
  EGLint attrs[] = {EGL_WIDTH, 1920, EGL_HEIGHT, 1080, EGL_LINUX_DRM_FOURCC_EXT, DRM_FORMAT_XRGB8888,
                    EGL_DMA_BUF_PLANE0_FD_EXT, fd, EGL_DMA_BUF_PLANE0_OFFSET_EXT, (EGLint)gbm_bo_get_offset(bo, 0),
                    EGL_DMA_BUF_PLANE0_PITCH_EXT, (EGLint)gbm_bo_get_stride_for_plane(bo, 0),
                    EGL_DMA_BUF_PLANE0_MODIFIER_LO_EXT, (EGLint)(mod & 0xffffffff),
                    EGL_DMA_BUF_PLANE0_MODIFIER_HI_EXT, (EGLint)(mod >> 32), EGL_NONE};
  PROC(PFNEGLCREATEIMAGEKHRPROC, eglCreateImageKHR);
  PROC(PFNEGLDESTROYIMAGEKHRPROC, eglDestroyImageKHR);
  EGLImageKHR img = eglCreateImageKHR(dpy, EGL_NO_CONTEXT, EGL_LINUX_DMA_BUF_EXT, NULL, attrs);
  snprintf(what, sizeof what, "B[%s]: eglCreateImage from dma-buf", label);
  check(img != EGL_NO_IMAGE_KHR, what);
  if (img == EGL_NO_IMAGE_KHR) { printf("   egl error 0x%x\n", eglGetError()); close(fd); gbm_bo_destroy(bo); return; }

  eglMakeCurrent(dpy, EGL_NO_SURFACE, EGL_NO_SURFACE, ctx);
  PFNGLEGLIMAGETARGETRENDERBUFFERSTORAGEOESPROC rbStorage =
      (PFNGLEGLIMAGETARGETRENDERBUFFERSTORAGEOESPROC)eglGetProcAddress("glEGLImageTargetRenderbufferStorageOES");
  PFNGLEGLIMAGETARGETTEXTURE2DOESPROC texStorage =
      (PFNGLEGLIMAGETARGETTEXTURE2DOESPROC)eglGetProcAddress("glEGLImageTargetTexture2DOES");
  GLuint rb, fb, tex;
  glGenRenderbuffers(1, &rb);
  glBindRenderbuffer(GL_RENDERBUFFER, rb);
  rbStorage(GL_RENDERBUFFER, img);
  glGenFramebuffers(1, &fb);
  glBindFramebuffer(GL_FRAMEBUFFER, fb);
  glFramebufferRenderbuffer(GL_FRAMEBUFFER, GL_COLOR_ATTACHMENT0, GL_RENDERBUFFER, rb);
  GLenum status = glCheckFramebufferStatus(GL_FRAMEBUFFER);
  printf("   framebuffer status 0x%x\n", status);
  snprintf(what, sizeof what, "B[%s]: FBO on imported dma-buf is complete (Orin fails here)", label);
  check(status == GL_FRAMEBUFFER_COMPLETE, what);
  if (status == GL_FRAMEBUFFER_COMPLETE) {
    glViewport(0, 0, 1920, 1080);
    glClearColor(0, 1, 0, 1);
    glClear(GL_COLOR_BUFFER_BIT);
    unsigned char px[4] = {0};
    glReadPixels(10, 10, 1, 1, GL_RGBA, GL_UNSIGNED_BYTE, px);
    printf("   pixel read back: %u %u %u %u\n", px[0], px[1], px[2], px[3]);
    snprintf(what, sizeof what, "B[%s]: render into imported buffer and read back green", label);
    check(px[0] < 10 && px[1] > 245 && px[2] < 10, what);
  }
  glGenTextures(1, &tex);
  glBindTexture(GL_TEXTURE_2D, tex);
  texStorage(GL_TEXTURE_2D, img);
  snprintf(what, sizeof what, "B[%s]: sample path: EGLImage as GL texture", label);
  check(glGetError() == GL_NO_ERROR, what);
  glDeleteTextures(1, &tex);
  glDeleteFramebuffers(1, &fb);
  glDeleteRenderbuffers(1, &rb);
  eglDestroyImageKHR(dpy, img);
  close(fd);
  gbm_bo_destroy(bo);
}

static void fences(EGLDisplay dpy, EGLContext ctx) {
  PROC(PFNEGLCREATESYNCKHRPROC, eglCreateSyncKHR);
  PROC(PFNEGLDUPNATIVEFENCEFDANDROIDPROC, eglDupNativeFenceFDANDROID);
  PROC(PFNEGLDESTROYSYNCKHRPROC, eglDestroySyncKHR);
  if (!eglCreateSyncKHR || !eglDupNativeFenceFDANDROID) { check(0, "native fence functions available"); return; }
  eglMakeCurrent(dpy, EGL_NO_SURFACE, EGL_NO_SURFACE, ctx);
  glClear(GL_COLOR_BUFFER_BIT);
  EGLSyncKHR s = eglCreateSyncKHR(dpy, EGL_SYNC_NATIVE_FENCE_ANDROID, NULL);
  glFlush();
  int fd = s == EGL_NO_SYNC_KHR ? -1 : eglDupNativeFenceFDANDROID(dpy, s);
  check(fd >= 0, "explicit sync: export native fence fd");
  if (fd >= 0) close(fd);
  if (s != EGL_NO_SYNC_KHR) eglDestroySyncKHR(dpy, s);
}

// What Hyprland does when EGL_EXT_platform_device is present: EGL on the platform
// device matching the KMS node, buffers allocated through GBM on another node
// (aquamarine reopens the KMS device as its render node). Try every EGL device.
static int device_platform(const char *alloc_node) {
  PROC(PFNEGLQUERYDEVICESEXTPROC, eglQueryDevicesEXT);
  PROC(PFNEGLQUERYDEVICESTRINGEXTPROC, eglQueryDeviceStringEXT);
  PROC(PFNEGLGETPLATFORMDISPLAYEXTPROC, eglGetPlatformDisplayEXT);
  PROC(PFNEGLQUERYDMABUFMODIFIERSEXTPROC, eglQueryDmaBufModifiersEXT);
  int fd = open(alloc_node, O_RDWR | O_CLOEXEC);
  struct gbm_device *gbm = fd >= 0 ? gbm_create_device(fd) : NULL;
  check(gbm != NULL, "allocator gbm_create_device");
  if (!gbm) return 1;
  EGLDeviceEXT devs[16];
  EGLint n = 0;
  eglQueryDevicesEXT(16, devs, &n);
  for (EGLint i = 0; i < n; i++) {
    const char *file = eglQueryDeviceStringEXT(devs[i], EGL_DRM_DEVICE_FILE_EXT);
    const char *render = eglQueryDeviceStringEXT(devs[i], EGL_DRM_RENDER_NODE_FILE_EXT);
    if (!file) continue;
    char label[160];
    snprintf(label, sizeof label, "egl device %d (drm=%s render=%s) <- buffers from %s", i, file,
             render ? render : "-", alloc_node);
    printf("== %s\n", label);
    EGLDisplay dpy = eglGetPlatformDisplayEXT(EGL_PLATFORM_DEVICE_EXT, devs[i], NULL);
    EGLint maj, min;
    int init = dpy != EGL_NO_DISPLAY && eglInitialize(dpy, &maj, &min);
    check(init, "device-platform eglInitialize");
    if (!init) continue;
    eglBindAPI(EGL_OPENGL_ES_API);
    EGLint cattrs[] = {EGL_CONTEXT_CLIENT_VERSION, 2, EGL_NONE};
    EGLContext ctx = eglCreateContext(dpy, EGL_NO_CONFIG_KHR, EGL_NO_CONTEXT, cattrs);
    check(ctx != EGL_NO_CONTEXT, "device-platform GLES2 context without config");
    if (ctx == EGL_NO_CONTEXT) continue;
    uint64_t mods[64];
    EGLBoolean ext_only[64];
    EGLint nmods = 0, renderable = 0;
    eglQueryDmaBufModifiersEXT(dpy, DRM_FORMAT_XRGB8888, 64, mods, ext_only, &nmods);
    for (EGLint k = 0; k < nmods; k++)
      if (!ext_only[k]) mods[renderable++] = mods[k];
    if (renderable) path_b(gbm, dpy, ctx, mods, renderable, label);
    eglMakeCurrent(dpy, EGL_NO_SURFACE, EGL_NO_SURFACE, EGL_NO_CONTEXT);
    eglDestroyContext(dpy, ctx);
  }
  printf("RESULT %s: %d failure(s)\n", fails ? "FAIL" : "PASS", fails);
  return fails ? 1 : 0;
}

int main(int argc, char **argv) {
  if (argc == 3 && strcmp(argv[1], "--device-platform") == 0) return device_platform(argv[2]);
  if (argc != 2) { fprintf(stderr, "usage: %s /dev/dri/NODE | --device-platform /dev/dri/ALLOC_NODE\n", argv[0]); return 2; }
  list_egl_devices();
  int fd = open(argv[1], O_RDWR | O_CLOEXEC);
  check(fd >= 0, "open DRM node");
  if (fd < 0) { perror(argv[1]); return 1; }
  drmVersionPtr v = drmGetVersion(fd);
  printf("node %s driver %s\n", argv[1], v ? v->name : "?");
  struct gbm_device *gbm = gbm_create_device(fd);
  check(gbm != NULL, "gbm_create_device");
  if (!gbm) return 1;
  printf("gbm backend: %s\n", gbm_device_get_backend_name(gbm));

  PROC(PFNEGLGETPLATFORMDISPLAYEXTPROC, eglGetPlatformDisplayEXT);
  EGLDisplay dpy = eglGetPlatformDisplayEXT(EGL_PLATFORM_GBM_KHR, gbm, NULL);
  EGLint maj, min;
  int init = dpy != EGL_NO_DISPLAY && eglInitialize(dpy, &maj, &min);
  check(init, "eglInitialize on GBM platform with a real gbm_device");
  if (!init) { printf("   egl error 0x%x\n", eglGetError()); return 1; }
  const char *ext = eglQueryString(dpy, EGL_EXTENSIONS);
  printf("EGL %d.%d vendor=%s\n", maj, min, eglQueryString(dpy, EGL_VENDOR));
  const char *need[] = {"EGL_EXT_image_dma_buf_import", "EGL_EXT_image_dma_buf_import_modifiers",
                        "EGL_KHR_image_base", "EGL_KHR_surfaceless_context", "EGL_ANDROID_native_fence_sync",
                        "EGL_KHR_wait_sync"};
  for (size_t i = 0; i < sizeof need / sizeof *need; i++) {
    char what[96];
    snprintf(what, sizeof what, "extension %s", need[i]);
    check(has_ext(ext, need[i]), what);
  }
  PROC(PFNEGLQUERYDISPLAYATTRIBEXTPROC, eglQueryDisplayAttribEXT);
  PROC(PFNEGLQUERYDEVICESTRINGEXTPROC, eglQueryDeviceStringEXT);
  EGLAttrib dev = 0;
  if (eglQueryDisplayAttribEXT && eglQueryDisplayAttribEXT(dpy, EGL_DEVICE_EXT, &dev) && dev) {
    const char *f = eglQueryDeviceStringEXT((EGLDeviceEXT)dev, EGL_DRM_DEVICE_FILE_EXT);
    printf("GBM display maps to EGL device drm=%s\n", f ? f : "-");
  }

  eglBindAPI(EGL_OPENGL_ES_API);
  EGLConfig cfg = pick_config(dpy, GBM_FORMAT_XRGB8888);
  check(cfg != NULL, "EGL config with native visual XRGB8888");
  EGLint cattrs[] = {EGL_CONTEXT_CLIENT_VERSION, 2, EGL_NONE};
  EGLContext ctx = eglCreateContext(dpy, cfg ? cfg : EGL_NO_CONFIG_KHR, EGL_NO_CONTEXT, cattrs);
  check(ctx != EGL_NO_CONTEXT, "GLES2 context");
  if (ctx == EGL_NO_CONTEXT) return 1;
  eglMakeCurrent(dpy, EGL_NO_SURFACE, EGL_NO_SURFACE, ctx);
  printf("GL renderer: %s | %s\n", glGetString(GL_RENDERER), glGetString(GL_VERSION));

  if (cfg) path_a(gbm, dpy, ctx, cfg);

  PROC(PFNEGLQUERYDMABUFMODIFIERSEXTPROC, eglQueryDmaBufModifiersEXT);
  uint64_t mods[64];
  EGLBoolean ext_only[64];
  EGLint nmods = 0;
  if (eglQueryDmaBufModifiersEXT) eglQueryDmaBufModifiersEXT(dpy, DRM_FORMAT_XRGB8888, 64, mods, ext_only, &nmods);
  printf("EGL modifiers for XRGB8888: %d\n", nmods);
  int renderable = 0;
  for (EGLint i = 0; i < nmods; i++) {
    printf("   0x%016" PRIx64 "%s\n", mods[i], ext_only[i] ? " (external only)" : "");
    if (!ext_only[i]) mods[renderable++] = mods[i];
  }
  if (renderable) path_b(gbm, dpy, ctx, mods, renderable, "egl modifiers");
  uint64_t linear = DRM_FORMAT_MOD_LINEAR;
  path_b(gbm, dpy, ctx, &linear, 1, "linear");
  fences(dpy, ctx);

  printf("RESULT %s: %d failure(s)\n", fails ? "FAIL" : "PASS", fails);
  return fails ? 1 : 0;
}
