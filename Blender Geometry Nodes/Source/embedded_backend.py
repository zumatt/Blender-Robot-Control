"""Launch and manage a bundled PRC.Server process from the Blender add-on."""

from __future__ import annotations

import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
import time
from typing import Optional
from urllib import request as _urlrequest


SERVER_HOST = "127.0.0.1"
SERVER_PORT = 5001

_process: Optional[subprocess.Popen] = None
_process_lock = threading.Lock()
_process_log_handle = None
_log_path: Optional[str] = None


def _addon_dir() -> str:
    return os.path.dirname(os.path.realpath(__file__))


def _server_dir() -> str:
    return os.path.join(_addon_dir(), "PRC.Server")


def log_path() -> Optional[str]:
    return _log_path


def _startup_log_hint() -> str:
    if _log_path:
        return f" See server log: {_log_path}"
    return ""


def _server_log_path() -> str:
    return os.path.join(tempfile.gettempdir(), "prc_blender_server.log")


def _is_port_open(host: str, port: int, timeout_s: float = 0.3) -> bool:
    try:
        with socket.create_connection((host, int(port)), timeout=timeout_s):
            return True
    except OSError:
        return False


def _find_dotnet() -> Optional[str]:
    """Locate a usable dotnet host binary across common install layouts."""
    from_path = shutil.which("dotnet")
    if from_path:
        return from_path
    candidates = [
        os.path.expanduser("~/.dotnet/dotnet"),
        "/usr/local/share/dotnet/dotnet",
    ]
    for candidate in candidates:
        if os.path.isfile(candidate) and os.access(candidate, os.X_OK):
            return candidate
    return None


