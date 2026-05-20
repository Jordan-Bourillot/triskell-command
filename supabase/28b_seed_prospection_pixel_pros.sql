-- Seed : 5 modèles de mails de prospection pour Pixel Pros.
--
-- Ces 5 mails ont été rédigés en chat avec Claude pour démarcher des
-- créateurs / influenceurs et leur proposer 5 façons différentes de gagner
-- de l'argent en parlant de Pixel Pros (commission, site offert, affiliation
-- ouverte, revenue share, paliers gamification). Ils sont rangés sous le
-- produit `pixel-pros` du catalogue Triskell, en category 'prospection'.
--
-- Variables disponibles dans tous les mails : {{name}}, {{first_name}},
-- {{domain}}, {{example_content}}, {{price}}, {{signature}}, {{link}}.
-- Ces variables sont remplacées à la main au moment de l'envoi (ou par un
-- futur composeur dédié à la prospection).

-- 1) Commission classique
insert into public.triskell_email_templates
  (product, key, from_address, from_name, subject, body_html, body_text,
   description, placeholders, enabled, category, label, updated_by)
values (
  'pixel-pros', 'prosp_pp_commission',
  'contact@triskell-studio.fr', 'Jordan Bourillot',
  'Une idée pour monétiser ton audience sans rien changer à ton contenu',
  $$<p>Salut {{first_name}},</p>
<p>Je suis tombé sur ta chaîne en cherchant du contenu autour de {{domain}}, et ton angle sur {{example_content}} m''a parlé.</p>
<p>Je tiens Pixel Pros, un studio qui fait des sites web pros pour les indépendants et petites entreprises, livrés clé en main. La cible recoupe pas mal ton audience.</p>
<p>Je te propose un truc simple : un code promo à ton nom (genre {{first_name}}50 = 50€ de réduc pour les tiens), et tu touches 15% sur chaque vente. Aucun engagement, tu en parles quand ça te semble naturel.</p>
<p>Si ça t''intéresse, je t''envoie un exemple concret de ce que ça donne en chiffres sur ta taille d''audience.</p>
<p>Bonne journée,<br>{{signature}}</p>$$,
  $$Salut {{first_name}},

Je suis tombé sur ta chaîne en cherchant du contenu autour de {{domain}}, et ton angle sur {{example_content}} m'a parlé.

Je tiens Pixel Pros, un studio qui fait des sites web pros pour les indépendants et petites entreprises, livrés clé en main. La cible recoupe pas mal ton audience.

Je te propose un truc simple : un code promo à ton nom (genre {{first_name}}50 = 50€ de réduc pour les tiens), et tu touches 15% sur chaque vente. Aucun engagement, tu en parles quand ça te semble naturel.

Si ça t'intéresse, je t'envoie un exemple concret de ce que ça donne en chiffres sur ta taille d'audience.

Bonne journée,
{{signature}}$$,
  'Mail 1 — Commission classique (volume, créateurs moyens). Code promo nominatif, 15% de commission par vente. Pas d''engagement.',
  '["first_name","domain","example_content","signature"]'::jsonb,
  true, 'prospection',
  'Mail 1 — Commission classique',
  'seed-28b'
)
on conflict (product, key) do update set
  subject = excluded.subject,
  body_html = excluded.body_html,
  body_text = excluded.body_text,
  description = excluded.description,
  placeholders = excluded.placeholders,
  category = excluded.category,
  label = excluded.label,
  updated_at = now(),
  updated_by = excluded.updated_by;


-- 2) Site offert + commission à vie
insert into public.triskell_email_templates
  (product, key, from_address, from_name, subject, body_html, body_text,
   description, placeholders, enabled, category, label, updated_by)
