"""Rapport mensuel Porte-Voix.

Ce que chaque client paie chaque mois : sa part de voix, celle de ses
concurrents désignés, l'évolution depuis le relevé précédent, ce qui a
été fait et ce qui vient. Toute la mesure vient du moteur (mesurer,
agreger, part_de) : aucune logique de mesure n'est dupliquée ici, et
chaque relevé est daté puis archivé par client.

Règle de rétention gravée : un rapport plat doit TOUJOURS montrer le
travail fait et le plan suivant. Quand ces rubriques manquent, le
rapport sort quand même mais porte une alerte, à traiter avant l'envoi.

Le rendu HTML est volontairement sobre et neutre (noir, blanc, gris,
aucune identité de marque) : l'identité visuelle est en cours de choix,
tout se repeint dans les variables CSS en tête de page. La méthode est
toujours en pied de page, et jamais de promesse de citation.
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

from . import clients, moteur, stockage

logger = logging.getLogger(__name__)

# En dessous de ce mouvement (en points de part de voix), on affiche
# « stable » : les réponses des IA varient naturellement d'un passage à
# l'autre, annoncer une hausse de 0,8 point serait de la fausse précision.
SEUIL_STABLE = 2.0

# Relevés conservés par client (dix ans de rythme mensuel : large) et
# rapports archivés au total (l'archive garde ce qui a été produit tel
# quel : un rapport regénéré plus tard n'aurait pas les mêmes rubriques).
MAX_RELEVES = 120
MAX_RAPPORTS_ARCHIVES = 120

_ETIQUETTES_IA = {"openai": "ChatGPT", "perplexity": "Perplexity",
                  "google": "Gemini"}
_FLECHES = {"hausse": "↗", "baisse": "↘", "stable": "→"}
_MOIS = ["janvier", "février", "mars", "avril", "mai", "juin", "juillet",
         "août", "septembre", "octobre", "novembre", "décembre"]


# --------------------------------------------------------- historique

def _charger_releves() -> dict:
    donnees = stockage.lire("releves", {})
    return donnees if isinstance(donnees, dict) else {}


def _sauver_releves(donnees: dict) -> None:
    if not stockage.ecrire("releves", donnees):
        raise ValueError("relevé non archivé : base partagée injoignable "
                         "— réessaie dans un moment")


def historique_client(client_id: str) -> list[dict]:
    """Les relevés datés d'un client, du plus ancien au plus récent."""
    return _charger_releves().get(client_id) or []


# ------------------------------------------------------------ mesurer

