# -*- coding: utf-8 -*-
"""Installe les modèles de prospection « pro » en plusieurs versions variées.

Demande Jordan (14/06/2026) : « prépare des versions variées + retravaille
les objets, plusieurs versions, je n'aime pas qu'on parle de 1500 € ».

→ 3 versions Commerces + 3 versions Artisans (angles différents), objets
variés, AUCUNE mention de prix d'agence (1500 €), chacune avec l'aperçu de
site {{apercu_site}} avant les boutons. Même charte dorée que l'existant.
Le modèle Cabinets reste tel quel (pas de démo qui colle).

Les clés _commerce / _artisan (sans suffixe) = version 1 (elles écrasent les
anciens modèles, dont l'artisan qui citait « 450 à 1500 € »). Les variantes
ajoutent le suffixe _2 / _3. L'auto-pilote pioche ensuite la bonne catégorie
selon le métier (cf. triskell-core pipeline `_pro_category`) puis fait tourner
les 3 versions.

Upsert COMPLET (toutes les colonnes) — jamais d'upsert partiel sur
triskell_email_templates (NULL → casse, leçon du 11/06/2026).

Usage :
    python scripts/seed_pro_variants.py            (test à blanc)
    python scripts/seed_pro_variants.py --apply    (écrit en base)
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from supabase import create_client  # noqa: E402

OFFER = ("<strong>24,90&euro; HT par mois</strong>, tout compris, livré en "
         "<strong>24h</strong>, sans engagement")

# (clé, libellé, objet, [paragraphes avant l'aperçu], phrase juste avant l'image,
#  [paragraphes après l'aperçu])
COMMERCE = [
    ("prosp_pp_pro_commerce", "Commerces — V1 (visibilité Google)",
     "Quand on cherche {{business_type}} à {{city}}, est-ce qu'on vous trouve ?",
     ["Bonjour,",
      "Petit message rapide. Avec mon frère Thomas, je dirige <strong>Pixel Pros</strong>, un studio web breton.",
      "Aujourd'hui, quand quelqu'un cherche « {{business_type}} {{city}} » sur Google, c'est souvent un concurrent qui ressort. Pour <strong>{{name}}</strong>, c'est dommage : des clients passent à côté de vous sans le savoir.",
      "On crée des sites clairs et rapides, pensés pour qu'on vous trouve. " + OFFER + "."],
     "Pour vous donner une idée concrète, voici à quoi pourrait ressembler votre site :",
     []),
    ("prosp_pp_pro_commerce_2", "Commerces — V2 (on a imaginé votre vitrine)",
     "On a imaginé le site de {{name}}",
     ["Bonjour,",
      "Avec mon frère Thomas, on tient <strong>Pixel Pros</strong>, un studio web en Bretagne.",
      "En découvrant <strong>{{name}}</strong>, on s'est dit que votre activité méritait une vraie vitrine en ligne — aussi soignée que ce que vous proposez à {{city}}. Alors on en a préparé un aperçu, juste pour vous montrer l'idée."],
     "Le voici :",
     ["Un site comme celui-ci : " + OFFER + ". Vos photos, vos infos, votre identité."]),
    ("prosp_pp_pro_commerce_3", "Commerces — V3 (simple et accessible)",
     "Un site pro pour {{name}}, sans prise de tête",
     ["Bonjour,",
      "Petit message rapide. Je dirige <strong>Pixel Pros</strong> avec mon frère Thomas, un studio web breton.",
      "Notre idée : qu'un commerce comme <strong>{{name}}</strong> puisse avoir un vrai site pro pour le prix d'un forfait de téléphone. " + OFFER + ".",
      "Pas de dossier compliqué : vous nous donnez vos infos, on s'occupe du reste."],
     "Pour vous donner une idée concrète, voici à quoi pourrait ressembler votre site :",
     []),
]

ARTISAN = [
    ("prosp_pp_pro_artisan", "Artisans — V1 (faire sonner le téléphone)",
     "Un site qui fait sonner le téléphone de {{name}}",
     ["Bonjour,",
      "Avec mon frère Thomas, je dirige <strong>Pixel Pros</strong>, un studio web breton.",
      "Pour un {{business_type}}, un site ne sert pas à faire joli : il sert à faire sonner le téléphone. Le nôtre met en avant votre zone d'intervention, vos avis, et un moyen simple de vous appeler ou de demander un devis.",
      OFFER.capitalize() + "."],
     "Pour vous donner une idée concrète, voici à quoi pourrait ressembler votre site :",
     []),
    ("prosp_pp_pro_artisan_2", "Artisans — V2 (visible sur Google en local)",
     "Sortir sur « {{business_type}} {{city}} » sur Google",
     ["Bonjour,",
      "Petit message rapide. Je dirige <strong>Pixel Pros</strong> avec mon frère Thomas, studio web breton.",
      "Quand quelqu'un cherche un {{business_type}} à {{city}} — parfois en urgence — tout se joue en ligne. Si <strong>{{name}}</strong> n'apparaît pas, l'appel part chez un autre.",
      "On fait des sites taillés pour le référencement local, pour que vous remontiez sur les bonnes recherches. " + OFFER + "."],
     "Pour vous donner une idée concrète, voici à quoi pourrait ressembler votre site :",
     []),
    ("prosp_pp_pro_artisan_3", "Artisans — V3 (en ligne en 24h, simplement)",
     "Le site de {{name}} en ligne en 24h",
     ["Bonjour,",
      "Avec mon frère Thomas, on tient <strong>Pixel Pros</strong>, un studio breton.",
      "On rend le site web simple pour les artisans : vous nous donnez vos infos, votre site est en ligne le lendemain. Sans avance, sans engagement — <strong>24,90&euro; HT par mois</strong> tout compris."],
     "Pour vous montrer, voici à quoi pourrait ressembler le vôtre :",
     []),
]

WRAP_OPEN = ('<div style="max-width:600px;margin:0 auto;font-family:-apple-system,'
             "BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif;color:#2a2a2a;"
             'line-height:1.65;font-size:15px;padding:24px 16px;">')
HEADER = ('<div style="font-size:11px;font-weight:700;letter-spacing:0.18em;'
          'color:#b8860b;margin-bottom:18px;padding-bottom:14px;'
          'border-bottom:2px solid #facc15;">PIXEL PROS &middot; STUDIO BRETON</div>')
BUTTONS = ('<p style="margin:24px 0 8px 0;"><a href="{{page_metier}}" '
           'style="display:inline-block;background:#facc15;color:#2a2a2a;'
           "text-decoration:none;font-weight:700;font-size:14px;padding:12px 22px;"
           'border-radius:8px;box-shadow:0 2px 0 #b8860b;">Découvrir Pixel Pros &rarr;</a> '
           '<a href="{{page_demo}}" style="display:inline-block;background:#fffaf0;'
           "color:#b8860b;text-decoration:none;font-weight:700;font-size:14px;"
           'padding:11px 21px;border-radius:8px;border:1px solid #facc15;'
           'margin-left:8px;">Voir un exemple &rarr;</a></p>')
SIG = ('<p style="margin-top:24px;margin-bottom:0;font-weight:600;color:#2a2a2a;">'
       'Jordan</p><p style="margin-top:2px;color:#999;font-size:13px;">'
       'Pixel Pros &middot; Studio breton</p>')


def _p(t):
    return '<p style="margin:0 0 14px 0;">' + t + "</p>"


def build_html(pre, leadin, post):
    parts = [WRAP_OPEN, HEADER]
    parts += [_p(t) for t in pre]
    parts.append(_p(leadin) + "{{apercu_site}}")
    parts += [_p(t) for t in post]
    parts += [BUTTONS, SIG, "</div>"]
    return "".join(parts)


def _plain(s):
    s = re.sub(r"<[^>]+>", "", s)
    return (s.replace("&euro;", "€").replace("&middot;", "·")
            .replace("&rarr;", "→").replace("&amp;", "&").replace("&nbsp;", " "))


def build_text(pre, leadin, post):
    lines = [_plain(t) for t in pre]
    lines.append(_plain(leadin))
    lines += [_plain(t) for t in post]
    lines.append("Un exemple en ligne : {{page_demo}}")
    lines.append("Jordan\nPixel Pros · Studio breton")
    return "\n\n".join(lines)


def main() -> int:
    apply = "--apply" in sys.argv
    cfg = json.loads((Path.home() / ".triskell-command" / "settings.json")
                     .read_text(encoding="utf-8"))
    sb = create_client(cfg["supabase"]["url"], cfg["supabase"]["service_role_key"])

    # Reprend l'expéditeur exact de l'existant (contact@pixel-pros.fr).
    cur = (sb.table("triskell_email_templates")
           .select("from_address, from_name")
           .eq("product", "pixel-pros").eq("key", "prosp_pp_pro_commerce")
           .limit(1).execute().data)
    from_address = (cur[0].get("from_address") if cur else "") or "contact@pixel-pros.fr"
    from_name = (cur[0].get("from_name") if cur else "") or "Pixel Pros"
    print("expéditeur :", from_name, "<" + from_address + ">\n")

    rows = []
    for cat, group in (("commerce", COMMERCE), ("artisan", ARTISAN)):
        for key, label, subject, pre, leadin, post in group:
            rows.append({
                "product": "pixel-pros", "key": key,
                "from_address": from_address, "from_name": from_name,
                "subject": subject,
                "body_html": build_html(pre, leadin, post),
                "body_text": build_text(pre, leadin, post),
                "description": label + " — aperçu de site inclus, sans mention de prix d'agence.",
                "placeholders": ["name", "business_type", "city", "apercu_site"],
                "enabled": True, "category": "prospection", "audience": "pro",
                "label": label, "updated_by": "apercu-variants-2026-06-14",
            })

    for r in rows:
        print(f"  {r['key']:26} | {r['label']}")
        print(f"     objet : {r['subject']}")
    print()

    if apply:
        for r in rows:
            sb.table("triskell_email_templates").upsert(
                r, on_conflict="product,key").execute()
        print(f"{len(rows)} modèles écrits (upsert complet).")
    else:
        print("(test à blanc — relancer avec --apply pour écrire)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
