"""The log fills itself from a source you already own, and nothing is guessed.

THE RULE (Layer 4): a collector reads a place where things already happen and turns
what it finds into events. Every collector decides identity in ONE place, the
resolver from Layer 2. Identity decided in five places is decided five different
ways.

WHAT SHOULD HAPPEN:
  - a plain export becomes events, with nobody typing anything
  - the same person named four different ways across three sources lands on one
    record
  - running the same file twice adds nothing the second time
  - somebody you do not already have gets a provisional record in _staging, and
    their events attach to it, and nothing is merged into anybody you did have
  - a row with no date or no identifier is skipped and counted, never given a
    made-up value

Every person and every file in here is invented.

Run:  python tests/test_capture.py
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


# A scratch folder. Never point a test at real records.
TMP = Path(tempfile.mkdtemp(prefix="outliers-crm-capture-"))
os.environ["OUTLIERS_CRM_VAULT"] = str(TMP)
(TMP / "People").mkdir(parents=True)
(TMP / "_engine").mkdir(parents=True)
(TMP / "_layers").mkdir(parents=True)
(TMP / "_engine" / "settings.json").write_text(json.dumps({
    "park_after_days": 30,
    "refresh_days": {"active": 0, "warm": 30, "cold": 90},
    "events": {"checked": {"means": "their details were re-checked",
                           "counts_as_contact": False}},
}, indent=2), encoding="utf-8")
(TMP / "_layers" / "config.json").write_text(json.dumps({
    "layer": 3, "your_name": "Nell Farrier",
    "scan_folders": ["People", "_staging"],
}, indent=2), encoding="utf-8")

# Three people who exist. Each is known by a different identifier, which is exactly
# the situation every real set of records is in.
(TMP / "People" / "Rowan Ashdown.md").write_text("""---
name: Rowan Ashdown
linkedin-url: https://www.linkedin.com/in/rowan-ashdown/
email: rowan@ashdown.example
aliases: [R Ashdown]
---
""", encoding="utf-8")
(TMP / "People" / "Mara Quennell.md").write_text("""---
name: Mara Quennell
email: mara@quennell.example
---
""", encoding="utf-8")
(TMP / "People" / "Tobias Fenwick.md").write_text("""---
name: Tobias Fenwick
linkedin-url: https://www.linkedin.com/in/tobias-fenwick/
---
""", encoding="utf-8")

import identity                                            # noqa: E402
import ledger                                              # noqa: E402
import derive                                              # noqa: E402
import collect                                             # noqa: E402

LOG = TMP / "_ledger" / "events.jsonl"


def days_ago(n):
    return (datetime.now(timezone.utc) - timedelta(days=n)).date().isoformat()


def csv_file(name, text):
    p = TMP / "exports" / name
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")
    return p


# A message export. Rowan appears by profile link, Mara by email address, and
# somebody nobody has a record for appears by name only.
MESSAGES = csv_file("messages.csv", """Date,Direction,Name,Profile URL,Email
{d1},Outgoing,Rowan Ashdown,https://uk.linkedin.com/in/rowan-ashdown?trk=x,
{d2},Incoming,R Ashdown,,
{d3},Outgoing,Mara Quennell,,mara@quennell.example
{d4},Incoming,Peregrine Duskwell,,
,Outgoing,No Date Person,,
{d5},Outgoing,,,
""".format(d1=days_ago(20), d2=days_ago(18), d3=days_ago(9),
           d4=days_ago(3), d5=days_ago(1)))

# A calendar export, naming the same people differently again.
MEETINGS = csv_file("meetings.csv", """Start,Attendee,Email,Subject
{past},Rowan Ashdown,rowan@ashdown.example,Quote review
{future},Tobias Fenwick,,Intro call
""".format(past=days_ago(7), future=(datetime.now(timezone.utc)
                                     + timedelta(days=9)).date().isoformat()))

CONNECTIONS = csv_file("connections.csv", """First Name,Last Name,URL,Company,Position,Connected On
Tobias,Fenwick,https://www.linkedin.com/in/tobias-fenwick/,Fenwick Catering,Owner,{d}
Delia,Marchetti,https://www.linkedin.com/in/delia-marchetti/,Marchetti Joinery,Director,{d}
""".format(d=days_ago(300)))

print("\n=== 1. a plain export becomes events, with nothing typed ===")

stats = collect.run("messages", MESSAGES, root=TMP, ledger_file=LOG)
check("rows were read", stats["read"] == 6, str(stats))
check("the good rows became events", stats["written"] == 4, str(stats))
check("a row with no date was skipped, not given one",
      stats["skipped"] >= 1 and "no readable date" in (stats["_reasons"] or {}),
      str(stats["_reasons"]))
check("a row with no identifier was skipped too",
      "no identifier" in (stats["_reasons"] or {}), str(stats["_reasons"]))

print("\n=== 2. direction decides which event it is ===")

kinds = {e["type"] for e in ledger.events(path=LOG)}
check("outgoing messages are recorded as sent by you", "message_sent" in kinds, str(kinds))
check("incoming messages are recorded as replies", "reply_received" in kinds, str(kinds))
check("no message content was stored",
      all("body" not in (e.get("payload") or {}) and "message" not in (e.get("payload") or {})
          for e in ledger.events(path=LOG)))

print("\n=== 3. one person, named differently in every source ===")

rowan = identity.resolve("https://www.linkedin.com/in/rowan-ashdown/", vault=TMP)
check("the resolver knows who Rowan is", rowan is not None)
mine = [e for e in ledger.events(person=rowan, path=LOG)]
check("both messages landed on the one record, from a link and from a nickname",
      len(mine) == 2, str([e["type"] for e in mine]))

collect.run("meetings", MEETINGS, root=TMP, ledger_file=LOG)
mine2 = [e for e in ledger.events(person=rowan, path=LOG)]
check("the meeting, which named him by email address, landed on the same record",
      len(mine2) == 3, str([e["type"] for e in mine2]))
check("a meeting in the past is recorded as one that happened",
      any(e["type"] == "meeting_held" for e in mine2), str([e["type"] for e in mine2]))
check("a meeting in the future is recorded as one that is booked",
      any(e["type"] == "call_booked" for e in ledger.events(path=LOG)))

print("\n=== 4. running the same file twice adds nothing ===")

again = collect.run("messages", MESSAGES, root=TMP, ledger_file=LOG)
check("nothing new was written", again["written"] == 0, str(again))
check("and it says why", again["already there"] == 4, str(again))
before = ledger.count(path=LOG)
collect.run("meetings", MEETINGS, root=TMP, ledger_file=LOG)
check("the same holds for a second collector", ledger.count(path=LOG) == before)

print("\n=== 5. a dry run reads everything and writes nothing ===")

count_before = ledger.count(path=LOG)
dry = collect.run("connections", CONNECTIONS, root=TMP, ledger_file=LOG, dry_run=True)
check("it read the rows", dry["read"] == 2, str(dry))
check("and wrote none of them", ledger.count(path=LOG) == count_before)

print("\n=== 6. somebody you do not already have gets a provisional record ===")

staged = sorted(f.name for f in (TMP / "_staging").glob("*.md"))
check("a record for them is waiting in _staging",
      any("Peregrine" in n for n in staged), str(staged))
check("nobody was invented in People",
      not any("Peregrine" in f.name for f in (TMP / "People").glob("*.md")))
check("their event attached to that record, so the history reads from row one",
      any("Peregrine Duskwell" in (e.get("identifiers") or []) and e.get("person")
          for e in ledger.events(path=LOG)),
      str([(e.get("person"), e.get("identifiers")) for e in ledger.events(path=LOG)][:6]))
check("and nothing was merged into somebody who was already there",
      identity.resolve("Peregrine Duskwell", vault=TMP) not in (rowan, None))

body = (TMP / "_staging" / "Peregrine Duskwell.md").read_text(encoding="utf-8")
check("the staged record says how it got there", "Found as:" in body)
check("and it is tagged as staged rather than settled", "staged" in body)

print("\n=== 7. a new connections export creates history for people you have ===")

identity.forget()
made = collect.run("connections", CONNECTIONS, root=TMP, ledger_file=LOG)
check("both rows were written", made["written"] == 2, str(made))
tob = identity.resolve("https://www.linkedin.com/in/tobias-fenwick/", vault=TMP)
check("the one you already had was attached to the right record",
      any(e["type"] == "connected" for e in ledger.events(person=tob, path=LOG)))
check("the one you did not have was recorded and staged",
      made["new people"] == 1 and made["staged"] == 1, str(made))
check("their company and role came across",
      any((e.get("payload") or {}).get("company") == "Fenwick Catering"
          for e in ledger.events(person=tob, path=LOG)))

print("\n=== 8. what the log now says, with nothing typed ===")

st = derive.person_state(rowan, path=LOG)
check("a relationship state exists", bool(st.get("relationship-state")), repr(st))
check("last contact is a real date from a real event",
      bool(st.get("last-contact")), repr(st.get("last-contact")))
check("conversation points were counted",
      st.get("conversation-points") == 2, repr(st.get("conversation-points")))
check("every event carries the identifiers it arrived with, attached or not",
      all(e.get("identifiers") for e in ledger.events(path=LOG)))

print("\n=== 9. every event says where it came from ===")

sources = {e.get("source") for e in ledger.events(path=LOG)}
check("each event names its collector",
      all(str(s).startswith("collector:") for s in sources), str(sources))
check("which is what tells a real record from something that got in by accident",
      len(sources) == 3, str(sources))

print("\n=== 10. an unknown collector is refused ===")

try:
    collect.run("telepathy", MESSAGES, root=TMP, ledger_file=LOG)
    check("a collector that does not exist is refused", False, "it ran")
except ValueError as e:
    check("a collector that does not exist is refused", True)
    check("and the refusal lists the ones that do", "messages" in str(e), str(e)[:70])

shutil.rmtree(TMP, ignore_errors=True)

print("\n%s" % ("ALL PASS" if not FAILS else "FAILURES: " + ", ".join(FAILS)))
sys.exit(1 if FAILS else 0)
