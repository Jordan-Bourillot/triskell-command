"""Audit personnalisé La Part de Voix.

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
        extraits_html += (
            f'<div class="extrait"><div class="qui">{e(x["ia"])}, à la '
            f'question « {e(x["question"])} »</div>'
            f'<blockquote>{e(x["texte"])}</blockquote></div>'
        )
    questions_html = "".join(
        f"<li>« {e(q)} »</li>" for q in audit.get("questions") or [])
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
  * {{ margin:0; padding:0; box-sizing:border-box; }}
  body {{ background:#f6f1e6; color:#1c2b3a; font-family:Georgia,'Times New Roman',serif;
         font-size:18px; line-height:1.6; }}
  .page {{ max-width:760px; margin:0 auto; padding:26px 20px 60px; }}
  .haut {{ border-bottom:3px double #1c2b3a; padding-bottom:12px; margin-bottom:30px;
          display:flex; justify-content:space-between; align-items:baseline; flex-wrap:wrap; gap:8px; }}
  .marque {{ font-size:22px; font-weight:bold; text-decoration:none; color:#1c2b3a; }}
  .marque span {{ color:#b23a22; }}
  .etiquette {{ font-family:'Trebuchet MS',Verdana,sans-serif; font-size:12px;
               letter-spacing:.2em; text-transform:uppercase; color:#55636f; }}
  h1 {{ font-size:clamp(28px,5vw,40px); line-height:1.15; text-wrap:balance; margin:10px 0 16px; }}
  p {{ text-wrap:pretty; }}
  .lecture {{ font-size:19px; color:#55636f; max-width:58ch; }}
  .bloc {{ border:1px solid #1c2b3a; background:#fffdf6; padding:24px; margin:30px 0; }}
  .bloc h2 {{ font-size:20px; margin-bottom:16px; }}
  .barre {{ margin:13px 0; }}
  .barre .ligne {{ display:flex; justify-content:space-between;
                  font-family:'Trebuchet MS',Verdana,sans-serif; font-size:15px; margin-bottom:4px; }}
  .barre .fond {{ background:#efe7d6; height:15px; border:1px solid #cfc4ac; }}
  .barre .plein {{ height:100%; background:#1c2b3a; }}
  .barre.vous .plein {{ background:#b23a22; }}
  .barre.vous .ligne {{ color:#b23a22; font-weight:bold; }}
  .extrait {{ margin:18px 0; }}
  .extrait .qui {{ font-family:'Trebuchet MS',Verdana,sans-serif; font-size:14px; color:#55636f; }}
  blockquote {{ border-left:4px solid #cfc4ac; padding:6px 0 6px 14px; margin-top:6px;
               font-size:16px; color:#333f4c; }}
  ul {{ margin:8px 0 0 20px; }}
  li {{ font-size:16px; color:#55636f; }}
  .methode {{ font-size:14px; color:#55636f; border-top:1px solid #cfc4ac; padding-top:14px; }}
  .suite {{ background:#f3d97a; border:2px solid #1c2b3a; padding:20px 22px; margin:34px 0 0; }}
  .suite a.bouton {{ display:inline-block; margin-top:12px; padding:13px 24px; background:#1c2b3a;
             color:#f6f1e6; text-decoration:none; font-family:'Trebuchet MS',Verdana,sans-serif;
             font-size:16px; }}
</style>
</head>
<body>
<div class="page">
  <div class="haut">
    <a class="marque" href="https://partdevoix.triskell-studio.fr">La Part de Voix<span>.</span></a>
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
    réponses recueillies sur ChatGPT, Perplexity et Gemini (modes recherche
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
    <br><a class="bouton" href="https://partdevoix.triskell-studio.fr">Découvrir La Part de Voix</a>
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
