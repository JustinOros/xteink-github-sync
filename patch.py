#!/usr/bin/env python3

import sys
import shutil
import subprocess
import getpass
import csv
import tempfile
from pathlib import Path
import glob
import os
import ssl
import urllib.request
import urllib.error
import json

PATCH_DIR = Path(__file__).parent
CROSSPOINT_URL = "https://github.com/crosspoint-reader/crosspoint-reader.git"
NVS_NAMESPACE  = "github_sync"
BOLD   = "\033[1m"
GREEN  = "\033[92m"
RED    = "\033[91m"
YELLOW = "\033[93m"
CYAN   = "\033[96m"
RESET  = "\033[0m"

def ok(msg):   print(f"{GREEN}  ✓ {msg}{RESET}")
def err(msg):  print(f"{RED}  ✗ {msg}{RESET}"); sys.exit(1)
def warn(msg): print(f"{YELLOW}  ! {msg}{RESET}")
def info(msg): print(f"  {msg}")

def ensure_python_module(module_name: str, pip_package: str | None = None, *, description: str = "") -> None:
    """If import fails, prompt user (Press Enter) then pip install into this Python."""
    pip_package = pip_package or module_name
    try:
        __import__(module_name)
        return
    except ImportError:
        pass
    desc = f" — {description}" if description else ""
    warn(f"Python module '{module_name}' is not installed{desc}.")
    input(f"  Press Enter to install {pip_package}... ")
    result = subprocess.run(
        [sys.executable, "-m", "pip", "install", pip_package],
        capture_output=True, text=True,
    )
    if result.returncode != 0:
        err(f"Failed to install {pip_package}:\n{result.stderr.strip()}")
    ok(f"{pip_package} installed")
    try:
        __import__(module_name)
    except ImportError:
        err(f"'{module_name}' still not importable after install — try restarting the terminal or use the same Python as: {sys.executable}")

_github_https_deps_ready = False

def ensure_github_https_dependencies() -> None:
    """certifi fixes macOS CERTIFICATE_VERIFY_FAILED for api.github.com unless user opted out."""
    global _github_https_deps_ready
    if _github_https_deps_ready:
        return
    if os.environ.get("GITHUB_SYNC_SSL_NO_VERIFY", "").strip().lower() in ("1", "true", "yes", "on"):
        _github_https_deps_ready = True
        return
    cf = os.environ.get("SSL_CERT_FILE", "").strip()
    if cf and os.path.isfile(cf):
        _github_https_deps_ready = True
        return
    try:
        import certifi  # noqa: F401
        _github_https_deps_ready = True
        return
    except ImportError:
        pass
    ensure_python_module(
        "certifi",
        description="recommended for GitHub HTTPS (fixes macOS SSL certificate errors)",
    )
    _github_https_deps_ready = True

def get_github_ssl_context():
    """
    macOS Python from python.org often lacks system CA bundle → CERTIFICATE_VERIFY_FAILED.
    Fixes: pip install certifi, set SSL_CERT_FILE, run Install Certificates.command,
    or (last resort) GITHUB_SYNC_SSL_NO_VERIFY=1.
    """
    flag = os.environ.get("GITHUB_SYNC_SSL_NO_VERIFY", "").strip().lower()
    if flag in ("1", "true", "yes", "on"):
        warn("SSL verification is OFF (GITHUB_SYNC_SSL_NO_VERIFY). Only use if you trust this network.")
        return ssl._create_unverified_context()
    cert_file = os.environ.get("SSL_CERT_FILE", "").strip()
    if cert_file and os.path.isfile(cert_file):
        return ssl.create_default_context(cafile=cert_file)
    try:
        import certifi
        return ssl.create_default_context(cafile=certifi.where())
    except ImportError:
        pass
    return ssl.create_default_context()