def mesurer_client(client: dict, passes: int = 3, cles: dict | None = None,
                   mesure: dict | None = None) -> dict:
    """Mesure la part de voix du client et de chacun de ses concurrents
    désignés, puis archive le relevé daté dans son historique.

    `mesure` peut être fournie (tests, rejeu) pour éviter tout appel
    réseau. Une mesure sans aucune réponse valide n'est PAS archivée :
    un relevé à zéro faute de clés API raconterait une fausse chute."""
    questions = clients.questions_du_client(client)
    if not questions:
        raise ValueError("aucune question à poser pour ce client (ni "
                         "questions personnalisées, ni métier + ville)")
    if mesure is None:
        cles = cles if cles is not None else moteur.recuperer_cles()
        if not cles.get("anthropic"):
            # Sans clé Anthropic, l'extraction des noms rendrait [] sur
            # chaque réponse : le relevé raconterait une fausse chute à
            # 0 %. On refuse AVANT de dépenser les appels aux IA web.
            raise ValueError("clé Anthropic manquante : impossible "
                             "d'extraire les noms cités — mesure annulée, "
                             "rien d'archivé")
        mesure = moteur.mesurer(questions, passes=passes, cles=cles)
    # La vérité vient des runs, jamais d'un compteur déclaré : une mesure
    # sans aucune réponse valide n'est pas archivée.
    reponses_ok = [r for r in (mesure.get("runs") or []) if r.get("ok")]
    if not reponses_ok:
        raise ValueError("aucune réponse d'IA recueillie : relevé non "
                         "archivé (clés OpenAI / Perplexity / Gemini ?)")
    agregat = moteur.agreger(mesure)
    if not agregat and any(
            (r.get("part_client") or 0) > 0
            or any((cc.get("part") or 0) > 0
                   for cc in r.get("concurrents") or [])
            for r in historique_client(client.get("id") or "")):
        # Zéro nom extrait sur TOUTES les réponses alors que l'historique
        # en avait : c'est l'extraction qui est morte (crédit IA vide,
        # panne déjà vécue le 07/07/2026), pas le marché qui s'est tu.
        raise ValueError("aucun nom extrait d'aucune réponse alors que les "
                         "relevés précédents en avaient : panne d'extraction "
                         "probable (crédit IA ?) — relevé non archivé")
    presents = {r.get("provider") for r in reponses_ok}
    releve = {
        "ts": mesure.get("ts") or datetime.now(timezone.utc).isoformat(),
        # moteur.mesurer fait toujours au moins un passage (max(1, n)) :
        # on archive ce qui a réellement tourné, pas la valeur demandée.
        "passes": max(1, passes),
        "nb_reponses": len(reponses_ok),
        "questions": questions,
        "ias": ([_ETIQUETTES_IA[p] for p in ("openai", "perplexity",
                                             "google") if p in presents]
                + sorted(str(p) for p in presents
                         if p and p not in _ETIQUETTES_IA)),
        "part_client": moteur.part_de(client.get("entreprise") or "",
                                      agregat),
        "concurrents": [
            {"nom": nom, "part": moteur.part_de(nom, agregat)}
            for nom in client.get("concurrents") or []],
    }
    with stockage.VERROU:
        donnees = _charger_releves()
        liste = donnees.setdefault(client["id"], [])
        liste.append(releve)
        del liste[:-MAX_RELEVES]
        _sauver_releves(donnees)
    logger.info("partdevoix relevé %s : client %s%%, %s réponses",
                client["id"], releve["part_client"], releve["nb_reponses"])
    return releve


# ---------------------------------------------------------- comparer

def _evolution(part_actuelle: float, part_precedente: float | None,
               precedent_ts: str = "") -> dict:
    """Compare deux parts de voix : hausse, baisse, stable, ou premier
    relevé quand il n'y a rien à comparer. Delta en points de part."""
    if part_precedente is None:
        return {"sens": "premier", "delta": None, "precedent_ts": ""}
    delta = round(float(part_actuelle) - float(part_precedente), 1)
    if abs(delta) < SEUIL_STABLE:
        sens = "stable"
    elif delta > 0:
        sens = "hausse"
    else:
        sens = "baisse"
    return {"sens": sens, "delta": delta, "precedent_ts": precedent_ts}


def _nombre(valeur) -> str:
    """Un nombre en écriture française (virgule décimale)."""
    return f"{float(valeur):g}".replace(".", ",")


def texte_evolution(ev: dict, pour_concurrent: bool = False) -> str:
    """L'évolution en français normal, pour la page comme pour le
    terminal. Le libellé « premier » change de sujet : « votre point de
    référence » ne peut pas s'afficher sous la barre d'un concurrent."""
    date_prec = _date_francaise(ev.get("precedent_ts") or "")
    if ev.get("sens") == "premier":
        return ("Première mesure pour ce concurrent" if pour_concurrent
                else "Premier relevé : votre point de référence")
    if ev.get("sens") == "stable":
        return f"Stable par rapport au relevé du {date_prec}"
    delta = abs(float(ev.get("delta") or 0.0))
    unite = "points" if delta >= 2 else "point"
    verbe = "En hausse" if ev.get("sens") == "hausse" else "En baisse"
    return (f"{verbe} de {_nombre(delta)} {unite} par rapport au relevé "
            f"du {date_prec}")


def _rubrique(parametre, sur_fiche) -> list[str]:
    """Une rubrique libre : le paramètre s'il est fourni, sinon ce qui est
    posé sur la fiche client."""
    source = parametre if parametre is not None else (sur_fiche or [])
    if isinstance(source, str):
        source = [source]
    return [str(x).strip() for x in source if str(x).strip()]


