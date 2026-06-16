# -*- coding: utf-8 -*-
"""Chauffe maison des boîtes mail (warm-up) — gratuit.

Fait circuler de VRAIS échanges entre les boîtes de Triskell Command pour bâtir
la réputation des boîtes NEUVES (Google Workspace) avant la prospection à froid.

Principe :
  - Boîtes « à chauffer » (warm) = les neuves (@triskell-studio.com/.org/.store).
    Elles reçoivent du trafic et montent en volume (J1 bas → S4 ~30/j).
  - Boîtes « parrains » (helper) = les anciennes déjà chaudes (contact@…). Elles
    envoient un peu vers les neuves (un échange avec une boîte établie = signal
    fort) mais ne sont pas sur-sollicitées.
  - Réponses automatiques + marquage lu + sortie du spam = les signaux qui
    comptent. Anti-boucle : on ne répond qu'aux messages initiaux.
  - AUTO-NETTOYAGE : nos mails de chauffe (en-tête caché X-TS-Warmup) sont mis à
    la corbeille après traitement → tes vraies boîtes restent propres.

État détaillé écrit dans shared_settings.warmup_state (alimente l'encart Cockpit).

DRY-RUN par défaut (montre le plan, n'envoie rien). --apply pour exécuter.
    python -X utf8 scripts/warmup_tick.py            # TEST
    python -X utf8 scripts/warmup_tick.py --apply     # un cycle réel
"""
from __future__ import annotations

import imaplib
import json
import random
import smtplib
import ssl
import sys
from datetime import datetime
from email.message import EmailMessage
from email.utils import formatdate, make_msgid, parseaddr
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT.parent / "triskell-core"))

from triskell_core.db import get_client, SupabaseNotConfigured  # noqa: E402
from triskell_command.integrations import shared_secrets  # noqa: E402

APPLY = "--apply" in sys.argv
WARMUP_HEADER = "X-TS-Warmup"
STATE_KEY = "warmup_state"
REPLY_PROB = 0.7
PER_TICK_CAP = 4                       # max d'envois par boîte et par passage
# (avec ~7 passages/jour planifiés, ça permet d'atteindre la cible quotidienne
#  même en fin de chauffe sans jamais envoyer en gros bloc)
ESTABLISHED_DAILY = 6                  # entretien/jour des boîtes déjà chaudes
# Domaines des boîtes NEUVES à chauffer (le reste = boîtes déjà chaudes, qu'on
# entretient quand même — demande de Jordan : chauffer TOUTES les boîtes).
WARM_DOMAINS = ("triskell-studio.com", "triskell-studio.org",
                "triskell-studio.store")


def _quota_for_day(day: int) -> int:
    if day <= 7:
        return 4
    if day <= 14:
        return 10
    if day <= 21:
        return 20
    return 30


_SUBJECTS = ["Petit point", "Dispo cette semaine ?", "Retour sur le doc",
             "Pour info", "Question rapide", "Compte-rendu", "On en parle ?",
             "Suivi", "Petit rappel", "Ça avance bien", "Idée à creuser",
             "Le planning"]
_OPENERS = ["Salut,", "Bonjour,", "Hello,", "Coucou,"]
_LINES = ["Juste pour faire le point sur le dossier en cours.",
          "Tu as eu le temps de regarder ce qu'on s'était dit ?",
          "Je te confirme pour la semaine prochaine.",
          "Rien d'urgent, on en reparle quand tu veux.",
          "Merci pour ton retour, c'est bien noté.",
          "Je m'occupe de la suite et je te tiens au courant.",
          "On peut caler un créneau rapide si tu veux.",
          "C'est bon de mon côté, à toi de voir.",
          "Petit rappel pour ne pas que ça traîne.",
          "Dis-moi ce que tu en penses quand tu peux."]
_SIGNOFFS = ["À bientôt", "Merci", "Bonne journée", "À +", "Bien à toi"]
_REPLIES = ["Parfait, merci !", "Ok, c'est noté de mon côté.",
            "Super, on fait comme ça.", "Très bien, à bientôt.",
            "Reçu, je regarde et je reviens vers toi."]


def _gen_mail() -> tuple[str, str]:
    body = (random.choice(_OPENERS) + "\n\n"
            + " ".join(random.sample(_LINES, k=random.randint(1, 3)))
            + "\n\n" + random.choice(_SIGNOFFS) + ",")
    return random.choice(_SUBJECTS), body


def _role_by_domain(email: str) -> str:
    """Repli SEULEMENT si l'historique réel est illisible (base injoignable) :
    ancienne règle par domaine. En marche normale, le rôle est décidé sur le
    vrai historique d'envoi (voir _established_addresses)."""
    e = (email or "").lower()
    return "warm" if any(e.endswith("@" + d) for d in WARM_DOMAINS) else "established"