def _required_frameworks(server_dir: str) -> list[tuple[str, str]]:
    """Return required framework tuples as (name, version) from runtimeconfig."""
    cfg_path = os.path.join(server_dir, "PRC.Server.runtimeconfig.json")
    try:
        with open(cfg_path, "r", encoding="utf-8") as f:
            doc = json.load(f)
    except Exception:  # noqa: BLE001
        return []

    rt = doc.get("runtimeOptions") if isinstance(doc, dict) else None
    if not isinstance(rt, dict):
        return []

    out: list[tuple[str, str]] = []

    one = rt.get("framework")
    if isinstance(one, dict):
        name = str(one.get("name") or "").strip()
        ver = str(one.get("version") or "").strip()
        if name and ver:
            out.append((name, ver))

    many = rt.get("frameworks")
    if isinstance(many, list):
        for item in many:
            if not isinstance(item, dict):
                continue
            name = str(item.get("name") or "").strip()
            ver = str(item.get("version") or "").strip()
            if name and ver:
                out.append((name, ver))

    # Deduplicate while preserving order.
    dedup: list[tuple[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for t in out:
        if t in seen:
            continue
        seen.add(t)
        dedup.append(t)
    return dedup


def _framework_is_installed(dotnet_bin: str, fw_name: str, fw_version: str) -> bool:
    """Check if a required framework major version is present."""
    try:
        proc = subprocess.run(
            [dotnet_bin, "--list-runtimes"],
            capture_output=True,
            text=True,
            check=False,
            timeout=8,
        )
    except Exception:  # noqa: BLE001
        return False
    if proc.returncode != 0:
        return False

    want_major = fw_version.split(".")[0]
    lines = (proc.stdout or "").splitlines()
    for line in lines:
        parts = line.split()
        if len(parts) < 2:
            continue
        if parts[0] != fw_name:
            continue
        got_major = parts[1].split(".")[0]
        if got_major == want_major:
            return True
    return False


def _version_to_channel(version: str) -> str:
    parts = (version or "").split(".")
    if len(parts) >= 2 and parts[0].isdigit() and parts[1].isdigit():
        return f"{parts[0]}.{parts[1]}"
    if parts and parts[0].isdigit():
        return f"{parts[0]}.0"
    return "10.0"


def _install_dotnet_runtime_user(frameworks: list[tuple[str, str]]) -> tuple[bool, str]:
    """Install missing runtimes to ~/.dotnet without admin rights."""
    if sys.platform not in {"darwin", "linux"}:
        return False, "Automatic dotnet install is supported on macOS/Linux only."

    runtime_kinds: list[tuple[str, str]] = []
    for name, version in frameworks:
        if name == "Microsoft.NETCore.App":
            runtime_kinds.append(("dotnet", _version_to_channel(version)))
        elif name == "Microsoft.AspNetCore.App":
            runtime_kinds.append(("aspnetcore", _version_to_channel(version)))

    if not runtime_kinds:
        # Conservative fallback for unknown/missing runtimeconfig.
        runtime_kinds = [("dotnet", "10.0"), ("aspnetcore", "10.0")]

    # Deduplicate install requests.
    dedup: list[tuple[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for item in runtime_kinds:
        if item in seen:
            continue
        seen.add(item)
        dedup.append(item)

    install_dir = os.path.expanduser("~/.dotnet")
    os.makedirs(install_dir, exist_ok=True)

    fd, script_path = tempfile.mkstemp(prefix="dotnet-install-", suffix=".sh")
    os.close(fd)
    try:
        _urlrequest.urlretrieve("https://dot.net/v1/dotnet-install.sh", script_path)
        os.chmod(script_path, 0o755)

        for runtime, channel in dedup:
            proc = subprocess.run(
                [
                    script_path,
                    "--channel", channel,
                    "--install-dir", install_dir,
                    "--runtime", runtime,
                ],
                capture_output=True,
                text=True,
                check=False,
                timeout=900,
            )
            if proc.returncode != 0:
                tail = (proc.stderr or proc.stdout or "").strip().splitlines()
                snippet = tail[-1] if tail else "installer failed"
                return False, f"Failed installing dotnet runtime ({runtime} {channel}): {snippet}"
    except Exception as exc:  # noqa: BLE001
        return False, f"Failed downloading/installing dotnet runtime: {exc!r}"
    finally:
        try:
            os.remove(script_path)
        except Exception:  # noqa: BLE001
            pass

    return True, "Installed required dotnet runtimes in ~/.dotnet."


def _ensure_dotnet_for_server(server_dir: str) -> tuple[bool, str]:
    """Ensure dotnet + required runtimes are available for PRC.Server.dll."""
    dll = os.path.join(server_dir, "PRC.Server.dll")
    if not os.path.isfile(dll):
        return True, ""

    frameworks = _required_frameworks(server_dir)
    dotnet_bin = _find_dotnet()
    if dotnet_bin is not None:
        all_present = True
        for name, version in frameworks:
            if not _framework_is_installed(dotnet_bin, name, version):
                all_present = False
                break
        if all_present:
            return True, ""

    ok, msg = _install_dotnet_runtime_user(frameworks)
    if not ok:
        return False, msg

    dotnet_bin = _find_dotnet()
    if dotnet_bin is None:
        return False, "Dotnet install completed but dotnet binary was not found."

    for name, version in frameworks:
        if not _framework_is_installed(dotnet_bin, name, version):
            return False, (
                "Dotnet installed, but required frameworks are still missing: "
                f"{name} {version}"
            )
    return True, msg


def is_running() -> bool:
    """True when the embedded process managed by this module is alive."""
    global _process
    with _process_lock:
        if _process is not None and _process.poll() is None:
            return True
        if _process is not None and _process.poll() is not None:
            _process = None
    return False


def endpoint_reachable() -> bool:
    """True when any server (embedded or external) listens on the PRC endpoint."""
    if is_running():
        return True
    return _is_port_open(SERVER_HOST, SERVER_PORT)


def _resolve_launch_command(server_dir: str) -> tuple[list[str], Optional[str]]:
    """Return command argv and a human-readable launcher description.

    Prefers self-contained binaries when present; otherwise falls back to
    `dotnet PRC.Server.dll` for framework-dependent distributions.
    """
    apphost = os.path.join(server_dir, "PRC.Server")
    dll = os.path.join(server_dir, "PRC.Server.dll")
    exe = os.path.join(server_dir, "PRC.Server.exe")

    if sys.platform == "win32":
        if os.path.isfile(exe):
            return [exe], "PRC.Server.exe"
        dotnet = _find_dotnet()
        if dotnet and os.path.isfile(dll):
            return [dotnet, dll], "dotnet PRC.Server.dll"
        return [], None

    if os.path.isfile(apphost) and os.access(apphost, os.X_OK):
        return [apphost], "PRC.Server"

    dotnet = _find_dotnet()
    if dotnet and os.path.isfile(dll):
        return [dotnet, dll], "dotnet PRC.Server.dll"

    if os.path.isfile(exe) and os.access(exe, os.X_OK):
        return [exe], "PRC.Server.exe"

    return [], None


def ensure_started(startup_timeout_s: float = 12.0) -> tuple[bool, str]:
    """Ensure the local PRC server endpoint is up.

    Returns (ok, message).
    """
    global _process, _process_log_handle, _log_path

    # If endpoint is already live (our process or user-started process), reuse it.
    if endpoint_reachable():
        return True, f"PRC server already reachable at {SERVER_HOST}:{SERVER_PORT}."

    server_dir = _server_dir()
    if not os.path.isdir(server_dir):
        return False, (
            "Bundled server folder missing. Expected 'PRC.Server' inside the add-on "
            "directory."
        )

    install_note = ""
    dotnet_ok, dotnet_msg = _ensure_dotnet_for_server(server_dir)
    if not dotnet_ok:
        return False, dotnet_msg
    if dotnet_msg:
        install_note = f" {dotnet_msg}"

    argv, launcher = _resolve_launch_command(server_dir)
    if not argv:
        return False, (
            "No runnable PRC server entrypoint found. Bundle a platform binary "
            "(PRC.Server) or install dotnet and include PRC.Server.dll."
        )

    with _process_lock:
        if _process is not None and _process.poll() is None:
            return True, "Embedded PRC server already running."

        env = os.environ.copy()
        env.setdefault("ASPNETCORE_URLS", "https://127.0.0.1:5001")
        if argv and os.path.basename(argv[0]) == "dotnet":
            env.setdefault("DOTNET_ROOT", os.path.dirname(argv[0]))
            env["PATH"] = f"{os.path.dirname(argv[0])}:{env.get('PATH', '')}"

        kwargs = {
            "cwd": server_dir,
            "env": env,
        }
        if sys.platform == "win32":
            kwargs["creationflags"] = getattr(subprocess, "CREATE_NO_WINDOW", 0)

        try:
            _log_path = _server_log_path()
            _process_log_handle = open(_log_path, "ab")
            kwargs["stdout"] = _process_log_handle
            kwargs["stderr"] = subprocess.STDOUT
            _process = subprocess.Popen(argv, **kwargs)
        except Exception as exc:  # noqa: BLE001
            if _process_log_handle is not None:
                try:
                    _process_log_handle.close()
                except Exception:  # noqa: BLE001
                    pass
                _process_log_handle = None
            _process = None
            return False, f"Failed to start embedded server ({launcher}): {exc!r}"

    deadline = time.time() + float(max(1.0, startup_timeout_s))
    while time.time() < deadline:
        with _process_lock:
            proc = _process
            if proc is not None and proc.poll() is not None:
                code = proc.returncode
                _process = None
                if _process_log_handle is not None:
                    try:
                        _process_log_handle.close()
                    except Exception:  # noqa: BLE001
                        pass
                    _process_log_handle = None
                return False, (
                    f"Embedded server exited during startup (code {code})."
                    f"{_startup_log_hint()}"
                )
        if _is_port_open(SERVER_HOST, SERVER_PORT):
            return True, (
                f"Embedded PRC server started via {launcher}.{install_note}"
                f"{_startup_log_hint()}"
            )
        time.sleep(0.1)

    return False, (
        "Embedded server did not open port 5001 before timeout."
        f"{_startup_log_hint()}"
    )


def stop() -> None:
    """Terminate the managed embedded server process, if any."""
    global _process, _process_log_handle
    with _process_lock:
        proc = _process
        _process = None
    if proc is None:
        return
    if proc.poll() is not None:
        return
    try:
        proc.terminate()
        proc.wait(timeout=5.0)
    except Exception:  # noqa: BLE001
        try:
            proc.kill()
        except Exception:  # noqa: BLE001
            pass
    finally:
        if _process_log_handle is not None:
            try:
                _process_log_handle.close()
            except Exception:  # noqa: BLE001
                pass
            _process_log_handle = None

