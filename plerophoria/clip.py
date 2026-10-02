
from prompt_toolkit import clipboard
import os, sys, shutil, subprocess, re, base64


def _candidates():
    e = os.environ
    if sys.platform == "darwin":
        yield ["pbcopy"], ["pbpaste"]
    if "TERMUX_VERSION" in e:
        yield ["termux-clipboard-set"], ["termux-clipboard-get"]
    if "WSL_DISTRO_NAME" in e:
        yield ["clip.exe"], ["powershell.exe", "-NoProfile", "-Command", "Get-Clipboard"]
    if e.get("WAYLAND_DISPLAY"):
        yield ["wl-copy"], ["wl-paste", "-n"]
    if e.get("DISPLAY"):                      # native X11, XWayland, or ssh -X
        yield ["xclip", "-selection", "clipboard"], ["xclip", "-selection", "clipboard", "-o"]
        yield ["xsel", "-bi"], ["xsel", "-bo"]

def native_copy(data: bytes) -> str | None:
    for put, get in _candidates():
        if not shutil.which(put[0]):
            continue
        try:
            subprocess.run(put, input=data, stdout=subprocess.DEVNULL,
                           stderr=subprocess.DEVNULL, timeout=2, check=True)
            got = subprocess.run(get, capture_output=True, timeout=2).stdout
            if got.rstrip(b"\r\n") == data.rstrip(b"\r\n"):
                return put[0]
        except (subprocess.SubprocessError, OSError):
            pass
    return None

def _pid_parent(pid: int) -> tuple[int, str]:

    _PROCESS_NAME_REGEX = re.compile(f"\((.*)\) \S (\d+)", re.DOTALL)
    assert sys.platform.startswith('linux', 'darwin') # Only linux and macOS should enter this function.

    if sys.platform.startswith('linux'):
        with open(f'/proc/{pid}/stat') as f:
            raw = f.read()
            matches = _PROCESS_NAME_REGEX.search(raw)
            if matches is None:
                raise ValueError(f'/proc/{pid}/stat unparseable')
            comm, ppid = matches.groups()
            return ppid, comm

    else:
        out = subprocess.run(['ps', '-o', 'ppid=,comm=', '-p', str(pid)],
                             capture_output=True, text=True).stdout.split(None,1)
        return int(out[0]), os.path.basename(out[1].strip())


def _pid_walk(init_pid: int) -> Optional[str]:
    REMOTE_MATCHES = {"sshd", "sshd-session", "dropbear", "mosh-server"}
    try:
        while pid > 1:
            found_pid, found_comm = _pid_parent(pid)
            if found_comm in REMOTE_MATCHES:
                return found_comm
            pid = found_pid
    except (OSError, ValueError, IndexError):
        pass

    return None


@dataclasses.dataclass
class SessionConditions:
    tmux_on: str
    tmux_supports_copy: bool
    remote_type: Optional[str]
    x11_forwarded: bool

class PleroClipboard(clipboard.Clipboard):
    def __init__(self):
        self._in_memory = clipboard.InMemoryClipboard()
        self.session_cache = self._load_session_conditions()

        self.is_tmux = os.environ.get('TMUX') is not None

        if self.is_tmux:
            import subprocess
        self.terminal_program = os.environ.get('TERM_PROGRAM')

    @property
    def session_conditions(self):
        return self._load_session_conditions()

    def _load_session_conditions(self):
        tmux_on = os.environ.get('TMUX') is not None
        SSH_CHECKS = ['SSH_CONNECTION', 'SSH_CLIENT', 'SSH_TTY']
        x11_forwarded = os.environ.get('DISPLAY', '').startswith('localhost:')

        if tmux_on:
            def query(*args: str) -> str:
                r = subprocess.run(['tmux', *args], capture_output=True, text=True)
                return r.stdout.strip() if r.returncode == 0 else ''

            pid = query('display', '-p', '#{client_pid}')
            if pid.isdigit():
                remote_type = _pid_walk(int(pid))
            else:
                remote_type = None


            clipboard_supported = 'clipboard' in query('display', '-p', '${client_termfeatures}')
            clipboard_allowed = query('show', '-sv', 'set-clipboard') not in ("", "off")
            tmux_attached = query('display', '-p', '${session_attached}') not in ("", "0")

            tmux_supports_copy = all(check is True for check in (clipboard_supported, clipboard_allowed, tmux_attached))
        else:
            remote_type = 'sshd' if any(os.environ.get(v) for v in SSH_CHECKS) else ''
            tmux_supports_copy = False

        return SessionConditions(
                tmux_on = tmux_on,
                tmux_supports_copy = tmux_supports_copy,
                remote_type = remote_type,
                x11_forwarded = x11_forwarded
                )

    def set_data(self, data: clipboard.ClipboardData, use_cached: bool = True):
        self._in_memory.set_data(data)
        text = data.text.encode()
        session_cond = self.session_cache if use_cached else self.session_conditions

        # Native copy (pipe the text directly to a subprocess) if forwarded or local
        if not session_cond.remote_type or session_cond.x11_forwarded:
            native_copy(text)
            return

        # If we're in tmux, use its subprocess to copy directly
        if session_cond.tmux_on and session_cond.tmux_supports_copy:
            r = subprocess.run(['tmux', 'load-buffer', '-w', '-'],
                               input=data,
                               stdout=subprocess.DEVNULL,
                               stderr=subprocess.DEVNULL)
            return

        # Otherwise, hail mary and attempt direct OSC52 escape sequence.
        OSC52_CODE = '\x1b]52;c;'
        BEL = '\x07'
        raw_buf_out = get_app().output
        payload = base64.b64encode(data.encode()).decode()
        raw_buf_out.write_raw(f'{OSC52_CODE}{payload}{BEL}')
        raw_buf_out.flush()

    def get_data(self) -> clipboard.ClipboardData:
        return self._in_memory.get_data()

