"""Audit personnalisé Porte-Voix.

Pour un prospect (entreprise, métier, ville) : pose les questions
d'intention d'achat aux IA web, mesure qui est cité, classe le résultat
en trois issues (concurrents cités / place vide / déjà cité) et produit
la page HTML personnalisée jointe au premier mail de prospection.

Chaque page affiche la méthode (passages, formulations, dates) et la
mention de variabilité. Jamais de promesse de citation.
"""
from __future__ import annotations

import html
import json
import logging
import re
import secrets
import unicodedata
from datetime import datetime, timezone
from pathlib import Path

from . import moteur

logger = logging.getLogger(__name__)

# Trois formulations par segment : la variété des tournures fait partie
# de la méthode (une seule tournure = mesure fragile).
QUESTIONS_PAR_METIER = {
    "courtier": [
        "vers quel courtier en assurance se tourner à {ville} ?",
        "quel est le meilleur courtier à {ville} pour un particulier ?",
        "je cherche un courtier de confiance à {ville}, lequel choisir ?",
    ],
    "expert-comptable": [
        "quel expert-comptable choisir pour une petite entreprise à {ville} ?",
        "quel est le meilleur cabinet comptable à {ville} pour une TPE ?",
        "je monte ma société à {ville}, quel expert-comptable prendre ?",
    ],
    "immobilier": [
        "quelle agence immobilière pour vendre un bien à {ville} ?",
        "quelle est la meilleure agence immobilière à {ville} ?",
        "à quelle agence confier la vente de ma maison à {ville} ?",
    ],
    "avocat": [
        "quel avocat consulter à {ville} ?",
        "quel est le meilleur cabinet d'avocats à {ville} ?",
        "je cherche un bon avocat à {ville}, lequel choisir ?",
    ],
}
QUESTIONS_GENERIQUES = [
    "quel {metier} choisir à {ville} ?",
    "quel est le meilleur {metier} à {ville} ?",
    "je cherche un {metier} sérieux à {ville}, lequel choisir ?",
]

# Seuil (en % de part de voix) au-dessus duquel on considère qu'un nom
# « occupe » vraiment les réponses.
SEUIL_PRESENCE = 15.0


def _cle_metier(metier: str) -> str:
    m = moteur.normaliser(metier)
    if "courtier" in m or "assurance" in m or "credit" in m:
        return "courtier"
    if "comptable" in m or "expertise" in m:
        return "expert-comptable"
    if "immobili" in m:
        return "immobilier"
    if "avocat" in m or "juridique" in m:
        return "avocat"
    return ""


def questions_pour(metier: str, ville: str) -> list[str]:
    cle = _cle_metier(metier)
    if cle:
        gabarits = QUESTIONS_PAR_METIER[cle]
        return [g.format(ville=ville) for g in gabarits]
    return [g.format(metier=metier.lower(), ville=ville)
            for g in QUESTIONS_GENERIQUES]


def classer(part_prospect: float, agregat: list[dict],
            entreprise: str) -> str:
    """Issue de l'audit : 'deja_cite', 'concurrents' ou 'vide'."""
    concurrents = [g for g in agregat
                   if not moteur.correspond(entreprise, g["nom"])]
    meilleur_concurrent = max((g["part"] for g in concurrents), default=0.0)
    if part_prospect >= SEUIL_PRESENCE:
        return "deja_cite"
    if meilleur_concurrent >= SEUIL_PRESENCE:
        return "concurrents"
    return "vide"


def generer_audit(entreprise: str, metier: str, ville: str,
                  passes: int = 3, cles: dict | None = None,
                  mesure: dict | None = None) -> dict:
    """Mesure + classement + matière pour la page. `mesure` peut être
    fournie (tests, rejeu) pour éviter les appels réseau."""
    cles = cles if cles is not None else moteur.recuperer_cles()
    questions = questions_pour(metier, ville)
    if mesure is None:
        mesure = moteur.mesurer(questions, passes=passes, cles=cles)
    agregat = moteur.agreger(mesure)
    part_prospect = moteur.part_de(entreprise, agregat)
    issue = classer(part_prospect, agregat, entreprise)
    concurrents = [g for g in agregat
                   if not moteur.correspond(entreprise, g["nom"])][:3]
    extraits = _choisir_extraits(mesure, entreprise, concurrents)
    # Les IA réellement interrogées avec succès : la page n'affiche que
    # ce qui a vraiment été mesuré (règle d'honnêteté).
    etiquettes = {"openai": "ChatGPT", "perplexity": "Perplexity",
                  "google": "Gemini"}
    presents = {r.get("provider") for r in (mesure.get("runs") or [])
                if r.get("ok")}
    ias = [etiquettes[p] for p in ("openai", "perplexity", "google")
           if p in presents]
    return {
        "entreprise": entreprise,
        "metier": metier,
        "ville": ville,
        "questions": questions,
        "nb_reponses": mesure.get("nb_reponses", 0),
        "nb_passes": passes,
        "ts": mesure.get("ts") or datetime.now(timezone.utc).isoformat(),
        "part_prospect": part_prospect,
        "concurrents": concurrents,
        "issue": issue,
        "extraits": extraits,
        "ias": ias,
    }