def ssl_troubleshoot_hint(err_txt: str | None) -> str:
    if not err_txt:
        return ""
    if "CERTIFICATE_VERIFY_FAILED" in err_txt or "SSL" in err_txt:
        return (
            " Try: pip install certifi (then re-run), or run macOS "
            "'Install Certificates.command' for your Python, or set SSL_CERT_FILE to a CA bundle. "
            "Last resort: GITHUB_SYNC_SSL_NO_VERIFY=1 (insecure)."
        )
    return ""

def github_api_get(path: str, token: str | None = None, timeout: int = 10):
    url = f"https://api.github.com{path}"
    headers = {
        "Accept": "application/vnd.github+json",
        "User-Agent": "xteink-github-sync-patcher",
    }
    if token:
        headers["Authorization"] = f"Bearer {token}"
    req = urllib.request.Request(url, headers=headers)
    ctx = get_github_ssl_context()
    try:
        with urllib.request.urlopen(req, timeout=timeout, context=ctx) as resp:
            body = resp.read().decode("utf-8", errors="replace")
            data = json.loads(body) if body else {}
            return resp.status, data, None
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace")
        try:
            data = json.loads(body) if body else {}
        except Exception:
            data = {"message": body.strip()} if body else {}
        return e.code, data, None
    except Exception as e:
        return None, None, str(e)

def validate_github_username(username: str) -> tuple[bool, str]:
    status, data, err_txt = github_api_get(f"/users/{username}")
    if err_txt:
        return False, f"Could not reach GitHub API: {err_txt}{ssl_troubleshoot_hint(err_txt)}"
    if status == 200:
        return True, "GitHub username is reachable."
    if status == 404:
        return False, "Username not found on GitHub."
    msg = data.get("message", "Unknown API error") if isinstance(data, dict) else "Unknown API error"
    return False, f"GitHub API error ({status}): {msg}"

def validate_pat(token: str) -> tuple[bool, str, str | None]:
    status, data, err_txt = github_api_get("/user", token=token)
    if err_txt:
        return False, f"Could not validate PAT: {err_txt}{ssl_troubleshoot_hint(err_txt)}", None
    if status == 200 and isinstance(data, dict):
        login = data.get("login")
        return True, f"PAT is valid (authenticated as {login}).", login
    if status in (401, 403):
        msg = data.get("message", "Unauthorized") if isinstance(data, dict) else "Unauthorized"
        return False, f"PAT rejected: {msg}", None
    msg = data.get("message", "Unknown API error") if isinstance(data, dict) else "Unknown API error"
    return False, f"PAT validation failed ({status}): {msg}", None

def validate_repo_access(owner: str, repo: str, token: str) -> tuple[bool, str]:
    status, data, err_txt = github_api_get(f"/repos/{owner}/{repo}", token=token)
    if err_txt:
        return False, f"Could not validate repo access: {err_txt}{ssl_troubleshoot_hint(err_txt)}"
    if status == 200:
        return True, "Repo is reachable with this PAT."
    if status == 404:
        return False, "Repo not found, or PAT cannot access it."
    if status in (401, 403):
        msg = data.get("message", "Unauthorized") if isinstance(data, dict) else "Unauthorized"
        return False, f"Access denied: {msg}"
    msg = data.get("message", "Unknown API error") if isinstance(data, dict) else "Unknown API error"
    return False, f"Repo validation failed ({status}): {msg}"

def prompt_install(pip_package: str):
    warn(f"{pip_package} is not installed or not available to this Python.")
    input(f"  Press Enter to install {pip_package}... ")
    result = subprocess.run(
        [sys.executable, "-m", "pip", "install", pip_package],
        capture_output=True, text=True,
    )
    if result.returncode != 0:
        err(f"Failed to install {pip_package}:\n{result.stderr.strip()}")
    ok(f"{pip_package} installed")

