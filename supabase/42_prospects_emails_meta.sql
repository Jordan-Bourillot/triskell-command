-- =====================================================================
-- Prospects — Trackage de la source de CHAQUE email
-- =====================================================================
-- Jusqu'ici on stockait juste une liste plate d'emails (`emails jsonb`)
-- sans savoir d'où venait chaque adresse. Du coup, quand l'autopilote
-- générait un mail, l'IA n'avait aucune idée de l'origine de l'adresse
-- de contact qu'elle utilisait — alors qu'un mail trouvé sur une page
-- « mentions légales » d'un site pro n'a pas le même contexte qu'un mail
-- récupéré sur un profil YouTube ou une fiche Google Maps.
--
-- À partir de cette migration, on stocke en parallèle une liste de
-- métadonnées par email : qui l'a trouvé, sur quelle URL, dans quel
-- contexte, et à quel moment.
--
-- Schéma de chaque entrée (le code applicatif sait lire/écrire) :
--   {
--     "email":     "contact@example.com",
--     "source":    "web" | "obelisk" | "maps" | "sirene" | "file" | …,
--     "source_id": "channel_id YouTube / SIREN / place_id…",
--     "url":       "https://exemple.com/mentions-legales",
--     "context":   "page mentions légales du site officiel",
--     "found_at":  "2026-05-23T14:32:01"
--   }
--
-- La colonne peut être plus courte que `emails` : pour les anciens
-- prospects (déjà en base avant cette migration), `emails_meta` reste
-- vide et le code retombe sur la source globale du prospect. Les
-- prospects ajoutés à partir de maintenant auront le tracking précis.
-- =====================================================================

alter table public.prospects
    add column if not exists emails_meta jsonb not null default '[]'::jsonb;

-- Pas d'index spécifique pour l'instant : on lit la meta seulement quand
-- on charge le prospect complet, jamais en filtre de requête globale.
