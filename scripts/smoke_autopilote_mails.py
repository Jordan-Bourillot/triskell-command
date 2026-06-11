# -*- coding: utf-8 -*-
"""Smoke test de l'audit Auto-pilote mails (2026-06-10).

Vérifie SANS réseau et SANS envoyer le moindre mail :
  1. Le rendu réel d'un mail en mode modèle (substitution pure, zéro
     réécriture IA, typographie française préservée).
  2. Les garde-fous de rédaction : placeholder oublié, fiche sans nom,
     refus IA, adresse devinée, plage horaire.
  3. Le seuil de la 2e IA de relecture (sentinelle -1 / défaut 7) et son
     prompt adapté à l'audience (tutoiement toléré pour les créateurs).
  4. Les relances drip J+7/J+30 : le mail initial ne bloque PLUS la
     relance (bug d'audit), mais client / réponse / re-stage bloquent
     toujours. Textes par défaut en vouvoiement.
  5. La décision de validation d'un brouillon rejouée au moment de
     l'envoi (désinscrit / rebond / déjà contacté / relance légitime).
  6. Le câblage modèle→adresse d'envoi : un modèle qui exige son adresse
     d'expéditeur part par CE compte ou ne part pas (jamais une autre
     adresse) ; le brouillon transporte l'exigence ; la relance repart
     de l'adresse du mail initial.

Usage :  python scripts/smoke_autopilote_mails.py
"""
from __future__ import annotations

import sys
from datetime import datetime, timedelta
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(HERE))
CORE = HERE.parent / "triskell-core"
if CORE.exists():
    sys.path.insert(0, str(CORE))

PASS = []
FAIL = []


def check(label: str, cond: bool, detail: str = "") -> None:
    if cond:
        PASS.append(label)
        print(f"  OK  - {label}")
    else:
        FAIL.append(label)
        print(f"  FAIL- {label} {detail}")


# ---------------------------------------------------------------------------
# Faux client Supabase : assez pour prospect_status / drip_runner.
# ---------------------------------------------------------------------------
class _FakeRes:
    def __init__(self, data):
        self.data = data
        self.count = len(data)


class _FakeQuery:
    def __init__(self, table, store):
        self.t = table
        self.store = store
        self.filters = {}
        self._gte = None
        self._lt = None

    def select(self, *a, **k):
        return self

    def eq(self, k, v):
        self.filters[k] = v
        return self

    def ilike(self, k, v):
        self.filters[k] = v
        return self

    def gte(self, k, v):
        self._gte = (k, v)
        return self

    def lt(self, k, v):
        self._lt = (k, v)
        return self

    def order(self, *a, **k):
        return self

    def limit(self, n):
        return self

    def in_(self, *a):
        return self

    def insert(self, row):
        self.store.setdefault(self.t + "_inserted", []).append(row)
        return self

    def update(self, row):
        self.store.setdefault(self.t + "_updated", []).append(
            (dict(self.filters), row))
        return self

    def execute(self):
        rows = self.store.get(self.t, [])
        out = []
        for r in rows:
            ok = True
            for k, v in self.filters.items():
                if k.startswith("extra->>"):
                    if (r.get("extra") or {}).get(k.split(">>")[1]) != v:
                        ok = False
                        break
                elif str(r.get(k, "")).lower() != str(v).lower():
                    ok = False
                    break
            if ok and self._gte:
                k, v = self._gte
                if str(r.get(k, "")) < str(v):
                    ok = False
            if ok and self._lt:
                k, v = self._lt
                if str(r.get(k, "")) >= str(v):
                    ok = False
            if ok:
                out.append(r)
        return _FakeRes(out)


class _FakeRaw:
    def __init__(self, store):
        self.store = store

    def table(self, name):
        return _FakeQuery(name, self.store)


