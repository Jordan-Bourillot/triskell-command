"""Release + notify Thomas — orchestrateur "fin de session".

Enchaîne automatiquement :
  1. Bump version (theme.py · TriskellCommand.iss · pyproject.toml)
  2. PyInstaller : génère dist/Triskell Command/
  3. Inno Setup : génère Output/TriskellCommand_Setup.exe
  4. Push git (commit + push origin main)
  5. GitHub release : crée le tag + upload l'installeur
  6. Message Thomas via le chat 1-à-1 (table messages dans Supabase)

Usage :
    py scripts/release_and_notify.py             → bump auto +0.1.0 (minor)
    py scripts/release_and_notify.py 0.7.0       → version explicite
    py scripts/release_and_notify.py --patch     → bump +0.0.1
    py scripts/release_and_notify.py --no-build  → skip PyInstaller + Inno (pour rejouer)
    py scripts/release_and_notify.py --dry-run   → affiche ce qui serait fait, sans rien faire
"""
from __future__ import annotations

import io
import json
import re
import subprocess
import sys
import urllib.error
import urllib.request
from pathlib import Path
from datetime import datetime

# Force UTF-8 sur Windows
try: sys.stdout.reconfigure(encoding="utf-8")
except Exception: pass

ROOT = Path(__file__).resolve().parent.parent
ISS_PATH = ROOT / "TriskellCommand.iss"
THEME_PATH = ROOT / "triskell_command" / "theme.py"
PYPROJECT_PATH = ROOT / "pyproject.toml"
SPEC_PATH = ROOT / "triskell_command.spec"
INSTALLER_OUT = ROOT / "Output" / "TriskellCommand_Setup.exe"
INNO_PATH = Path(r"C:\Program Files (x86)\Inno Setup 6\ISCC.exe")

OWNER = "Jordan-Bourillot"
REPO = "triskell-command"


# ---------------------------------------------------------------------------
# Bump version
# ---------------------------------------------------------------------------
def get_current_version() -> str:
    m = re.search(r'#define MyAppVersion\s+"([^"]+)"', ISS_PATH.read_text(encoding="utf-8"))
    if not m:
        raise SystemExit("Version introuvable dans TriskellCommand.iss")
    return m.group(1)


def bump_version(current: str, mode: str) -> str:
    parts = [int(x) for x in current.split(".")]
    while len(parts) < 3: parts.append(0)
    if mode == "major":
        parts = [parts[0] + 1, 0, 0]
    elif mode == "patch":
        parts = [parts[0], parts[1], parts[2] + 1]
    else:  # minor
        parts = [parts[0], parts[1] + 1, 0]
    return ".".join(str(x) for x in parts)


def write_version_to_files(new_version: str) -> None:
    # 1. TriskellCommand.iss
    iss = ISS_PATH.read_text(encoding="utf-8")
    iss = re.sub(r'#define MyAppVersion\s+"[^"]+"',
                  f'#define MyAppVersion   "{new_version}"', iss)
    ISS_PATH.write_text(iss, encoding="utf-8")
    # 2. theme.py — APP_VERSION_LABEL
    label = "v" + ".".join(new_version.split(".")[:2])  # ex: v0.6
    theme = THEME_PATH.read_text(encoding="utf-8")
    theme = re.sub(r'APP_VERSION_LABEL\s*=\s*"[^"]+"',
                    f'APP_VERSION_LABEL = "{label}"', theme)
    THEME_PATH.write_text(theme, encoding="utf-8")
    # 3. pyproject.toml
    pp = PYPROJECT_PATH.read_text(encoding="utf-8")
    pp = re.sub(r'^version\s*=\s*"[^"]+"',
                 f'version = "{new_version}"', pp, count=1, flags=re.M)
    PYPROJECT_PATH.write_text(pp, encoding="utf-8")
    print(f"  ✓ Version bumped à {new_version} (label {label})")


# ---------------------------------------------------------------------------
# Build
# ---------------------------------------------------------------------------
def run_pyinstaller(dry_run: bool) -> None:
    print("\n[BUILD] PyInstaller…")
    if dry_run:
        print("  (dry-run) py -m PyInstaller --noconfirm triskell_command.spec")
        return
    r = subprocess.run([sys.executable, "-m", "PyInstaller", "--noconfirm",
                         str(SPEC_PATH)], cwd=ROOT)
    if r.returncode != 0:
        raise SystemExit(f"PyInstaller a échoué (code {r.returncode})")
    print("  ✓ Build OK")