def _choisir_extraits(mesure: dict, entreprise: str,
                      concurrents: list[dict]) -> list[dict]:
    """2-3 extraits de réponses réelles, priorité à celles qui citent un
    concurrent (c'est la preuve qui fait mal), sinon les plus parlantes."""
    runs_ok = [r for r in (mesure.get("runs") or []) if r.get("ok")]
    noms_concurrents = [c["nom"] for c in concurrents]

    def cite_concurrent(run):
        return any(moteur.correspond(n, c) for n in (run.get("cites") or [])
                   for c in noms_concurrents)

    choisis = [r for r in runs_ok if cite_concurrent(r)][:2]
    for r in runs_ok:
        if len(choisis) >= 3:
            break
        if r not in choisis:
            choisis.append(r)
    etiquettes = {"openai": "ChatGPT", "perplexity": "Perplexity",
                  "google": "Gemini"}
    extraits = []
    for r in choisis[:3]:
        texte = (r.get("reponse") or "").strip()
        texte = re.sub(r"\s+", " ", texte)
        if len(texte) > 420:
            texte = texte[:420].rsplit(" ", 1)[0] + "…"
        extraits.append({
            "ia": etiquettes.get(r.get("provider"), r.get("provider", "IA")),
            "question": r.get("question", ""),
            "texte": texte,
        })
    return extraits


# ------------------------------------------------------------- la page

_TITRES = {
    "concurrents": "Vos concurrents sont dans les réponses. Pas vous.",
    "vide": "Personne n'a encore pris la place. Elle est libre.",
    "deja_cite": "Vous êtes cité. Cette position se défend.",
}
_LECTURES = {
    "concurrents": ("Quand un futur client pose ces questions, les noms "
                    "ci-dessous lui sont proposés. Le vôtre n'y figure pas, "
                    "ou trop rarement pour compter. Ce client contacte "
                    "quelqu'un d'autre, sans jamais avoir su que vous "
                    "existiez."),
    "vide": ("Aucun professionnel local n'occupe encore ces réponses. Les "
             "IA citent ceux dont elles trouvent des traces solides en "
             "ligne, et le premier qui fait ce travail sérieusement prendra "
             "la place. Aujourd'hui, elle ne coûte pas cher. Ça ne durera "
             "pas."),
    "deja_cite": ("Votre nom apparaît dans une partie des réponses, c'est "
                  "une vraie position, et elle n'est pas acquise. Les "
                  "réponses des IA bougent au fil de ce qu'elles trouvent, "
                  "et vos concurrents finiront par s'intéresser au sujet."),
}


