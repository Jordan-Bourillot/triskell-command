"""Studio — création de site à partir d'un sujet libre.

Workflow :
  1. L'utilisateur tape un sujet, choisit type + template + nb photos + nb vidéos.
  2. À la soumission, le studio :
       - crée un dossier de brief `C:\\Users\\jorda\\Triskell\\_briefs\\<slug>\\`
       - écrit `brief.md` + `prompt-claude-code.txt`
       - copie le prompt dans le presse-papier
       - lance gallery-dl en arrière-plan sur les 3 plateformes (handle = slug)
       - **ouvre Windows Terminal dans le dossier site avec Claude Code prêt**
         et le prompt déjà copié → un Ctrl+V suffit pour lancer la pipeline.

Pas de pipeline 100 % auto dans cette version : Claude Code prend le relais
à partir du prompt. Voir la doc dans le brief.md pour les options Agent SDK.
"""

from __future__ import annotations

import datetime as _dt
import logging
import os
import re
import subprocess
import threading
import unicodedata
from pathlib import Path

import customtkinter as ctk

from .. import theme as T
from ..services import site_agent
from .base import BaseView

logger = logging.getLogger("triskell.command.studio")

# === Constantes chemins ===
BRIEFS_ROOT = Path(r"C:\Users\jorda\Triskell\_briefs")
GALLERY_DL = Path(
    r"C:\Users\jorda\Triskell\_SESSION_PC_SECONDAIRE_2026-05-11\instagram-downloader\.venv\Scripts\gallery-dl.exe"
)
IG_COOKIES = Path(os.environ.get("APPDATA", "")) / "InstagramDownloader" / "instagram_cookies.txt"
DOWNLOADS_ROOT = Path(r"C:\Users\jorda\Desktop\Telechargements_Reseaux")

# === Templates disponibles ===
TEMPLATES = [
    {
        "id": "template-sportif-editorial",
        "label": "Magazine éditorial (Playfair)",
        "desc": "Sérif élégant, header horizontal, photos en fonds discrets, grain papier. Idéal sportif, personnalité, contenu long.",
        "path": r"C:\Users\jorda\Triskell\template-sportif-editorial",
    },
    {
        "id": "template-sportif",
        "label": "Cinéma sidebar (Bebas Neue)",
        "desc": "Sidebar verticale, hero plein écran avec slideshow, gros titres bâton. Idéal sportif de combat, marque urbaine.",
        "path": r"C:\Users\jorda\Triskell\template-sportif",
    },
]

# Heuristique type → template par défaut
TYPE_TO_TEMPLATE = {
    "Sportif (combat)": "template-sportif",
    "Sportif (raquette / collectif)": "template-sportif-editorial",
    "Personnalité publique": "template-sportif-editorial",
    "Entreprise": "template-sportif-editorial",
    "Association": "template-sportif-editorial",
}

SUBJECT_TYPES = list(TYPE_TO_TEMPLATE.keys())


def _slugify(text: str) -> str:
    """`Loïs Boisson` → `lois-boisson`."""
    nfkd = unicodedata.normalize("NFKD", text)
    ascii_text = "".join(c for c in nfkd if not unicodedata.combining(c))
    slug = re.sub(r"[^a-zA-Z0-9]+", "-", ascii_text).strip("-").lower()
    return slug or "nouveau-projet"


def _handle_guess(text: str) -> str:
    """Devine un handle social compact à partir du nom : `Loïs Boisson` → `loisboisson`."""
    nfkd = unicodedata.normalize("NFKD", text)
    ascii_text = "".join(c for c in nfkd if not unicodedata.combining(c))
    return re.sub(r"[^a-zA-Z0-9]+", "", ascii_text).lower()


