-- Seed : 3 modèles de mails de prospection Pixel Pros, audience='pro'.
--
-- Ces 3 mails ciblent des PROSPECTS DIRECTS (commerces locaux, artisans,
-- cabinets pro), pas des influenceurs. Le pitch est radicalement différent
-- des 5 templates 'creator' : pas de partenariat, pas de commission ; on
-- propose un service (site web) en vente directe.
--
-- Sources Obelisk associées : OpenStreetMap (filtres `restaurants`,
-- `artisans`, `services`, `sante`, `tourisme`, etc.) + à terme tout autre
-- source B2B.
--
-- Variables disponibles : {{name}}, {{first_name}}, {{business_type}}
-- (resto / cabinet / artisan…), {{city}}, {{competitor_example}},
-- {{example_pain}}, {{signature}}, {{link}}.

-- A) Commerces locaux : restos, boutiques, hôtels, salons
insert into public.triskell_email_templates
  (product, key, from_address, from_name, subject, body_html, body_text,
   description, placeholders, enabled, category, audience, label, updated_by)
values (
  'pixel-pros', 'prosp_pp_pro_commerce',
  'contact@triskell-studio.fr', 'Jordan Bourillot',
  'Pour {{name}} — un site qui amène vraiment des clients',
  $$<p>Bonjour,</p>
<p>Je vous écris à propos de {{name}}. J''ai regardé ce que vous proposez à {{city}}, et j''ai trouvé votre {{example_pain}}. Mais en cherchant votre site sur Google, soit je n''ai rien trouvé, soit ce qui sort ne vous rend honnêtement pas justice.</p>
<p>Je dirige Pixel Pros, un studio qui fait des sites web pour les commerces locaux comme le vôtre. Pas un template à 50€ recopié partout : un vrai site, avec votre identité, vos photos, vos horaires, votre carte ou votre catalogue, et qui apparaît bien sur Google quand quelqu''un cherche « {{business_type}} {{city}} ».</p>
<p>Tarif : 1200€ tout compris, livré sous 14 jours. Hébergement et entretien la première année inclus.</p>
<p>Si vous voulez, je vous prépare en 48h un aperçu gratuit de ce que ça donnerait pour vous — concret, avec vos infos. Vous décidez après si ça vous parle.</p>
<p>Cordialement,<br>{{signature}}</p>$$,
  $$Bonjour,

Je vous écris à propos de {{name}}. J'ai regardé ce que vous proposez à {{city}}, et j'ai trouvé votre {{example_pain}}. Mais en cherchant votre site sur Google, soit je n'ai rien trouvé, soit ce qui sort ne vous rend honnêtement pas justice.

Je dirige Pixel Pros, un studio qui fait des sites web pour les commerces locaux comme le vôtre. Pas un template à 50€ recopié partout : un vrai site, avec votre identité, vos photos, vos horaires, votre carte ou votre catalogue, et qui apparaît bien sur Google quand quelqu'un cherche « {{business_type}} {{city}} ».

Tarif : 1200€ tout compris, livré sous 14 jours. Hébergement et entretien la première année inclus.

Si vous voulez, je vous prépare en 48h un aperçu gratuit de ce que ça donnerait pour vous — concret, avec vos infos. Vous décidez après si ça vous parle.

Cordialement,
{{signature}}$$,
  'Template A — Commerces locaux (restos, boutiques, hôtels, salons). Angle : visibilité Google + image. Aperçu gratuit en 48h pour amorcer.',
  '["name","business_type","city","example_pain","signature"]'::jsonb,
  true, 'prospection', 'pro',
  'Template A — Commerces locaux',
  'seed-34b'
)
on conflict (product, key) do update set
  subject = excluded.subject,
  body_html = excluded.body_html,
  body_text = excluded.body_text,
  description = excluded.description,
  placeholders = excluded.placeholders,
  category = excluded.category,
  audience = excluded.audience,
  label = excluded.label,
  updated_at = now(),
  updated_by = excluded.updated_by;


-- B) Artisans (plombiers, électriciens, garagistes, paysagistes…)
insert into public.triskell_email_templates
  (product, key, from_address, from_name, subject, body_html, body_text,
   description, placeholders, enabled, category, audience, label, updated_by)