def rendre_html(audit: dict) -> str:
    """La page d'audit, autonome (styles inclus), même famille visuelle
    que lapartdevoix.fr."""
    e = html.escape
    entreprise = e(audit["entreprise"])
    ville = e(audit["ville"])
    date_txt = (audit.get("ts") or "")[:10]
    barres = []
    for c in audit.get("concurrents") or []:
        largeur = max(1.0, min(100.0, float(c["part"])))
        barres.append(
            f'<div class="barre"><div class="ligne"><span>{e(c["nom"])}'
            f'</span><span>{c["part"]:g}&nbsp;%</span></div>'
            f'<div class="fond"><div class="plein" style="width:{largeur}%">'
            f'</div></div></div>'
        )
    part_p = float(audit.get("part_prospect") or 0.0)
    largeur_p = max(0.5, min(100.0, part_p))
    barres.append(
        f'<div class="barre vous"><div class="ligne"><span>{entreprise}'
        f'</span><span>{part_p:g}&nbsp;%</span></div>'
        f'<div class="fond"><div class="plein" style="width:{largeur_p}%">'
        f'</div></div></div>'
    )
    extraits_html = ""
    for x in audit.get("extraits") or []:
        # Nettoyage d'affichage : les IA répondent en mise en forme brute
        # (gras **, liens [texte](url)) qui ferait sale dans une citation.
        brut = x.get("texte") or ""
        brut = re.sub(r"\[([^\]]+)\]\([^)]*\)", r"\1", brut)
        brut = brut.replace("**", "").replace("__", "").replace("##", "")
        x = dict(x, texte=re.sub(r"\s+", " ", brut).strip())
        extraits_html += (
            f'<div class="extrait"><div class="qui">{e(x["ia"])}, à la '
            f'question « {e(x["question"])} »</div>'
            f'<blockquote>{e(x["texte"])}</blockquote></div>'
        )
    questions_html = "".join(
        f"<li>« {e(q)} »</li>" for q in audit.get("questions") or [])
    ias = audit.get("ias") or ["ChatGPT", "Gemini"]
    ias_txt = (ias[0] if len(ias) == 1
               else ", ".join(ias[:-1]) + " et " + ias[-1])
    titre = _TITRES.get(audit.get("issue"), _TITRES["concurrents"])
    lecture = _LECTURES.get(audit.get("issue"), _LECTURES["concurrents"])
    return f"""<!DOCTYPE html>
<html lang="fr">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<meta name="robots" content="noindex">
<title>Audit de part de voix. {entreprise}, {ville}.</title>
<style>
  *, *::before, *::after {{ margin:0; padding:0; box-sizing:border-box; }}
  html, body {{ overflow-x:hidden; }}
  body {{
    background:
      radial-gradient(1100px 560px at 85% -8%, rgba(74,222,128,0.09), transparent 60%),
      radial-gradient(900px 520px at 0% 6%, rgba(76,110,245,0.12), transparent 55%),
      #131c39;
    color:#e9edf9;
    font-family:system-ui,-apple-system,'Segoe UI','Helvetica Neue',Arial,sans-serif;
    font-size:17px; line-height:1.65; min-height:100vh;
  }}
  .page {{ max-width:760px; margin:0 auto; padding:26px 20px 60px; }}
  .haut {{ border-bottom:1px solid rgba(255,255,255,0.13); padding-bottom:14px; margin-bottom:30px;
          display:flex; justify-content:space-between; align-items:baseline; flex-wrap:wrap; gap:8px; }}
  .marque {{ font-size:21px; font-weight:800; letter-spacing:-0.02em; text-decoration:none; color:#e9edf9; }}
  .marque span {{ color:#4ade80; }}
  .etiquette {{ font-size:12px; font-weight:600; letter-spacing:.16em;
               text-transform:uppercase; color:#9aa7c7; }}
  h1 {{ font-size:clamp(28px,5vw,40px); font-weight:800; letter-spacing:-0.02em;
       line-height:1.15; text-wrap:balance; margin:10px 0 16px; }}
  p {{ text-wrap:pretty; }}
  .lecture {{ font-size:18px; color:#9aa7c7; max-width:58ch; }}
  .bloc {{ border:1px solid rgba(255,255,255,0.13); background:rgba(255,255,255,0.055);
          border-radius:18px; padding:24px; margin:30px 0; }}
  .bloc h2 {{ font-size:20px; letter-spacing:-0.01em; margin-bottom:16px; }}
  .barre {{ margin:14px 0; }}
  .barre .ligne {{ display:flex; justify-content:space-between; gap:12px;
                  font-size:15px; font-weight:600; color:#9aa7c7; margin-bottom:6px; }}
  .barre .ligne span:last-child {{ font-variant-numeric:tabular-nums; color:#e9edf9; }}
  .barre .fond {{ background:rgba(255,255,255,0.06); height:14px; border-radius:999px; overflow:hidden; }}
  .barre .plein {{ height:100%; border-radius:999px;
                  background:linear-gradient(90deg,#2dd4bf,#4ade80);
                  box-shadow:0 0 16px rgba(74,222,128,0.5); }}
  .barre.vous .plein {{ background:#fb923c; box-shadow:0 0 14px rgba(251,146,60,0.55); min-width:4px; }}
  .barre.vous .ligne span {{ color:#fb923c; font-weight:700; }}
  .extrait {{ margin:18px 0; background:#1a2547; border:1px solid rgba(255,255,255,0.1);
             border-radius:4px 16px 16px 16px; padding:14px 17px;
             box-shadow:0 12px 34px rgba(0,0,0,0.35); }}
  .extrait .qui {{ font-size:13.5px; font-weight:700; color:#4ade80; margin-bottom:8px; }}
  blockquote {{ font-family:ui-monospace,'Cascadia Code','SF Mono',Consolas,'Liberation Mono',monospace;
               font-size:13.5px; line-height:1.6; color:#cdd6ee; margin:0; }}
  ul {{ margin:8px 0 0 20px; }}
  li {{ font-size:15.5px; color:#9aa7c7; }}
  .methode {{ font-size:14px; color:#9aa7c7; border-top:1px solid rgba(255,255,255,0.13); padding-top:14px; }}
  .suite {{ background:linear-gradient(180deg, rgba(74,222,128,0.12), rgba(74,222,128,0.03));
           border:1px solid rgba(74,222,128,0.5); border-radius:18px;
           padding:24px; margin:34px 0 0; box-shadow:0 0 46px rgba(74,222,128,0.1); }}
  .suite strong {{ color:#4ade80; font-size:18px; letter-spacing:-0.01em; }}
  .suite a.bouton {{ display:inline-block; margin-top:14px; padding:13px 24px;
             background:linear-gradient(180deg,#5fe796,#3ecf70); color:#04240f;
             text-decoration:none; font-weight:700; font-size:15.5px; border-radius:12px;
             box-shadow:0 10px 30px rgba(74,222,128,0.28); }}
</style>
</head>
<body>
<div class="page">
  <div class="haut">
    <a class="marque" href="https://portevoix.triskell-studio.fr"><img
      src="../logo-rond-96.png" alt="" width="30" height="30"
      style="vertical-align:middle;margin-right:9px">Porte-Voix<span>.</span></a>
    <span class="etiquette">Audit établi le {e(date_txt)}</span>
  </div>
  <p class="etiquette">{entreprise}, {ville}</p>
  <h1>{e(titre)}</h1>
  <p class="lecture">{e(lecture)}</p>

  <div class="bloc">
    <h2>La part de voix mesurée</h2>
    {"".join(barres)}
    <p class="methode" style="border:none;padding-top:8px">La part de voix,
    c'est la fréquence à laquelle un nom apparaît dans les réponses des IA
    aux questions ci-dessous, sur l'ensemble de nos passages.</p>
  </div>

  <div class="bloc">
    <h2>Ce que les IA répondent, mot pour mot</h2>
    {extraits_html or "<p class='lecture'>Les réponses complètes sont conservées et consultables sur demande.</p>"}
  </div>

  <div class="bloc">
    <h2>La méthode, en clair</h2>
    <p style="font-size:16px">Questions posées :</p>
    <ul>{questions_html}</ul>
    <p class="methode" style="margin-top:14px">{audit.get("nb_reponses", 0)}
    réponses recueillies sur {e(ias_txt)} (modes recherche
    web), en {audit.get("nb_passes", 0)} passages par question, le {e(date_txt)}.
    Les réponses des IA varient d'une conversation à l'autre, vos propres
    essais peuvent différer de nos mesures. C'est précisément pour cela que
    nous mesurons une tendance sur plusieurs passages, jamais un essai isolé.</p>
  </div>

  <div class="suite">
    <strong>La suite, si le sujet vous parle.</strong><br>
    Chaque mois, nous faisons le travail qui construit cette part de voix,
    nous la mesurons, et vous recevez ce relevé mis à jour. Sans engagement,
    premier mois remboursé s'il ne vous convainc pas.
    <br><a class="bouton" href="https://portevoix.triskell-studio.fr">Découvrir Porte-Voix</a>
  </div>
</div>
</body>
</html>
"""


def _slug(texte: str) -> str:
    texte = unicodedata.normalize("NFKD", texte or "")
    texte = "".join(c for c in texte if not unicodedata.combining(c))
    texte = re.sub(r"[^a-z0-9]+", "-", texte.lower()).strip("-")
    return texte[:40] or "audit"


def enregistrer(audit: dict, dossier: str | Path) -> dict:
    """Écrit la page HTML + les données JSON de l'audit.

    Le nom de fichier contient un jeton aléatoire : l'adresse d'un audit
    ne se devine pas (un prospect ne doit jamais tomber sur l'audit d'un
    autre)."""
    dossier = Path(dossier)
    dossier.mkdir(parents=True, exist_ok=True)
    jeton = secrets.token_urlsafe(6).replace("_", "a").replace("-", "b")
    nom = f"{_slug(audit['entreprise'])}-{jeton}"
    chemin_html = dossier / f"{nom}.html"
    chemin_html.write_text(rendre_html(audit), encoding="utf-8")
    (dossier / f"{nom}.json").write_text(
        json.dumps(audit, ensure_ascii=False, indent=1), encoding="utf-8")
    return {"nom": nom, "html": str(chemin_html),
            "url_relative": f"audits/{nom}.html"}