class _FakeClient:
    user_id = "test"

    def __init__(self, store):
        self.raw = _FakeRaw(store)

    def get_shared_setting(self, k, d=None):
        return d

    def _current_workspace_id(self):
        return "ws-test"


class _FakeAppState:
    def get(self, *a, **k):
        return k.get("default")


# Le vrai modèle Pixel Pros « Variante B » (copie verbatim de la base).
TPL_PRO = {
    "key": "prosp_pp_pro_artisan",
    "subject": "Un site pro à 24,90€/mois — sans 1500€ d'avance",
    "body_text": (
        "Bonjour,\n\nPetit message rapide. Je dirige Pixel Pros, notre "
        "studio breton, avec mon frère Thomas.\n\nSur le marché, une agence "
        "demande 450 à 1500€ d'avance pour faire un site web. C'est leur "
        "modèle. Mais pour une entreprise comme {{name}}, c'est parfois une "
        "vraie barrière.\n\nNotre approche : 24,90€ HT par mois, tout "
        "compris, livré en 24h, sans avance ni engagement.\n\nSi vous "
        "voulez voir ce que ça donne ou en discuter, je suis là.\n\nJordan\n"
        "Pixel Pros · Studio breton"
    ),
    "body_html": "",
    "audience": "pro",
}

PME = {
    "raison_sociale": "Boulangerie Le Fournil de Goulven", "prenom": "",
    "nom": "", "email": "contact@fournil-goulven.fr", "ville": "Quimper",
    "code_postal": "29000", "secteur": "Boulangerie", "notes": "",
}


print("1) Rendu réel d'un mail en mode modèle…")
from triskell_command.integrations.convoy_ai import (  # noqa: E402
    generate_message_from_templates,
)
from triskell_core.prospect.pipeline import (  # noqa: E402
    _effective_template_brief, _has_unfilled_placeholder,
    _looks_like_ai_refusal, _resolve_review_min_score,
    _template_requires_identity, PipelineConfig,
)

gen = generate_message_from_templates(
    PME, templates=[TPL_PRO], template_product="pixel-pros",
    sender_name="Jordan", user_brief="", provider="anthropic", model="x",
    api_keys={},
)
check("le nom de l'entreprise est injecté dans le corps",
      "Boulangerie Le Fournil de Goulven" in gen["body"])
check("aucune variable non remplie ne reste",
      _has_unfilled_placeholder(gen["subject"], gen["body"]) == "")
check("zéro réécriture : le texte du modèle est respecté",
      "Je dirige Pixel Pros, notre studio breton" in gen["body"]
      and "450 à 1500€" in gen["body"])
check("typographie française préservée (« approche : » garde son espace)",
      "Notre approche : 24,90€" in gen["body"],
      detail=repr([l for l in gen["body"].splitlines() if "approche" in l]))
check("un HTML propre est généré pour Gmail", bool(gen["body_html"]))
check("le HTML auto est signalé comme régénérable (html_is_custom=False)",
      gen.get("html_is_custom") is False)
gen_html = generate_message_from_templates(
    PME, templates=[dict(TPL_PRO, body_html="<div>{{name}}</div>")],
    template_product="pixel-pros", sender_name="Jordan", user_brief="",
    provider="anthropic", model="x", api_keys={},
)
check("le HTML écrit main est signalé intouchable (html_is_custom=True)",
      gen_html.get("html_is_custom") is True)

print("2) Garde-fous de rédaction…")
gen3 = generate_message_from_templates(
    PME, templates=[dict(TPL_PRO,
                         body_text=TPL_PRO["body_text"]
                         + "\n\nPS: {{custom_offer}}")],
    template_product="pixel-pros", sender_name="Jordan", user_brief="",
    provider="anthropic", model="x", api_keys={},
)
check("placeholder inconnu détecté → le mail serait jeté",
      _has_unfilled_placeholder(gen3["subject"], gen3["body"])
      == "{{custom_offer}}")
