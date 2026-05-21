"""Applique une mise en forme HTML sobre aux 5 mails de prospection Pixel Pros.

Lancé une fois pour stylier les body_html en base + re-exporter le JSON
versionné. Le body_text n'est pas touché (déjà propre en texte brut).
"""

from __future__ import annotations

import json
from pathlib import Path
from supabase import create_client


WRAP_OPEN = (
    "<div style=\"max-width:600px;margin:0 auto;"
    "font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif;"
    "color:#2a2a2a;line-height:1.65;font-size:15px;padding:24px 16px;\">"
    # Petit kicker en haut, couleur d'accent Pixel Pros
    "<div style=\"font-size:11px;font-weight:700;letter-spacing:0.18em;"
    "color:#b8860b;margin-bottom:18px;padding-bottom:14px;"
    "border-bottom:2px solid #facc15;\">PIXEL PROS &middot; STUDIO BRETON</div>"
)

# Bouton CTA jaune Pixel Pros — placé juste avant la signature.
CTA_BTN = (
    "<p style=\"margin:24px 0 8px 0;\">"
    "<a href=\"https://pixel-pros.fr\" "
    "style=\"display:inline-block;background:#facc15;color:#2a2a2a;"
    "text-decoration:none;font-weight:700;font-size:14px;"
    "padding:12px 22px;border-radius:8px;"
    "box-shadow:0 2px 0 #b8860b;\">"
    "Découvre Pixel Pros &rarr;</a></p>"
)

WRAP_CLOSE = (
    CTA_BTN
    + "<p style=\"margin-top:24px;margin-bottom:0;font-weight:600;color:#2a2a2a;\">"
    "Jordan</p>\n"
    "<p style=\"margin-top:2px;color:#999;font-size:13px;\">"
    "Pixel Pros &middot; Studio breton</p>\n"
    "</div>"
)


def p(text: str) -> str:
    return f'<p style="margin:0 0 14px 0;">{text}</p>'


# ------------------ Mail 1 — Commission classique ------------------
m1 = WRAP_OPEN + p("Salut {{first_name}},") + p(
    "Je suis tombé sur ton compte et ce que tu fais m'a parlé."
) + p(
    "Avec mon frère Thomas, on tient <strong>Pixel Pros</strong>, un studio breton. "
    "Le concept : on a cassé le marché du site internet pour les indépendants. "
    "<strong>24,90€ HT par mois</strong>, tout compris, livré en <strong>24h</strong>, "
    "sans avance ni engagement. Le client remplit un formulaire de 20 minutes, paie en carte, "
    "et son site est en ligne le lendemain. Là où une agence classique demande "
    "<strong>450 à 1500€ d'avance</strong> pour le même résultat."
) + p(
    "Ce que je te propose : un code promo à ton nom (un truc du genre TONPRÉNOM10 = 10€ de réduc "
    "pour les tiens), et tu touches <strong>20% sur chaque vente</strong> qui passe par toi. "
    "Pas d'engagement, pas de minimum, tu en parles si et quand ça te semble naturel."
) + p(
    "Et rien de ce que je propose là n'est figé. Si tu vois une autre façon de bosser ensemble "
    "qui te conviendrait mieux, dis-le moi — on est totalement ouverts à imaginer un autre format."
) + p("Si l'idée te plaît, dis-moi et on creuse avec plaisir.") + WRAP_CLOSE


# ------------------ Mail 2 — Site offert + commission à vie ------------------
LINKS = [
    ("pauldena.netlify.app", "https://pauldena.netlify.app"),
    ("missor.triskell-studio.fr", "https://missor.triskell-studio.fr"),
    ("elsa-jacquemot.netlify.app", "https://elsa-jacquemot.netlify.app"),
    ("anyme.triskell-studio.fr", "https://anyme.triskell-studio.fr"),
]
links_html = '<ul style="margin:0 0 14px 0;padding-left:20px;">'
for label, url in LINKS:
    links_html += (
        f'<li style="margin:4px 0;"><a href="{url}" '
        f'style="color:#b8860b;text-decoration:none;border-bottom:1px solid #facc15;">{label}</a></li>'
    )
links_html += "</ul>"

