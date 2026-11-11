# Kaggle GPU render script v2 — R4 improvements over Phase 0 kaggle_render.py.
# Same contract (blender -b scene.blend -P kaggle_render_v2.py, env-driven),
# with the gaps found by R4 closed. Original kept untouched at kaggle_render.py.
#
# CHANGES vs v1 (each verified against Blender 4.5.15 bpy on disk, 2026-11-10):
#  1. Persistent Data ON (scene.render.use_persistent_data; default False in 4.5).
#     For animation this skips scene re-prep on every frame. On a T4 where a
#     frame renders in seconds, prep was a large fraction of wall time.
#  2. Adaptive sampling set EXPLICITLY (use_adaptive_sampling, adaptive_threshold,
#     adaptive_min_samples). v1 set only fixed samples and silently inherited
#     whatever the .blend had saved. Min samples 32 stops early cut-off blotches.
#  3. Animated seed ON (cycles.use_animated_seed; default False). Fixed seed =
#     static noise pattern, more visible in motion than varying noise.
#  4. Device audit: prints every detected GPU, asserts >=1 GPU when DEVICE != CPU,
#     runs nvidia-smi if present. v1 silently ran on 1 GPU if the 2nd was missed.
#  5. Crash-safe writes: render to fNNNN.tmp.png, os.replace() to final name.
#     v1's skip-if-exists accepted a half-written PNG from a killed session
#     as "done" and never re-rendered it.
#  6. Corrupt-frame validation on resume: existing PNG must be >10 KB and
#     openable (PNG signature check); otherwise it is re-rendered.
#  7. Per-frame CSV log (render_log.csv: frame, seconds, status, timestamp)
#     appended + flushed per frame. v1 logged only to stdout, which Kaggle
#     kernel logs can truncate/lose.
#  8. Per-frame try/except: one bad frame is logged FAILED and the run
#     continues; exit code is non-zero if any frame failed (v1 died entirely).
#  9. FRAME_STEP env + documented two-instance split: run two Blender
#     processes with CUDA_VISIBLE_DEVICES=0 / =1 and complementary ranges
#     for near-linear 2x scaling (one instance sharing both GPUs scales
#     only ~1.6-1.9x; see R4 report §1.3).
# 10. Eevee raytracing env (EEVEE_RAYTRACE=1) — Phase 0 Eevee rendered the
#     glass bowl as an opaque dome with raytracing off (default False).
# 11. FORMAT env (PNG default, OPEN_EXR_MULTILAYER optional). EXR note:
#     ~10-20 MB/frame x 1200 = 12-24 GB, over Kaggle's 20 GB output cap,
#     so PNG stays the default; EXR only for a shot-range, never the full job.
# 12. Pre-flight checks BEFORE the Blender download step in the shell wrapper:
#     .blend exists, FRAME_START <= FRAME_END, OUTDIR writable. (Shell side,
#     see R4 report §2.2.)
# NOT changed: engine/device/resolution/samples env names, skip-if-exists
# resume semantics, PNG default, OptiX-first device order.
import bpy
import os
import sys
import time
import csv
import subprocess

def env_int(name, default):
    try:
        return int(os.environ.get(name, str(default)))
    except ValueError:
        print("WARN bad int for %s, using %s" % (name, default))
        return default

engine = os.environ.get("ENGINE", "CYCLES")
device = os.environ.get("DEVICE", "OPTIX")  # OPTIX | CUDA | CPU
resx = env_int("RESX", 1080)
resy = env_int("RESY", 1920)
samples = env_int("SAMPLES", 64)
noise_threshold = float(os.environ.get("NOISE_THRESHOLD", "0.01"))
min_samples = env_int("MIN_SAMPLES", 32)
denoise = os.environ.get("DENOISE", "1") == "1"
outdir = os.environ.get("OUTDIR", "/kaggle/working/frames")
f_start = env_int("FRAME_START", 1)
f_end = env_int("FRAME_END", 1200)
f_step = env_int("FRAME_STEP", 1)
fmt = os.environ.get("FORMAT", "PNG")  # PNG | OPEN_EXR_MULTILAYER
depth = os.environ.get("DEPTH", "16")  # PNG color depth 8/16 (Q4: 16-bit final)
eevee_raytrace = os.environ.get("EEVEE_RAYTRACE", "0") == "1"
log_path = os.path.join(outdir, "render_log.csv")