values (
  'pixel-pros', 'prosp_pp_pro_artisan',
  'contact@triskell-studio.fr', 'Jordan Bourillot',
  'Votre site doit amener des appels — pas juste exister',
  $$<p>Bonjour,</p>
<p>Je tombe sur {{name}} en cherchant un {{business_type}} à {{city}}. Vous êtes visiblement actifs, mais côté présence en ligne, ça n''aide pas un client à vous trouver et à vous choisir.</p>
<p>Je suis Jordan, je dirige Pixel Pros. On fait des sites pensés pour les artisans : pas une vitrine joliment décorée, mais un site qui fait sonner votre téléphone. Concrètement ça veut dire :</p>
<ul>
<li>page de garde claire avec votre zone d''intervention + numéro en gros</li>
<li>section « les avis Google » qui rassure dès la première seconde</li>
<li>formulaire de devis en 30 secondes (les concurrents en mettent un en 7 champs, c''est dissuasif)</li>
<li>vous sortez sur Google sur les recherches « {{business_type}} {{city}} », « urgence {{business_type}} {{city}} », etc.</li>
</ul>
<p>1200€ tout compris, livré en 14 jours. Vous gardez la main, on peut couper la prestation quand vous voulez.</p>
<p>Si vous voulez voir ce que ça donnerait pour vous avant de décider, dites-le moi : je vous monte un aperçu réel en 48h, gratuit, sans engagement.</p>
<p>Cordialement,<br>{{signature}}</p>$$,
  $$Bonjour,

Je tombe sur {{name}} en cherchant un {{business_type}} à {{city}}. Vous êtes visiblement actifs, mais côté présence en ligne, ça n'aide pas un client à vous trouver et à vous choisir.

Je suis Jordan, je dirige Pixel Pros. On fait des sites pensés pour les artisans : pas une vitrine joliment décorée, mais un site qui fait sonner votre téléphone. Concrètement ça veut dire :
- page de garde claire avec votre zone d'intervention + numéro en gros
- section « les avis Google » qui rassure dès la première seconde
- formulaire de devis en 30 secondes (les concurrents en mettent un en 7 champs, c'est dissuasif)
- vous sortez sur Google sur les recherches « {{business_type}} {{city}} », « urgence {{business_type}} {{city}} », etc.

1200€ tout compris, livré en 14 jours. Vous gardez la main, on peut couper la prestation quand vous voulez.

Si vous voulez voir ce que ça donnerait pour vous avant de décider, dites-le moi : je vous monte un aperçu réel en 48h, gratuit, sans engagement.

Cordialement,
{{signature}}$$,
  'Template B — Artisans (plombier, électricien, garagiste, paysagiste, etc.). Angle ROI : un site qui fait sonner le téléphone. Mise en avant des avis Google + référencement local.',
  '["name","business_type","city","signature"]'::jsonb,
  true, 'prospection', 'pro',
  'Template B — Artisans',
  'seed-34b'
)
on conflict (product, key) do update set
  subject = excluded.subject,
  body_html = excluded.body_html,
  body_text = excluded.body_text,
  description = excluded.description,
  placeholders = excluded.placeholders,
  category = excluded.category,
  audience = excluded.audience,
  label = excluded.label,
  updated_at = now(),
  updated_by = excluded.updated_by;


-- C) Cabinets professionnels (avocats, comptables, médecins, kinés, notaires…)
insert into public.triskell_email_templates
  (product, key, from_address, from_name, subject, body_html, body_text,
   description, placeholders, enabled, category, audience, label, updated_by)
values (
  'pixel-pros', 'prosp_pp_pro_cabinet',
  'contact@triskell-studio.fr', 'Jordan Bourillot',
  'Votre image en ligne — un détail qui pèse plus qu''on ne le pense',
  $$<p>Bonjour {{first_name}},</p>
<p>Je vous écris suite à un constat un peu désagréable : en cherchant votre cabinet à {{city}}, votre présence en ligne ne reflète pas le sérieux de ce que vous faites.</p>
<p>Pour un cabinet {{business_type}}, c''est dommage. Un client (ou un patient) qui hésite entre vous et un confrère regarde le site, lit les avis, vérifie la prise de rendez-vous. Si ce parcours est confus ou daté, il bascule chez votre concurrent — souvent sans même vous appeler.</p>
<p>Je gère Pixel Pros, un studio qui crée des sites web pour les professions libérales et les cabinets pros. Le rendu est sobre, clair, conforme aux exigences de votre profession (RGPD, mentions ordinales, prise de RDV intégrée). Pas de design tape-à-l''œil, pas de jargon marketing : un site qui inspire confiance.</p>
<p>Tarif : 1200€ tout compris, livré en 14 jours. La première année d''hébergement et de mises à jour est offerte.</p>
<p>Si l''idée vous intéresse, je vous propose un échange de 15 minutes pour comprendre votre situation actuelle. Aucune obligation derrière.</p>
<p>Cordialement,<br>{{signature}}</p>$$,
  $$Bonjour {{first_name}},

Je vous écris suite à un constat un peu désagréable : en cherchant votre cabinet à {{city}}, votre présence en ligne ne reflète pas le sérieux de ce que vous faites.

Pour un cabinet {{business_type}}, c'est dommage. Un client (ou un patient) qui hésite entre vous et un confrère regarde le site, lit les avis, vérifie la prise de rendez-vous. Si ce parcours est confus ou daté, il bascule chez votre concurrent — souvent sans même vous appeler.

Je gère Pixel Pros, un studio qui crée des sites web pour les professions libérales et les cabinets pros. Le rendu est sobre, clair, conforme aux exigences de votre profession (RGPD, mentions ordinales, prise de RDV intégrée). Pas de design tape-à-l'œil, pas de jargon marketing : un site qui inspire confiance.

Tarif : 1200€ tout compris, livré en 14 jours. La première année d'hébergement et de mises à jour est offerte.

Si l'idée vous intéresse, je vous propose un échange de 15 minutes pour comprendre votre situation actuelle. Aucune obligation derrière.

Cordialement,
{{signature}}$$,
  'Template C — Cabinets professionnels (avocats, comptables, médecins, kinés, notaires…). Angle crédibilité + sérieux. Vouvoiement obligatoire, conformité RGPD/ordinale mentionnée.',
  '["first_name","business_type","city","signature"]'::jsonb,
  true, 'prospection', 'pro',
  'Template C — Cabinets professionnels',
  'seed-34b'
)
on conflict (product, key) do update set
  subject = excluded.subject,
  body_html = excluded.body_html,
  body_text = excluded.body_text,
  description = excluded.description,
  placeholders = excluded.placeholders,
  category = excluded.category,
  audience = excluded.audience,
  label = excluded.label,
  updated_at = now(),
  updated_by = excluded.updated_by;
