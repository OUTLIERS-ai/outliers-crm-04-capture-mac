"""
schema.py -- the record contract, enforced. Layer 2.

The contract itself lives next door in `_schema/person.json`, held as DATA rather
than as prose repeated in a dozen places. Prose cannot be checked. Data can.

This module does two jobs against it:

  validate(fields)  Refuse a badly shaped record AS IT IS BEING WRITTEN. A rule that
                    nothing checks is not a rule, it is a preference. Drift happens
                    one reasonable exception at a time, and by the time it is
                    obvious you have several generations of record and no way to ask
                    a question across all of them.

  adapt(fields)     Read a record written to ANY earlier shape and return the
                    canonical one. Old records are not rewritten. Writers write the
                    canonical shape, readers normalise, so the contract can change
                    without a migration.

That split is the whole trick. Enforce on the way in, forgive on the way out.

Use:
    import schema
    ok, errors = schema.validate(fields, mode="write")
    canonical  = schema.adapt(fields)

CLI:
    python _engine/schema.py contract            # print the loaded contract
    python _engine/schema.py check <note.md>     # validate one record
    python _engine/schema.py sweep [--limit N]   # check your records, write nothing
"""

import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import identity                                    # noqa: E402

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

CONTRACT_PATH = Path(__file__).resolve().parent / "_schema" / "person.json"

_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}")


def contract(path=None):
    """The contract, as data.

    Read fresh on every call. You own this file, and code holding a stale copy is
    code enforcing a rule that has since changed.
    """
    return json.loads(Path(path or CONTRACT_PATH).read_text(encoding="utf-8"))


# ------------------------------------------------------------------ validation

def validate(fields, mode="write", c=None):
    """Return (ok, [problems]).

    mode="write"  the full contract: required fields, allowed values, calculated
                  fields that must not be typed, provenance, retired fields. Use
                  this before writing a record.
    mode="read"   structure only. Records written before the contract existed still
                  have to be readable; adapt() is the path for those.
    """
    c = c or contract()
    problems = []
    f = {str(k).lower(): v for k, v in (fields or {}).items()}

    for name, spec in c["required"].items():
        if name.startswith("_"):
            continue
        if name not in f or f[name] in (None, "", []):
            problems.append("missing required field: %s" % name)
            continue
        if spec.get("type") == "date" and not _DATE.match(str(f[name])):
            problems.append("%s is not YYYY-MM-DD: %r" % (name, f[name]))
        if spec.get("type") == "enum" and str(f[name]) not in spec["values"]:
            problems.append("%s=%r is not one of %s" % (name, f[name], spec["values"]))
        if spec.get("must_include"):
            got = {str(g).strip().strip("'\"") for g in identity.listify(f[name])}
            for need in spec["must_include"]:
                if need not in got:
                    problems.append("%s must include %r" % (name, need))

    key = c["identity"]["canonical_key"]
    if mode == "write" and c["identity"].get("required_on_write"):
        if not f.get(key):
            problems.append(
                "%s is the identity key and every new record needs one" % key)

    if mode == "read":
        return (not problems, problems)

    for name, spec in c.get("state", {}).items():
        if name.startswith("_") or not isinstance(spec, dict):
            continue
        if f.get(name) in (None, ""):
            continue
        if spec.get("type") == "enum" and str(f[name]) not in spec["values"]:
            problems.append("%s=%r is not one of %s" % (name, f[name], spec["values"]))
        if spec.get("hand_written") is False:
            problems.append(
                "%s is calculated from what happened and must not be typed by hand" % name)

    for name in c.get("calculated", {}):
        if name.startswith("_"):
            continue
        if f.get(name) not in (None, ""):
            problems.append(
                "%s is calculated and must not be typed by hand" % name)

    for name, why in c.get("retired", {}).items():
        if name.startswith("_"):
            continue
        if name.split(":")[0].strip() in f:
            problems.append("%s is retired: %s" % (name, why))

    prov = c.get("provenance", {})
    for name in prov.get("required_on", []):
        if f.get(name) in (None, ""):
            continue
        v = f[name]
        if not (isinstance(v, dict) and v.get("source")):
            problems.append(
                "%s carries no provenance (it needs source, established, confidence)" % name)

    return (not problems, problems)


# ---------------------------------------------------------------- read adapter

