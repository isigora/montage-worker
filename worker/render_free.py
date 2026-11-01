"""Render a project's approved edit with plain FFmpeg, without calling Claude.

Reads edit_decisions + asset_manifest that the agent already wrote and builds
renders/final.mp4: cuts in order (1280x720, 30 fps), narration placed at its
start times, music under it, subtitles burned in when a subtitle file exists.
"""
from __future__ import annotations

import json
import subprocess
import tempfile
from pathlib import Path

W, H, FPS = 1280, 720, 30
IMAGE_EXT = {".png", ".jpg", ".jpeg", ".webp"}


def _log(msg: str) -> None:
    print(f"[render-free] {msg}", flush=True)


def _run(cmd: list[str]) -> None:
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError(f"ffmpeg failed: {' '.join(cmd[:6])}...\n{r.stderr[-1500:]}")


def _duration(p: Path) -> float:
    r = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                        "-of", "default=nw=1:nk=1", str(p)], capture_output=True, text=True)
    try:
        return float(r.stdout.strip())
    except ValueError:
        return 0.0


def _artifact(proj: Path, name: str) -> dict | None:
    """Find an artifact in checkpoints (newest first) or artifacts/<name>.json."""
    cands = []
    for cp in proj.glob("checkpoint_*.json"):
        try:
            data = json.loads(cp.read_text())
        except Exception:
            continue
        art = (data.get("artifacts") or {}).get(name)
        if isinstance(art, dict):
            cands.append((cp.stat().st_mtime, art))
    f = proj / "artifacts" / f"{name}.json"
    if f.exists():
        try:
            cands.append((f.stat().st_mtime, json.loads(f.read_text())))
        except Exception:
            pass
    return max(cands, key=lambda c: c[0])[1] if cands else None


def _resolver(proj: Path, manifest: dict | None):
    by_id = {a["id"]: a for a in (manifest or {}).get("assets", []) if "id" in a and "path" in a}

    def resolve(ref: str | None) -> Path | None:
        if not ref:
            return None
        if ref in by_id:
            ref = by_id[ref]["path"]
        for cand in (Path(ref), proj / ref, proj.parent.parent / ref):
            if cand.is_file():
                return cand.resolve()
        hits = list(proj.rglob(Path(ref).name))
        return hits[0].resolve() if hits else None

    return resolve, by_id