check("modèle nominatif repéré ({{name}} dans le corps)",
      _template_requires_identity(TPL_PRO) is True)
check("modèle générique non concerné",
      _template_requires_identity(
          {"subject": "Bonjour", "body_text": "Offre générale."}) is False)
check("refus IA détecté (méta-analyse au lieu d'un mail)",
      _looks_like_ai_refusal("PROBLÈME MAJEUR : je ne peux pas rédiger…"))
check("un vrai mail n'est pas pris pour un refus",
      not _looks_like_ai_refusal(gen["body"]))

from triskell_core.prospect.pipeline import (  # noqa: E402
    _email_is_guessed, _is_within_send_window,
)


class _P:
    def __init__(self, email, meta=None):
        self.emails = [email]
        self.emails_meta = meta or []


check("contact@ = adresse devinée (part au compte-gouttes)",
      _email_is_guessed(_P("contact@fournil.fr")) is True)
check("adresse nominative = confirmée (part en premier)",
      _email_is_guessed(_P("marie.dupont@fournil.fr")) is False)
check("adresse fabriquée (source guess) = devinée même si nominative",
      _email_is_guessed(_P("marie@fournil.fr",
                           [{"email": "marie@fournil.fr",
                             "source": "guess"}])) is True)

_h = datetime.now().hour
cfg_in = PipelineConfig(send_hour_start=_h, send_hour_end=(_h + 1) % 24)
cfg_out = PipelineConfig(send_hour_start=(_h + 1) % 24,
                         send_hour_end=(_h + 2) % 24)
cfg_closed = PipelineConfig(send_hour_start=_h, send_hour_end=_h)
check("dans la plage horaire → envoi autorisé",
      _is_within_send_window(cfg_in) is True)
check("hors plage horaire → brouillon",
      _is_within_send_window(cfg_out) is False)
check("plage vide (début = fin) → jamais d'envoi direct",
      _is_within_send_window(cfg_closed) is False)

print("3) 2e IA de relecture…")
check("brief vide → consignes par défaut restaurées (format OBJET exigé)",
      "OBJET" in _effective_template_brief(PipelineConfig(
          ai_template_brief="")))
check("brief personnalisé → respecté",
      _effective_template_brief(PipelineConfig(
          ai_template_brief="Mes consignes")) == "Mes consignes")
check("interrupteur Relit=Manuel (-1) → relecture coupée",
      _resolve_review_min_score(-1) == 0)
check("vieille config (0/absent) → défaut 7 restauré",
      _resolve_review_min_score(0) == 7
      and _resolve_review_min_score(None) == 7)
check("seuil choisi (5) → respecté", _resolve_review_min_score(5) == 5)

from triskell_core.prospect.quality_reviewer import (  # noqa: E402
    _REVIEW_PROMPT, _parse_review,
)

check("relectrice : prompt créateur tolère le tutoiement",
      "tutoiement est VOULU" in _REVIEW_PROMPT.format(
          prospect_context="x", subject="s", body="b",
          tone_rule="- Ce prospect est un CREATEUR : le tutoiement est "
                    "VOULU par l'auteur du modele."))
check("relectrice : réponse cassée → brouillon (l'humain tranche)",
      _parse_review("n'importe quoi sans JSON")["verdict"] == "draft")
check("relectrice : réponse valide → notée",
      _parse_review('{"score": 9, "verdict": "ok", "comment": "bon"}')
      ["score"] == 9)

print("4) Relances drip J+7 / J+30…")
from triskell_command.integrations import drip_runner  # noqa: E402

_sent_7d = (datetime.now() - timedelta(days=7)).isoformat(timespec="seconds")
_BASE = {
    "prospects": [{"id": "P1", "status": "contacted",
                   "name": "Boulangerie Le Fournil", "legal_name": "",
                   "emails": ["contact@fournil.fr"]}],
    "clients": [],
    "email_history": [{"id": "H1", "prospect_id": "P1",
                       "kind": "email_sent", "ts": _sent_7d,
                       "subject": "Un site pro à 24,90€/mois",
                       "message_id": "<m1@x>",
                       "extra": {"to": "contact@fournil.fr"}}],
}