def _aliases(c):
    """canonical field name -> every spelling that has ever meant it."""
    out = {}
    for canon, spellings in c.get("field_aliases", {}).items():
        if canon.startswith("_"):
            continue
        out[canon] = [canon] + [s for s in spellings if s != canon]
    return out


def adapt(fields, c=None):
    """Normalise a record of any vintage into the canonical shape.

    Records keep their own spelling on disk. This is the ONLY place that knows the
    older vocabularies, so nothing built on top of Layer 2 has to.
    """
    c = c or contract()
    f = {str(k).lower(): v for k, v in (fields or {}).items()}
    out = {}

    for canon, spellings in _aliases(c).items():
        for s in spellings:
            if f.get(s) not in (None, "", "unknown"):
                out[canon] = f[s]
                break

    state_spec = c.get("state", {}).get("relationship-state", {})
    legacy = state_spec.get("legacy_map", {})
    values = state_spec.get("values", [])
    rs = str(out.get("relationship-state", "")).strip().lower()
    if rs:
        out["relationship-state"] = legacy.get(rs, rs)
        if values and out["relationship-state"] not in values:
            out["relationship-state-unrecognised"] = rs
            out["relationship-state"] = values[0]

    if "score" in out:
        try:
            out["score"] = int(str(out["score"]).strip())
        except (ValueError, TypeError):
            out.pop("score")

    if "aliases" in out:
        out["aliases"] = identity.listify(out["aliases"])

    return out


def front_matter(text):
    """The same small frontmatter reader identity.py uses. One reader, one result."""
    return identity.front_matter(text)


# ------------------------------------------------------------------------- cli

def _sweep(limit=None):
    c = contract()
    root = identity.vault_root()
    seen = 0
    problems = {}
    unrecognised = {}
    for rel in identity.scan_folders(root):
        d = root / rel
        if not d.exists():
            continue
        for f in sorted(d.rglob("*.md")):
            if limit and seen >= limit:
                break
            seen += 1
            fm = front_matter(f.read_text(encoding="utf-8", errors="replace")[:3000])
            canon = adapt(fm, c)
            if "relationship-state-unrecognised" in canon:
                u = canon["relationship-state-unrecognised"]
                unrecognised[u] = unrecognised.get(u, 0) + 1
            ok, errs = validate(fm, mode="read", c=c)
            for e in errs:
                key = re.sub(r":.*", "", e)
                problems[key] = problems.get(key, 0) + 1
    print("records read     %d" % seen)
    if problems:
        print("\nstructural problems, worst first:")
        for k, v in sorted(problems.items(), key=lambda x: -x[1])[:10]:
            print("  %-48s %d" % (k, v))
    else:
        print("\nevery record has the fields the contract requires.")
    if unrecognised:
        print("\nstate values with no entry in the translation table:")
        for k, v in sorted(unrecognised.items(), key=lambda x: -x[1]):
            print("  %-22s %d" % (k, v))


def main(argv):
    cmd = argv[1] if len(argv) > 1 else "contract"
    if cmd == "contract":
        c = contract()
        print("contract       %s (v%s, %s)" % (CONTRACT_PATH, c["version"], c["updated"]))
        print("identity key   %s" % c["identity"]["canonical_key"])
        print("required       %s" % ", ".join(k for k in c["required"] if not k.startswith("_")))
        print("calculated     %s" % ", ".join(k for k in c["calculated"] if not k.startswith("_")))
        print("retired        %s" % ", ".join(k for k in c["retired"] if not k.startswith("_")))
    elif cmd == "check" and len(argv) > 2:
        p = Path(argv[2])
        fm = front_matter(p.read_text(encoding="utf-8", errors="replace"))
        ok, errs = validate(fm, mode="read")
        print("%s: %s" % (p.name, "OK" if ok else "PROBLEMS"))
        for e in errs:
            print("  - %s" % e)
        print("canonical view: %s" % json.dumps(adapt(fm), ensure_ascii=False)[:400])
    elif cmd == "sweep":
        lim = None
        if "--limit" in argv:
            lim = int(argv[argv.index("--limit") + 1])
        _sweep(lim)
    else:
        print(__doc__.replace("    python _engine/schema.py", "    python " + _typed("schema.py"))
              .replace("    python ", "    %s " % PY))
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