def check_tool(cmd: list[str], pip_package: str, fatal: bool = True) -> bool:
    try:
        subprocess.run(cmd, check=True, capture_output=True)
        return True
    except (subprocess.CalledProcessError, FileNotFoundError):
        if fatal:
            prompt_install(pip_package)
            try:
                subprocess.run(cmd, check=True, capture_output=True)
                return True
            except (subprocess.CalledProcessError, FileNotFoundError):
                err(f"{cmd[0]} still not found after install — check your PATH")
        else:
            return False

def check_git():
    try:
        subprocess.run(["git", "--version"], check=True, capture_output=True)
    except (subprocess.CalledProcessError, FileNotFoundError):
        err("git is not installed. Install from https://git-scm.com and re-run.")

def check_pio():
    check_tool(["pio", "--version"], "platformio")

def check_esptool():
    return check_tool(["esptool.py", "version"], "esptool", fatal=False)

def check_nvs_gen() -> bool:
    result = subprocess.run(
        ["python3", "-m", "esp_idf_nvs_partition_gen", "--help"],
        capture_output=True, text=True
    )
    if result.returncode == 0:
        return True
    check_tool(["python3", "-m", "esp_idf_nvs_partition_gen", "--help"], "esp-idf-nvs-partition-gen", fatal=False)
    result2 = subprocess.run(
        ["python3", "-m", "esp_idf_nvs_partition_gen", "--help"],
        capture_output=True, text=True
    )
    return result2.returncode == 0

def clone_or_update(dest: Path) -> Path:
    repo = dest / "crosspoint-reader"
    if repo.exists() and (repo / ".git").exists():
        info(f"Repo already exists at {repo}, pulling latest...")
        result = subprocess.run(
            ["git", "-C", str(repo), "pull", "--recurse-submodules"],
            capture_output=True, text=True
        )
        if result.returncode != 0:
            err(f"git pull failed:\n{result.stderr}")
        ok("Repo updated to latest")
    else:
        info(f"Cloning CrossPoint into {repo}...")
        result = subprocess.run(
            ["git", "clone", "--recurse-submodules", CROSSPOINT_URL, str(repo)],
            capture_output=True, text=True
        )
        if result.returncode != 0:
            err(f"git clone failed:\n{result.stderr}")
        ok("Repo cloned successfully")
    return repo

def prompt_github_config() -> dict:
    print(f"\n{BOLD}GitHub Sync Configuration{RESET}")
    print(f"{CYAN}  Press Enter to skip and configure on-device later.{RESET}\n")

    while True:
        username = input("  GitHub username: ").strip()
        if not username:
            return {}
        ensure_github_https_dependencies()
        ok_user, msg = validate_github_username(username)
        if ok_user:
            ok(msg)
            break
        warn(msg)
        retry = input("  Try another username? [Y/n]: ").strip().lower()
        if retry == "n":
            return {}

    print(f"\n{CYAN}  To generate a Personal Access Token (PAT):{RESET}")
    print(f"{CYAN}    1. Go to github.com -> Settings -> Developer settings{RESET}")
    print(f"{CYAN}    2. Personal access tokens -> Fine-grained tokens{RESET}")
    print(f"{CYAN}    3. Click 'Generate new token'{RESET}")
    print(f"{CYAN}    4. Token name: xteink{RESET}")
    print(f"{CYAN}    5. Expiration: No expiration{RESET}")
    print(f"{CYAN}    6. Repository access: Only selected repositories -> select 'xteink'{RESET}")
    print(f"{CYAN}    7. Permissions -> Add permissions -> Contents: Read-only{RESET}")
    print(f"{CYAN}    8. Click 'Generate token' then copy it - GitHub only shows it once\n{RESET}")

    authenticated_login = None
    while True:
        pat = getpass.getpass("  Personal Access Token (PAT): ").strip()
        if not pat:
            return {}
        ok_pat, msg, authenticated_login = validate_pat(pat)
        if ok_pat:
            ok(msg)
            break
        warn(msg)
        retry = input("  Try entering PAT again? [Y/n]: ").strip().lower()
        if retry == "n":
            return {}

    while True:
        repo = input("  Repo name [xteink]: ").strip() or "xteink"
        owner_for_repo = authenticated_login or username
        ok_repo, msg = validate_repo_access(owner_for_repo, repo, pat)
        if ok_repo:
            ok(msg)
            if authenticated_login and authenticated_login != username:
                warn(f"Username '{username}' differs from PAT owner '{authenticated_login}'. Repo was validated under '{owner_for_repo}'.")
            break
        warn(msg)
        retry = input("  Try another repo name? [Y/n]: ").strip().lower()
        if retry == "n":
            return {}

    branch = input("  Branch [main]: ").strip() or "main"

    return {"username": username, "pat": pat, "repo": repo, "branch": branch}