values (
  'pixel-pros', 'prosp_pp_site_offert',
  'contact@triskell-studio.fr', 'Jordan Bourillot',
  'Je t''offre ton site pro — proposition sérieuse, pas un mailing',
  $$<p>Salut {{first_name}},</p>
<p>Je te contacte avec une proposition que j''envoie à peu de personnes, donc je vais aller droit au but.</p>
<p>Je gère Pixel Pros, un studio qui crée des sites web pros pour les indépendants. En regardant ton compte, je me suis dit que tu aurais mérité un vrai site à la hauteur de ton image — pas un Linktree ou un site bricolé.</p>
<p>Ma proposition : je te fais ton site pro, entièrement offert (valeur 1200€). En contrepartie, tu en parles à ton audience comme bon te semble pendant un an, et tu touches 15% à vie sur les clients que tu nous amènes.</p>
<p>Pas de scénario imposé, pas de post obligatoire chaque mois. Juste un vrai partenariat entre nous.</p>
<p>Si l''idée te parle, on s''appelle 15 minutes pour que je te montre ce qu''on ferait pour toi.</p>
<p>{{signature}}</p>$$,
  $$Salut {{first_name}},

Je te contacte avec une proposition que j'envoie à peu de personnes, donc je vais aller droit au but.

Je gère Pixel Pros, un studio qui crée des sites web pros pour les indépendants. En regardant ton compte, je me suis dit que tu aurais mérité un vrai site à la hauteur de ton image — pas un Linktree ou un site bricolé.

Ma proposition : je te fais ton site pro, entièrement offert (valeur 1200€). En contrepartie, tu en parles à ton audience comme bon te semble pendant un an, et tu touches 15% à vie sur les clients que tu nous amènes.

Pas de scénario imposé, pas de post obligatoire chaque mois. Juste un vrai partenariat entre nous.

Si l'idée te parle, on s'appelle 15 minutes pour que je te montre ce qu'on ferait pour toi.

{{signature}}$$,
  'Mail 2 — Site offert + commission à vie. Approche premium pour créateurs ciblés. Site gratuit en échange de communication + 15% à vie.',
  '["first_name","signature"]'::jsonb,
  true, 'prospection',
  'Mail 2 — Site offert + commission à vie',
  'seed-28b'
)
on conflict (product, key) do update set
  subject = excluded.subject,
  body_html = excluded.body_html,
  body_text = excluded.body_text,
  description = excluded.description,
  placeholders = excluded.placeholders,
  category = excluded.category,
  label = excluded.label,
  updated_at = now(),
  updated_by = excluded.updated_by;


-- 3) Affiliation ouverte
insert into public.triskell_email_templates
  (product, key, from_address, from_name, subject, body_html, body_text,
   description, placeholders, enabled, category, label, updated_by)
values (
  'pixel-pros', 'prosp_pp_affiliation',
  'contact@triskell-studio.fr', 'Jordan Bourillot',
  'On lance un programme d''affiliation — tu peux en être en 2 minutes',
  $$<p>Salut {{first_name}},</p>
<p>Petit message rapide pour te prévenir qu''on vient de lancer le programme d''affiliation Pixel Pros.</p>
<p>Le principe est tout bête : tu t''inscris en deux minutes sur notre page, tu récupères ton lien personnel, et tu touches 10% sur chaque site vendu via ce lien. Tableau de bord en direct pour suivre tes gains, paiement automatique en fin de mois.</p>
<p>Pas de minimum à atteindre, pas d''exclusivité, pas d''engagement. Tu partages quand ça t''arrange et où ça te semble pertinent.</p>
<p>Si ça te dit, le lien d''inscription est ici : {{link}}. Et si tu veux en discuter avant de t''inscrire, je suis dispo.</p>
<p>{{signature}}</p>$$,
  $$Salut {{first_name}},

Petit message rapide pour te prévenir qu'on vient de lancer le programme d'affiliation Pixel Pros.

Le principe est tout bête : tu t'inscris en deux minutes sur notre page, tu récupères ton lien personnel, et tu touches 10% sur chaque site vendu via ce lien. Tableau de bord en direct pour suivre tes gains, paiement automatique en fin de mois.

Pas de minimum à atteindre, pas d'exclusivité, pas d'engagement. Tu partages quand ça t'arrange et où ça te semble pertinent.

Si ça te dit, le lien d'inscription est ici : {{link}}. Et si tu veux en discuter avant de t'inscrire, je suis dispo.

{{signature}}$$,
  'Mail 3 — Affiliation ouverte. Annonce du programme à grande échelle. 10% par vente, libre service.',
  '["first_name","link","signature"]'::jsonb,
  true, 'prospection',
  'Mail 3 — Affiliation ouverte',
  'seed-28b'
)
on conflict (product, key) do update set
  subject = excluded.subject,
  body_html = excluded.body_html,
  body_text = excluded.body_text,
  description = excluded.description,
  placeholders = excluded.placeholders,
  category = excluded.category,
  label = excluded.label,
  updated_at = now(),
  updated_by = excluded.updated_by;


-- 4) Revenue share gros créateur
insert into public.triskell_email_templates
  (product, key, from_address, from_name, subject, body_html, body_text,
   description, placeholders, enabled, category, label, updated_by)
