# -*- coding: utf-8 -*-
"""Réécrit en profondeur les 4 modèles de prospection Pixel Pros (commerce +
3 artisan) pour les rendre plus percutants et mieux ancrés (ville + métier +
nom), SANS toucher à l'offre, au ton, ni à la structure HTML (en-tête, aperçu
du site {{apercu_site}}, boutons, signature).

UPDATE (pas upsert) des seules colonnes subject / body_text / body_html :
les autres colonnes restent intactes (pas de NULL qui casse).

Usage :
    python -X utf8 scripts/improve_templates.py            # TEST (montre, n'écrit pas)
    python -X utf8 scripts/improve_templates.py --apply     # enregistre les 4 modèles
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT.parent / "triskell-core"))

from triskell_core.db import get_client  # noqa: E402

APPLY = "--apply" in sys.argv

_HEAD = ('<div style="max-width:600px;margin:0 auto;font-family:-apple-system,'
         "BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif;color:#2a2a2a;"
         'line-height:1.65;font-size:15px;padding:24px 16px;">'
         '<div style="font-size:11px;font-weight:700;letter-spacing:0.18em;'
         'color:#b8860b;margin-bottom:18px;padding-bottom:14px;'
         'border-bottom:2px solid #facc15;">PIXEL PROS &middot; STUDIO BRETON</div>')

_FOOT = ('<p style="margin:24px 0 8px 0;">'
         '<a href="{{page_metier}}" style="display:inline-block;background:#facc15;'
         'color:#2a2a2a;text-decoration:none;font-weight:700;font-size:14px;'
         'padding:12px 22px;border-radius:8px;box-shadow:0 2px 0 #b8860b;">'
         'Découvrir Pixel Pros &rarr;</a> '
         '<a href="{{page_demo}}" style="display:inline-block;background:#fffaf0;'
         'color:#b8860b;text-decoration:none;font-weight:700;font-size:14px;'
         'padding:11px 21px;border-radius:8px;border:1px solid #facc15;'
         'margin-left:8px;">Voir un exemple &rarr;</a></p>'
         '<p style="margin-top:24px;margin-bottom:0;font-weight:600;color:#2a2a2a;">Jordan</p>'
         '<p style="margin-top:2px;color:#999;font-size:13px;">Pixel Pros &middot; Studio breton</p>'
         '</div>')


def _html(paragraphs: list[str]) -> str:
    """Assemble en-tête + paragraphes + aperçu du site + boutons + signature."""
    body = "".join(f'<p style="margin:0 0 14px 0;">{p}</p>' for p in paragraphs)
    return _HEAD + body + "{{apercu_site}}" + _FOOT


def _text(paragraphs_txt: list[str]) -> str:
    """Version texte : paragraphes + lien exemple + signature."""
    return ("\n\n".join(paragraphs_txt)
            + "\n\nUn exemple en ligne : {{page_demo}}"
            + "\n\nJordan\nPixel Pros · Studio breton")


MODELS = {
    # 1) COMMERCE — angle « visibilité locale sur Google »
    "prosp_pp_pro_commerce": {
        "subject": "Quand on cherche {{business_type}} à {{city}}, est-ce qu'on vous trouve ?",
        "txt": [
            "Bonjour,",
            "Avec mon frère Thomas, je tiens Pixel Pros, un petit studio web breton.",
            "À {{city}}, dès qu'on tape « {{business_type}} » sur Google, c'est souvent "
            "un concurrent qui sort en premier — et {{name}} reste invisible. Résultat : "
            "des clients du quartier passent à côté de vous sans même savoir que vous existez.",
            "Notre métier, c'est de remettre votre nom devant : un site clair et rapide, "
            "avec vos horaires, vos avis et un bouton d'appel bien en vue. 24,90€ HT par "
            "mois, tout compris, livré en 24h, sans engagement.",
            "Pour que ce soit concret, voici à quoi pourrait ressembler le vôtre :",
        ],
        "html_p": [
            "Bonjour,",
            "Avec mon frère Thomas, je tiens <strong>Pixel Pros</strong>, un petit studio web breton.",
            "À <strong>{{city}}</strong>, dès qu'on tape « {{business_type}} » sur Google, "
            "c'est souvent un concurrent qui sort en premier — et <strong>{{name}}</strong> "
            "reste invisible. Résultat : des clients du quartier passent à côté de vous sans "
            "même savoir que vous existez.",
            "Notre métier, c'est de remettre votre nom devant : un site clair et rapide, avec "
            "vos horaires, vos avis et un bouton d'appel bien en vue. <strong>24,90&euro; HT "
            "par mois</strong>, tout compris, livré en <strong>24h</strong>, sans engagement.",
            "Pour que ce soit concret, voici à quoi pourrait ressembler le vôtre :",
        ],
    },
    # 2) ARTISAN — angle « faire sonner le téléphone »
    "prosp_pp_pro_artisan": {
        "subject": "Un site qui fait sonner le téléphone de {{name}}",
        "txt": [
            "Bonjour,",
            "Avec mon frère Thomas, je tiens Pixel Pros, un petit studio web breton.",
            "Pour un {{business_type}} à {{city}}, un site ne sert pas à faire joli — il sert "
            "à faire sonner le téléphone. Le nôtre met en avant votre zone d'intervention, vos "
            "réalisations et vos avis, avec un numéro et un bouton « devis » qu'on trouve en "
            "deux secondes.",
            "C'est exactement ce qu'un client regarde avant de vous appeler. 24,90€ HT par "
            "mois, tout compris, livré en 24h, sans engagement.",
            "Pour que ce soit concret, voici à quoi pourrait ressembler le site de {{name}} :",
        ],
        "html_p": [
            "Bonjour,",
            "Avec mon frère Thomas, je tiens <strong>Pixel Pros</strong>, un petit studio web breton.",
            "Pour un {{business_type}} à <strong>{{city}}</strong>, un site ne sert pas à faire "
            "joli — il sert à faire sonner le téléphone. Le nôtre met en avant votre zone "
            "d'intervention, vos réalisations et vos avis, avec un numéro et un bouton "
            "« devis » qu'on trouve en deux secondes.",
            "C'est exactement ce qu'un client regarde avant de vous appeler. <strong>24,90&euro; "
            "HT par mois</strong>, tout compris, livré en <strong>24h</strong>, sans engagement.",
            "Pour que ce soit concret, voici à quoi pourrait ressembler le site de <strong>{{name}}</strong> :",
        ],
    },
    # 3) ARTISAN #2 — angle « recherche / urgence »
    "prosp_pp_pro_artisan_2": {
        "subject": "À {{city}}, vos clients vous cherchent sur Google — vous trouvent-ils ?",
        "txt": [
            "Bonjour,",
            "Je tiens Pixel Pros avec mon frère Thomas, un petit studio web breton.",
            "Quand quelqu'un cherche un {{business_type}} à {{city}} — souvent pressé, parfois "
            "en urgence — tout se joue dans les premières secondes sur Google. Si {{name}} "
            "n'apparaît pas, l'appel file droit chez le concurrent d'à côté.",
            "On fait des sites taillés pour qu'on vous trouve : bien placés, rapides, avec un "
            "bouton d'appel et un formulaire de devis évidents. 24,90€ HT par mois, tout "
            "compris, livré en 24h, sans engagement.",
            "Pour que ce soit concret, voici à quoi pourrait ressembler le vôtre :",
        ],
        "html_p": [
            "Bonjour,",
            "Je tiens <strong>Pixel Pros</strong> avec mon frère Thomas, un petit studio web breton.",
            "Quand quelqu'un cherche un {{business_type}} à <strong>{{city}}</strong> — souvent "
            "pressé, parfois en urgence — tout se joue dans les premières secondes sur Google. "
            "Si <strong>{{name}}</strong> n'apparaît pas, l'appel file droit chez le concurrent "
            "d'à côté.",
            "On fait des sites taillés pour qu'on vous trouve : bien placés, rapides, avec un "
            "bouton d'appel et un formulaire de devis évidents. <strong>24,90&euro; HT par "
            "mois</strong>, tout compris, livré en <strong>24h</strong>, sans engagement.",
            "Pour que ce soit concret, voici à quoi pourrait ressembler le vôtre :",
        ],
    },
    # 4) ARTISAN #3 — angle « simplicité / en ligne en 24h »
    "prosp_pp_pro_artisan_3": {
        "subject": "Le site de {{name}} en ligne en 24h",
        "txt": [
            "Bonjour,",
            "Avec mon frère Thomas, on tient Pixel Pros, un petit studio web breton.",
            "On a rendu le site web simple pour les artisans comme {{name}} : vous nous donnez "
            "vos infos, on s'occupe de tout, et votre site de {{business_type}} à {{city}} est "
            "en ligne dès le lendemain. Pas d'avance à payer, pas d'engagement — 24,90€ HT par "
            "mois, tout compris.",
            "Pour que ce soit concret, voici à quoi pourrait ressembler le vôtre :",
        ],
        "html_p": [
            "Bonjour,",
            "Avec mon frère Thomas, on tient <strong>Pixel Pros</strong>, un petit studio web breton.",
            "On a rendu le site web simple pour les artisans comme <strong>{{name}}</strong> : "
            "vous nous donnez vos infos, on s'occupe de tout, et votre site de {{business_type}} "
            "à <strong>{{city}}</strong> est en ligne dès le lendemain. Pas d'avance à payer, "
            "pas d'engagement — <strong>24,90&euro; HT par mois</strong>, tout compris.",
            "Pour que ce soit concret, voici à quoi pourrait ressembler le vôtre :",
        ],
    },
}


def main() -> int:
    c = get_client()
    if not getattr(c, "is_authenticated", False):
        try:
            c.restore_session()
        except Exception:
            pass
    if not getattr(c, "is_authenticated", False):
        print("Pas connecté à la base."); return 2
    sb = c.raw

    print("MODE : ECRITURE REELLE" if APPLY else "MODE : TEST (rien ecrit)")
    written = 0
    for key, m in MODELS.items():
        body_text = _text(m["txt"])
        body_html = _html(m["html_p"])
        # Garde-fous : tous les placeholders clés doivent rester présents
        manque = [ph for ph in ("{{apercu_site}}", "{{page_metier}}", "{{page_demo}}")
                  if ph not in body_html]
        print("=" * 72)
        print(f"KEY     : {key}")
        print(f"SUBJECT : {m['subject']}")
        print(f"placeholders OK : {'oui' if not manque else 'MANQUE ' + str(manque)}")
        print("--- nouveau texte ---")
        print(body_text)
        if APPLY:
            try:
                sb.table("triskell_email_templates").update({
                    "subject": m["subject"],
                    "body_text": body_text,
                    "body_html": body_html,
                }).eq("key", key).execute()
                written += 1
            except Exception as e:
                print(f"  ! ecriture KO : {e}")
    print("=" * 72)
    if APPLY:
        print(f"{written}/{len(MODELS)} modele(s) enregistre(s).")
    else:
        print("(TEST : rien ecrit. --apply pour enregistrer les 4 modeles.)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
