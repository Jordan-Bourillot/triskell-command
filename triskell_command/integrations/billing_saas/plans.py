"""Catalogue des plans SaaS de Triskell Command.

Source de vérité pour les tarifs, les modules inclus, et le mapping
vers les Stripe Price IDs.

À configurer dans Stripe Dashboard une fois pour toutes :
- 1 produit "Triskell Command Essentiel" avec 1 prix mensuel 39 €
- 1 produit "Module Pro"               avec 1 prix mensuel 49 €
- 1 produit "Module Le Phare"          avec 1 prix mensuel 149 €

Puis renseigner les Stripe Price IDs (price_XXX) dans les variables
d'environnement (cf. config.py) ou dans `~/.triskell-command/settings.json`
section `stripe_prices`.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class Plan:
    code: str                       # "essential", "pro", "phare"
    name: str                       # "Essentiel" — affiché à l'utilisateur
    monthly_cents: int              # tarif mensuel en centimes
    short_pitch: str
    features: tuple[str, ...] = field(default_factory=tuple)
    is_addon: bool = False          # True = module additionnel, False = socle


# Catalogue figé. Si tu changes les tarifs, ce sera une nouvelle version
# (plan v2) — les abonnés actuels restent grandfathered sur leur prix.
PLANS: dict[str, Plan] = {
    "essential": Plan(
        code="essential",
        name="Essentiel",
        monthly_cents=3900,
        short_pitch="Le socle complet pour trouver des clients sans aide externe.",
        features=(
            "Recherche prospects (Sirene + Maps)",
            "Le Convoi (1 catalogue d'offres)",
            "Génération IA des mails",
            "Envoi avec ta propre boîte mail",
            "Détection des réponses",
            "Relances automatiques",
            "Fichier client unifié",
            "1 utilisateur",
        ),
        is_addon=False,
    ),
    "pro": Plan(
        code="pro",
        name="Module Pro",
        monthly_cents=4900,
        short_pitch="Équipe, analyse, multi-comptes mail.",
        features=(
            "Utilisateurs supplémentaires (10 €/personne en plus)",
            "Tableau de bord avancé",
            "Funnel par segment / période",
            "Kanban clients (briefing → livré)",
            "Multi-comptes mail",
            "Export comptable",
        ),
        is_addon=True,
    ),
    "phare": Plan(
        code="phare",
        name="Module Le Phare",
        monthly_cents=14900,
        short_pitch="Une agence SEO autonome pour ton site.",
        features=(
            "Audit technique continu",
            "Surveillance positions Google",
            "Réécriture title/meta automatique",
            "Détection cannibalisation + zombies",
            "Démarchage backlinks",
            "Veille algo + alertes",
            "Bulletin mensuel PDF",
            "Jusqu'à 3 sites",
        ),
        is_addon=True,
    ),
}


def plan_for_modules(modules: list[str]) -> str:
    """Renvoie le code de plan correspondant à un ensemble de modules.

    Exemples :
        ["essential"]                  → "essential"
        ["essential", "pro"]           → "essential+pro"
        ["essential", "pro", "phare"]  → "essential+pro+phare"

    L'ordre canonique est : essential, pro, phare.
    """
    if "essential" not in modules:
        return ""
    order = ["essential", "pro", "phare"]
    selected = [m for m in order if m in modules]
    return "+".join(selected)


def total_monthly_cents(modules: list[str]) -> int:
    """Total mensuel en centimes pour un ensemble de modules."""
    return sum(PLANS[m].monthly_cents for m in modules if m in PLANS)