values (
  'pixel-pros', 'prosp_pp_revenue_share',
  'contact@triskell-studio.fr', 'Jordan Bourillot',
  'Un deal court et juteux — uniquement pour toi',
  $$<p>Salut {{first_name}},</p>
<p>Je vais être franc : je t''écris parce que ton audience colle exactement à ce qu''on vend, et que tu as la taille pour faire bouger les chiffres pour de vrai.</p>
<p>Je tiens Pixel Pros, on fait des sites web pros pour les indépendants. Le panier moyen tourne autour de {{price}}€.</p>
<p>Ma proposition, claire : pendant 3 mois, tu touches 35% sur chaque vente venue de ton audience. Sur ta taille, si tu pousses sérieusement, on parle de plusieurs milliers d''euros par mois pour toi. Après les 3 mois, tu peux continuer avec nous en programme classique ou arrêter, comme tu veux.</p>
<p>Je te garantis qu''aucun autre créateur de ton niveau n''aura ce deal en même temps que toi — j''en sélectionne un par trimestre.</p>
<p>Si tu veux en parler, 20 minutes en visio cette semaine ?</p>
<p>{{signature}}</p>$$,
  $$Salut {{first_name}},

Je vais être franc : je t'écris parce que ton audience colle exactement à ce qu'on vend, et que tu as la taille pour faire bouger les chiffres pour de vrai.

Je tiens Pixel Pros, on fait des sites web pros pour les indépendants. Le panier moyen tourne autour de {{price}}€.

Ma proposition, claire : pendant 3 mois, tu touches 35% sur chaque vente venue de ton audience. Sur ta taille, si tu pousses sérieusement, on parle de plusieurs milliers d'euros par mois pour toi. Après les 3 mois, tu peux continuer avec nous en programme classique ou arrêter, comme tu veux.

Je te garantis qu'aucun autre créateur de ton niveau n'aura ce deal en même temps que toi — j'en sélectionne un par trimestre.

Si tu veux en parler, 20 minutes en visio cette semaine ?

{{signature}}$$,
  'Mail 4 — Revenue share gros créateur (50k-500k abonnés). Deal exclusif 3 mois à 35% de commission. 1 créateur par trimestre.',
  '["first_name","price","signature"]'::jsonb,
  true, 'prospection',
  'Mail 4 — Revenue share gros créateur',
  'seed-28b'
)
on conflict (product, key) do update set
  subject = excluded.subject,
  body_html = excluded.body_html,
  body_text = excluded.body_text,
  description = excluded.description,
  placeholders = excluded.placeholders,
  category = excluded.category,
  label = excluded.label,
  updated_at = now(),
  updated_by = excluded.updated_by;


-- 5) Paliers gamification
insert into public.triskell_email_templates
  (product, key, from_address, from_name, subject, body_html, body_text,
   description, placeholders, enabled, category, label, updated_by)
values (
  'pixel-pros', 'prosp_pp_paliers',
  'contact@triskell-studio.fr', 'Jordan Bourillot',
  'Le programme où plus tu pousses, plus tu gagnes — pour de vrai',
  $$<p>Salut {{first_name}},</p>
<p>La plupart des programmes d''affiliation te paient pareil que tu fasses 1 vente ou 50. Le nôtre est construit à l''envers.</p>
<p>Chez Pixel Pros (studio de sites web pros pour indépendants), voilà comment ça marche :</p>
<ul>
  <li>De 1 à 5 ventes : 10%</li>
  <li>De 6 à 20 ventes : 15%</li>
  <li>De 21 à 50 ventes : 20%</li>
  <li>Au-delà de 50 : 25% + 1000€ de bonus</li>
</ul>
<p>Ton tableau de bord te montre en direct où tu en es et combien il te reste pour passer au palier suivant. Beaucoup de nos ambassadeurs nous disent que c''est ça qui les motive à continuer à en parler plutôt que de poster une fois et oublier.</p>
<p>Si tu veux le lien d''inscription ou en savoir plus, dis-moi.</p>
<p>{{signature}}</p>$$,
  $$Salut {{first_name}},

La plupart des programmes d'affiliation te paient pareil que tu fasses 1 vente ou 50. Le nôtre est construit à l'envers.

Chez Pixel Pros (studio de sites web pros pour indépendants), voilà comment ça marche :
- De 1 à 5 ventes : 10%
- De 6 à 20 ventes : 15%
- De 21 à 50 ventes : 20%
- Au-delà de 50 : 25% + 1000€ de bonus

Ton tableau de bord te montre en direct où tu en es et combien il te reste pour passer au palier suivant. Beaucoup de nos ambassadeurs nous disent que c'est ça qui les motive à continuer à en parler plutôt que de poster une fois et oublier.

Si tu veux le lien d'inscription ou en savoir plus, dis-moi.

{{signature}}$$,
  'Mail 5 — Paliers gamification. Motivation longue durée, commission qui grimpe avec le volume, bonus 1000€ au-delà de 50 ventes.',
  '["first_name","signature"]'::jsonb,
  true, 'prospection',
  'Mail 5 — Paliers gamification',
  'seed-28b'
)
on conflict (product, key) do update set
  subject = excluded.subject,
  body_html = excluded.body_html,
  body_text = excluded.body_text,
  description = excluded.description,
  placeholders = excluded.placeholders,
  category = excluded.category,
  label = excluded.label,
  updated_at = now(),
  updated_by = excluded.updated_by;