m2 = WRAP_OPEN + p("Salut {{first_name}},") + p(
    "Je vais aller droit au but parce que ton temps est certainement très précieux."
) + p(
    "Avec mon frère Thomas, on tient <strong>Pixel Pros</strong>, un studio breton. "
    "Le concept : on a cassé le marché du site internet pour les indépendants. "
    "<strong>24,90€ HT par mois</strong>, tout compris, livré en <strong>24h</strong>, "
    "sans avance ni engagement. On veut que tout le monde puisse avoir le même accès à "
    "un site pro pour le prix d'un forfait de téléphone. Là où une agence classique facture "
    "<strong>450 à 1500€ d'avance</strong> pour le même résultat."
) + p(
    "En tombant sur ton compte, je me suis dit qu'on pourrait faire quelque chose ensemble."
) + p(
    "Ma proposition : on te fait <strong>ton site Pixel Pros, entièrement offert</strong>, "
    "niveau ultra haut de gamme comme on sait faire. Pour te donner une idée du niveau qu'on "
    "propose, voilà quelques sites qu'on a réalisés :"
) + links_html + p(
    "En échange, tu en parles à ton audience comme bon te semble pendant un an, et tu touches "
    "<strong>20% à vie</strong> sur les clients que tu nous amènes."
) + p(
    "Pas de quota de posts, pas de planning imposé. C'est un vrai partenariat."
) + p(
    "Et bien sûr, rien n'est figé là-dedans. Si tu vois une autre forme de partenariat qui te "
    "conviendrait mieux, dis-le moi — on est complètement ouverts à imaginer un autre format ensemble."
) + p("Si ça te parle, on en discute quand tu veux.") + WRAP_CLOSE


# ------------------ Mail 3 — Affiliation ouverte ------------------
m3 = WRAP_OPEN + p("Salut {{first_name}},") + p(
    "Petit message rapide. Avec mon frère Thomas, on vient de lancer le programme d'affiliation "
    "de <strong>Pixel Pros</strong>, notre studio breton."
) + p(
    "Pour te situer : Pixel Pros, c'est le site web pro à <strong>24,90€ HT par mois</strong>, "
    "tout compris, livré en <strong>24h</strong>, sans avance ni engagement. On veut que tout "
    "le monde puisse avoir le même accès à un site pro pour le prix d'un forfait de téléphone. "
    "Le client remplit un formulaire, paie, et a son site le lendemain. À l'inverse des "
    "<strong>450 à 1500€ d'avance</strong> qu'une agence demande pour le même résultat."
) + p(
    "Le principe de l'affiliation est simple : tu récupères un lien personnel à ton nom, et tu "
    "touches <strong>20% sur chaque site vendu via ce lien</strong>. Paiement automatique en fin "
    "de mois, avec un récap de ce que tu as généré."
) + p(
    "Pas de minimum, pas d'exclusivité, pas d'engagement. Tu partages quand ça t'arrange et où "
    "ça te semble pertinent."
) + p(
    "Et si tu vois une façon de bosser ensemble qui sort du programme classique, n'hésite pas à "
    "m'en parler. On est ouverts à imaginer autre chose si t'as une idée qui te conviendrait mieux."
) + p("Si ça t'intéresse, réponds-moi et je t'envoie le lien d'inscription.") + WRAP_CLOSE


# ------------------ Mail 4 — Revenue share gros créateur ------------------
m4 = WRAP_OPEN + p("Salut {{first_name}},") + p(
    "Je te contacte parce que je pense qu'on pourrait faire quelque chose intéressant ensemble."
) + p(
    "Avec mon frère Thomas, on tient <strong>Pixel Pros</strong>, un studio breton. "
    "Le concept est simple, le site web pro à <strong>24,90€ HT par mois</strong>, tout compris, "
    "livré en <strong>24h</strong>, sans avance ni engagement. À la place des "
    "<strong>450 à 1500€ d'avance</strong> qu'une agence demande pour le même résultat. "
    "On veut que tout le monde puisse avoir le même accès à un site pro pour le prix d'un "
    "forfait de téléphone."
) + p(
    "Voilà l'idée : pendant <strong>6 mois</strong>, je te propose "
    "<strong>35% de commission</strong> sur chaque vente qui vient de ton audience. "
    "C'est plus haut que notre programme classique parce que je pense que ton audience peut "
    "générer du volume."
) + p(
    "Comme c'est un taux qu'on ne peut pas tenir sur le long terme, c'est limité à 6 mois. "
    "Ensuite tu peux continuer en programme classique (20%) ou arrêter, comme tu veux."
) + p(
    "Et rien de ce que je propose là n'est figé. Si tu préfères un autre format de partenariat, "
    "dis-le moi — on est totalement ouverts à en discuter."
) + p("Si l'idée te parle, dis-le moi et on en discute avec plaisir.") + WRAP_CLOSE


