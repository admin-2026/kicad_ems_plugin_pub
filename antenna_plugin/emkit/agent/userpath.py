"""Putting one directory on the user's PATH, and taking it off again.

The shortcut (``shim.py``) is only a shortcut once a shell can find it, and
the folder it lives in is not on anybody's PATH by default. This does that one
step, on the user's own PATH and never the machine's: a marked block in a
shell startup file on Linux and macOS, the ``HKCU\\Environment`` value on
Windows.

**Everything it writes, it can take back.** The POSIX block is fenced by two
comment lines carrying a tag, so removing it is exact rather than a guess at
which line was ours, and writing it twice replaces the first block instead of
stacking another. The Windows value is split on ``;`` and the one entry is
dropped. Nothing else in the file (or the registry) is rewritten, and the
system-wide PATH is never touched.

**Which file.** The one a *new terminal* reads, because that is what the user
will try:

    zsh    ~/.zshrc
    bash   ~/.bashrc, else ~/.bash_profile, else ~/.profile (first that exists)
    other  ~/.profile

An interactive rc file rather than a login profile: a new terminal window
sources it on every desktop, where ``~/.profile`` on Linux waits for the next
login. The ceiling is that a shell nobody here knows (fish, nushell) gets
``~/.profile`` written and will not read it -- said on the status line rather
than guessed at, since the alternative is writing files for shells this cannot
test.

Nothing here changes the running process' own PATH: an environment is
inherited, so the shell that is already open keeps the one it started with.
Every message says so.
"""

import os

# The fence. The tag is the caller's (the shortcut's name), so two products
# each own their own block and neither can remove the other's.
_START = "# >>> {tag} >>>"
_END = "# <<< {tag} <<<"

# What the block sets. ``$PATH`` first: an entry appended cannot shadow a
# command the user already had.
_LINE = 'export PATH="$PATH:{directory}"'

# Where Windows keeps the user's own environment (never the machine's, which
# is HKLM and needs administrator rights).
_WIN_KEY = "Environment"


# --------------------------------------------------------------------------- #
# Where
# --------------------------------------------------------------------------- #
def profile():
    """The shell startup file this would edit, or ``None`` on Windows, where
    PATH is not a file. Returns a path that may not exist yet -- writing it is
    what creates it.

    ``os.path.join`` rather than pathlib's ``/``: nothing under ``agent/``
    divides, which is the rule that keeps arithmetic out of the verb surface
    (tests/test_agent_layout.py).
    """
    if os.name == "nt":
        return None
    home = os.path.expanduser("~")
    # ponytail: three shells and one file each; a fish or nushell user is told
    # (known_shell) rather than written for. Add a case here if one is asked
    # for -- not a table of every shell that exists.
    shell = os.path.basename(os.environ.get("SHELL", ""))
    candidates = {
        "zsh": (".zshrc",),
        "bash": (".bashrc", ".bash_profile", ".profile"),
    }.get(shell, (".profile",))
    for name in candidates:
        if os.path.isfile(os.path.join(home, name)):
            return os.path.join(home, name)
    return os.path.join(home, candidates[0])


def where():
    """What to tell the user is being changed, in their own words."""
    return "your account's environment" if os.name == "nt" else profile()


def known_shell():
    """Is the shell one whose startup file this actually knows? A fish or
    nushell user gets ``~/.profile``, which their shell will not read -- worth
    saying rather than leaving them to find out."""
    if os.name == "nt":
        return True
    return os.path.basename(os.environ.get("SHELL", "")) in ("sh", "bash", "zsh")


def on_path(directory):
    """Is ``directory`` on the PATH *this process* inherited? Not the same
    question as :func:`installed` -- a user may have put it there by hand, and
    a block written a minute ago is not in this environment at all."""
    wanted = _norm(directory)
    return any(
        entry and _norm(entry) == wanted
        for entry in os.environ.get("PATH", "").split(os.pathsep)
    )


def installed(directory, tag):
    """Is our own entry there -- the block we wrote, or our directory in the
    user's registry PATH? This is what the checkbox's line reports."""
    if os.name == "nt":
        return _norm(directory) in [_norm(e) for e in _win_entries() if e]
    text = _read(profile())
    return _block(text, tag) is not None


