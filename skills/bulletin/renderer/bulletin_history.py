#!/usr/bin/env python3
"""
Query the bulletin log (weekly-bulletins/bulletin-log.json).

The log is written automatically by render_bulletin.py on every render;
--backfill seeds it from every bulletin-config.json already on disk.

Usage:
    python3 bulletin_history.py --hymn "mighty fortress"
    python3 bulletin_history.py --reading "Matthew 18"
    python3 bulletin_history.py --preacher            # tally by preacher
    python3 bulletin_history.py --recent 8            # last N services
    python3 bulletin_history.py --backfill            # seed from configs
"""

import argparse
import json
import sys
from datetime import date
from pathlib import Path

import os

HERE = Path(__file__).resolve().parent


def find_bulletins_root(start):
    start = Path(start).resolve()
    for cand in [start] + list(start.parents):
        if cand.name in ("bulletins", "weekly-bulletins"):
            return cand
        for name in ("bulletins", "weekly-bulletins"):
            d = cand / name
            if d.is_dir():
                return d
    return start


WEEKLY = find_bulletins_root(os.environ.get("CHURCH_FOLDER", "."))
LOG_PATH = WEEKLY / "bulletin-log.json"

sys.path.insert(0, str(HERE))
from render_bulletin import build_log_entry  # noqa: E402


def load_log():
    if not LOG_PATH.exists():
        print(f"No log yet at {LOG_PATH}. Run --backfill or render a bulletin.")
        sys.exit(1)
    return json.loads(LOG_PATH.read_text(encoding="utf-8"))


def weeks_ago(datestr):
    try:
        y, m, d = (int(x) for x in datestr.split("-"))
        delta = (date.today() - date(y, m, d)).days
    except Exception:
        return ""
    if delta < 0:
        return f"(in {-delta} days)"
    if delta < 14:
        return f"({delta} days ago)"
    return f"({delta // 7} weeks ago)"


def cmd_hymn(log, needle):
    needle = needle.lower()
    hits = []
    for d, e in sorted(log.items(), reverse=True):
        for h in e.get("hymns", []) + e.get("service_music", []):
            title = (h.get("title") or "").lower()
            num = str(h.get("number") or "")
            hid = (h.get("id") or "").lower()
            if needle in title or needle == num.lower() or needle == hid:
                hits.append((d, e, h))
    if not hits:
        print(f"Never recorded: no bulletin in the log includes '{needle}'.")
        return
    d0, e0, h0 = hits[0]
    label = h0.get("title") or h0.get("id")
    print(f"Last sung: {d0} {weeks_ago(d0)} - {e0.get('occasion')} "
          f"({h0.get('slot')})")
    print(f"  {label}" + (f" - Hymn {h0['number']}" if h0.get("number") else ""))
    if len(hits) > 1:
        print(f"All {len(hits)} uses on record:")
        for d, e, h in hits:
            print(f"  {d}  {h.get('slot'):<16} {e.get('occasion')}")


def cmd_reading(log, needle):
    needle = needle.lower()
    hits = []
    for d, e in sorted(log.items(), reverse=True):
        r = e.get("readings", {})
        for slot, cit in r.items():
            if cit and needle in str(cit).lower():
                hits.append((d, e, slot, cit))
    if not hits:
        print(f"No recorded service used a reading matching '{needle}'.")
        return
    for d, e, slot, cit in hits:
        print(f"{d}  {slot:<8} {cit}  - {e.get('occasion')} {weeks_ago(d)}")


def cmd_preacher(log, name=None):
    tally = {}
    for d, e in sorted(log.items(), reverse=True):
        p = e.get("preacher") or "(unrecorded)"
        tally.setdefault(p, []).append(d)
    if name:
        needle = name.lower()
        for p, dates in tally.items():
            if needle in p.lower():
                print(f"{p}: {len(dates)} service(s); last {dates[0]} "
                      f"{weeks_ago(dates[0])}")
        return
    for p, dates in sorted(tally.items(), key=lambda kv: -len(kv[1])):
        print(f"{len(dates):>3}  {p}  (last {dates[0]})")


def cmd_recent(log, n):
    for d, e in sorted(log.items(), reverse=True)[:n]:
        hymns = ", ".join(str(h.get("number") or h.get("id") or "?")
                          for h in e.get("hymns", []))
        tpl = ",".join(e.get("templates", {}).keys()) or "-"
        print(f"{d}  {e.get('occasion') or '?':<42.42} "
              f"preacher: {e.get('preacher') or '?':<24.24} "
              f"hymns: {hymns:<20.20} tpl: {tpl}")


def cmd_backfill():
    log = {}
    if LOG_PATH.exists():
        log = json.loads(LOG_PATH.read_text(encoding="utf-8"))
    added = 0
    for cfg_path in sorted(WEEKLY.glob("**/bulletin-config.json")):
        try:
            cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
            entry = build_log_entry(cfg)
        except Exception as exc:
            print(f"skip {cfg_path.relative_to(WEEKLY)}: {exc}")
            continue
        d = entry.get("date")
        if not d:
            print(f"skip {cfg_path.relative_to(WEEKLY)}: no service date")
            continue
        if d in log:
            continue  # rendered entries and earlier backfills win
        entry["templates"] = {}
        entry["backfilled_from"] = str(cfg_path.relative_to(WEEKLY))
        log[d] = entry
        added += 1
    ordered = {k: log[k] for k in sorted(log)}
    LOG_PATH.write_text(json.dumps(ordered, indent=2, ensure_ascii=False),
                        encoding="utf-8")
    print(f"Backfill complete: {added} added, {len(log)} total in "
          f"{LOG_PATH.name}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--hymn")
    ap.add_argument("--reading")
    ap.add_argument("--preacher", nargs="?", const="", default=None)
    ap.add_argument("--recent", type=int)
    ap.add_argument("--backfill", action="store_true")
    args = ap.parse_args()

    if args.backfill:
        cmd_backfill()
        return 0
    log = load_log()
    if args.hymn:
        cmd_hymn(log, args.hymn)
    elif args.reading:
        cmd_reading(log, args.reading)
    elif args.preacher is not None:
        cmd_preacher(log, args.preacher or None)
    elif args.recent:
        cmd_recent(log, args.recent)
    else:
        cmd_recent(log, 10)
    return 0


if __name__ == "__main__":
    sys.exit(main())