def write_nvs_partition(cfg: dict, repo: Path) -> Path:
    if not check_nvs_gen():
        prompt_install("esp-idf-nvs-partition-gen")

    nvs_csv = Path(tempfile.mkdtemp()) / "github_sync_nvs.csv"
    rows = [
        ["key", "type", "encoding", "value"],
        [NVS_NAMESPACE, "namespace", "", ""],
        ["username", "data", "string", cfg["username"]],
        ["pat",      "data", "string", cfg["pat"]],
        ["repo",     "data", "string", cfg["repo"]],
        ["branch",   "data", "string", cfg["branch"]],
    ]
    with open(nvs_csv, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerows(rows)

    nvs_bin = nvs_csv.with_suffix(".bin")
    result = subprocess.run(
        ["python3", "-m", "esp_idf_nvs_partition_gen", "generate",
         str(nvs_csv), str(nvs_bin), "0x3000"],
        capture_output=True, text=True
    )
    if result.returncode != 0:
        warn(f"nvs_partition_gen failed — enter credentials on-device via Settings -> GitHub Sync.\n{result.stderr.strip()}")
        return None

    ok(f"NVS partition written to {nvs_bin}")
    return nvs_bin

def flash_nvs(nvs_bin: Path, port: str | None):
    if not check_esptool():
        prompt_install("esptool")
    info("Flashing NVS credentials partition...")
    cmd = ["esptool.py", "--chip", "esp32c3", "write_flash", "0x9000", str(nvs_bin)]
    if port:
        cmd += ["--port", port]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        warn("esptool.py flash failed — you may need to enter credentials on-device.")
        warn(result.stderr.strip())
    else:
        ok("Credentials flashed to device NVS")

def copy_new_files(repo: Path):
    copies = [
        (PATCH_DIR / "GitHubSync.h",
         repo / "include" / "GitHubSync.h"),
        (PATCH_DIR / "GitHubSyncSettingsActivity.h",
         repo / "include" / "GitHubSyncSettingsActivity.h"),
        (PATCH_DIR / "GitHubSync.cpp",
         repo / "src" / "github_sync" / "GitHubSync.cpp"),
        (PATCH_DIR / "GitHubSyncSettingsActivity.cpp",
         repo / "src" / "activities" / "settings" / "GitHubSyncSettingsActivity.cpp"),
    ]
    for src, dst in copies:
        if not src.exists():
            err(f"Patch file missing: {src}")
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)
        ok(f"Copied {dst.relative_to(repo)}")

def inject_into_file(path: Path, marker: str, injection: str, after: bool = True, once: bool = True):
    if not path.exists():
        warn(f"File not found, skipping: {path}")
        return False
    text = path.read_text()
    if injection.strip() in text:
        ok(f"Already patched: {path.name}")
        return True
    if marker not in text:
        warn(f"Marker not found in {path.name}: {repr(marker)}")
        warn(f"  → Add manually per INTEGRATION.md")
        return False
    if after:
        new_text = text.replace(marker, marker + "\n" + injection, 1 if once else -1)
    else:
        new_text = text.replace(marker, injection + "\n" + marker, 1 if once else -1)
    path.write_text(new_text)
    ok(f"Patched {path.name}")
    return True