def generer_rapport(client: dict, fait: list | None = None,
                    avenir: list | None = None) -> dict:
    """Les données du rapport mensuel : dernier relevé, comparaison au
    relevé précédent (client ET chaque concurrent), série complète pour
    le graphique, rubriques « ce qui a été fait » / « ce qui vient »
    (passées en paramètre, sinon lues sur la fiche client)."""
    historique = historique_client(client["id"])
    if not historique:
        raise ValueError("aucun relevé pour ce client : lancer une mesure "
                         "d'abord")
    releve = historique[-1]
    precedent = historique[-2] if len(historique) > 1 else None
    evolution = _evolution(
        releve.get("part_client") or 0.0,
        precedent.get("part_client") if precedent else None,
        (precedent or {}).get("ts") or "")
    concurrents = []
    for c in releve.get("concurrents") or []:
        part_prec, ts_prec = None, ""
        if precedent:
            for cp in precedent.get("concurrents") or []:
                if moteur.correspond(cp.get("nom") or "", c.get("nom") or ""):
                    part_prec = cp.get("part") or 0.0
                    ts_prec = precedent.get("ts") or ""
                    break
        concurrents.append(dict(c, evolution=_evolution(
            c.get("part") or 0.0, part_prec, ts_prec)))
    parts = [float(c.get("part") or 0.0) for c in concurrents]
    moyenne = round(sum(parts) / len(parts), 1) if parts else None
    fait = _rubrique(fait, client.get("fait"))
    avenir = _rubrique(avenir, client.get("avenir"))
    alertes = []
    if not fait:
        alertes.append("règle de rétention : rien dans « ce qui a été "
                       "fait » — à compléter avant d'envoyer le rapport")
    if not avenir:
        alertes.append("règle de rétention : rien dans « ce qui vient » "
                       "— à compléter avant d'envoyer le rapport")
    # Le graphique : une colonne par MOIS (le dernier relevé du mois fait
    # foi — une re-mesure en cours de mois remplace, elle ne double pas),
    # 12 mois au plus.
    par_mois: dict = {}
    for r in historique:
        point = {"ts": r.get("ts") or "",
                 "part": float(r.get("part_client") or 0.0)}
        par_mois[point["ts"][:7]] = point
    return {
        "client_id": client.get("id") or "",
        "entreprise": client.get("entreprise") or "",
        "metier": client.get("metier") or "",
        "villes": list(client.get("villes") or []),
        "palier": client.get("palier") or "",
        "ts": releve.get("ts") or "",
        "mois": _mois_de(releve.get("ts") or ""),
        "part_client": float(releve.get("part_client") or 0.0),
        "evolution": evolution,
        "concurrents": concurrents,
        "moyenne_concurrents": moyenne,
        "serie": list(par_mois.values())[-12:],
        "premier_ts": historique[0].get("ts") or "",
        "premier_part": float(historique[0].get("part_client") or 0.0),
        "fait": fait,
        "avenir": avenir,
        "questions": list(releve.get("questions") or []),
        "nb_passes": releve.get("passes", 0),
        "nb_reponses": releve.get("nb_reponses", 0),
        "ias": list(releve.get("ias") or []),
        "alertes": alertes,
    }


# ------------------------------------------------------------- dates

def _mois_de(ts: str) -> str:
    try:
        return f"{_MOIS[int(ts[5:7]) - 1]} {ts[:4]}"
    except Exception:
        return ts[:10]


def _mois_court(ts: str) -> str:
    return f"{ts[5:7]}/{ts[2:4]}" if len(ts) >= 7 else ts


def _date_francaise(ts: str) -> str:
    try:
        jour = int(ts[8:10])
        texte = f"{jour} {_MOIS[int(ts[5:7]) - 1]} {ts[:4]}"
        return ("1er" + texte[1:]) if jour == 1 else texte
    except Exception:
        return ts[:10]


# ------------------------------------------------------------ la page

def _evo_html(ev: dict, pour_concurrent: bool = False) -> str:
    fleche = _FLECHES.get((ev or {}).get("sens"), "")
    texte = texte_evolution(ev or {}, pour_concurrent=pour_concurrent)
    return f"{fleche} {html.escape(texte)}".strip()