def _fresh_store():
    import copy
    return copy.deepcopy(_BASE)


store = _fresh_store()
client = _FakeClient(store)
sent_row = store["email_history"][0]
check("le mail initial ne bloque PLUS la relance J+7 (bug d'audit corrigé)",
      drip_runner._should_skip(client, sent_row, "follow_up_7d") is False)

store2 = _fresh_store()
store2["clients"] = [{"id": "C1", "email": "contact@fournil.fr"}]
check("…mais un prospect devenu client reste bloqué",
      drip_runner._should_skip(_FakeClient(store2),
                               store2["email_history"][0],
                               "follow_up_7d") is True)

store3 = _fresh_store()
store3["email_history"].append({
    "id": "H2", "prospect_id": "P1", "kind": "reply_received",
    "ts": datetime.now().isoformat(timespec="seconds"),
    "subject": "Re:", "extra": {}})
check("…et une réponse reçue bloque la relance",
      drip_runner._should_skip(_FakeClient(store3),
                               store3["email_history"][0],
                               "follow_up_7d") is True)

store4 = _fresh_store()
store4["email_history"].append({
    "id": "H3", "prospect_id": "P1", "kind": "email_sent",
    "ts": datetime.now().isoformat(timespec="seconds"),
    "subject": "Relance", "message_id": "<m2@x>",
    "extra": {"to": "contact@fournil.fr", "drip_stage": "follow_up_7d"}})
check("…et une relance déjà partie n'est jamais doublée",
      drip_runner._should_skip(_FakeClient(store4),
                               store4["email_history"][0],
                               "follow_up_7d") is True)

store5 = _fresh_store()
store5["prospects"][0]["status"] = "unsubscribed"
check("…et un désinscrit n'est JAMAIS relancé",
      drip_runner._should_skip(_FakeClient(store5),
                               store5["email_history"][0],
                               "follow_up_7d") is True)

store6 = _fresh_store()
client6 = _FakeClient(store6)
res = drip_runner._create_drip_draft(
    client6, _FakeAppState(), store6["email_history"][0], "follow_up_7d",
    drip_runner.load_config(client6))
draft_rows = store6.get("prospect_drafts_inserted") or []
check("la relance est déposée en brouillon (mode manuel par défaut)",
      bool(res.get("created")) and len(draft_rows) == 1)
_drip_body = (draft_rows[0].get("body") if draft_rows else "") or ""
check("texte de relance par défaut en VOUVOIEMENT",
      "vous" in _drip_body and " tu " not in f" {_drip_body} "
      and "te laisse" not in _drip_body)
check("plus d'artefact « ton sujet » dans la relance",
      "ton sujet" not in _drip_body)
check("aucune variable non remplie dans la relance",
      _has_unfilled_placeholder(draft_rows[0].get("subject", ""),
                                _drip_body) == "")
check("sujet de relance = Re: + sujet d'origine",
      (draft_rows[0].get("subject") or "").startswith("Re: Un site pro"))

print("4bis) Filtre anti-fausses-adresses : domaines en parking…")
from triskell_core.prospect.enrichers.email_filter import (  # noqa: E402
    clean_email,
)

check("inquire@webname.com (placeholder parking) rejeté",
      clean_email("inquire@webname.com") is None)
check("service@atom.com (marketplace de domaines) rejeté",
      clean_email("service@atom.com") is None)
check("info@sedo.com (régie de parking) rejeté",
      clean_email("info@sedo.com") is None)
check("une vraie adresse pro passe toujours",
      clean_email("contact@fournil-goulven.fr")
      == "contact@fournil-goulven.fr")

