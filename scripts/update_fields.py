"""Keep every field current with the newest SPHEREx data: python scripts/update_fields.py [--dry-run]

For each analysed field, asks the running web app (/api/field/<id>/fresh) whether IRSA has newer exposures and,
if so, queues a re-analysis (/api/field/<id>/refresh). The worker rebuilds the field next to the live one and swaps
it in when complete, re-measuring a named target. Meant for a weekly timer (deploy/spherex-update.timer).
Standard library only, so the timer can run it with any Python.
"""
import json
import sys
import urllib.request

BASE = "http://127.0.0.1:8791"
SKIP = {"planetx"}          # the simulated-planet field is a fixed test case
MAX_PER_RUN = 1             # each re-analysis caches ~0.4 GB of cutouts; one per weekly run keeps the disk safe
TIMEOUT = 300


def call(path, method="GET"):
    req = urllib.request.Request(BASE + path, method=method)
    with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
        return json.loads(r.read())


def main(dry=False):
    h = call("/api/health")
    if not h["ok"]:
        print(f"WARNING: only {h['disk_free_gb']} GB free (minimum {h['min_free_gb']} GB); no re-analysis this run")
        return
    queued = 0
    for f in call("/api/fields"):
        fid = f["id"]
        if fid in SKIP:
            continue
        try:
            fr = call(f"/api/field/{fid}/fresh")
        except Exception as e:  # noqa: BLE001
            print(fid, "check failed:", e)
            continue
        if not fr["n_new"]:
            print(fid, "up to date")
            continue
        if queued >= MAX_PER_RUN:
            print(fid, f"{fr['n_new']} new exposures, left for the next run")
            continue
        print(fid, f"{fr['n_new']} new exposures", "(dry run)" if dry else "-> queued")
        queued += 1
        if not dry:
            try:
                print("  ", call(f"/api/field/{fid}/refresh", "POST").get("status"))
            except Exception as e:  # noqa: BLE001 - queue full: the next run picks it up
                print("   not queued:", e)


if __name__ == "__main__":
    main("--dry-run" in sys.argv)
