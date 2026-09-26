"""A failed write must never destroy a record.

THE RULE, and it is absolute: never open an existing file for writing.

Opening a file for writing truncates it the instant the handle opens. If anything
goes wrong between that moment and the last byte, what is left is an empty or
half-written file, and what was there before is gone. The record IS the history.
There is no second copy.

WHAT SHOULD HAPPEN: writing a record either replaces it completely or leaves it
exactly as it was, byte for byte. Anything reading it at the same time sees one or
the other and never a fragment.

WHY IT MATTERS HERE: this layer writes files while running through an export, which
is exactly when it is most likely to be interrupted, and it does it once per person.
The cost of one badly timed moment would otherwise be somebody's entire record.

Every person in here is invented.

Run:  python tests/test_atomic_writes.py
"""

import builtins
import shutil
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "crm"))

FAILS = []


def check(label, cond, detail=""):
    ok = bool(cond)
    print(("  PASS  " if ok else "  FAIL  ") + label
          + (("   [" + detail + "]") if detail and not ok else ""))
    if not ok:
        FAILS.append(label)


import safe_write                                          # noqa: E402

TMP = Path(tempfile.mkdtemp(prefix="outliers-crm-atomic-"))
NOTE = TMP / "Rowan Ashdown.md"
ORIGINAL = ("---\nname: Rowan Ashdown\ncompany: Ashdown and Co\n---\n\n"
            "## What we have talked about\n\nThe quote for the second unit.\n")
NOTE.write_text(ORIGINAL, encoding="utf-8")

print("\n=== 1. the ordinary case replaces the file completely ===")

safe_write.write_text(NOTE, ORIGINAL.replace("Ashdown and Co", "Ashdown Joinery"))
after = NOTE.read_text(encoding="utf-8")
check("the new contents are there", "Ashdown Joinery" in after)
check("nothing else in the record was lost",
      "## What we have talked about" in after and "second unit" in after)
check("no temporary file was left behind",
      not list(TMP.glob("*.tmp")), str(list(TMP.glob("*.tmp"))))

print("\n=== 2. a write that dies partway through leaves the record untouched ===")

NOTE.write_text(ORIGINAL, encoding="utf-8")

real_open = builtins.open
state = {"boom": True}


class _DyingFile:
    """A file that accepts the open, then fails partway through writing. That is the
    shape of a real interruption: the handle is live, the disk is not."""

    def __init__(self, fh):
        self._fh = fh
        self._written = 0

    def write(self, data):
        self._written += len(data)
        if state["boom"] and self._written > 10:
            raise OSError("a failure, on purpose, halfway through the write")
        return self._fh.write(data)

    def __getattr__(self, k):
        return getattr(self._fh, k)

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return self._fh.__exit__(*a)


def _patched_open(file, mode="r", *a, **kw):
    fh = real_open(file, mode, *a, **kw)
    if "w" in mode:
        return _DyingFile(fh)
    return fh


builtins.open = _patched_open
try:
    try:
        safe_write.write_text(NOTE, "COMPLETELY DIFFERENT TEXT THAT MUST NOT LAND")
        crashed = False
    except OSError:
        crashed = True
finally:
    builtins.open = real_open

check("the write did fail, so the test is exercising the failure", crashed)
survived = NOTE.read_text(encoding="utf-8")
check("the original record is intact, byte for byte", survived == ORIGINAL,
      "%d bytes vs %d" % (len(survived), len(ORIGINAL)))
check("the half-written text is nowhere in it", "COMPLETELY DIFFERENT" not in survived)

state["boom"] = False
for f in list(TMP.glob("*.tmp")):
    f.unlink()

print("\n=== 3. a record that does not exist yet is created ===")

NEW = TMP / "nested" / "Mara Quennell.md"
safe_write.write_text(NEW, "---\nname: Mara Quennell\n---\n")
check("the file was created", NEW.exists())
check("and the folders above it were created too", NEW.parent.is_dir())

print("\n=== 4. everything in this layer that writes, writes this way ===")

crm = Path(__file__).resolve().parents[1] / "crm"
offenders = []
for f in sorted(crm.glob("*.py")):
    if f.name == "safe_write.py":
        continue
    for i, line in enumerate(f.read_text(encoding="utf-8", errors="replace").splitlines(), 1):
        s = line.strip()
        if s.startswith("#") or s.startswith('"'):
            continue
        if ".write_text(" in s and "safe_write" not in s:
            offenders.append("%s:%d %s" % (f.name, i, s[:60]))
        if "open(" in s and ('"w"' in s or "'w'" in s):
            offenders.append("%s:%d %s" % (f.name, i, s[:60]))
check("nothing opens an existing file for writing", not offenders,
      "; ".join(offenders[:3]))

print("\n=== 5. the event log is the one exception, and it appends ===")

ledger_src = (crm / "ledger.py").read_text(encoding="utf-8", errors="replace")
writing = [ln.strip() for ln in ledger_src.splitlines()
           if "open(" in ln and not ln.strip().startswith("#")
           and any(m in ln for m in ('"a"', "'a'", '"w"', "'w'"))]
check("the log is only ever opened in append mode, which never truncates",
      writing and all('"a"' in ln or "'a'" in ln for ln in writing), str(writing))
check("and there is exactly one place that writes to it", len(writing) == 1, str(writing))

shutil.rmtree(TMP, ignore_errors=True)

print("\n%s" % ("ALL PASS" if not FAILS else "FAILURES: " + ", ".join(FAILS)))
sys.exit(1 if FAILS else 0)