# ------------------ Mail 5 — Paliers (petit tableau stylé) ------------------
paliers_html = (
    '<table cellpadding="0" cellspacing="0" border="0" '
    'style="border-collapse:separate;border-spacing:0 6px;margin:8px 0 18px 0;width:100%;max-width:380px;">'
    '<tr>'
    '<td style="padding:10px 14px;background:#fef9e7;border-radius:6px;">'
    '<strong>1 à 5 ventes</strong></td>'
    '<td style="padding:10px 14px;background:#fef9e7;border-radius:6px;text-align:right;'
    'color:#b8860b;font-weight:600;">10%</td>'
    '</tr>'
    '<tr>'
    '<td style="padding:10px 14px;background:#fef9e7;border-radius:6px;">'
    '<strong>6 à 20 ventes</strong></td>'
    '<td style="padding:10px 14px;background:#fef9e7;border-radius:6px;text-align:right;'
    'color:#b8860b;font-weight:600;">15%</td>'
    '</tr>'
    '<tr>'
    '<td style="padding:10px 14px;background:#fef9e7;border-radius:6px;">'
    '<strong>21 à 50 ventes</strong></td>'
    '<td style="padding:10px 14px;background:#fef9e7;border-radius:6px;text-align:right;'
    'color:#b8860b;font-weight:600;">20%</td>'
    '</tr>'
    '<tr>'
    '<td style="padding:10px 14px;background:#fef3c7;border:1px solid #facc15;border-radius:6px;">'
    '<strong>Au-delà de 50</strong></td>'
    '<td style="padding:10px 14px;background:#fef3c7;border:1px solid #facc15;border-radius:6px;'
    'text-align:right;color:#b8860b;font-weight:700;">25%</td>'
    '</tr>'
    '</table>'
)

m5_body = WRAP_OPEN + p("Salut {{first_name}},") + p(
    "Avec mon frère Thomas, on tient <strong>Pixel Pros</strong>, un petit studio breton. "
    "On a monté un truc dont on est plutôt fiers : le site web pro à "
    "<strong>24,90€ HT par mois</strong>, tout compris, livré en <strong>24h</strong>, sans "
    "avance ni engagement. Pour les indépendants qui n'ont ni le budget ni l'envie d'une agence "
    "à 3000€. On veut que tout le monde puisse avoir le même accès à un site pro pour le prix "
    "d'un forfait de téléphone."
) + p(
    "Et on a aussi monté un programme d'affiliation où <strong>plus tu en parles, plus tu gagnes "
    "par vente</strong>. C'est notre façon de remercier vraiment les gens qui prennent le temps "
    "de nous porter dans la durée :"
) + paliers_html + p(
    "L'idée, c'est que plus tu en parles sur la durée, plus chaque vente devient rentable pour toi. "
    "C'est fait pour motiver à continuer plutôt qu'à poster une fois et oublier."
) + p(
    "Et si jamais notre format ne te correspond pas, dis-le moi quand même. On est totalement "
    "ouverts à imaginer un autre type de partenariat si t'as une idée qui te conviendrait mieux."
)
m5 = m5_body + (
    CTA_BTN
    + '<p style="margin:18px 0 0 0;">Au plaisir,</p>'
    '<p style="margin-top:8px;margin-bottom:0;font-weight:600;color:#2a2a2a;">Jordan</p>'
    '<p style="margin-top:2px;color:#999;font-size:13px;">Pixel Pros &middot; Studio breton</p>'
    "</div>"
)


UPDATES = {
    "prosp_pp_commission":    m1,
    "prosp_pp_site_offert":   m2,
    "prosp_pp_affiliation":   m3,
    "prosp_pp_revenue_share": m4,
    "prosp_pp_paliers":       m5,
}


def main() -> int:
    cfg = json.loads(
        (Path.home() / ".triskell-command" / "settings.json").read_text(encoding="utf-8")
    )
    c = create_client(cfg["supabase"]["url"], cfg["supabase"]["service_role_key"])

    for key, html in UPDATES.items():
        c.table("triskell_email_templates").update(
            {"body_html": html, "updated_by": "html-soigne-2026-05-20"}
        ).eq("product", "pixel-pros").eq("key", key).execute()
        print(f"OK  {key}  ({len(html)} chars)")

    # Resynchronise le JSON versionné
    rows = (
        c.table("triskell_email_templates")
        .select("key, label, subject, body_html, body_text, description, placeholders")
        .eq("product", "pixel-pros")
        .eq("category", "prospection")
        .order("key")
        .execute()
        .data
    )
    out = Path(__file__).resolve().parent / "_prospection_pixel_pros_data.json"
    out.write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\nJSON re-exporté ({len(rows)} mails) dans {out.name}.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