def rendre_html(rapport: dict) -> str:
    """La page du rapport mensuel, autonome (styles inclus), à la charte
    Porte-Voix validée le 09/07/2026 (portevoix/CHARTE.md) : clair,
    encre #101826, accent corail, coins coupés, échelle graduée. Textes,
    structure et honnêteté du pied de page inchangés."""
    e = html.escape
    entreprise = e(rapport.get("entreprise") or "")
    mois = e(rapport.get("mois") or "")
    date_txt = e(_date_francaise(rapport.get("ts") or ""))
    sous_titre = " · ".join(x for x in [
        rapport.get("metier") or "",
        ", ".join(rapport.get("villes") or [])] if x)
    part = float(rapport.get("part_client") or 0.0)

    # Le comparatif du mois (jamais de moyenne inventée : sans concurrent
    # désigné, on le dit).
    concurrents = rapport.get("concurrents") or []
    moyenne = rapport.get("moyenne_concurrents")
    if moyenne is None:
        comparatif = ("Aucun concurrent désigné pour l'instant : ce "
                      "rapport suit votre part de voix seule.")
    elif len(concurrents) == 1:
        comparatif = (f"Votre concurrent désigné est à "
                      f"{_nombre(moyenne)}&nbsp;% ce mois-ci.")
    else:
        comparatif = (f"La moyenne de vos {len(concurrents)} concurrents "
                      f"désignés est à {_nombre(moyenne)}&nbsp;% ce mois-ci.")
    titre_detail = ("Vous et vos concurrents désignés, ce mois-ci"
                    if concurrents else "Votre position, ce mois-ci")

    # Le graphique : une colonne par relevé, hauteur = part de voix.
    colonnes = []
    for point in rapport.get("serie") or []:
        part_point = float(point.get("part") or 0.0)
        hauteur = max(3, min(120, round(part_point * 1.2)))
        colonnes.append(
            '<div class="colonne">'
            f'<span class="col-part">{_nombre(part_point)}%</span>'
            f'<div class="tige" style="height:{hauteur}px"></div>'
            f'<span class="col-mois">{e(_mois_court(point.get("ts") or ""))}'
            '</span></div>')
    notes_graphe = ""
    if len(colonnes) == 1:
        notes_graphe += ("<p class=\"note\">Premier relevé : il sert de "
                         "point de référence, les prochains rapports "
                         "montreront l'évolution à partir d'ici.</p>")
    # Si le point de départ n'est plus dans le graphique (plus de 12 mois,
    # ou premier relevé remplacé par une re-mesure du même mois), il reste
    # écrit en toutes lettres : c'est la référence promise au client.
    premier_ts = rapport.get("premier_ts") or ""
    if premier_ts and all((p.get("ts") or "") != premier_ts
                          for p in rapport.get("serie") or []):
        notes_graphe += (
            f'<p class="note">Point de départ : '
            f'{_nombre(rapport.get("premier_part") or 0.0)}&nbsp;% le '
            f'{e(_date_francaise(premier_ts))}.</p>')

    # Les barres du détail : le client d'abord, puis chaque concurrent,
    # chacun avec son évolution depuis le relevé précédent. Sur le tout
    # premier rapport, pas de ligne d'évolution : tout dirait « premier »,
    # le haut de page le dit déjà.
    premier_rapport = (rapport.get("evolution") or {}).get("sens") == "premier"
    barres = []
    largeur_p = max(1.0, min(100.0, part))
    evo_client = ("" if premier_rapport else
                  f'<div class="evo">'
                  f'{_evo_html(rapport.get("evolution") or {})}</div>')
    barres.append(
        '<div class="barre vous">'
        f'<div class="ligne"><span>{entreprise} (vous)</span>'
        f'<span>{_nombre(part)}&nbsp;%</span></div>'
        f'<div class="fond"><div class="plein" style="width:{largeur_p}%">'
        f'</div></div>{evo_client}'
        '</div>')
    for c in concurrents:
        part_c = float(c.get("part") or 0.0)
        largeur = max(1.0, min(100.0, part_c))
        evo_conc = ("" if premier_rapport else
                    f'<div class="evo">'
                    f'{_evo_html(c.get("evolution") or {}, pour_concurrent=True)}'
                    '</div>')
        barres.append(
            '<div class="barre">'
            f'<div class="ligne"><span>{e(c.get("nom") or "")}</span>'
            f'<span>{_nombre(part_c)}&nbsp;%</span></div>'
            f'<div class="fond"><div class="plein" style="width:{largeur}%">'
            f'</div></div>{evo_conc}'
            '</div>')

    fait_items = "".join(f"<li>{e(x)}</li>" for x in rapport.get("fait") or [])
    avenir_items = "".join(f"<li>{e(x)}</li>"
                           for x in rapport.get("avenir") or [])
    bloc_fait = (f'<div class="cadre"><div class="cadre-in">'
                 f'<h2>Ce qui a été fait ce mois-ci</h2>'
                 f'<ul class="liste">{fait_items}</ul></div></div>'
                 if fait_items else "")
    bloc_avenir = (f'<div class="cadre"><div class="cadre-in">'
                   f'<h2>Ce qui vient le mois prochain</h2>'
                   f'<ul class="liste">{avenir_items}</ul></div></div>'
                   if avenir_items else "")

    questions_html = "".join(f"<li>« {e(q)} »</li>"
                             for q in rapport.get("questions") or [])
    # Jamais de liste d'IA inventée : si le relevé ne l'a pas tracée, la
    # méthode reste générique plutôt que d'affirmer des noms.
    ias = [str(x) for x in rapport.get("ias") or [] if str(x).strip()]
    ias_txt = ("les IA interrogées" if not ias
               else ias[0] if len(ias) == 1
               else ", ".join(ias[:-1]) + " et " + ias[-1])
    nb_reponses = int(rapport.get("nb_reponses") or 0)
    nb_passes = int(rapport.get("nb_passes") or 0)
    mot_reponses = ("réponse recueillie" if nb_reponses == 1
                    else "réponses recueillies")
    mot_passages = "passage" if nb_passes == 1 else "passages"

    return f"""<!DOCTYPE html>
<html lang="fr">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<meta name="robots" content="noindex">
<title>Rapport mensuel. {entreprise}, {mois}.</title>
<style>
  @import url('https://fonts.googleapis.com/css2?family=Bricolage+Grotesque:wght@700;800&family=Inter:wght@400;600;700&display=swap');
  /* Charte Porte-Voix (portevoix/CHARTE.md, validée le 09/07/2026) :
     toutes les couleurs se règlent ici. */
  :root {{
    --papier:#eef1f4;               /* fond de page */
    --carte:#ffffff;                /* fond des cartes */
    --encre:#101826;                /* texte principal */
    --sourdine:#4a566d;             /* texte secondaire */
    --corail:#ff5a36;               /* accent (vous) */
    --corail-encre:#c2330f;         /* corail foncé lisible */
    --sable:#e8dcc8;                /* soutien discret (les autres) */
    --trait:rgba(16,24,38,0.14);    /* filets */
    --trait-fort:rgba(16,24,38,0.30);
    --grille:rgba(16,24,38,0.032);  /* grille de fond 44px */
  }}
  *, *::before, *::after {{ margin:0; padding:0; box-sizing:border-box; }}
  html, body {{ overflow-x:hidden; }}
  body {{
    background:
      linear-gradient(var(--grille) 1px, transparent 1px),
      linear-gradient(90deg, var(--grille) 1px, transparent 1px),
      var(--papier);
    background-size:44px 44px;
    color:var(--encre);
    font-family:'Inter',system-ui,-apple-system,'Segoe UI',Arial,sans-serif;
    font-size:16.5px; line-height:1.65; min-height:100vh;
  }}
  .page {{ max-width:780px; margin:0 auto; padding:26px 20px 60px; }}
  .haut {{ border-bottom:1px solid var(--trait-fort); padding-bottom:14px; margin-bottom:22px;
          display:flex; justify-content:space-between; align-items:center; flex-wrap:wrap; gap:8px; }}
  .marque {{ display:flex; align-items:center; gap:9px; font-weight:800; font-size:20px;
            font-family:'Bricolage Grotesque',system-ui,sans-serif; letter-spacing:-0.02em; }}
  .marque svg {{ display:block; }}
  .marque .pt {{ color:var(--corail); }}
  .etiquette {{ font-size:11.5px; font-weight:700; letter-spacing:.13em;
               text-transform:uppercase; color:var(--sourdine); }}
  .etiquette .pastille {{ display:inline-block; width:8px; height:8px; background:var(--corail);
    border-radius:50%; margin-right:7px; vertical-align:1px; animation:pvPulse 2.2s infinite; }}
  @keyframes pvPulse {{ 0%,100% {{ opacity:1 }} 50% {{ opacity:.35 }} }}
  h1 {{ font-family:'Bricolage Grotesque',system-ui,sans-serif; font-size:clamp(27px,5vw,38px);
       font-weight:800; letter-spacing:-0.02em; line-height:1.12; text-wrap:balance; margin:8px 0 2px; }}
  h2 {{ font-family:'Bricolage Grotesque',system-ui,sans-serif; font-size:19px;
       letter-spacing:-0.01em; margin-bottom:12px; }}
  .sous {{ color:var(--sourdine); }}
  p {{ text-wrap:pretty; }}
  /* Coins coupés signés (jamais de border-radius sur les cartes). */
  .cadre {{ --ch:16px; background:var(--trait); padding:1px; margin:22px 0;
    clip-path:polygon(var(--ch) 0, 100% 0, 100% calc(100% - var(--ch)),
                      calc(100% - var(--ch)) 100%, 0 100%, 0 var(--ch)); }}
  .cadre-in {{ --chi:calc(var(--ch) - 0.8px); background:var(--carte); padding:22px;
    clip-path:polygon(var(--chi) 0, 100% 0, 100% calc(100% - var(--chi)),
                      calc(100% - var(--chi)) 100%, 0 100%, 0 var(--chi)); }}
  .chiffre {{ font-family:'Bricolage Grotesque',system-ui,sans-serif;
             font-size:clamp(40px,8vw,56px); font-weight:800; letter-spacing:-0.02em;
             font-variant-numeric:tabular-nums; line-height:1.05; }}
  .evo-principale {{ font-weight:600; margin:6px 0 4px; }}
  .note {{ font-size:14.5px; color:var(--sourdine); margin-top:10px; }}
  .graphe {{ display:flex; align-items:flex-end; gap:14px; padding:8px 2px 0;
            min-height:150px; overflow-x:auto; }}
  .colonne {{ display:flex; flex-direction:column; align-items:center; gap:5px; }}
  .colonne .tige {{ width:34px; background:var(--sable); }}
  .colonne:last-child .tige {{ background:var(--corail); }}
  .col-part {{ font-size:13px; font-weight:700;
              font-family:ui-monospace,Consolas,'Cascadia Mono',monospace; }}
  .col-mois {{ font-size:12px; color:var(--sourdine);
              font-family:ui-monospace,Consolas,'Cascadia Mono',monospace; }}
  .echelle {{ display:flex; justify-content:space-between; font-size:11px;
             color:var(--sourdine); letter-spacing:.06em;
             font-family:ui-monospace,Consolas,'Cascadia Mono',monospace;
             border-bottom:1px solid var(--trait); padding-bottom:4px; margin-bottom:12px; }}
  .barre {{ margin:16px 0; }}
  .barre .ligne {{ display:flex; justify-content:space-between; gap:12px;
                  font-size:15px; font-weight:600; color:var(--sourdine); margin-bottom:6px; }}
  .barre .ligne span:last-child {{ color:var(--encre);
    font-family:ui-monospace,Consolas,'Cascadia Mono',monospace; }}
  .barre .fond {{ background:rgba(16,24,38,0.06); height:14px; }}
  .barre .plein {{ height:100%; background:var(--sable);
    border-right:2px solid var(--trait-fort); }}
  .barre.vous .plein {{ background:var(--corail); border-right:2px solid var(--corail-encre); }}
  .barre.vous .ligne span {{ color:var(--encre); font-weight:700; }}
  .barre .evo {{ font-size:13.5px; color:var(--sourdine); margin-top:4px; }}
  ul.liste {{ margin:4px 0 0 20px; }}
  ul.liste li {{ margin:6px 0; }}
  ul.liste li::marker {{ color:var(--corail); }}
  ul.questions {{ margin:8px 0 0 20px; }}
  ul.questions li {{ font-size:14px; color:var(--sourdine);
    font-family:ui-monospace,Consolas,'Cascadia Mono',monospace; }}
  .methode {{ font-size:14px; color:var(--sourdine); border-top:1px solid var(--trait);
             padding-top:14px; margin-top:14px; }}
</style>
</head>
<body>
<div class="page">
  <div class="haut">
    <span class="marque">
      <svg viewBox="0 0 40 32" width="30" height="24" aria-hidden="true" focusable="false">
        <path d="M3 12 L19 4 V28 L3 20 Z" fill="#101826"/>
        <rect x="1" y="11" width="2.5" height="10" fill="#101826"/>
        <path d="M23 11 a7 7 0 0 1 0 10" fill="none" stroke="#ff5a36" stroke-width="2.2" stroke-linecap="round"/>
        <path d="M27 7 a13 13 0 0 1 0 18" fill="none" stroke="#ff5a36" stroke-width="2.2" stroke-linecap="round"/>
        <circle cx="34.5" cy="16" r="2.2" fill="#ff5a36"/>
      </svg>
      Porte-Voix<span class="pt">.</span>
    </span>
    <span class="etiquette">Établi le {date_txt}</span>
  </div>
  <p class="etiquette"><span class="pastille"></span>Rapport mensuel · part de voix</p>
  <h1>{entreprise}</h1>
  <p class="sous">{e(sous_titre)}</p>

  <div class="cadre"><div class="cadre-in">
    <h2>Votre part de voix en {mois}</h2>
    <p class="chiffre">{_nombre(part)}&nbsp;%</p>
    <p class="evo-principale">{_evo_html(rapport.get("evolution") or {})}.</p>
    <p class="note">{comparatif}</p>
    <p class="note">La part de voix, c'est la fréquence à laquelle un nom
    apparaît dans les réponses des IA aux questions listées en pied de
    page, sur l'ensemble de nos passages.</p>
  </div></div>

  <div class="cadre"><div class="cadre-in">
    <h2>L'évolution, mois par mois</h2>
    <div class="graphe">{"".join(colonnes)}</div>
    {notes_graphe}
  </div></div>

  <div class="cadre"><div class="cadre-in">
    <h2>{titre_detail}</h2>
    <div class="echelle"><span>0</span><span>25</span><span>50</span><span>75</span><span>100</span></div>
    {"".join(barres)}
  </div></div>

  {bloc_fait}
  {bloc_avenir}

  <div class="cadre"><div class="cadre-in">
    <h2>La méthode, en clair</h2>
    <p style="font-size:16px">Questions posées :</p>
    <ul class="questions">{questions_html}</ul>
    <p class="methode">{nb_reponses} {mot_reponses} sur {e(ias_txt)},
    en {nb_passes} {mot_passages} par question, le {date_txt}. Les
    réponses des IA varient d'une
    conversation à l'autre : ce rapport mesure une tendance sur plusieurs
    passages, jamais un essai isolé. La part de voix se construit dans la
    durée ; aucune citation ponctuelle ne peut être promise, et nous ne le
    faisons jamais.</p>
  </div></div>
</div>
</body>
</html>
"""


