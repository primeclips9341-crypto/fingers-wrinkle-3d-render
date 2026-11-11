# Fingers Wrinkle — Blender 3D Render Farm (GitHub Actions CPU)

Renders the true-3D Blender video **"Why Your Fingers Wrinkle in Water"** on
GitHub Actions free CPU runners. 1169 frames, 1080x1920, Cycles, 64 samples,
OpenImageDenoise, PNG 16-bit RGBA. Quality is locked — no Eevee, no lower
samples/resolution.

## How it works

- Scenes live in `scenes/` as **base64 text** (`.blend.b64`) because the GitHub
  MCP connector cannot push binary files. The workflow decodes each scene back
  to a byte-identical `.blend` (verified by md5 in `scenes/checksums.md5`)
  before rendering.
- The workflow downloads the official Blender **4.2.23** tarball (never a
  preinstalled Blender) and verifies `blender --version` prints 4.2.23.
- Render settings come from `kaggle_render_v3.py` (env-driven, same script used
  on Colab/Kaggle): `ENGINE=CYCLES DEVICE=CPU RESX=1080 RESY=1920 SAMPLES=64
  NOISE_THRESHOLD=0.01 MIN_SAMPLES=32 DENOISE=1 DEPTH=16`.
- Each job renders one frame range, verifies every PNG (magic bytes, >10 KB,
  1080x1920 16-bit RGBA), zips the frames + `render_log.csv`, and publishes the
  zip as a GitHub Release asset (downloadable without auth for this public repo).

## Dispatching a render

Edit `jobs.json` and push it — the workflow triggers on `jobs.json` changes.
Each entry: `{"scene", "frame_start", "frame_end", "tag"}`. The `tag` becomes
the release tag and the zip name, so it must be unique per job.

Frame ranges are the scenes' **stored ranges** (boundaries overlap by 1 frame;
dedupe happens at merge time, not during rendering):
- s1 hook: 1–189 (frames 1–40 already rendered on Colab; render 41–189 here)
- s2 mechanism: 189–497
- s3 twist: 497–796
- s4 payoff: 796–1039
- s5 takeaway: 1039–1170

## Files

- `.github/workflows/render.yml` — the render workflow
- `kaggle_render_v3.py` — env-driven Blender render script
- `scenes/*.blend.b64` — the 5 scene files, base64-encoded
- `scenes/checksums.md5` — md5 of the decoded .blend files
- `jobs.json` — the job matrix (edit + push to dispatch)