def _build_prompt(
    *,
    subject: str,
    subject_type: str,
    template: dict,
    max_photos: int,
    max_videos: int,
    site_dir: str,
    briefs_dir: str,
    handle: str,
) -> str:
    """Compose le prompt à coller dans Claude Code."""
    return f"""Crée un site **{subject_type}** pour **{subject}** à partir du template `{template['id']}`.

## Brief

- Sujet : **{subject}**
- Type : {subject_type}
- Template de départ : `{template['id']}` ({template['label']})
- Dossier cible : `{site_dir}`
- Brief : `{briefs_dir}`
- Médias maximum à intégrer : **{max_photos} photos** + **{max_videos} vidéos** (dissociés)

## Étapes attendues

1. **Copier** `{template['path']}` vers `{site_dir}` (exclure `node_modules`, `dist`, `.astro`, `.netlify`).
2. **Rechercher** sur le web et dans Wikipedia tout ce qui est utile sur {subject} : bio, parcours, palmarès / réalisations, citations marquantes, partenaires, dates clés. Source à chaque affirmation.
3. **Identifier les comptes sociaux** réels de {subject} (handle Instagram / TikTok / X) — le studio a déjà tenté le téléchargement avec `{handle}` comme handle par défaut. Vérifier dans `{DOWNLOADS_ROOT}\\Instagram_{handle}\\` et corriger si le compte est différent.
4. **Identifier** une palette qui colle à {subject} (couleur signature, ambiance). Modifier `src/styles/global.css` (3 thèmes : clair, intermédiaire, sombre).
5. **Réécrire** `src/data/profile.ts` avec les vraies données vérifiées.
6. **Adapter** les pages : `index.astro` (hero, édito, épisodes, citation, chiffres, finale), `parcours.astro` (timeline), `combats.astro` (palmarès — ou renommer selon discipline), `le-code.astro` (5 signatures), `media-kit.astro` (bio courte / longue), `contact.astro`, `sponsors.astro`, `videos.astro`, `galerie.astro`, `mentions-legales.astro` (Triskell Studio pré-rempli), `404.astro`.
7. **Adapter** `Header.astro` (monogramme 2 lettres), `Base.astro` (canonical, sameAs, JSON-LD), `astro.config.mjs`, `public/robots.txt`, `src/pages/sitemap.xml.ts`.
8. **Sélectionner les médias** : trier les fichiers téléchargés par taille décroissante, garder les **{max_photos} meilleures photos** + **{max_videos} meilleures vidéos**, copier vers `public/photos/photo-1.jpg…` et `public/videos/video-1.mp4…`. Remplacer tous les `placeholder.svg` par les vraies photos.
9. **Builder** et lancer un dev server pour relire avec moi.
10. **Vérifier** zéro référence aux placeholders génériques restants (« Prénom Nom », « Le Surnom », `@compte_instagram`, `exemple.fr`, `XX`).
11. **Apporter ta touche** : palette / animations / petits détails qui rendent le site unique à {subject}.

## À éviter

- Aucun élément mocké présenté comme réel (chiffres d'audience inventés, témoignages fictifs).
- Pas de YouTube si la chaîne n'est pas confirmée.
- Pas de domaine .com inventé — utiliser `{_slugify(subject)}.fr` comme placeholder, à confirmer.

Commence par la copie du template puis la recherche d'infos sur {subject}. Quand tu as un premier draft, fais-moi un point.
"""


def _build_brief_md(**ctx) -> str:
    """Compose le fichier brief.md (humain-lisible + checklist)."""
    return f"""# Brief — {ctx['subject']}

| Champ | Valeur |
|---|---|
| Sujet | **{ctx['subject']}** |
| Slug | `{ctx['slug']}` |
| Type | {ctx['subject_type']} |
| Template | `{ctx['template']['id']}` — {ctx['template']['label']} |
| Photos max | {ctx['max_photos']} |
| Vidéos max | {ctx['max_videos']} |
| Brief créé le | {ctx['now']} |
| Dossier site | `{ctx['site_dir']}` |
| Téléchargements | `{ctx['downloads_dir']}` |
| Handle deviné | `{ctx['handle']}` (à vérifier) |

## Prompt prêt à coller dans Claude Code

```
{ctx['prompt']}
```

## Commandes utiles

```powershell
# Relancer un téléchargement Instagram (cookies dans %APPDATA%\\InstagramDownloader)
& "{GALLERY_DL}" --cookies "{IG_COOKIES}" -d "{ctx['downloads_dir']}" "https://www.instagram.com/{ctx['handle']}/"

# Copier le template puis lancer Claude Code dans le dossier
robocopy "{ctx['template']['path']}" "{ctx['site_dir']}" /E /XD node_modules dist .astro .vercel .netlify
```
"""