# ------------------------------------------------------- enregistrer

def _slug(texte: str) -> str:
    texte = unicodedata.normalize("NFKD", texte or "")
    texte = "".join(c for c in texte if not unicodedata.combining(c))
    texte = re.sub(r"[^a-z0-9]+", "-", texte.lower()).strip("-")
    return texte[:40] or "rapport"


def enregistrer(rapport: dict, dossier: str | Path) -> dict:
    """Écrit la page HTML + les données JSON du rapport.

    Même principe que les audits : le nom de fichier contient un jeton
    aléatoire, l'adresse d'un rapport ne se devine pas (un client ne
    doit jamais tomber sur le rapport d'un autre)."""
    dossier = Path(dossier)
    dossier.mkdir(parents=True, exist_ok=True)
    jeton = secrets.token_urlsafe(6).replace("_", "a").replace("-", "b")
    mois_cle = (rapport.get("ts") or "")[:7] or "rapport"
    nom = f"{_slug(rapport.get('entreprise') or '')}-{mois_cle}-{jeton}"
    chemin_html = dossier / f"{nom}.html"
    chemin_html.write_text(rendre_html(rapport), encoding="utf-8")
    (dossier / f"{nom}.json").write_text(
        json.dumps(rapport, ensure_ascii=False, indent=1), encoding="utf-8")
    return {"nom": nom, "html": str(chemin_html),
            "url_relative": f"rapports/{nom}.html"}


