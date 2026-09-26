"""
derive.py -- the fields you stop typing. Layer 3.

Nothing in here is typed by a person. When you last spoke to someone, what state the
relationship is in, how many exchanges there have been, how often their details
should be re-checked: all of it is a consequence of events, so all of it is
calculated from the log rather than kept up to date by hand.

Recalculating is safe to do at any time. Run it twice and you get the same answer,
because it only ever reads events and events never change.

This is what makes the Layer 2 contract's `hand_written: false` mean something. A
field you maintain by hand is a field that starts lying within weeks, and the lie is
invisible because a stale value looks exactly like a current one.

The rules below are deliberately dull. Anything needing judgement -- is this reply
warm, is this person worth your time -- belongs at a later layer, and its ANSWER
arrives here as an event.

WHAT IS CALCULATED

  last-contact          the date of the newest event that counts as contact
  conversation-points   how many messages went each way
  relationship-state    cold / warming / active / parked / client / suppressed
  refresh-tier          active / warm / cold: how often to re-check their details
  next-contact-due      last contact plus the tier's window
  last-verified         when a re-check last confirmed their role and company

Use:
    import derive
    state = derive.person_state("rowan-ashdown")
    quiet = derive.quiet_for(60)          # who you have not spoken to in 60 days

CLI:
    python _engine/derive.py show "<identifier>"    what the log says about them
    python _engine/derive.py quiet [days]           who has gone quiet
    python _engine/derive.py summary                the shape of the whole log
"""

import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import ledger                                              # noqa: E402
import settings                                            # noqa: E402

# The command a member types to start Python: `python3` on a Mac, which has no plain
# `python` command, and `python` everywhere else, as the Windows guides print it.
PY = "python3" if sys.platform == "darwin" else "python"


def _typed(name):
    """The program `name` (it sits beside this file) as the member types it from the folder
    they are in: `_engine/<name>` from the CRM folder, `<name>` from inside `_engine`."""
    import os
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), name)
    try:
        typed = os.path.relpath(path)
    except ValueError:                      # the member is on another drive
        typed = path
    if typed.startswith(".."):
        typed = path
    typed = typed.replace("\\", "/")
    return '"%s"' % typed if " " in typed else typed

# Which events count as an exchange, for counting how much conversation there has
# been. One each way is a reply; ten each way is a relationship.
EXCHANGE_EVENTS = ("message_sent", "reply_received")


def _days_since(ts):
    if not ts:
        return None
    try:
        t = datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
    except ValueError:
        return None
    if not t.tzinfo:
        t = t.replace(tzinfo=timezone.utc)
    return (datetime.now(timezone.utc) - t).days


def person_state(pid, path=None, root=None):
    """The calculated view of one person, from events alone.

    Returns an empty result when the log knows nothing about them. Somebody with no
    events is not "cold", they are unobserved, and saying otherwise invents a fact.
    """
    evs = list(ledger.events(person=pid, path=path, root=root))
    if not evs:
        return {}

    s = settings.load(root)
    park_after = int(s.get("park_after_days", 30))
    tier_days = s.get("refresh_days") or {"active": 0, "warm": 30, "cold": 90}
    contact_types = ledger.contact_types(root)

    by_type = {}
    for e in evs:
        by_type.setdefault(e.get("type"), []).append(e)

    contact = [e for e in evs if e.get("type") in contact_types]
    last_contact = contact[-1]["ts"] if contact else None
    quiet_days = _days_since(last_contact)

    out = {
        "last-contact": (last_contact or "")[:10] or None,
        "conversation-points": sum(len(by_type.get(t, [])) for t in EXCHANGE_EVENTS),
        "events": len(evs),
    }
    if quiet_days is not None:
        out["days-quiet"] = quiet_days

    # ---- relationship state -------------------------------------------------
    # Order matters. The strongest fact wins, and a hold beats everything.
    if by_type.get("held"):
        held_at = by_type["held"][-1]["ts"]
        released = by_type.get("released", [])
        if not released or released[-1]["ts"] < held_at:
            out["relationship-state"] = "suppressed"

    if "relationship-state" not in out:
        # "Active" means they did something, or something is in the diary. "Warming"
        # means you did something and are waiting. Anything you added as one of your
        # own contact types warms them too, which is why this reads the contact list
        # rather than naming events one by one.
        if by_type.get("joined"):
            out["relationship-state"] = "client"
        elif any(by_type.get(t) for t in ("meeting_held", "reply_received", "call_booked")):
            out["relationship-state"] = "active"
        elif any(by_type.get(t) for t in contact_types) or by_type.get("they_engaged"):
            out["relationship-state"] = "warming"
        else:
            out["relationship-state"] = "cold"

        # ...and then it ages. Silence past the window parks the thread without
        # anybody deciding to give up on it. This is the only way a pipeline one
        # person is running stays honest: nothing sits in "active" for a year
        # because nobody wanted to be the one to write it off.
        if quiet_days is not None and quiet_days > park_after \
                and out["relationship-state"] in ("active", "warming"):
            out["relationship-state"] = "parked"
            out["parked-reason"] = "%d days since the last contact" % quiet_days

    # ---- how often to re-check them ----------------------------------------
    st = out.get("relationship-state")
    if st in ("active", "client"):
        out["refresh-tier"] = "active"
    elif st == "warming":
        out["refresh-tier"] = "warm"
    else:
        out["refresh-tier"] = "cold"

    window = int(tier_days.get(out["refresh-tier"], 0) or 0)
    if window and last_contact:
        try:
            base = datetime.fromisoformat(str(last_contact).replace("Z", "+00:00"))
            out["next-contact-due"] = (base + timedelta(days=window)).date().isoformat()
        except ValueError:
            pass

    changed = by_type.get("details_changed")
    if changed:
        out["last-verified"] = changed[-1]["ts"][:10]

    return out