print("5) Validation d'un brouillon rejouée au moment de l'envoi…")
from triskell_command.integrations.prospect_status import (  # noqa: E402
    draft_approval_check, mail_is_safe_to_send,
)

check("prospect désinscrit entre-temps → envoi refusé",
      draft_approval_check(status="unsubscribed",
                           draft_kind="first_contact")["ok"] is False)
check("adresse en rebond → envoi refusé",
      draft_approval_check(status="bounced",
                           draft_kind="first_contact")["ok"] is False)
check("déjà contacté par un autre chemin → premier contact refusé (doublon)",
      draft_approval_check(status="qualified", draft_kind="first_contact",
                           last_send_ts="2026-06-08T10:00:00")["ok"]
      is False)
check("relance J+7 légitime → l'envoi antérieur ne bloque pas",
      draft_approval_check(status="contacted", draft_kind="follow_up_7d",
                           last_send_ts="2026-06-03T10:00:00",
                           draft_created_ts="2026-06-10T09:00:00")["ok"]
      is True)
check("relance doublée par un envoi plus récent → refusée",
      draft_approval_check(status="contacted", draft_kind="follow_up_7d",
                           last_send_ts="2026-06-10T12:00:00",
                           draft_created_ts="2026-06-10T09:00:00")["ok"]
      is False)
check("prospect propre jamais contacté → envoi autorisé",
      draft_approval_check(status="qualified",
                           draft_kind="first_contact")["ok"] is True)
check("variable non remplie dans un brouillon → détectée avant envoi",
      mail_is_safe_to_send("Sujet", "Bonjour {{name}}")["ok"] is False)

print("6) Câblage modèle→adresse d'envoi…")
import inspect  # noqa: E402

from triskell_core.prospect import pipeline as _pl  # noqa: E402
from triskell_core.prospect.pipeline import (  # noqa: E402
    _route_for_template_address,
)
from triskell_command.integrations import shared_secrets  # noqa: E402
from triskell_command.integrations import (  # noqa: E402
    prospection_templates,
)

_POOL_IDX = {"contact@pixel-pros.fr": "pixelpros",
             "contact@lagriffe-studio.fr": "lagriffe"}
_REMAIN = {"pixelpros": 3, "lagriffe": 0}

check("modèle sans adresse exigée → tirage au sort habituel (rien ne change)",
      _route_for_template_address("", _POOL_IDX, _REMAIN) == ("none", ""))
check("adresse exigée disponible → envoi par CE compte précisément",
      _route_for_template_address("contact@pixel-pros.fr", _POOL_IDX,
                                  _REMAIN) == ("ok", "pixelpros"))
check("casse et espaces ignorés dans l'adresse exigée",
      _route_for_template_address("  Contact@PIXEL-pros.FR ", _POOL_IDX,
                                  _REMAIN) == ("ok", "pixelpros"))
check("adresse exigée au plafond 24h → brouillon, jamais une autre adresse",
      _route_for_template_address("contact@lagriffe-studio.fr", _POOL_IDX,
                                  _REMAIN) == ("cap", "lagriffe"))
check("adresse exigée absente du pool → brouillon, jamais une autre adresse",
      _route_for_template_address("jordan@triskell-studio.fr", _POOL_IDX,
                                  _REMAIN) == ("missing", ""))
check("pool vide (mode mono-adresse) + adresse exigée → brouillon aussi",
      _route_for_template_address("contact@pixel-pros.fr", {}, {})
      == ("missing", ""))


class _FakeSecretClient:
    """Comptes d'envoi factices : un principal + un secondaire."""

    def get_shared_setting(self, key, default=None):
        if key == "smtp_config":
            return {"smtp_host": "smtp.x.fr", "smtp_port": 587,
                    "smtp_user": "u", "smtp_password": "p",
                    "from_email": "jordan@triskell-studio.fr",
                    "from_name": "Jordan"}
        if key == "mail_accounts":
            return {"accounts": [{
                "id": "pixelpros", "label": "Pixel Pros",
                "from_email": "contact@pixel-pros.fr",
                "from_name": "Pixel Pros", "smtp_host": "smtp.x.fr",
                "smtp_port": 587, "smtp_user": "u2",
                "smtp_password": "p2"}]}
        return default