# --------------------------------------------------------------- archive

def archiver_rapport(rapport: dict) -> dict:
    """Fige un rapport produit dans l'archive partagée (c'est ce que le
    client a reçu : un rapport regénéré plus tard n'aurait pas forcément
    les mêmes rubriques). Renvoie l'entrée archivée, avec son id non
    devinable."""
    entree = dict(rapport)
    entree["id"] = secrets.token_urlsafe(9)
    entree["archive_ts"] = datetime.now(timezone.utc).isoformat()
    with stockage.VERROU:
        archives = rapports_archives()
        archives.append(entree)
        archives.sort(key=lambda r: r.get("archive_ts") or "")
        del archives[:-MAX_RAPPORTS_ARCHIVES]
        if not stockage.ecrire("rapports", archives):
            raise ValueError("rapport non archivé : base partagée "
                             "injoignable — réessaie dans un moment")
    return entree


def rapports_archives(client_id: str = "") -> list[dict]:
    """Les rapports archivés, du plus ancien au plus récent (tous les
    clients, ou un seul si client_id est fourni)."""
    archives = stockage.lire("rapports", [])
    if not isinstance(archives, list):
        archives = []
    if client_id:
        archives = [r for r in archives if r.get("client_id") == client_id]
    return archives


def alerte_rubriques_perimees(client: dict, rapport: dict) -> None:
    """Règle de rétention, versant « recyclage » : des rubriques restées
    telles quelles depuis le dernier rapport archivé referaient dire au
    nouveau rapport le MÊME « ce qui a été fait ». On pose l'alerte sur
    le rapport (badge à l'écran + notification) avant son archivage."""
    if not (rapport.get("fait") or rapport.get("avenir")):
        return  # déjà couvert par l'alerte « rubriques vides »
    derniers = rapports_archives(client.get("id") or "")
    if not derniers:
        return
    if ((client.get("rubriques_maj") or "")
            <= (derniers[-1].get("archive_ts") or "")):
        rapport.setdefault("alertes", []).append(
            "règle de rétention : rubriques inchangées depuis le rapport "
            "précédent — à rafraîchir avant l'envoi")


def rapport_par_id(rapport_id: str) -> dict | None:
    """Retrouve un rapport archivé par son id ("" ou inconnu = None)."""
    if not (rapport_id or "").strip():
        return None
    for r in rapports_archives():
        if r.get("id") == rapport_id:
            return r
    return None


def marquer_envoye(rapport_id: str, email: str) -> dict | None:
    """Marque un rapport archivé comme envoyé au client (date + adresse) :
    l'écran affiche « ✓ envoyé », et un deuxième envoi demande
    confirmation en connaissance de cause."""
    with stockage.VERROU:
        archives = rapports_archives()
        for r in archives:
            if r.get("id") == rapport_id:
                r["envoye_le"] = datetime.now(timezone.utc).isoformat()
                r["envoye_a"] = (email or "").strip().lower()
                if not stockage.ecrire("rapports", archives):
                    raise ValueError("marquage impossible : base partagée "
                                     "injoignable — réessaie dans un moment")
                return r
    return None