def _established_addresses(client):
    """Adresses RÉELLEMENT établies (historique d'envoi solide), mesurées par
    mail_reputation. Renvoie un set d'adresses, ou None si le calcul est
    impossible → on retombe alors sur la règle par domaine. Une boîte non
    établie = à chauffer pour de vrai (et non « entretenue » à tort)."""
    try:
        from triskell_command.integrations import mail_reputation
        return mail_reputation.established_addresses(client)
    except Exception as exc:
        print(f"  (réputation illisible, repli sur la règle domaine : {exc})")
        return None


def _accounts(client) -> list[dict]:
    raw = []
    primary = shared_secrets.get_smtp_config(client=client) or {}
    if primary.get("from_email"):
        raw.append({"id": "primary", **primary})
    for a in shared_secrets.list_secondary_accounts(client=client):
        raw.append(a)
    out = []
    established = _established_addresses(client)
    for a in raw:
        acc = {"id": a.get("id"), "from_email": (a.get("from_email") or "").strip(),
               "from_name": a.get("from_name") or "",
               "smtp_host": a.get("smtp_host") or "", "smtp_port": int(a.get("smtp_port") or 587),
               "smtp_user": a.get("smtp_user") or "", "smtp_password": a.get("smtp_password") or "",
               "imap_host": a.get("imap_host") or "", "imap_port": int(a.get("imap_port") or 993),
               "imap_user": a.get("imap_user") or "", "imap_password": a.get("imap_password") or ""}
        if acc["smtp_host"] and acc["smtp_password"] and acc["imap_host"] and acc["from_email"]:
            if established is None:
                acc["role"] = _role_by_domain(acc["from_email"])
            else:
                acc["role"] = ("established"
                               if acc["from_email"].strip().lower() in established
                               else "warm")
            out.append(acc)
    return out


def _smtp_send(acc: dict, msg: EmailMessage) -> None:
    ctx = ssl.create_default_context()
    with smtplib.SMTP(acc["smtp_host"], acc["smtp_port"], timeout=20) as s:
        s.starttls(context=ctx)
        s.login(acc["smtp_user"], acc["smtp_password"])
        s.send_message(msg)


def _send(sender: dict, to_email: str, subj: str, body: str) -> None:
    msg = EmailMessage()
    msg["From"] = (f'{sender["from_name"]} <{sender["from_email"]}>'
                   if sender["from_name"] else sender["from_email"])
    msg["To"] = to_email
    msg["Subject"] = subj
    msg["Date"] = formatdate(localtime=True)
    msg["Message-ID"] = make_msgid()
    msg[WARMUP_HEADER] = "1"
    msg.set_content(body)
    _smtp_send(sender, msg)


def _process_inbox(acc: dict, by_email: dict) -> tuple[int, int]:
    """Sort du spam, répond aux mails initiaux, marque lu, met à la corbeille
    les mails de chauffe traités. Renvoie (reçus, répondus)."""
    received = replied = 0
    try:
        M = imaplib.IMAP4_SSL(acc["imap_host"], acc["imap_port"])
        M.login(acc["imap_user"], acc["imap_password"])
    except Exception:
        return 0, 0
    try:
        # 1) Sortir nos mails du spam (signal « pas spam »).
        for box in ("[Gmail]/Spam", "Spam", "Junk", "INBOX.Junk"):
            try:
                if M.select(box)[0] != "OK":
                    continue
                typ, data = M.search(None, f'HEADER {WARMUP_HEADER} "1"')
                if typ == "OK" and data and data[0]:
                    for num in data[0].split():
                        M.copy(num, "INBOX")
                        M.store(num, "+FLAGS", "\\Deleted")
                    M.expunge()
            except Exception:
                pass
        # 2) INBOX : répondre aux initiaux, puis tout mettre à la corbeille.
        if M.select("INBOX")[0] != "OK":
            return received, replied
        typ, data = M.search(None, f'HEADER {WARMUP_HEADER} "1"')
        if typ != "OK" or not data or not data[0]:
            return received, replied
        for num in data[0].split():
            received += 1
            typ, md = M.fetch(
                num, "(BODY.PEEK[HEADER.FIELDS (FROM SUBJECT MESSAGE-ID IN-REPLY-TO)])")
            if typ == "OK" and md and md[0]:
                raw = md[0][1].decode("utf-8", "replace")
                frm = subj = mid = inrep = ""
                for line in raw.splitlines():
                    low = line.lower()
                    if low.startswith("from:"):
                        frm = parseaddr(line[5:])[1]
                    elif low.startswith("subject:"):
                        subj = line[8:].strip()
                    elif low.startswith("message-id:"):
                        mid = line[11:].strip()
                    elif low.startswith("in-reply-to:"):
                        inrep = line[12:].strip()
                # Répondre UNIQUEMENT aux messages initiaux (anti-boucle).
                sender_acc = by_email.get((frm or "").lower())
                if (not inrep and sender_acc and random.random() <= REPLY_PROB):
                    reply = EmailMessage()
                    reply["From"] = acc["from_email"]
                    reply["To"] = frm
                    reply["Subject"] = subj if subj.lower().startswith("re:") else f"Re: {subj or ''}".strip()
                    reply["Date"] = formatdate(localtime=True)
                    reply["Message-ID"] = make_msgid()
                    if mid:
                        reply["In-Reply-To"] = mid
                        reply["References"] = mid
                    reply[WARMUP_HEADER] = "1"
                    reply.set_content(random.choice(_REPLIES))
                    try:
                        _smtp_send(acc, reply)
                        replied += 1
                    except Exception:
                        pass
            M.store(num, "+FLAGS", "\\Seen")          # lu = engagement
            M.store(num, "+FLAGS", "\\Deleted")       # nettoyage (corbeille)
        M.expunge()
    finally:
        try:
            M.logout()
        except Exception:
            pass
    return received, replied