_sc = _FakeSecretClient()
check("compte principal retrouvé par son adresse",
      (shared_secrets.get_account_by_address(
          "jordan@triskell-studio.fr", client=_sc) or {}).get("id")
      == "primary")
check("compte secondaire retrouvé par son adresse (casse ignorée)",
      (shared_secrets.get_account_by_address(
          "Contact@Pixel-Pros.fr", client=_sc) or {}).get("id")
      == "pixelpros")
check("adresse inconnue → aucun compte (rien ne pourra partir)",
      shared_secrets.get_account_by_address(
          "inconnu@nulle-part.fr", client=_sc) is None)

check("la lecture des modèles de prospection ramène l'adresse exigée",
      "from_address" in inspect.getsource(
          prospection_templates.list_prospection_templates))


class _FakeRemoteCRM:
    """Assez de surface pour _store_validation_draft (base partagée)."""

    def __init__(self, store):
        self.store = store
        self._client = _FakeClient(store)

    def get_row_id(self, prospect):
        return "P1"


_FakeRemoteCRM.__name__ = "RemoteCRM"

store7 = {"prospects": []}


class _Pr:
    pass


ok7 = _pl._store_validation_draft(_FakeRemoteCRM(store7), _Pr(), {
    "subject": "S", "body": "B", "template_key": "k1",
    "kind": "first_contact", "sender_address": "contact@pixel-pros.fr",
})
_rows7 = store7.get("prospect_drafts_inserted") or []
check("le brouillon en base transporte l'adresse exigée",
      ok7 is True and len(_rows7) == 1
      and _rows7[0].get("sender_address") == "contact@pixel-pros.fr")

check("relance : l'adresse du mail initial est lue dans sa trace",
      drip_runner._initial_sender(
          {"extra": {"from": "contact@pixel-pros.fr",
                     "account_id": "pixelpros"}})
      == ("contact@pixel-pros.fr", "pixelpros"))
check("relance : trace stockée en texte JSON tolérée",
      drip_runner._initial_sender(
          {"extra": '{"from": "a@b.fr", "account_id": "x"}'})
      == ("a@b.fr", "x"))
check("vieux mail sans trace d'expéditeur → comportement historique",
      drip_runner._initial_sender({"extra": {}}) == ("", ""))

store8 = _fresh_store()
store8["email_history"][0]["extra"]["from"] = "contact@pixel-pros.fr"
client8 = _FakeClient(store8)
res8 = drip_runner._create_drip_draft(
    client8, _FakeAppState(), store8["email_history"][0], "follow_up_7d",
    drip_runner.load_config(client8))
_rows8 = store8.get("prospect_drafts_inserted") or []
check("le brouillon de relance porte l'adresse du mail initial",
      bool(res8.get("created")) and len(_rows8) == 1
      and _rows8[0].get("sender_address") == "contact@pixel-pros.fr")

_api_src = (HERE / "triskell_command" / "web" / "api.py").read_text(
    encoding="utf-8")
check("validation web : l'adresse exigée du brouillon est respectée",
      "sender_address" in _api_src
      and "get_account_by_address" in _api_src)
check("validation web : filet via le modèle d'origine (vieux brouillons)",
      "_template_required_address" in _api_src)
check("validation locale de secours : même règle, jamais une autre adresse",
      "sender_address" in inspect.getsource(_pl.approve_draft)
      and "get_account_by_address" in inspect.getsource(_pl.approve_draft))

print()
print(f"{len(PASS)} OK / {len(FAIL)} échec(s)")
if FAIL:
    sys.exit(1)
