"""Publie une nouvelle release de Triskell Command sur GitHub.

Workflow type pour une v0.X.Y :
    1. Bumpe APP_VERSION_LABEL dans triskell_command/theme.py
       (ex: "v0.4" -> "v0.5")
    2. Bumpe MyAppVersion dans TriskellCommand.iss
       (ex: "0.4.0" -> "0.5.0")
    3. Bumpe version dans pyproject.toml
    4. Rebuild :
        py -m PyInstaller --noconfirm triskell_command.spec
        "C:\\Program Files (x86)\\Inno Setup 6\\ISCC.exe" TriskellCommand.iss
    5. Mets à jour TAG / NAME / BODY ci-dessous
    6. Lance ce script :
        py scripts/publish_release.py

L'app installée chez toi et chez Thomas détectera automatiquement la nouvelle
version au prochain démarrage et proposera l'installation.

Le token GitHub doit être lu depuis Supabase shared_settings.phare_config.
"""
import json
import sys
import urllib.request
import urllib.error
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

# ============== À MODIFIER À CHAQUE NOUVELLE RELEASE ====================
TAG = "v0.4.0"
NAME = "Triskell Command 0.4.0"
BODY = """\
## Triskell Command 0.4.0

Première release publique avec auto-update activé.

**Au menu** :
- Connexion simplifiée par prénom (plus besoin de retaper email + password à chaque fois)
- Module **Le Phare** intégré : agence SEO embarquée pour tous tes sites Triskell
- 8 agents Claude qui auditent, analysent et optimisent en continu
- UI nettoyée : labels en français accessible, plus de jargon technique
- Connexion Supabase avec stockage local sécurisé

**Pré-requis** :
- Windows 10 ou 11
- Une connexion internet pour la première configuration

L'installeur va simplement remplacer la version actuelle. Tes réglages
et ton historique sont conservés.
"""
# ========================================================================

OWNER = "Jordan-Bourillot"
REPO = "triskell-command"

PROJECT_ROOT = Path(__file__).resolve().parent.parent
INSTALLER = PROJECT_ROOT / "Output" / "TriskellCommand_Setup.exe"


def _load_gh_token() -> str:
    """Lit le GitHub PAT depuis Supabase shared_settings.phare_config."""
    cfg_path = Path.home() / ".triskell-command" / "settings.json"
    if not cfg_path.exists():
        raise SystemExit("settings.json introuvable. Lance Triskell Command une fois.")
    cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
    sb = cfg.get("supabase") or {}
    url = sb.get("url") or ""
    anon = sb.get("anon_key") or ""
    if not url or not anon:
        raise SystemExit("Section supabase manquante dans settings.json.")

    auth_path = Path.home() / ".triskell-command" / "auth.json"
    if not auth_path.exists():
        raise SystemExit("auth.json absent. Logge-toi dans Triskell Command d'abord.")
    auth = json.loads(auth_path.read_text(encoding="utf-8"))
    jwt = auth.get("access_token") or ""
    if not jwt:
        raise SystemExit("access_token manquant dans auth.json. Re-logge-toi.")

    req = urllib.request.Request(
        f"{url}/rest/v1/shared_settings?key=eq.phare_config&select=value",
        headers={"apikey": anon, "Authorization": f"Bearer {jwt}"},
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            data = json.loads(r.read())
    except urllib.error.HTTPError as e:
        if e.code == 401:
            raise SystemExit(
                "JWT expiré. Lance Triskell Command pour rafraîchir la session, "
                "puis relance ce script."
            )
        raise
    if not data:
        raise SystemExit("phare_config introuvable dans Supabase.")
    token = data[0].get("value", {}).get("github_token", "")
    if not token:
        raise SystemExit("github_token manquant dans phare_config.")
    return token


def main() -> None:
    if not INSTALLER.exists():
        raise SystemExit(
            f"Installeur introuvable : {INSTALLER}\n"
            "Lance d'abord Inno Setup pour générer Output/TriskellCommand_Setup.exe."
        )
    print(f"Installeur : {INSTALLER.name} "
          f"({INSTALLER.stat().st_size / 1024 / 1024:.1f} MB)")

    gh_token = _load_gh_token()
    print(f"GitHub token chargé ({len(gh_token)} chars)")

    # 1. Crée la release
    print(f"\nCréation release {TAG}...")
    req = urllib.request.Request(
        f"https://api.github.com/repos/{OWNER}/{REPO}/releases",
        method="POST",
        headers={
            "Authorization": f"token {gh_token}",
            "Accept": "application/vnd.github+json",
            "Content-Type": "application/json",
        },
        data=json.dumps({
            "tag_name": TAG,
            "name": NAME,
            "body": BODY,
            "draft": False,
            "prerelease": False,
        }).encode("utf-8"),
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            release = json.loads(r.read())
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace")
        raise SystemExit(f"Création release KO HTTP {e.code} : {body[:500]}")
    print(f"  ✓ Release créée : {release['html_url']}")

    # 2. Upload de l'asset
    upload_url = release["upload_url"].replace("{?name,label}", "")
    asset_name = f"TriskellCommand_Setup_{TAG.lstrip('v')}.exe"
    print(f"\nUpload de l'installeur ({asset_name})...")
    data = INSTALLER.read_bytes()
    req = urllib.request.Request(
        f"{upload_url}?name={asset_name}",
        method="POST",
        headers={
            "Authorization": f"token {gh_token}",
            "Accept": "application/vnd.github+json",
            "Content-Type": "application/octet-stream",
        },
        data=data,
    )
    try:
        with urllib.request.urlopen(req, timeout=180) as r:
            asset = json.loads(r.read())
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace")
        raise SystemExit(f"Upload KO HTTP {e.code} : {body[:500]}")

    print(f"  ✓ Asset uploadé : {asset['browser_download_url']}")
    print(f"  ✓ Taille : {asset['size'] / 1024 / 1024:.1f} MB")
    print(f"\nRelease URL : {release['html_url']}")
    print("\nL'auto-update est armé : toi et Thomas verrez la mise à jour "
          "au prochain démarrage de l'app.")


if __name__ == "__main__":
    main()
