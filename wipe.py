#!/usr/bin/env python3
"""
wipe.py — one-command wrapper for delete_reddit_comments.py, with a live
progress bar.

Put this file in your redact-reddit folder, then:
    python wipe.py                          # dry run (counts only, changes nothing)
    python wipe.py --execute --overwrite    # overwrite + delete for real

Token sources, tried in order:
  1. Chrome's token_v2 cookie (needs: pip install browser-cookie3; you must be
     logged into reddit.com in Chrome; macOS will ask for Keychain access once)
  2. token.txt in this folder (paste the token in, delete the file afterwards)
  3. Your clipboard (copy the token from Chrome DevTools first)

The token is passed to the deleter for this run only. It is never printed or
saved by this script. The original delete_reddit_comments.py is not modified.
"""
import asyncio
import builtins
import importlib.util
import os
import platform
import shutil
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
DELETER = HERE / "delete_reddit_comments.py"
TOKEN_FILE = HERE / "token.txt"


# ---------------------------------------------------------------- token lookup

def looks_like_token(t):
    return bool(t) and t.startswith("eyJ") and len(t) > 100


def _strip_bearer(t):
    t = (t or "").strip()
    return t[7:].strip() if t.lower().startswith("bearer ") else t


def from_chrome():
    try:
        import browser_cookie3
    except ImportError:
        print("  - Chrome: skipped (run 'pip install browser-cookie3' to enable)")
        return None
    try:
        for c in browser_cookie3.chrome(domain_name="reddit.com"):
            if c.name == "token_v2" and looks_like_token(c.value):
                return c.value
        print("  - Chrome: no token_v2 cookie (open reddit.com in Chrome, logged in)")
    except Exception as e:
        print(f"  - Chrome: couldn't read cookies ({type(e).__name__})")
    return None


def from_file():
    if TOKEN_FILE.exists():
        t = _strip_bearer(TOKEN_FILE.read_text(encoding="utf-8"))
        if looks_like_token(t):
            return t
        print("  - token.txt: found, but contents don't look like a token")
    return None


def from_clipboard():
    cmds = {
        "Darwin": ["pbpaste"],
        "Windows": ["powershell", "-NoProfile", "-Command", "Get-Clipboard"],
    }
    cmd = cmds.get(platform.system(), ["xclip", "-o", "-selection", "clipboard"])
    try:
        t = _strip_bearer(subprocess.run(cmd, capture_output=True, text=True).stdout)
    except Exception:
        return None
    if looks_like_token(t):
        return t
    print("  - Clipboard: doesn't contain a token")
    return None


# ---------------------------------------------------------------- progress bar

class Progress:
    def __init__(self):
        self.total = 0
        self.ok = 0
        self.fail = 0
        self.start = None
        self.status = ""
        self.active = False
        self.pause_time = 0.0  # time spent in rate-limit pauses (for ETA)

    def begin(self, total):
        self.total, self.start, self.active = total, time.time(), True
        self.draw()

    def end(self):
        if self.active:
            self.status = ""
            self.draw()
            builtins.print()
            self.active = False

    def _eta(self, done):
        if done == 0:
            return "--"
        elapsed = time.time() - self.start
        secs = elapsed / done * (self.total - done)
        if secs < 60:
            return f"{secs:.0f}s"
        if secs < 3600:
            return f"{secs / 60:.0f}m"
        return f"{secs / 3600:.1f}h"

    def draw(self):
        if not self.active:
            return
        done = self.ok + self.fail
        pct = done / self.total if self.total else 1
        cols = shutil.get_terminal_size((80, 20)).columns
        tail = f" {done}/{self.total} {pct:4.0%}  ✓{self.ok} ✗{self.fail}  ETA {self._eta(done)}"
        if self.status:
            tail += f"  {self.status}"
        width = max(10, min(30, cols - len(tail) - 3))
        filled = int(width * pct)
        line = f"[{'█' * filled}{'░' * (width - filled)}]{tail}"
        sys.stdout.write("\r\033[K" + line[: cols - 1])
        sys.stdout.flush()

    def message(self, *a, **k):
        """print() replacement: keeps messages above the bar."""
        if self.active:
            sys.stdout.write("\r\033[K")
        builtins.print(*a, **k)
        self.draw()


def instrument(mod, bar):
    """Hook progress reporting into the deleter without editing its file."""
    mod.print = bar.message  # module-level print now redraws the bar

    orig_log = mod.log

    def log(record):
        orig_log(record)
        if record.get("result") == "deleted":
            bar.ok += 1
        elif record.get("result") == "error":
            bar.fail += 1
        bar.draw()

    mod.log = log

    async def respect_ratelimit(h):
        try:
            remaining = float(h.get("X-Ratelimit-Remaining", "1"))
            reset = float(h.get("X-Ratelimit-Reset", "0"))
        except ValueError:
            return
        if remaining <= 1 and reset > 0:
            end = time.time() + reset
            while (left := end - time.time()) > 0:
                bar.status = f"⏸ rate-limit {int(left) // 60}:{int(left) % 60:02d}"
                bar.draw()
                await asyncio.sleep(min(1, left))
            bar.status = ""
            bar.draw()

    mod.respect_ratelimit = respect_ratelimit

    orig_process = mod.process

    async def process(session, items, args):
        bar.begin(len(items))
        try:
            return await orig_process(session, items, args)
        finally:
            bar.end()

    mod.process = process


# ---------------------------------------------------------------- main

def load_deleter():
    spec = importlib.util.spec_from_file_location("delete_reddit_comments", DELETER)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def main():
    if not DELETER.exists():
        sys.exit(f"Can't find {DELETER.name}. Put wipe.py in the redact-reddit folder.")

    print("Looking for your Reddit token ...")
    for name, fn in (("Chrome", from_chrome), ("token.txt", from_file), ("clipboard", from_clipboard)):
        token = fn()
        if token:
            print(f"  + using token from {name}\n")
            break
    else:
        sys.exit("\nNo token found. Copy token_v2 from Chrome DevTools "
                 "(Application > Cookies > reddit.com) and run again.")

    os.chdir(HERE)  # keep the log file next to the scripts
    os.environ["REDDIT_TOKEN"] = token
    sys.argv = [str(DELETER), *sys.argv[1:]]

    mod = load_deleter()
    bar = Progress()
    instrument(mod, bar)
    try:
        asyncio.run(mod.main())
    except KeyboardInterrupt:
        bar.end()
        print("\nStopped. Anything already deleted stays deleted; rerun to continue.")
    finally:
        os.environ.pop("REDDIT_TOKEN", None)
        if TOKEN_FILE.exists():
            print("\nReminder: delete token.txt now — it's a live login token.")


if __name__ == "__main__":
    main()