def patch_main(repo: Path):
    candidates = [repo / "src" / "main.cpp", repo / "src" / "Main.cpp"]
    main = next((p for p in candidates if p.exists()), None)
    if not main:
        warn("Could not find main.cpp — add GitHub sync call manually per INTEGRATION.md")
        return

    inject_into_file(main,
        marker='#include "CrossPointSettings.h"',
        injection='#include "GitHubSync.h"',
        after=False)

    sync_injection = (
        '\n  if (GitHubSync::isConfigured()) {\n'
        '    GitHubSyncResult result = GitHubSync::sync();\n'
        '    if (result != GitHubSyncResult::OK) {\n'
        '      LOG_ERR("SYNC", "%s", GitHubSync::resultMessage(result));\n'
        '    }\n'
        '  }\n'
    )

    inject_into_file(main,
        marker="activityManager.goToBoot();",
        injection=sync_injection,
        after=True)

def patch_settings_menu(repo: Path):
    # 1. Patch SettingsActivity.h — add GitHubSync to SettingAction enum
    settings_h_candidates = list(repo.rglob("SettingsActivity.h"))
    if not settings_h_candidates:
        warn("Could not find SettingsActivity.h — add GitHubSync to SettingAction enum manually")
    else:
        inject_into_file(settings_h_candidates[0],
            marker="  CheckForUpdates,",
            injection="  GitHubSync,",
            after=True)

    # 2. Patch SettingsActivity.cpp — add include, menu entry, and switch case
    candidates = list(repo.rglob("SettingsActivity.cpp"))
    if not candidates:
        warn("Could not find SettingsActivity.cpp — add menu entry manually per INTEGRATION.md")
        return

    settings = candidates[0]

    inject_into_file(settings,
        marker='#include "SettingsActivity.h"',
        injection='#include "GitHubSyncSettingsActivity.h"',
        after=False)

    inject_into_file(settings,
        marker="SettingInfo::Action(StrId::STR_CHECK_UPDATES, SettingAction::CheckForUpdates));",
        injection="  systemSettings.push_back(SettingInfo::Action(StrId::STR_GITHUB_SYNC, SettingAction::GitHubSync));",
        after=True)

    inject_into_file(settings,
        marker="case SettingAction::CheckForUpdates:",
        injection="      case SettingAction::GitHubSync:\n        startActivityForResult(std::make_unique<GitHubSyncSettingsActivity>(renderer, mappedInput), resultHandler);\n        break;",
        after=True)

    # 3. Patch all YAML translation files — add STR_GITHUB_SYNC entry
    yaml_files = list((repo / "lib" / "I18n" / "translations").glob("*.yaml"))
    if not yaml_files:
        warn("Could not find translation YAML files — add STR_GITHUB_SYNC manually to lib/I18n/translations/*.yaml")
    else:
        patched = 0
        for yf in yaml_files:
            content = yf.read_text()
            if 'STR_GITHUB_SYNC' in content:
                ok(f"Already patched: {yf.name}")
                patched += 1
                continue
            lines = content.splitlines(keepends=True)
            new_lines = []
            for line in lines:
                new_lines.append(line)
                if line.startswith("STR_CHECK_UPDATES:"):
                    new_lines.append('STR_GITHUB_SYNC: "GitHub Sync"\n')
            if len(new_lines) > len(lines):
                yf.write_text("".join(new_lines))
                ok(f"Patched {yf.name}")
                patched += 1
            else:
                warn(f"STR_CHECK_UPDATES not found in {yf.name} — add STR_GITHUB_SYNC manually")
        ok(f"Added STR_GITHUB_SYNC to {patched} translation files")

def patch_platformio(repo: Path):
    ini = repo / "platformio.ini"
    if not ini.exists():
        warn("platformio.ini not found")
        return
    if "ArduinoJson" in ini.read_text():
        ok("ArduinoJson already in platformio.ini")
        return
    inject_into_file(ini,
        marker="lib_deps",
        injection="\tbblanchon/ArduinoJson @ ^7",
        after=True)

