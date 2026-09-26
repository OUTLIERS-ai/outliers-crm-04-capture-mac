"""
safe_write.py -- never leave a record half written.

The rule, and it is absolute: never open an existing file for writing.

Opening a file for writing truncates it the instant the handle opens. Everything
that was in it is gone at that moment, before a single new byte has been written.
If anything goes wrong between then and the last byte -- the machine loses power,
the disk fills, another program has the file locked, you close the window -- what is
left is an empty or half-written record, and the previous contents are not
recoverable. The record IS the history. There is no second copy.

Instead: write to a temporary file beside the target, push it to disk, then swap it
into place in one operation. `os.replace` is atomic on Windows and on everything
else, which means a reader either sees the whole old file or the whole new one and
never a fragment.

This matters most exactly when a system is busiest, because that is when it is most
likely to be interrupted.

Use:
    from safe_write import write_text
    write_text(path, contents)          # same signature as Path.write_text
"""

import os
from pathlib import Path


def write_text(path, data, encoding="utf-8", newline=None):
    """Replace `path` with `data` in one step. Returns the path.

    `newline=None` behaves exactly like Path.write_text, so swapping an existing
    call over to this function changes the safety and nothing else. Pass newline=""
    to write the text through untouched.
    """
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_name(p.name + ".tmp")
    with open(tmp, "w", encoding=encoding, newline=newline) as fh:
        fh.write(data)
        fh.flush()
        os.fsync(fh.fileno())          # the temporary file must be on disk first
    os.replace(tmp, p)
    return p