def _today() -> str:
    return datetime.now().date().isoformat()


def main() -> int:
    try:
        c = get_client()
    except SupabaseNotConfigured:
        print("Base non configurée."); return 2
    if not getattr(c, "is_authenticated", False):
        try:
            c.restore_session()
        except Exception:
            pass

    accts = _accounts(c)
    by_email = {a["from_email"].lower(): a for a in accts}
    warm = [a for a in accts if a["role"] == "warm"]
    established = [a for a in accts if a["role"] == "established"]
    print(f"{len(accts)} boîte(s) : {len(warm)} neuve(s) à chauffer "
          f"({', '.join(a['id'] for a in warm)}) + "
          f"{len(established)} déjà chaude(s) (entretien).")
    if len(warm) < 1 or len(accts) < 2:
        print("Pas assez de boîtes."); return 1

    state = c.get_shared_setting(STATE_KEY, {}) or {}
    if isinstance(state, str):
        try:
            state = json.loads(state)
        except Exception:
            state = {}
    today = _today()
    start = state.get("start") or today
    day = (datetime.fromisoformat(today) - datetime.fromisoformat(start)).days + 1
    quota = _quota_for_day(day)
    accmap = state.get("accounts") or {}

    def _rec(aid: str) -> dict:
        r = accmap.get(aid) or {}
        if r.get("date") != today:
            r = {"date": today, "sent": 0, "received": 0, "replied": 0}
        accmap[aid] = r
        return r

    print(f"Jour de chauffe : J{day}  →  cible {quota} mails/j pour les neuves "
          f"({ESTABLISHED_DAILY}/j d'entretien pour les déjà chaudes)")
    print("MODE : ENVOI RÉEL" if APPLY else "MODE : TEST (rien envoyé)")
    print("-" * 70)

    # Cibles d'envoi : on privilégie les boîtes à chauffer comme destinataires.
    def _pick_targets(sender, n):
        pool = [x for x in warm if x["id"] != sender["id"]] or \
               [x for x in accts if x["id"] != sender["id"]]
        random.shuffle(pool)
        return pool[:n]

    sent = replied = received = 0
    for a in accts:
        rec = _rec(a["id"])
        cap = quota if a["role"] == "warm" else ESTABLISHED_DAILY
        n = max(0, min(PER_TICK_CAP, cap - rec["sent"]))
        for t in _pick_targets(a, n):
            subj, body = _gen_mail()
            if APPLY:
                try:
                    _send(a, t["from_email"], subj, body)
                except Exception as exc:
                    print(f"  ! envoi {a['id']}→{t['id']} KO : {exc}")
                    continue
            print(f"  {a['id']:14} → {t['id']:14} « {subj} »")
            sent += 1
            rec["sent"] += 1
        if APPLY:
            r, rp = _process_inbox(a, by_email)
            received += r
            replied += rp
            rec["received"] += r
            rec["replied"] += rp
        rec["role"] = a["role"]
        rec["day"] = day if a["role"] == "warm" else None
        rec["last"] = datetime.now().isoformat(timespec="seconds")

    print("-" * 70)
    print(f"Bilan : {sent} envoi(s), {received} reçu(s), {replied} réponse(s).")
    if APPLY:
        c.set_shared_setting(STATE_KEY, {"start": start, "accounts": accmap})
        print("État de chauffe sauvegardé (visible sur le Cockpit).")
    else:
        print("(TEST : rien envoyé, état non modifié.)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