def quiet_for(days, path=None, root=None):
    """Everyone whose last contact was more than `days` ago, longest first.

    This is the question a hand-kept CRM can never answer honestly, because the
    field it would have to answer from is the one nobody keeps up to date. Here the
    answer comes from what happened.

    People who are suppressed or already parked are still included, with their state
    on the row, so you can see them and decide rather than have them hidden.
    """
    out = []
    for pid in sorted(ledger.people(path=path, root=root)):
        st = person_state(pid, path=path, root=root)
        d = st.get("days-quiet")
        if d is None or d < days:
            continue
        out.append({
            "person": pid,
            "days-quiet": d,
            "last-contact": st.get("last-contact"),
            "relationship-state": st.get("relationship-state"),
            "conversation-points": st.get("conversation-points"),
        })
    return sorted(out, key=lambda r: -r["days-quiet"])


def drift(pid, record_fields, path=None, root=None):
    """What a record CLAIMS against what the log SAYS. Returns {field: (claimed, actual)}.

    Nothing is corrected from here. This exists so you can look at the gap before
    anything writes, which is the difference between a considered change and an
    accident.
    """
    calc = person_state(pid, path=path, root=root)
    out = {}
    for k, v in calc.items():
        if k in ("events", "parked-reason", "days-quiet"):
            continue
        claimed = record_fields.get(k)
        if claimed not in (None, "", "unknown") and str(claimed) != str(v):
            out[k] = (claimed, v)
    return out


def summary(path=None, root=None):
    """How many people are in each state, and how many are due a re-check."""
    states, tiers = {}, {}
    for pid in ledger.people(path=path, root=root):
        st = person_state(pid, path=path, root=root)
        states[st.get("relationship-state")] = states.get(st.get("relationship-state"), 0) + 1
        tiers[st.get("refresh-tier")] = tiers.get(st.get("refresh-tier"), 0) + 1
    return {"states": states, "tiers": tiers}


# ------------------------------------------------------------------------- cli

def main(argv):
    cmd = argv[1] if len(argv) > 1 else "summary"
    if cmd == "show" and len(argv) > 2:
        try:
            import identity
            pid = identity.resolve(argv[2]) or argv[2]
        except Exception:
            pid = argv[2]
        st = person_state(pid)
        if not st:
            print("%s: no events." % pid)
            print("Unobserved, which is not the same as cold. Nothing has been")
            print("recorded about them yet, so nothing can honestly be said.")
            return 0
        print("%s" % pid)
        for k, v in st.items():
            print("  %-22s %s" % (k, v))
    elif cmd == "quiet":
        days = int(argv[2]) if len(argv) > 2 else 60
        rows = quiet_for(days)
        print("People with no contact in %d days: %d\n" % (days, len(rows)))
        for r in rows[:50]:
            print("  %-30s %4d days   %-10s  last: %s"
                  % (r["person"][:30], r["days-quiet"],
                     r["relationship-state"], r["last-contact"]))
        if len(rows) > 50:
            print("  ... and %d more" % (len(rows) - 50))
        if not rows:
            print("  Nobody, which either means you are on top of it or the log is")
            print("  empty. `%s %s stats` says which." % (PY, _typed("ledger.py")))
    elif cmd == "summary":
        s = summary()
        total = sum(s["states"].values())
        print("people the log knows about: %d" % total)
        if not total:
            print("\nNothing yet. Layer 4 is what fills the log without you typing.")
            return 0
        print("\nby state:")
        for k, v in sorted(s["states"].items(), key=lambda x: -x[1]):
            print("  %-14s %d" % (k, v))
        print("\nby re-check tier:")
        for k, v in sorted(s["tiers"].items(), key=lambda x: -x[1]):
            print("  %-14s %d" % (k, v))
    else:
        print(__doc__.replace("    python _engine/derive.py", "    python " + _typed("derive.py"))
              .replace("    python ", "    %s " % PY))
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
