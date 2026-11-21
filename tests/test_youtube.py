"""Asking YouTube less, and waiting when it refuses. Runs against the code directly; nothing is downloaded."""
import os
import sys
import tempfile
import time
from pathlib import Path

os.environ["PEAKCUT_DATA"] = tempfile.mkdtemp(prefix="pc-yt-")
os.environ["DATABASE_URL"] = ""
sys.path.insert(0, ".")
import yt_dlp  # noqa: E402
from studio import db, jobs, media  # noqa: E402

db.init()
fails = []


def check(name, got, want=True):
    ok = got == want
    print(("PASS " if ok else "FAIL ") + name + ("" if ok else f"  got {got!r}, want {want!r}"))
    ok or fails.append(name)


# ---- one opening of the video for everything
opened, fetched = [], []
RAW = {"id": "x", "title": "Um vídeo", "uploader": "Canal", "duration": 3419, "automatic_captions": {}, "subtitles": {}}


def fake_extract(self, url, download=False, process=True, **kw):
    opened.append(url)
    return dict(RAW)


def fake_process(self, info, download=True, **kw):
    fetched.append(info.get("title"))
    tmpl = self.params.get("outtmpl")
    tmpl = tmpl.get("default") if isinstance(tmpl, dict) else tmpl
    Path(tmpl.replace("%(ext)s", "mp4")).write_bytes(b"x")
    return info


yt_dlp.YoutubeDL.extract_info = fake_extract
yt_dlp.YoutubeDL.process_ie_result = fake_process
URL = "https://www.youtube.com/watch?v=abc"
work = Path(tempfile.mkdtemp(prefix="pc-yt-job-"))
i = media.info(URL)
media.youtube_words(URL)
media.download_audio(URL, work)
for n in range(3):
    media.download_section(URL, work / "clips", f"clip{n}.src", 100 + n * 60, 160 + n * 60)
check("the title and length come from the site", (i["title"], i["duration"]), ("Um vídeo", 3419.0))
check("the video is opened once for title, transcript, audio and three clips", (len(opened), len(fetched)), (1, 4))


def broken(self, info, download=True, **kw):
    raise RuntimeError("HTTP Error 403: Forbidden")


yt_dlp.YoutubeDL.process_ie_result = broken
try:
    media.download_section(URL, work / "clips", "late.src", 10, 20)
except RuntimeError:
    pass
yt_dlp.YoutubeDL.process_ie_result = fake_process
media.download_section(URL, work / "clips", "late.src", 10, 20)
check("a download that fails drops the kept answer, and the next one asks afresh", len(opened), 2)

# ---- YouTube refuses: the video waits and starts again by itself
media._yt_refused_until = time.time() + 600
job_dir = Path(tempfile.mkdtemp(prefix="pc-yt-wait-"))
job = {"id": "j1", "user": "u1", "dir": str(job_dir), "creator": None, "status": "running", "clips": [
    {"id": "clip01", "status": "done"}, {"id": "clip02", "status": "rendering"}]}
(job_dir / "words.json").write_text("[]", encoding="utf-8")
check("a refused video waits instead of failing", jobs._wait_for_youtube(job), True)
check("...it is back in line, saying when it tries again", (job["status"], "Tries again by itself at" in job["stage"]), ("queued", True))
check("...it carries on from what was done", (job["resume"], [c["status"] for c in job["clips"]]), (True, ["done", "queued"]))
job["yt_waits"] = jobs.YT_MAX_WAITS
check("...and after about three hours of refusals it is given up", jobs._wait_for_youtube(job), False)
check("the wait follows the pause YouTube asked for", 590 <= media.yt_pause_left() <= 600)

import shutil  # noqa: E402

db.engine.dispose()
for d in (os.environ["PEAKCUT_DATA"], work, job_dir):
    shutil.rmtree(d, ignore_errors=True)
print("ALL PASSED" if not fails else f"{len(fails)} FAILED")
sys.exit(1 if fails else 0)