def run_inno_setup(dry_run: bool) -> None:
    print("\n[BUILD] Inno Setup…")
    if dry_run:
        print(f"  (dry-run) \"{INNO_PATH}\" {ISS_PATH.name}")
        return
    if not INNO_PATH.exists():
        raise SystemExit(f"Inno Setup introuvable : {INNO_PATH}\n"
                          "Installe depuis https://jrsoftware.org/isdl.php")
    r = subprocess.run([str(INNO_PATH), str(ISS_PATH)], cwd=ROOT)
    if r.returncode != 0:
        raise SystemExit(f"Inno Setup a échoué (code {r.returncode})")
    if not INSTALLER_OUT.exists():
        raise SystemExit(f"Installer attendu absent : {INSTALLER_OUT}")
    size_mb = INSTALLER_OUT.stat().st_size / 1024 / 1024
    print(f"  ✓ Installer : {INSTALLER_OUT.name} ({size_mb:.1f} MB)")


# ---------------------------------------------------------------------------
# Git push
# ---------------------------------------------------------------------------
def git_push(version: str, dry_run: bool) -> None:
    print("\n[GIT] Commit + push…")
    if dry_run:
        print(f"  (dry-run) git add -A && git commit -m 'release v{version}' && git push")
        return
    subprocess.run(["git", "add", "-A"], cwd=ROOT, check=True)
    # Si rien à commiter, on saute
    diff = subprocess.run(["git", "diff", "--cached", "--quiet"], cwd=ROOT)
    if diff.returncode == 0:
        print("  (rien de neuf à committer)")
    else:
        subprocess.run(["git", "commit", "-m", f"release v{version}"], cwd=ROOT, check=True)
        print(f"  ✓ Commit : release v{version}")
    subprocess.run(["git", "push"], cwd=ROOT, check=True)
    print("  ✓ Push origin main")


# ---------------------------------------------------------------------------
# Release GitHub
# ---------------------------------------------------------------------------
def load_gh_token() -> str:
    cfg = json.loads((Path.home() / ".triskell-command" / "settings.json")
                      .read_text(encoding="utf-8"))
    sb = cfg.get("supabase") or {}
    url, anon = sb.get("url", ""), sb.get("anon_key", "")
    auth = json.loads((Path.home() / ".triskell-command" / "auth.json")
                       .read_text(encoding="utf-8"))
    jwt = auth.get("access_token", "")
    req = urllib.request.Request(
        f"{url}/rest/v1/shared_settings?key=eq.phare_config&select=value",
        headers={"apikey": anon, "Authorization": f"Bearer {jwt}"})
    data = json.loads(urllib.request.urlopen(req, timeout=10).read())
    if not data:
        raise SystemExit("phare_config introuvable dans Supabase.")
    token = data[0].get("value", {}).get("github_token", "")
    if not token:
        raise SystemExit("github_token manquant dans phare_config.")
    return token


def get_recent_commits(since_tag: str) -> list[str]:
    """Renvoie la liste des messages de commit depuis le dernier tag."""
    try:
        r = subprocess.run(
            ["git", "log", f"{since_tag}..HEAD", "--pretty=format:%s", "--no-merges"],
            cwd=ROOT, capture_output=True, text=True, encoding="utf-8")
        if r.returncode == 0:
            return [l.strip() for l in r.stdout.splitlines() if l.strip()]
    except Exception:
        pass
    return []


def get_last_tag() -> str:
    try:
        r = subprocess.run(["git", "describe", "--tags", "--abbrev=0"],
                            cwd=ROOT, capture_output=True, text=True, encoding="utf-8")
        if r.returncode == 0:
            return r.stdout.strip()
    except Exception:
        pass
    return ""


def make_release_body(version: str) -> str:
    last_tag = get_last_tag()
    commits = get_recent_commits(last_tag) if last_tag else []
    body = f"## Triskell Command {version}\n\n"
    if commits:
        body += "**Au menu** :\n"
        for c in commits[:25]:
            body += f"- {c}\n"
    else:
        body += "Mise à jour interne.\n"
    body += f"\n*Release auto le {datetime.now().strftime('%d/%m/%Y %H:%M')}*\n"
    return body