class StudioView(BaseView):
    """Studio : créer un site à partir d'un sujet libre."""

    title = "Studio"
    subtitle = "Créer un nouveau site à partir d'un sujet"

    def build(self) -> None:
        c = self.colors
        self.configure(fg_color=c.bg)

        scroll = ctk.CTkScrollableFrame(self, fg_color="transparent", corner_radius=0)
        scroll.pack(fill="both", expand=True, padx=T.SPACE_XL, pady=T.SPACE_XL)
        scroll.grid_columnconfigure(0, weight=1)

        # === Header ===
        ctk.CTkLabel(
            scroll, text="STUDIO · NOUVEAU SITE",
            font=(T.FONT_FAMILY_FALLBACK, T.FONT_SIZE_TINY, "bold"),
            text_color=c.accent, anchor="w",
        ).pack(fill="x", pady=(0, 4))
        ctk.CTkLabel(
            scroll, text="Crée un site complet à partir d'un sujet",
            font=(T.FONT_FAMILY_DISPLAY, 28, "bold"),
            text_color=c.text_primary, anchor="w",
        ).pack(fill="x", pady=(0, 4))
        ctk.CTkLabel(
            scroll,
            text=(
                "Tape un sujet (personne, entreprise, association). Le studio devine les "
                "comptes sociaux, lance les téléchargements en arrière-plan, ouvre Claude "
                "Code dans le dossier du brief et te donne le prompt prêt à coller."
            ),
            font=(T.FONT_FAMILY_FALLBACK, T.FONT_SIZE_BODY),
            text_color=c.text_muted, anchor="w", justify="left",
            wraplength=820,
        ).pack(fill="x", pady=(0, T.SPACE_XL))

        # === Sujet ===
        self._add_label(scroll, "1 · Sujet du site")
        self._subject = ctk.CTkEntry(
            scroll, placeholder_text="ex : Loïs Boisson · Saladine Parnasse · Studio Wallace …",
            height=44, font=(T.FONT_FAMILY_FALLBACK, T.FONT_SIZE_BODY),
        )
        self._subject.pack(fill="x", pady=(0, T.SPACE_LG))

        # === Type ===
        self._add_label(scroll, "2 · Type")
        self._subject_type = ctk.CTkOptionMenu(
            scroll, values=SUBJECT_TYPES, height=40,
            command=self._on_type_change,
        )
        self._subject_type.set(SUBJECT_TYPES[0])
        self._subject_type.pack(fill="x", pady=(0, T.SPACE_LG))

        # === Template ===
        self._add_label(scroll, "3 · Template de départ")
        self._template_choice = ctk.CTkOptionMenu(
            scroll,
            values=[t["label"] for t in TEMPLATES],
            height=40,
        )
        default_tpl_id = TYPE_TO_TEMPLATE[SUBJECT_TYPES[0]]
        default_tpl = next(t for t in TEMPLATES if t["id"] == default_tpl_id)
        self._template_choice.set(default_tpl["label"])
        self._template_choice.pack(fill="x", pady=(0, T.SPACE_SM))
        self._template_desc = ctk.CTkLabel(
            scroll, text=default_tpl["desc"],
            font=(T.FONT_FAMILY_FALLBACK, T.FONT_SIZE_TINY, "italic"),
            text_color=c.text_muted, anchor="w", justify="left", wraplength=820,
        )
        self._template_desc.pack(fill="x", pady=(0, T.SPACE_LG))
        self._template_choice.configure(command=self._on_template_change)

        # === Médias : photos + vidéos dissociés ===
        self._add_label(scroll, "4 · Médias à intégrer")
        media_grid = ctk.CTkFrame(scroll, fg_color="transparent")
        media_grid.pack(fill="x", pady=(0, T.SPACE_LG))
        media_grid.grid_columnconfigure(0, weight=1)
        media_grid.grid_columnconfigure(1, weight=1)

        # Photos
        self._max_photos = ctk.IntVar(value=50)
        photo_card = self._media_card(media_grid, "Photos", "📷", self._max_photos, 5, 200, 50)
        photo_card.grid(row=0, column=0, sticky="ew", padx=(0, T.SPACE_SM))

        # Vidéos
        self._max_videos = ctk.IntVar(value=10)
        video_card = self._media_card(media_grid, "Vidéos", "▶", self._max_videos, 0, 50, 10)
        video_card.grid(row=0, column=1, sticky="ew", padx=(T.SPACE_SM, 0))

        # === Mode d'exécution ===
        self._add_label(scroll, "5 · Mode d'exécution")
        mode_card = ctk.CTkFrame(scroll, fg_color=c.panel, corner_radius=10,
                                  border_width=1, border_color=c.border)
        mode_card.pack(fill="x", pady=(0, T.SPACE_LG))
        agent_ok = site_agent.is_available()

        # Segmented control : 2 modes
        self._mode = ctk.StringVar(value="terminal" if not agent_ok else "agent")
        mode_seg = ctk.CTkSegmentedButton(
            mode_card,
            values=["Terminal (Ctrl+V)", "Agent (auto)"],
            command=lambda v: self._mode.set("agent" if v.startswith("Agent") else "terminal"),
            height=40,
        )
        mode_seg.set("Agent (auto)" if self._mode.get() == "agent" else "Terminal (Ctrl+V)")
        if not agent_ok:
            # Désactive l'option Agent si SDK absent
            mode_seg.configure(state="disabled")
        mode_seg.pack(fill="x", padx=T.SPACE_MD, pady=(T.SPACE_MD, T.SPACE_SM))

        mode_help = ctk.CTkLabel(
            mode_card,
            text=(
                "Terminal : ouvre Claude Code dans Windows Terminal, prompt déjà copié — "
                "1 Ctrl+V et la pipeline démarre. Coût : inclus dans l'abonnement Claude.\n"
                "Agent : exécute la pipeline directement depuis Triskell Command, log temps "
                "réel ci-dessous. Coût : abonnement Claude (binaire local) ou clé API."
            ) if agent_ok else (
                "claude-agent-sdk non installé. Pour activer le mode Agent : "
                "pip install claude-agent-sdk"
            ),
            font=(T.FONT_FAMILY_FALLBACK, T.FONT_SIZE_TINY, "italic"),
            text_color=c.text_muted, anchor="w", justify="left", wraplength=820,
        )
        mode_help.pack(fill="x", padx=T.SPACE_MD, pady=(0, T.SPACE_MD))

        # === Action ===
        self._primary_btn = ctk.CTkButton(
            scroll, text="✦   Lancer la séquence",
            height=52, corner_radius=10,
            fg_color=c.accent, hover_color=c.accent_hover,
            font=(T.FONT_FAMILY_FALLBACK, T.FONT_SIZE_BODY + 1, "bold"),
            command=self._on_submit,
        )
        self._primary_btn.pack(fill="x", pady=(T.SPACE_LG, T.SPACE_MD))

        # === Zone de log ===
        self._log = ctk.CTkTextbox(
            scroll, height=240, corner_radius=8,
            font=("Consolas", 12), text_color=c.text_primary,
            fg_color=c.panel, border_width=1, border_color=c.border,
        )
        self._log.pack(fill="both", expand=True, pady=(T.SPACE_MD, 0))
        self._log.insert("end", "Prêt. Renseigne un sujet et clique sur « Lancer la séquence ».\n")
        self._log.configure(state="disabled")

    # ------------------------------------------------------------------
    # Helpers UI
    # ------------------------------------------------------------------
    def _add_label(self, parent, text: str) -> None:
        ctk.CTkLabel(
            parent, text=text,
            font=(T.FONT_FAMILY_FALLBACK, T.FONT_SIZE_BODY, "bold"),
            text_color=self.colors.text_primary, anchor="w",
        ).pack(fill="x", pady=(0, T.SPACE_SM))

    def _media_card(
        self, parent, label: str, icon: str, var: ctk.IntVar,
        min_val: int, max_val: int, default: int,
    ) -> ctk.CTkFrame:
        c = self.colors
        card = ctk.CTkFrame(parent, fg_color=c.panel, corner_radius=10,
                            border_width=1, border_color=c.border)
        # Header
        header = ctk.CTkFrame(card, fg_color="transparent")
        header.pack(fill="x", padx=T.SPACE_MD, pady=(T.SPACE_MD, 0))
        ctk.CTkLabel(
            header, text=f"{icon}  {label}",
            font=(T.FONT_FAMILY_FALLBACK, T.FONT_SIZE_BODY, "bold"),
            text_color=c.text_primary, anchor="w",
        ).pack(side="left")
        value_label = ctk.CTkLabel(
            header, text=str(default),
            font=(T.FONT_FAMILY_DISPLAY, 22, "bold"),
            text_color=c.accent,
        )
        value_label.pack(side="right")
        # Slider
        steps = max_val - min_val
        slider = ctk.CTkSlider(
            card, from_=min_val, to=max_val,
            number_of_steps=max(steps, 1),
            variable=var,
            command=lambda _v, lbl=value_label, v=var: lbl.configure(text=str(v.get())),
        )
        slider.pack(fill="x", padx=T.SPACE_MD, pady=(T.SPACE_SM, T.SPACE_MD))
        return card

    def _log_msg(self, msg: str) -> None:
        self._log.configure(state="normal")
        self._log.insert("end", msg + "\n")
        self._log.see("end")
        self._log.configure(state="disabled")
        self.update_idletasks()

    def _on_type_change(self, choice: str) -> None:
        tpl_id = TYPE_TO_TEMPLATE.get(choice)
        if not tpl_id:
            return
        tpl = next((t for t in TEMPLATES if t["id"] == tpl_id), None)
        if tpl:
            self._template_choice.set(tpl["label"])
            self._template_desc.configure(text=tpl["desc"])

    def _on_template_change(self, choice: str) -> None:
        tpl = next((t for t in TEMPLATES if t["label"] == choice), None)
        if tpl:
            self._template_desc.configure(text=tpl["desc"])

    def _selected_template(self) -> dict:
        label = self._template_choice.get()
        return next(t for t in TEMPLATES if t["label"] == label)

    # ------------------------------------------------------------------
    # Soumission
    # ------------------------------------------------------------------
    def _on_submit(self) -> None:
        subject = self._subject.get().strip()
        if not subject:
            self._log_msg("⚠ Renseigne d'abord un sujet.")
            return

        subject_type = self._subject_type.get()
        template = self._selected_template()
        max_photos = int(self._max_photos.get())
        max_videos = int(self._max_videos.get())
        slug = _slugify(subject)
        handle = _handle_guess(subject)
        now = _dt.datetime.now().strftime("%Y-%m-%d %H:%M")

        # Préparer chemins
        BRIEFS_ROOT.mkdir(parents=True, exist_ok=True)
        briefs_dir = BRIEFS_ROOT / slug
        briefs_dir.mkdir(parents=True, exist_ok=True)
        site_dir = Path(r"C:\Users\jorda\Triskell") / f"{slug}-site"
        downloads_dir = DOWNLOADS_ROOT / f"Instagram_{handle}"

        ctx = {
            "subject": subject,
            "slug": slug,
            "subject_type": subject_type,
            "template": template,
            "max_photos": max_photos,
            "max_videos": max_videos,
            "now": now,
            "site_dir": str(site_dir),
            "downloads_dir": str(downloads_dir),
            "handle": handle,
        }
        prompt = _build_prompt(
            subject=subject, subject_type=subject_type, template=template,
            max_photos=max_photos, max_videos=max_videos,
            site_dir=str(site_dir), briefs_dir=str(briefs_dir),
            handle=handle,
        )
        ctx["prompt"] = prompt

        # Écrire brief.md + prompt.txt
        brief_path = briefs_dir / "brief.md"
        brief_path.write_text(_build_brief_md(**ctx), encoding="utf-8")
        prompt_path = briefs_dir / "prompt-claude-code.txt"
        prompt_path.write_text(prompt, encoding="utf-8")
        self._log_msg(f"✔ Brief : {brief_path}")
        self._log_msg(f"✔ Prompt : {prompt_path}")

        # Copier prompt dans le presse-papier
        try:
            self.clipboard_clear()
            self.clipboard_append(prompt)
            self.update()
            self._log_msg("✔ Prompt copié dans le presse-papier.")
        except Exception as exc:
            self._log_msg(f"⚠ Copie presse-papier échouée : {exc}")

        # Lancer les téléchargements automatiquement (handle = slug deviné)
        self._launch_downloads(handle, downloads_dir)

        # Router selon le mode choisi
        if self._mode.get() == "agent":
            self._launch_agent_pipeline(prompt, briefs_dir)
        else:
            self._launch_claude_code(briefs_dir)
            self._log_msg("\n— Terminal Claude Code ouvert. Colle le prompt (Ctrl+V) et Entrée.")

    # ------------------------------------------------------------------
    # Téléchargements en background
    # ------------------------------------------------------------------
    def _launch_downloads(self, handle: str, downloads_dir: Path) -> None:
        if not GALLERY_DL.exists():
            self._log_msg(f"⚠ gallery-dl introuvable à {GALLERY_DL}. Skip.")
            return
        downloads_dir.mkdir(parents=True, exist_ok=True)

        urls = [
            ("Instagram", f"https://www.instagram.com/{handle}/", IG_COOKIES),
            ("TikTok",    f"https://www.tiktok.com/@{handle}", None),
            ("X",         f"https://x.com/{handle}", None),
        ]
        for platform, url, cookies in urls:
            self._log_msg(f"⏳ {platform} → {url}")
            thread = threading.Thread(
                target=self._run_gallery_dl,
                args=(platform, url, cookies, downloads_dir),
                daemon=True,
            )
            thread.start()

    def _run_gallery_dl(self, platform: str, url: str, cookies: Path | None, out: Path) -> None:
        cmd = [str(GALLERY_DL), "-d", str(out)]
        if cookies and cookies.exists():
            cmd += ["--cookies", str(cookies)]
        cmd.append(url)
        try:
            res = subprocess.run(
                cmd, capture_output=True, text=True, encoding="utf-8", errors="replace",
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
            if res.returncode == 0:
                self.after(0, lambda: self._log_msg(f"✔ {platform} terminé."))
            else:
                self.after(0, lambda: self._log_msg(
                    f"⚠ {platform} exit {res.returncode} — peut-être handle incorrect."
                ))
        except Exception as exc:
            self.after(0, lambda: self._log_msg(f"⚠ {platform} échec : {exc}"))

    # ------------------------------------------------------------------
    # Pipeline Agent SDK
    # ------------------------------------------------------------------
    def _launch_agent_pipeline(self, prompt: str, cwd: Path) -> None:
        """Lance la pipeline via claude-agent-sdk dans un thread daemon.

        Tous les logs remontent en temps réel dans la zone log via `after(0, …)`
        pour rester thread-safe avec Tk.
        """
        self._log_msg("\n— Lancement de l'Agent (claude-agent-sdk) —")
        self._primary_btn.configure(state="disabled", text="Pipeline en cours…")

        def safe_log(line: str) -> None:
            # Trampoline thread → main loop Tk
            self.after(0, lambda l=line: self._log_msg(l))

        def on_done(success: bool, error: str | None) -> None:
            def _finish():
                if success:
                    self._log_msg("\n✓ Pipeline terminée. Vérifie le dossier site puis builde.")
                else:
                    self._log_msg(f"\n✗ Pipeline échouée : {error or '(inconnu)'}")
                self._primary_btn.configure(
                    state="normal", text="✦   Lancer la séquence",
                )
            self.after(0, _finish)

        site_agent.run_in_background(prompt, cwd, safe_log, on_done)

    # ------------------------------------------------------------------
    # Lancer Claude Code dans Windows Terminal (mode manuel)
    # ------------------------------------------------------------------
    def _launch_claude_code(self, cwd: Path) -> None:
        """Ouvre Windows Terminal dans le dossier du brief avec Claude Code lancé.

        Le prompt est déjà dans le presse-papier → un Ctrl+V dans le terminal
        suffit pour démarrer la pipeline.
        """
        candidates = [
            ["wt.exe", "-d", str(cwd), "powershell", "-NoExit", "-Command", "claude"],
            ["cmd.exe", "/c", "start", "powershell", "-NoExit", "-Command",
             f"cd '{cwd}'; claude"],
        ]
        for cmd in candidates:
            try:
                subprocess.Popen(
                    cmd,
                    creationflags=getattr(subprocess, "CREATE_NEW_CONSOLE", 0),
                )
                self._log_msg(f"✔ Claude Code lancé dans {cwd.name}")
                return
            except FileNotFoundError:
                continue
            except Exception as exc:
                self._log_msg(f"⚠ Lancement {cmd[0]} échec : {exc}")

        # Fallback : ouvre juste l'explorateur sur le dossier
        try:
            os.startfile(str(cwd))  # type: ignore[attr-defined]
            self._log_msg(f"ℹ Dossier ouvert dans l'explorateur : {cwd}")
        except Exception:
            pass