def render(proj: Path) -> Path:
    edit = _artifact(proj, "edit_decisions")
    if not edit:
        raise RuntimeError("edit_decisions not found")
    manifest = _artifact(proj, "asset_manifest")
    resolve, by_id = _resolver(proj, manifest)
    out = proj / "renders" / "final.mp4"
    out.parent.mkdir(parents=True, exist_ok=True)

    cuts = [c for c in edit.get("cuts", []) if c.get("layer", "primary") == "primary"]
    _log(f"{len(cuts)} cuts")
    with tempfile.TemporaryDirectory(dir=proj) as tmpd:
        tmp = Path(tmpd)
        segs = []
        vf = (f"scale={W}:{H}:force_original_aspect_ratio=decrease,"
              f"pad={W}:{H}:(ow-iw)/2:(oh-ih)/2,setsar=1,fps={FPS},format=yuv420p")
        for i, c in enumerate(cuts):
            src = resolve(c.get("source"))
            if not src:
                _log(f"skip cut {c.get('id')}: source not found ({c.get('source')})")
                continue
            dur = max(0.2, float(c["out_seconds"]) - float(c["in_seconds"]))
            speed = float(c.get("speed") or 1.0)
            seg = tmp / f"seg_{i:03d}.mp4"
            if src.suffix.lower() in IMAGE_EXT:
                cmd = ["ffmpeg", "-nostdin", "-y", "-loop", "1", "-t", f"{dur:.3f}", "-i", str(src),
                       "-vf", vf, "-an", "-c:v", "libx264", "-preset", "veryfast", "-crf", "22", str(seg)]
            else:
                f = vf if speed == 1.0 else f"setpts=PTS/{speed},{vf}"
                cmd = ["ffmpeg", "-nostdin", "-y", "-ss", f"{float(c['in_seconds']):.3f}", "-t", f"{dur:.3f}",
                       "-i", str(src), "-vf", f, "-an", "-c:v", "libx264", "-preset", "veryfast",
                       "-crf", "22", str(seg)]
            _run(cmd)
            segs.append(seg)
        if not segs:
            raise RuntimeError("no usable cuts")
        lst = tmp / "list.txt"
        lst.write_text("".join(f"file '{s}'\n" for s in segs))
        video = tmp / "video.mp4"
        _run(["ffmpeg", "-nostdin", "-y", "-f", "concat", "-safe", "0", "-i", str(lst), "-c", "copy", str(video)])
        total = _duration(video)
        _log(f"video {total:.1f}s")

        # Audio: narration segments + music bed.
        audio = edit.get("audio") or {}
        inputs, filters, labels = [], [], []
        n_in = 0
        for seg in (audio.get("narration") or {}).get("segments", []):
            p = resolve(seg.get("asset_id"))
            if not p:
                _log(f"skip narration {seg.get('asset_id')}")
                continue
            k = n_in
            n_in += 1
            inputs += ["-i", str(p)]
            ms = int(float(seg.get("start_seconds", 0)) * 1000)
            filters.append(f"[{k}:a]aresample=48000,aformat=channel_layouts=stereo,adelay={ms}|{ms}[n{k}]")
            labels.append(f"[n{k}]")
        music = audio.get("music") or edit.get("music") or {}
        mp = resolve(music.get("asset_id"))
        if mp:
            k = n_in
            n_in += 1
            inputs += ["-stream_loop", "-1", "-i", str(mp)]
            vol = float(music.get("volume", 0.25))
            fo = float(music.get("fade_out_seconds", 2))
            filters.append(f"[{k}:a]aresample=48000,aformat=channel_layouts=stereo,volume={vol},atrim=0:{total:.3f},"
                           f"afade=t=out:st={max(0, total - fo):.3f}:d={fo:.3f}[m]")
            labels.append("[m]")
        mixed = None
        if labels:
            filters.append(f"{''.join(labels)}amix=inputs={len(labels)}:normalize=0,"
                           f"apad=whole_dur={total:.3f},atrim=0:{total:.3f}[aout]")
            mixed = tmp / "audio.m4a"
            _run(["ffmpeg", "-nostdin", "-y", *inputs, "-filter_complex", ";".join(filters),
                  "-map", "[aout]", "-c:a", "aac", "-b:a", "160k", str(mixed)])

        # Subtitles.
        subs = edit.get("subtitles") or {}
        sp = resolve(subs.get("source")) if subs.get("enabled", True) else None
        if not sp:
            found = [p for p in proj.rglob("*") if p.suffix.lower() in {".srt", ".ass"} and "history" not in p.parts]
            sp = found[0] if found else None
        cmd = ["ffmpeg", "-nostdin", "-y", "-i", str(video)]
        if mixed:
            cmd += ["-i", str(mixed)]
        if sp:
            esc = str(sp).replace("\\", "\\\\").replace(":", "\\:").replace("'", "\\'")
            style = "FontName=Noto Sans CJK KR,FontSize=22,Outline=2,MarginV=40"
            cmd += ["-vf", f"subtitles='{esc}':force_style='{style}'"]
            _log(f"subtitles {sp.name}")
        cmd += ["-map", "0:v"] + (["-map", "1:a", "-c:a", "copy"] if mixed else [])
        cmd += ["-c:v", "libx264", "-preset", "veryfast", "-crf", "21", "-movflags", "+faststart",
                "-shortest", str(out)]
        _run(cmd)
    _log(f"done {out} {_duration(out):.1f}s {out.stat().st_size // 1024} KB")
    return out