scene = bpy.context.scene
scene.render.engine = engine
scene.render.resolution_x = resx
scene.render.resolution_y = resy
scene.render.resolution_percentage = 100
scene.render.image_settings.file_format = fmt
scene.render.image_settings.color_depth = depth  # Q4/Q5
scene.render.use_persistent_data = True  # (1) skip scene re-prep per frame
scene.frame_start = f_start
scene.frame_end = f_end

if engine == 'CYCLES':
    if device in ('OPTIX', 'CUDA'):
        scene.cycles.device = 'GPU'
        prefs = bpy.context.preferences.addons['cycles'].preferences
        prefs.compute_device_type = device
        prefs.get_devices()
        gpu_names = []
        for d in prefs.devices:
            if d.type in ('OPTIX', 'CUDA'):
                d.use = True
                gpu_names.append(d.name)
                print("GPU DEVICE ENABLED:", d.name, d.type)
        print("GPU_COUNT=%d %s" % (len(gpu_names), gpu_names))
        if not gpu_names:
            print("FATAL: DEVICE=%s requested but no GPU detected" % device)
            sys.exit(2)
        try:
            print(subprocess.run(["nvidia-smi", "--query-gpu=name,memory.total",
                  "--format=csv"], capture_output=True, text=True,
                  timeout=15).stdout)
        except Exception as e:
            print("nvidia-smi unavailable:", e)
    else:
        scene.cycles.device = 'CPU'
    scene.cycles.samples = samples
    scene.cycles.use_adaptive_sampling = True  # (2) explicit, not inherited
    scene.cycles.adaptive_threshold = noise_threshold
    scene.cycles.adaptive_min_samples = min_samples
    scene.cycles.use_denoising = denoise
    if denoise:
        scene.cycles.denoiser = 'OPENIMAGEDENOISE'
    scene.cycles.use_animated_seed = True  # (3) varying noise per frame
    print("COMBO cycles device=%s samples(max)=%d noise=%.3f min=%d denoise=%s "
          "res=%dx%d frames=%d-%d step=%d persistent=1"
          % (device, samples, noise_threshold, min_samples, denoise,
             resx, resy, f_start, f_end, f_step))
else:
    scene.eevee.taa_render_samples = samples
    scene.eevee.use_raytracing = eevee_raytrace  # (10) glass needs this
    print("COMBO eevee taa=%d raytrace=%s res=%dx%d frames=%d-%d step=%d"
          % (samples, eevee_raytrace, resx, resy, f_start, f_end, f_step))

os.makedirs(outdir, exist_ok=True)
ext = "png" if fmt == "PNG" else "exr"


def valid_frame(path):
    # (6) resume validation: exists + plausible size + PNG magic bytes.
    try:
        if not os.path.exists(path) or os.path.getsize(path) < 10240:
            return False
        if ext == "png":
            with open(path, "rb") as fh:
                return fh.read(8) == b"\x89PNG\r\n\x1a\n"
        return True
    except Exception:
        return False


log_exists = os.path.exists(log_path)
logf = open(log_path, "a", newline="")
writer = csv.writer(logf)
if not log_exists:
    writer.writerow(["frame", "seconds", "status", "timestamp"])
    logf.flush()

t_all = time.time()
done = skipped = failed = 0
for f in range(f_start, f_end + 1, f_step):
    path = os.path.join(outdir, "f%04d.%s" % (f, ext))
    if valid_frame(path):
        print("SKIP valid frame=%d" % f)
        skipped += 1
        continue
    tmp = os.path.join(outdir, "f%04d.tmp.%s" % (f, ext))
    scene.frame_set(f)
    scene.render.filepath = tmp
    t0 = time.time()
    try:
        bpy.ops.render.render(write_still=True)
        os.replace(tmp, path)  # (5) atomic publish, no half-written "done"
        dt = time.time() - t0
        done += 1
        writer.writerow([f, "%.2f" % dt, "OK",
                         time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())])
        logf.flush()
        print("FRAME_DONE frame=%d seconds=%.2f file=%s" % (f, dt, path))
    except Exception as e:
        dt = time.time() - t0
        failed += 1
        writer.writerow([f, "%.2f" % dt, "FAILED:%s" % e,
                         time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())])
        logf.flush()
        print("FRAME_FAILED frame=%d seconds=%.2f error=%s" % (f, dt, e))
        if os.path.exists(tmp):
            os.remove(tmp)
logf.close()
print("KAGGLE_RENDER_DONE rendered=%d skipped=%d failed=%d total_wall=%.1fs "
      "outdir=%s log=%s" % (done, skipped, failed, time.time() - t_all,
                            outdir, log_path))
if failed:
    sys.exit(3)
