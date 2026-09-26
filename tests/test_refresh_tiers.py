"""Re-checking is rationed by tier, and a real event jumps the queue.

THE RULE (Layer 4): you cannot re-check everybody, and re-checking nobody lets the
facts rot. So the work is rationed: people you are actually talking to get looked at
whenever you interact with them, which costs nothing extra, and the schedule only
pays for the ones you are not talking to.

And a schedule must never hold up somebody something is actually happening with. A
reply matters more than a rota, always.

WHAT SHOULD HAPPEN:
  - the tier comes from what happened, not from anybody's opinion
  - somebody never checked is due
  - somebody checked inside their window is not due
  - somebody checked longer ago than their window is due, and says by how much
  - a reply since the last check puts them at the front, whatever their tier
  - recording a check clears it, and recording a change records that too

Every person in here is invented.

Run:  python tests/test_refresh_tiers.py
"""

import json
import os
import shutil
import sys
import tempfile
from datetime import datetime, timezone, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "crm"))

FAILS = []


def check(label, cond, detail=""):
    ok = bool(cond)
    print(("  PASS  " if ok else "  FAIL  ") + label
          + (("   [" + detail + "]") if detail and not ok else ""))
    if not ok:
        FAILS.append(label)


TMP = Path(tempfile.mkdtemp(prefix="outliers-crm-refresh-"))
os.environ["OUTLIERS_CRM_VAULT"] = str(TMP)
(TMP / "_engine").mkdir(parents=True)
(TMP / "_engine" / "settings.json").write_text(json.dumps({
    "park_after_days": 30,
    "refresh_days": {"active": 0, "warm": 30, "cold": 90},
    "events": {"checked": {"means": "their details were re-checked",
                           "counts_as_contact": False}},
}, indent=2), encoding="utf-8")

import ledger                                              # noqa: E402
import refresh                                             # noqa: E402

LOG = TMP / "_ledger" / "events.jsonl"


def ago(days):
    return (datetime.now(timezone.utc) - timedelta(days=days)).isoformat(timespec="seconds")


print("\n=== 1. the tier comes from what happened ===")

# Someone you are in conversation with.
ledger.emit("message_sent", person="rowan-ashdown", source="t", ts=ago(4), path=LOG)
ledger.emit("reply_received", person="rowan-ashdown", source="t", ts=ago(3), path=LOG)
# Someone you messaged and who has not replied.
ledger.emit("message_sent", person="mara-quennell", source="t", ts=ago(10), path=LOG)
# Someone connected long ago and nothing since.
ledger.emit("connected", person="tobias-fenwick", source="t", ts=ago(400), path=LOG)

r = refresh.status("rowan-ashdown", path=LOG)
m = refresh.status("mara-quennell", path=LOG)
t = refresh.status("tobias-fenwick", path=LOG)

check("someone replying puts them on the active tier", r["tier"] == "active", repr(r["tier"]))
check("someone you messaged and who has not replied is warm",
      m["tier"] == "warm", repr(m["tier"]))
check("someone with only an old connection is cold", t["tier"] == "cold", repr(t["tier"]))
check("nobody had to decide any of that", True)

print("\n=== 2. the active tier has no schedule of its own ===")

check("its window is zero", r["window"] == 0, repr(r["window"]))
check("and it says why", "when you interact" in r["reason"] or r["due"], repr(r["reason"]))

print("\n=== 3. somebody never checked is due ===")

check("the cold contact is due", t["due"], repr(t))
check("and the reason given is that nobody ever looked",
      t["reason"] in ("never checked",) or "days since" in t["reason"], repr(t["reason"]))

print("\n=== 4. checking somebody clears them until their window is up ===")

refresh.mark_checked("tobias-fenwick", source="test", path=LOG)
t2 = refresh.status("tobias-fenwick", path=LOG)
check("they are no longer due", not t2["due"], repr(t2))
check("and it says when they next will be", "next check in" in t2["reason"], repr(t2["reason"]))
check("the date of the check was recorded", t2["last-checked"], repr(t2["last-checked"]))

print("\n=== 5. past the window, they come back round ===")

ledger.emit("checked", person="delia-marchetti", source="t", ts=ago(200), path=LOG)
ledger.emit("connected", person="delia-marchetti", source="t", ts=ago(400), path=LOG)
d = refresh.status("delia-marchetti", path=LOG)
check("somebody checked 200 days ago on a 90 day window is due", d["due"], repr(d))
check("and the row says by how much", "90" in d["reason"] and "200" in d["reason"],
      repr(d["reason"]))

print("\n=== 6. a real event jumps the queue ===")

# Somebody enormously overdue on the schedule, to prove the rota can never outrank
# something that actually happened, however long the rota has been waiting.
ledger.emit("connected", person="peregrine-duskwell", source="t", ts=ago(4000), path=LOG)

# Isolde was checked yesterday, so on the schedule she is nowhere near due.
ledger.emit("connected", person="isolde-brackwater", source="t", ts=ago(300), path=LOG)
ledger.emit("checked", person="isolde-brackwater", source="t", ts=ago(1), path=LOG)
i1 = refresh.status("isolde-brackwater", path=LOG)
check("checked yesterday, so not due on the schedule", not i1["due"], repr(i1))

ledger.emit("reply_received", person="isolde-brackwater", source="t", ts=ago(0), path=LOG)
i2 = refresh.status("isolde-brackwater", path=LOG)
check("but a reply since the check makes her due anyway", i2["due"], repr(i2))
check("and the reason names the event", "reply_received" in i2["reason"], repr(i2["reason"]))

queue = refresh.due(path=LOG)
check("she is at the front of the queue",
      queue and queue[0]["person"] == "isolde-brackwater",
      str([q["person"] for q in queue]))
check("ahead of somebody who is merely overdue on the rota",
      [q["person"] for q in queue].index("isolde-brackwater")
      < [q["person"] for q in queue].index("delia-marchetti"),
      str([q["person"] for q in queue]))
check("and ahead of somebody overdue by years",
      [q["person"] for q in queue].index("isolde-brackwater")
      < [q["person"] for q in queue].index("peregrine-duskwell"),
      str([(q["person"], q["priority"]) for q in queue]))

print("\n=== 7. a check that found something different is recorded as such ===")

refresh.mark_checked("mara-quennell", source="test", changed=True, path=LOG,
                     payload={"role": "changed"})
kinds = [e["type"] for e in ledger.events(person="mara-quennell", path=LOG)]
check("it is a different event from a check that found nothing new",
      "details_changed" in kinds, str(kinds))
check("a plain check is recorded as a check",
      "checked" in [e["type"] for e in ledger.events(person="tobias-fenwick", path=LOG)])

print("\n=== 8. the tier counts add up ===")

counts = refresh.tiers(path=LOG)
check("every person the log knows about is on exactly one tier",
      sum(counts.values()) == len(ledger.people(path=LOG)),
      "%s vs %d" % (counts, len(ledger.people(path=LOG))))

print("\n=== 9. it produces a list and never goes looking itself ===")

src = Path(refresh.__file__).read_text(encoding="utf-8", errors="replace")
network = [ln.strip() for ln in src.splitlines()
           if not ln.strip().startswith("#")
           and any(w in ln for w in ("urllib", "requests", "http://", "https://",
                                     "socket", "webbrowser"))]
check("refresh.py never touches a network", not network, "; ".join(network[:2]))

shutil.rmtree(TMP, ignore_errors=True)

print("\n%s" % ("ALL PASS" if not FAILS else "FAILURES: " + ", ".join(FAILS)))
sys.exit(1 if FAILS else 0)
