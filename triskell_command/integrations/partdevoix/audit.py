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
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Bricolage+Grotesque:opsz,wght@12..96,500..800&family=Inter:wght@400;600;700&display=swap" rel="stylesheet">
<style>
  *, *::before, *::after {{ margin:0; padding:0; box-sizing:border-box; }}
  html, body {{ overflow-x:hidden; }}
  body {{
    background:
      linear-gradient(rgba(16,24,38,0.032) 1px, transparent 1px),
      linear-gradient(90deg, rgba(16,24,38,0.032) 1px, transparent 1px),
      #eef1f4;
    background-size:44px 44px, 44px 44px, auto;
    color:#101826;
    font-family:'Inter',system-ui,-apple-system,'Segoe UI','Helvetica Neue',Arial,sans-serif;
    font-size:17px; line-height:1.65; min-height:100vh;
  }}
  .page {{ max-width:760px; margin:0 auto; padding:26px 20px 60px; }}
  .haut {{ border-bottom:1px solid rgba(16,24,38,0.30); padding-bottom:14px; margin-bottom:30px;
          display:flex; justify-content:space-between; align-items:center; flex-wrap:wrap; gap:8px; }}
  .marque {{ display:inline-flex; align-items:center; gap:10px;
            font-family:'Bricolage Grotesque','Inter',system-ui,sans-serif;
            font-size:21px; font-weight:800; letter-spacing:-0.02em; text-decoration:none; color:#101826; }}
  .marque svg {{ display:block; }}
  .marque span {{ color:#c2330f; }}
  .etiquette {{ font-size:11.5px; font-weight:700; letter-spacing:.13em;
               text-transform:uppercase; color:#35415a; }}
  h1 {{ font-family:'Bricolage Grotesque','Inter',system-ui,sans-serif;
       font-size:clamp(28px,5vw,40px); font-weight:800; letter-spacing:-0.02em;
       line-height:1.12; text-wrap:balance; margin:10px 0 16px; }}
  p {{ text-wrap:pretty; }}
  .lecture {{ font-size:18px; color:#4a566d; max-width:58ch; }}
  .bloc {{ background:rgba(16,24,38,0.30); padding:1px; margin:30px 0;
          clip-path:polygon(0 0, calc(100% - 16px) 0, 100% 16px, 100% 100%, 16px 100%, 0 calc(100% - 16px)); }}
  .bloc-in {{ background:#ffffff; padding:24px;
             clip-path:polygon(0 0, calc(100% - 14.6px) 0, 100% 14.6px, 100% 100%, 14.6px 100%, 0 calc(100% - 14.6px)); }}
  .bloc h2 {{ font-family:'Bricolage Grotesque','Inter',system-ui,sans-serif;
             font-size:20px; letter-spacing:-0.01em; margin-bottom:16px; }}
  .barre {{ margin:14px 0; }}
  .barre .ligne {{ display:flex; justify-content:space-between; gap:12px;
                  font-size:15px; font-weight:600; color:#4a566d; margin-bottom:6px; }}
  .barre .ligne span:last-child {{ font-variant-numeric:tabular-nums; color:#101826; }}
  .barre .fond {{ background:rgba(16,24,38,0.08); height:12px; border:1px solid rgba(16,24,38,0.14); }}
  .barre .plein {{ height:100%; background:#101826; }}
  .barre.vous .plein {{ background:#ff5a36; min-width:4px; }}
  .barre.vous .ligne span {{ color:#c2330f; font-weight:700; }}
  .extrait {{ margin:18px 0; background:rgba(16,24,38,0.03); border:1px solid rgba(16,24,38,0.14);
             padding:14px 17px; }}
  .extrait .qui {{ font-size:13.5px; font-weight:700; color:#c2330f; margin-bottom:8px; }}
  blockquote {{ font-family:ui-monospace,'Cascadia Code','SF Mono',Consolas,'Liberation Mono',monospace;
               font-size:13.5px; line-height:1.6; color:#35415a; margin:0; }}
  ul {{ margin:8px 0 0 20px; }}
  li {{ font-size:15.5px; color:#4a566d; }}
  .methode {{ font-size:14px; color:#4a566d; border-top:1px solid rgba(16,24,38,0.14); padding-top:14px; }}
  .suite {{ background:#ff5a36; padding:1px; margin:34px 0 0;
           clip-path:polygon(0 0, calc(100% - 16px) 0, 100% 16px, 100% 100%, 16px 100%, 0 calc(100% - 16px)); }}
  .suite-in {{ background:#fff7f2; padding:24px;
              clip-path:polygon(0 0, calc(100% - 14.6px) 0, 100% 14.6px, 100% 100%, 14.6px 100%, 0 calc(100% - 14.6px)); }}
  .suite strong {{ font-family:'Bricolage Grotesque','Inter',system-ui,sans-serif;
                  color:#c2330f; font-size:18px; letter-spacing:-0.01em; }}
  .suite a.bouton {{ display:inline-block; margin-top:14px; padding:13px 24px;
             background:#ff5a36; color:#101826;
             text-decoration:none; font-weight:700; font-size:15.5px;
             clip-path:polygon(0 0, calc(100% - 10px) 0, 100% 10px, 100% 100%, 10px 100%, 0 calc(100% - 10px)); }}
  .suite a.bouton:hover {{ background:#ff6f4d; }}
</style>
</head>
<body>
<div class="page">
  <div class="haut">
    <a class="marque" href="https://portevoix.triskell-studio.fr">
      <svg viewBox="0 0 40 32" width="30" height="24" aria-hidden="true" focusable="false">
        <path d="M3 12 L19 4 V28 L3 20 Z" fill="#101826"/>
        <rect x="1" y="11" width="2.5" height="10" fill="#101826"/>
        <path d="M23 11 a7 7 0 0 1 0 10" fill="none" stroke="#ff5a36" stroke-width="2.2" stroke-linecap="round"/>
        <path d="M27 7 a13 13 0 0 1 0 18" fill="none" stroke="#ff5a36" stroke-width="2.2" stroke-linecap="round"/>
        <circle cx="34.5" cy="16" r="2.2" fill="#ff5a36"/>
      </svg>
      Porte-Voix<span>.</span></a>
    <span class="etiquette">Audit établi le {e(date_txt)}</span>
  </div>
  <p class="etiquette">{entreprise}, {ville}</p>
  <h1>{e(titre)}</h1>
  <p class="lecture">{e(lecture)}</p>

  <div class="bloc"><div class="bloc-in">
    <h2>La part de voix mesurée</h2>
    {"".join(barres)}
    <p class="methode" style="border:none;padding-top:8px">La part de voix,
    c'est la fréquence à laquelle un nom apparaît dans les réponses des IA
    aux questions ci-dessous, sur l'ensemble de nos passages.</p>
  </div></div>

  <div class="bloc"><div class="bloc-in">
    <h2>Ce que les IA répondent, mot pour mot</h2>
    {extraits_html or "<p class='lecture'>Les réponses complètes sont conservées et consultables sur demande.</p>"}
  </div></div>

  <div class="bloc"><div class="bloc-in">
    <h2>La méthode, en clair</h2>
    <p style="font-size:16px">Questions posées :</p>
    <ul>{questions_html}</ul>
    <p class="methode" style="margin-top:14px">{audit.get("nb_reponses", 0)}
    réponses recueillies sur {e(ias_txt)} (modes recherche
    web), en {audit.get("nb_passes", 0)} passages par question, le {e(date_txt)}.
    Les réponses des IA varient d'une conversation à l'autre, vos propres
    essais peuvent différer de nos mesures. C'est précisément pour cela que
    nous mesurons une tendance sur plusieurs passages, jamais un essai isolé.</p>
  </div></div>

  <div class="suite"><div class="suite-in">
    <strong>La suite, si le sujet vous parle.</strong><br>
    Chaque mois, nous faisons le travail qui construit cette part de voix,
    nous la mesurons, et vous recevez ce relevé mis à jour. Sans engagement,
    premier mois remboursé s'il ne vous convainc pas.
    <br><a class="bouton" href="https://portevoix.triskell-studio.fr">Découvrir Porte-Voix</a>
  </div></div>
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