# --------------------------------------------------------------------------- #
# Add / remove
# --------------------------------------------------------------------------- #
def add(directory, tag):
    """Put ``directory`` on the user's PATH. Idempotent: an existing block is
    replaced, an entry already in the registry is left alone. Raises ``OSError``
    on a write that fails -- the caller has a status line for it."""
    directory = str(directory)
    if os.name == "nt":
        entries = [e for e in _win_entries() if e and _norm(e) != _norm(directory)]
        _win_write(entries + [directory])
        return
    target = profile()
    text = _without_block(_read(target), tag)
    if text and not text.endswith("\n"):
        text += "\n"
    block = "\n".join(
        (
            _START.format(tag=tag),
            f"# Added by {tag}; delete this block or untick the box that wrote it.",
            _LINE.format(directory=directory),
            _END.format(tag=tag),
        )
    )
    _write(target, f"{text}{block}\n")


def remove(directory, tag):
    """Take it off again, leaving everything else in the file exactly as it
    was. A PATH that never had it is the wanted state, not an error."""
    if os.name == "nt":
        _win_write([e for e in _win_entries() if e and _norm(e) != _norm(directory)])
        return
    target = profile()
    text = _read(target)
    stripped = _without_block(text, tag)
    if stripped != text:
        _write(target, stripped)


# --------------------------------------------------------------------------- #
# The block, as text (pure -- and so the part every OS's tests can check)
# --------------------------------------------------------------------------- #
def _block(text, tag):
    """Our block's (start, end) line indices in ``text``'s lines, or None."""
    lines = text.splitlines()
    try:
        start = lines.index(_START.format(tag=tag))
        end = lines.index(_END.format(tag=tag), start)
    except ValueError:
        return None
    return start, end


def _without_block(text, tag):
    """``text`` with our block taken out -- every one of them, if a hand-edit
    left two behind."""
    while True:
        found = _block(text, tag)
        if found is None:
            return text
        lines = text.splitlines(keepends=True)
        start, end = found
        text = "".join(lines[:start] + lines[end + 1 :])


def _read(path):
    try:
        with open(path, encoding="utf-8") as handle:
            return handle.read()
    except (OSError, UnicodeDecodeError):
        return ""


def _write(path, text):
    with open(path, "w", encoding="utf-8") as handle:
        handle.write(text)


def _norm(directory):
    """One spelling of a directory, for comparing two of them. Case-folded on
    Windows, where PATH is not case-sensitive."""
    return os.path.normcase(os.path.normpath(str(directory)))


# --------------------------------------------------------------------------- #
# Windows
# --------------------------------------------------------------------------- #
def _win_entries():
    """The user's own PATH entries, or [] when the value has never been set
    (a machine where PATH is entirely the system's)."""
    import winreg

    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, _WIN_KEY) as key:
            value, _kind = winreg.QueryValueEx(key, "PATH")
    except FileNotFoundError:
        return []
    return str(value).split(";")


def _win_write(entries):
    """Write the user's PATH back and tell the desktop it changed, so a new
    terminal picks it up without a logout.

    ``REG_EXPAND_SZ``, always: an entry somebody else wrote may well contain a
    ``%USERPROFILE%``, and storing it as a plain string would freeze that into
    a literal.
    """
    import ctypes
    import winreg

    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, _WIN_KEY, 0, winreg.KEY_WRITE) as key:
        winreg.SetValueEx(key, "PATH", 0, winreg.REG_EXPAND_SZ, ";".join(entries))
    try:  # best effort: the value is written either way
        # A second and a half, not five: this is a courtesy to windows that
        # are listening, and the wait is a user sitting in front of a checkbox.
        # ``SMTO_ABORTIFHUNG`` already skips the ones that have stopped
        # answering; the timeout is for the ones that are merely slow.
        ctypes.windll.user32.SendMessageTimeoutW(
            0xFFFF, 0x001A, 0, "Environment", 0x0002, 1500, None
        )
    except Exception:
        pass
