"""Analysis worker for user-submitted fields (runs as spherex-worker.service, separate from the web server).

The web server validates a request and drops var/queue/<time>_<id>.json; this process takes the oldest,
runs the full pipeline on a 0.3 deg field and keeps var/jobs/<id>.json up to date (status + last log lines),
so job state survives restarts of either process. A failed job's partial output is removed.

    python -m web.worker
"""
import json
import shutil
import sys
import time
import traceback
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
FIELDS = ROOT / "web" / "data" / "fields"
QUEUE, JOBS = ROOT / "var" / "queue", ROOT / "var" / "jobs"
MODELS = ROOT / "models"
POLL_S = 3                      # how often an empty queue is looked at again
SAVE_EVERY_S = 2                # the state file is rewritten at most this often while a job logs
LOG_KEEP = 200                  # log lines kept in a job's state file
REQUEUE_HEAD = "0000000000.000"  # queue-file prefix that sorts before every timestamp
KEEP_ON_REFRESH = ("universe.json", "deep_rgb.webp")      # hand-made products carried over to a refreshed field


def save(job):
    """Write a job's state file atomically (the web server reads it at any moment)."""
    tmp = JOBS / f".{job['id']}.tmp"
    tmp.write_text(json.dumps(job), encoding="utf-8")
    tmp.replace(JOBS / f"{job['id']}.json")


def recover():
    """A job left 'running' by a crash or restart goes back to the queue head."""
    for p in JOBS.glob("*.json"):
        try:
            j = json.loads(p.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if j.get("status") == "running":
            j["status"] = "queued"
            j.setdefault("log", []).append("worker restarted; job requeued")
            save(j)
            item = j.get("item") or {"id": j["id"], "ra": j["ra"], "dec": j["dec"], "size": j.get("size", 0.3)}
            (QUEUE / f"{REQUEUE_HEAD}_{j['id']}.json").write_text(json.dumps(item), encoding="utf-8")


def _swap_in(fid, tmp, doc):
    """Replace the live field <fid> by the refreshed build <tmp>, keeping its id and hand-made products."""
    from sxlib.analyze import write_doc
    old, new = FIELDS / fid, FIELDS / tmp
    prev = json.loads((old / "field.json").read_text(encoding="utf-8"))
    doc["id"] = fid
    for keep in KEEP_ON_REFRESH:
        if (old / keep).exists() and not (new / keep).exists():
            shutil.copy2(old / keep, new / keep)
    write_doc(new, doc)
    retired = FIELDS / f"{fid}.old"
    shutil.rmtree(retired, ignore_errors=True)
    old.rename(retired)
    new.rename(old)
    shutil.rmtree(retired, ignore_errors=True)
    return prev


def run(item, scorer):
    from sxlib.analyze import analyze_field
    fid = item["id"]
    job = json.loads((JOBS / f"{fid}.json").read_text(encoding="utf-8"))
    job.update(status="running", started=time.time())
    save(job)
    last = [0.0]

    def log(msg):
        job["log"] = (job["log"] + [str(msg)])[-LOG_KEEP:]
        if time.time() - last[0] > SAVE_EVERY_S:          # don't rewrite the state file on every line
            last[0] = time.time()
            save(job)
    size = float(item.get("size", 0.3))
    refresh = bool(item.get("refresh"))
    # a refresh is built next to the live field and swapped in only when complete
    tmp = f"{fid}.new" if refresh else fid
    name = item.get("name") or f"RA {item['ra']:.3f}, Dec {item['dec']:+.3f}"
    desc = item.get("description") or "Analysed on request from the web app."
    try:
        shutil.rmtree(FIELDS / f"{fid}.new", ignore_errors=True)
        doc = analyze_field(tmp, name, item["ra"], item["dec"], size, FIELDS, scorer, description=desc,
                            simulate_planet_x=bool(item.get("simulate")), log=log)
        if refresh:
            kl = doc.get("known_lookup") or {}
            if kl.get("failed"):        # never replace a good field by one that silently lost its known asteroids
                raise RuntimeError(f"JPL lookup failed for {kl['failed']} of {kl.get('visits')} visits; kept the old field")
            prev = _swap_in(fid, tmp, doc)
            if prev.get("target"):                           # re-measure a named target on the new data
                from scripts.build_targets import annotate
                annotate(fid)
            log("updated with the newest data")
        job["status"] = "done"
    except Exception as e:  # noqa: BLE001
        job.update(status="error", error=str(e)[:300])
        log("ERROR: " + traceback.format_exc(limit=2).splitlines()[-1])
        shutil.rmtree(FIELDS / tmp, ignore_errors=True)      # never leave a half-written field behind
    job["finished"] = time.time()
    save(job)


def main():
    for d in (QUEUE, JOBS):
        d.mkdir(parents=True, exist_ok=True)
    recover()
    from sxlib.rbnet import Scorer
    scorer = Scorer(MODELS / "rb_cnn.pt")
    print("worker ready", flush=True)
    while True:
        items = sorted(QUEUE.glob("*.json"))
        if not items:
            time.sleep(POLL_S)
            continue
        p = items[0]
        try:
            item = json.loads(p.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            item = None                                       # a broken queue file is dropped, not retried forever
        finally:
            p.unlink(missing_ok=True)
        if item is None:
            continue
        print("job", item["id"], flush=True)
        run(item, scorer)


if __name__ == "__main__":
    main()     # niceness comes from the unit (Nice=10)