def create_github_release(version: str, body: str, dry_run: bool) -> None:
    tag = f"v{version}"
    name = f"Triskell Command {version}"
    print(f"\n[GITHUB] Release {tag}…")
    if dry_run:
        print(f"  (dry-run) POST releases tag={tag} + upload {INSTALLER_OUT.name}")
        print(f"  body preview:\n{body[:300]}…")
        return
    if not INSTALLER_OUT.exists():
        raise SystemExit(f"Installer absent : {INSTALLER_OUT}")
    gh = load_gh_token()

    # 1. Crée la release
    req = urllib.request.Request(
        f"https://api.github.com/repos/{OWNER}/{REPO}/releases",
        method="POST",
        headers={"Authorization": f"token {gh}",
                 "Accept": "application/vnd.github+json",
                 "Content-Type": "application/json"},
        data=json.dumps({
            "tag_name": tag, "name": name, "body": body,
            "draft": False, "prerelease": False,
        }).encode("utf-8"))
    try:
        release = json.loads(urllib.request.urlopen(req, timeout=15).read())
    except urllib.error.HTTPError as e:
        raise SystemExit(f"Création release KO HTTP {e.code} : {e.read()[:300].decode()}")
    print(f"  ✓ Release créée : {release['html_url']}")

    # 2. Upload asset
    upload_url = release["upload_url"].replace("{?name,label}", "")
    asset_name = f"TriskellCommand_Setup_{version}.exe"
    data = INSTALLER_OUT.read_bytes()
    req = urllib.request.Request(
        f"{upload_url}?name={asset_name}",
        method="POST",
        headers={"Authorization": f"token {gh}",
                 "Accept": "application/vnd.github+json",
                 "Content-Type": "application/octet-stream"},
        data=data)
    try:
        urllib.request.urlopen(req, timeout=120).read()
        print(f"  ✓ Asset uploadé : {asset_name}")
    except urllib.error.HTTPError as e:
        raise SystemExit(f"Upload asset KO HTTP {e.code} : {e.read()[:300].decode()}")

    return release["html_url"]


# ---------------------------------------------------------------------------
# Notify Thomas via chat 1-à-1
# ---------------------------------------------------------------------------
def notify_thomas(version: str, release_url: str, body: str, dry_run: bool) -> None:
    print(f"\n[CHAT] Message à Thomas…")
    msg = (
        f"🚀 Nouvelle release Triskell Command v{version} dispo.\n\n"
        f"Ouvre l'app, elle va te proposer la mise à jour automatiquement "
        f"au prochain démarrage. Sinon : {release_url}\n\n"
        f"Au menu :\n"
    )
    # Reprend les bullets du body
    for line in body.splitlines():
        if line.startswith("- "):
            msg += line + "\n"
    if dry_run:
        print("  (dry-run) Message Thomas :")
        print("  " + msg.replace("\n", "\n  "))
        return
    try:
        # Ajoute le path racine au sys.path pour importer triskell_command
        sys.path.insert(0, str(ROOT))
        from triskell_command.integrations.messages import send_message
        result = send_message(msg)
        if result:
            print("  ✓ Message envoyé à Thomas")
        else:
            print("  ⚠ Envoi message a renvoyé None — vérifie Triskell Command")
    except Exception as exc:
        print(f"  ⚠ Échec envoi message Thomas (non bloquant) : {exc}")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main() -> None:
    args = sys.argv[1:]
    dry_run = "--dry-run" in args
    no_build = "--no-build" in args
    explicit_version = None
    bump_mode = "minor"
    for a in args:
        if a in ("--dry-run", "--no-build"):
            continue
        if a == "--patch":
            bump_mode = "patch"
        elif a == "--major":
            bump_mode = "major"
        elif a == "--minor":
            bump_mode = "minor"
        elif re.match(r"^\d+\.\d+\.\d+$", a):
            explicit_version = a

    current = get_current_version()
    new_version = explicit_version or bump_version(current, bump_mode)
    print("=" * 60)
    print(f"  Triskell Command — Release {current} → {new_version}")
    print("=" * 60)
    if dry_run:
        print("  (DRY-RUN — rien ne sera modifié)")

    # 1. Bump version
    print("\n[BUMP] Mise à jour des fichiers de version…")
    if not dry_run:
        write_version_to_files(new_version)
    else:
        print(f"  (dry-run) bump {current} → {new_version}")

    # 2. Build
    if not no_build:
        run_pyinstaller(dry_run)
        run_inno_setup(dry_run)
    else:
        print("\n[BUILD] Skippé (--no-build)")

    # 3. Git push
    git_push(new_version, dry_run)

    # 4. GitHub release
    body = make_release_body(new_version)
    release_url = create_github_release(new_version, body, dry_run) or ""

    # 5. Notify Thomas
    notify_thomas(new_version, release_url, body, dry_run)

    print("\n" + "=" * 60)
    print(f"  ✓ Release v{new_version} terminée")
    print("=" * 60)


if __name__ == "__main__":
    main()