def list_likely_serial_ports() -> list[str]:
    patterns = [
        "/dev/cu.usb*",
        "/dev/tty.usb*",
        "/dev/cu.wchusb*",
        "/dev/tty.wchusb*",
        "/dev/cu.SLAB*",
        "/dev/tty.SLAB*",
        "/dev/ttyACM*",
        "/dev/ttyUSB*",
    ]
    ports: list[str] = []
    for pattern in patterns:
        ports.extend(glob.glob(pattern))
    # Keep stable order and remove duplicates.
    return sorted(set(ports))

def prompt_for_upload_port(existing_port: str | None) -> str | None:
    print(f"\n{BOLD}Ready to upload firmware{RESET}")
    print(f"{CYAN}  Connect your xteink device via USB now, then press Enter.{RESET}")
    input("  Press Enter when connected... ")

    likely_ports = list_likely_serial_ports()
    if likely_ports:
        print("\n  Detected likely USB serial ports:")
        for p in likely_ports:
            print(f"   - {p}")
    else:
        warn("No obvious USB serial ports detected. You can still enter one manually.")

    # Show PlatformIO's own device list as extra context.
    device_list = subprocess.run(["pio", "device", "list"], capture_output=True, text=True)
    if device_list.returncode == 0 and device_list.stdout.strip():
        print("\n  PlatformIO device list:")
        print(device_list.stdout.rstrip())

    if existing_port:
        info(f"Current upload port argument: {existing_port}")
        entered = input("  Upload port (Enter to keep current): ").strip()
        return entered or existing_port

    entered = input("  Upload port (recommended, e.g. /dev/cu.usbmodemXXXX; Enter for auto-detect): ").strip()
    if entered:
        return entered

    warn("Proceeding with auto-detect. This may choose a non-USB port (like Bluetooth).")
    return None

def main():
    print(f"\n{BOLD}CrossPoint GitHub Sync Patcher{RESET}\n")

    check_git()
    check_pio()
    check_esptool()

    dest = Path(sys.argv[1]) if len(sys.argv) > 1 else Path.cwd()
    port = sys.argv[2] if len(sys.argv) > 2 else None

    print(f"{BOLD}1. Fetching CrossPoint repo ({CROSSPOINT_URL}){RESET}")
    repo = clone_or_update(dest)
    info(f"Repo: {repo}\n")

    print(f"{BOLD}2. Copying new files{RESET}")
    copy_new_files(repo)

    print(f"\n{BOLD}3. Patching platformio.ini{RESET}")
    patch_platformio(repo)

    print(f"\n{BOLD}4. Patching main.cpp{RESET}")
    patch_main(repo)

    print(f"\n{BOLD}5. Patching settings menu{RESET}")
    patch_settings_menu(repo)

    print(f"\n{BOLD}6. GitHub credentials{RESET}")
    cfg = prompt_github_config()
    nvs_bin = None
    if cfg:
        nvs_bin = write_nvs_partition(cfg, repo)

    port = prompt_for_upload_port(port)

    print(f"\n{BOLD}7. Building and flashing firmware{RESET}")
    info("Running: pio run --target upload")
    result = subprocess.run(
        ["pio", "run", "--target", "upload"] + (["--upload-port", port] if port else []),
        cwd=repo
    )
    if result.returncode != 0:
        err("pio build/flash failed — check output above")
    ok("Firmware flashed")

    if nvs_bin:
        print(f"\n{BOLD}8. Flashing credentials{RESET}")
        flash_nvs(nvs_bin, port)

    print(f"\n{GREEN}{BOLD}All done.{RESET}")
    if not cfg:
        print("No credentials entered — configure on-device via Settings → GitHub Sync.")
    print()

if __name__ == "__main__":
    main()
