"""Batterie « vérité » du Copilote (étape 1 — conversation écrite).

Contrôles SANS réseau : le filtre anti-fuite des tags pendant le stream,
la persistance du fil (mode secours fichier local), l'assemblage du prompt,
les refus propres (message vide, IA non configurée), et un tour complet
simulé de bout en bout (deltas → action navigate → fil persisté).

Usage :  python scripts/smoke_copilot.py
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

from triskell_command.integrations import (claude_advisor, copilot,
                                           copilot_actions, copilot_habits,
                                           copilot_watch)

PASS = 0
FAIL = 0


def check(label: str, ok: bool, detail: str = "") -> None:
    global PASS, FAIL
    if ok:
        PASS += 1
        print(f"  OK   {label}")
    else:
        FAIL += 1
        print(f"  ECHEC {label}" + (f" — {detail}" if detail else ""))


class FakeState:
    """app_state minimal : get/set ne plantent jamais."""

    def __init__(self):
        self.data = {}

    def get(self, *path, default=None):
        return default

    def set(self, *path, value=None):
        self.data["/".join(path)] = value

    def save(self):
        pass


def main() -> int:
    print("— Filtre anti-fuite (TagScrubber) —")

    # 1. Tag ACTION coupé en plein milieu par le découpage du flux
    sc = copilot.TagScrubber()
    out = sc.push("Voici ce que je lance. [ACT")
    out += sc.push('ION:{"do":"navigate","view":"drafts"}]')
    check("tag ACTION coupé en deux : rien ne fuit",
          "ACTION" not in out and out.startswith("Voici"), repr(out))

    # 2. CHAT_THOMAS, casse différente
    sc = copilot.TagScrubber()
    out = sc.push("C'est envoyé.\n[chat_th") + sc.push("omas]\nSalut\n[/chat_thomas]")
    check("tag CHAT_THOMAS (minuscules) masqué",
          "Salut" not in out and "chat" not in out.lower(), repr(out))

    # 2bis. Tags mémoire coupés en plein vol : masqués aussi
    sc = copilot.TagScrubber()
    out = sc.push("C'est noté. [MEMO") + sc.push('IRE:{"note":"x"}]')
    check("tag MEMOIRE coupé en deux : rien ne fuit",
          "MEMOIRE" not in out and out.startswith("C'est noté."), repr(out))

    # 3. Crochets innocents : tout passe
    sc = copilot.TagScrubber()
    out = sc.push("Bilan [2026] : 3 réponses [voir détail] ok.")
    out += sc.push("")  # flush sans rien
    check("crochets innocents non retenus",
          out == "Bilan [2026] : 3 réponses [voir détail] ok.", repr(out))

    # 4. Reconstitution exacte d'un texte sans tag, en mini-morceaux
    msg = "Trois choses à voir : **2 réponses** et 1 brouillon."
    sc = copilot.TagScrubber()
    out = "".join(sc.push(c) for c in msg)
    check("texte sans tag reconstitué à l'identique", out == msg, repr(out))

    print("— Hygiène des messages —")

    # 5. _clean_message
    check("message au rôle inconnu rejeté",
          copilot._clean_message({"role": "robot", "content": "x"}) is None)
    check("message vide rejeté",
          copilot._clean_message({"role": "user", "content": "   "}) is None)
    big = copilot._clean_message({"role": "user", "content": "a" * 9000})
    check("message monstre tronqué",
          big is not None and len(big["content"]) == copilot.MAX_MESSAGE_CHARS)

    print("— Persistance du fil (secours fichier local) —")

    # Coupe Supabase + redirige les fichiers de secours vers un tmp
    orig_client = claude_advisor._client
    orig_file = copilot._LOCAL_FALLBACK_FILE
    orig_mem_file = copilot._LOCAL_MEMORY_FILE
    orig_state_file = copilot._LOCAL_STATE_FILE
    orig_prefs_file = copilot._LOCAL_PREFS_FILE
    claude_advisor._client = lambda: None
    tmpdir = tempfile.mkdtemp(prefix="copilot_smoke_")
    copilot._LOCAL_FALLBACK_FILE = Path(tmpdir) / "threads.json"
    copilot._LOCAL_MEMORY_FILE = Path(tmpdir) / "memory.json"
    copilot._LOCAL_STATE_FILE = Path(tmpdir) / "state.json"
    copilot._LOCAL_PREFS_FILE = Path(tmpdir) / "prefs.json"
    orig_props_file = copilot_actions._LOCAL_PROPS_FILE
    orig_journal_file = copilot_actions._LOCAL_JOURNAL_FILE
    copilot_actions._LOCAL_PROPS_FILE = Path(tmpdir) / "props.json"
    copilot_actions._LOCAL_JOURNAL_FILE = Path(tmpdir) / "journal.json"
    orig_habits_file = copilot_habits._LOCAL_HABITS_FILE
    orig_sc_file = copilot_habits._LOCAL_SHORTCUTS_FILE
    copilot_habits._LOCAL_HABITS_FILE = Path(tmpdir) / "habits.json"
    copilot_habits._LOCAL_SHORTCUTS_FILE = Path(tmpdir) / "shortcuts.json"
    try:
        # 6. append + load
        copilot.clear_thread("jordan")
        copilot.append_turn("jordan", "Salut !", "Salut Jordan.")
        thread = copilot.load_thread("jordan")
        check("un tour écrit = deux messages relus",
              len(thread) == 2 and thread[0]["role"] == "user"
              and thread[1]["content"] == "Salut Jordan.")

        # 7. débordement : le fil retombe à SUMMARY_KEEP_RECENT (les vieux
        # partent en condensation — ici sans app_state, ils sont tronqués)
        many = [{"role": "user", "content": f"m{i}"} for i in range(20)]
        copilot.clear_thread("jordan")
        for _ in range(5):  # 5 × 20 = 100 > 80 au dernier paquet
            copilot.append_messages("jordan", many)
        thread = copilot.load_thread("jordan")
        check(f"débordement → fil ramené à {copilot.SUMMARY_KEEP_RECENT}",
              len(thread) == copilot.SUMMARY_KEEP_RECENT, str(len(thread)))

        # 8. fils séparés par utilisateur
        copilot.clear_thread("thomas")
        copilot.append_turn("thomas", "Yo", "Salut Thomas.")
        check("fils jordan/thomas séparés",
              len(copilot.load_thread("thomas")) == 2
              and copilot.load_thread("jordan") != copilot.load_thread("thomas"))

        # 9. clear
        copilot.clear_thread("jordan")
        check("nouvelle discussion = fil vide",
              copilot.load_thread("jordan") == [])

        print("— Assemblage du prompt —")

        # 10. build_prompt (contexte app court-circuité : pas le sujet ici)
        orig_ctx = copilot._context_block
        copilot._context_block = lambda app_state: "ÉTAT DE L'APP (test)"
        try:
            thread = [{"role": "user", "content": "ping", "at": "x"},
                      {"role": "assistant", "content": "pong", "at": "x"}]
            prompt = copilot.build_prompt(FakeState(), "jordan", thread,
                                          "Où en est ma chasse ?", view="drafts")
            check("prompt : question présente", "Où en est ma chasse ?" in prompt)
            check("prompt : protocole d'actions présent",
                  "[ACTION:" in prompt and "start_prospection" in prompt)
            check("prompt : écran courant transmis",
                  "Écran actuellement ouvert" in prompt and "drafts" in prompt)
            check("prompt : fil précédent injecté",
                  "ping" in prompt and "pong" in prompt)
            check("prompt : bloc Thomas réservé à Jordan",
                  "[CHAT_THOMAS]" in prompt
                  and "[CHAT_THOMAS]" not in copilot.build_prompt(
                      FakeState(), "thomas", [], "salut", view=""))
        finally:
            copilot._context_block = orig_ctx

        print("— Le snapshot voit le GEO —")

        # 10bis. Le module GEO (audits « être cité par les IA ») vit dans
        # l'AppState serveur : le snapshot du copilote doit le refléter,
        # sinon « j'ai lancé un audit GEO, ça donne quoi ? » → « aucune
        # trace » alors que l'audit existe (bug du 11/06/2026).
        class GeoState(FakeState):
            def __init__(self, geo):
                super().__init__()
                self._geo = geo

            def get(self, *path, default=None):
                if path and path[0] == "geo":
                    return self._geo
                return default

        geo_data = {
            "sites": [{"id": "s1", "name": "Pixel Pros",
                       "url": "https://pixel-pros.fr", "brand": "Pixel Pros",
                       "domain": "pixel-pros.fr"}],
            "questions": {"s1": [{"id": "q1", "text": "Quel presta ?"}]},
            "audits": [{"id": "a1", "site_id": "s1",
                        "url": "https://pixel-pros.fr",
                        "ts": "2026-06-11T14:02:33", "score": 62,
                        "findings": [
                            {"status": "fail",
                             "label": "Pas de données structurées (JSON-LD)",
                             "advice": "…", "points": 10},
                            {"status": "warn", "label": "Pas de tableau",
                             "advice": "…", "points": 4},
                        ]}],
            "ai_audits": [{"id": "ia1", "site_id": "s1",
                           "url": "https://pixel-pros.fr",
                           "ts": "2026-06-11T14:05:10",
                           "verdict": "Page correcte mais peu citable",
                           "score_estimated": 55,
                           "findings": [{"id": "f1", "title": "Pas de FAQ",
                                         "fix_title": "Ajouter une FAQ",
                                         "fix_html": "<section/>"}]}],
            "surveillance_runs": [{"id": "r1", "site_id": "s1",
                                   "ts": "2026-06-10T09:00:00", "score": 25,
                                   "cited": 1, "total": 4, "results": []}],
            "reputation_runs": [],
            "generated": [],
            "autopilot": {"enabled": False, "running": False},
        }
        snap = claude_advisor.gather_voice_context(GeoState(geo_data))
        g = snap.get("geo") or {}
        a = (g.get("recent_audits") or [{}])[0]
        check("audit GEO dans le snapshot (site, score, horodatage)",
              a.get("score_sur_100") == 62
              and a.get("site") == "Pixel Pros"
              and a.get("at") == "2026-06-11T14:02", repr(a))
        check("audit GEO : problèmes et points à améliorer résumés",
              a.get("problemes") == ["Pas de données structurées (JSON-LD)"]
              and a.get("a_ameliorer") == ["Pas de tableau"], repr(a))
        ia = (g.get("recent_ai_audits") or [{}])[0]
        check("audit IA : verdict et suggestions transmis",
              ia.get("verdict") == "Page correcte mais peu citable"
              and ia.get("suggestions") == ["Ajouter une FAQ"], repr(ia))
        sv = (g.get("recent_surveillance") or [{}])[0]
        check("surveillance : citations résumées",
              sv.get("citations") == "1/4"
              and sv.get("score_citation_pct") == 25, repr(sv))
        json.dumps(snap, ensure_ascii=False, default=str)
        g_vide = (claude_advisor.gather_voice_context(FakeState())
                  .get("geo") or {})
        check("état GEO vierge : bloc présent, listes vides",
              g_vide.get("sites") == []
              and g_vide.get("recent_audits") == [], repr(g_vide))
        check("prompts système : le GEO est annoncé au copilote",
              "GEO" in copilot.COPILOT_SYSTEM_PROMPT
              and "GEO" in claude_advisor.CONVO_SYSTEM_PROMPT)

        print("— Refus propres —")

        # 11. message vide
        evts = list(copilot.stream_reply(FakeState(), "jordan", "   "))
        check("message vide → erreur en français",
              len(evts) == 1 and evts[0]["type"] == "error"
              and "vide" in evts[0]["error"].lower())

        # 12. IA non configurée
        orig_resolve = claude_advisor._resolve_ai
        claude_advisor._resolve_ai = lambda s: {"provider": "", "model": "",
                                                "api_key": ""}
        try:
            evts = list(copilot.stream_reply(FakeState(), "jordan", "salut"))
            check("pas de clé IA → message Réglages",
                  evts and evts[0]["type"] == "error"
                  and "Réglages" in evts[0]["error"])
        finally:
            claude_advisor._resolve_ai = orig_resolve

        # 13. provider non-Anthropic
        claude_advisor._resolve_ai = lambda s: {"provider": "google",
                                                "model": "g", "api_key": "k"}
        try:
            evts = list(copilot.stream_reply(FakeState(), "jordan", "salut"))
            check("clé non-Anthropic → refus clair",
                  evts and evts[0]["type"] == "error"
                  and "Anthropic" in evts[0]["error"])
        finally:
            claude_advisor._resolve_ai = orig_resolve

        # 14. send_blocking sur message vide
        r = copilot.send_blocking(FakeState(), "jordan", "")
        check("send_blocking refuse proprement",
              r.get("ok") is False and r.get("error"))

        print("— Fin de tour : actions et nettoyage —")

        # 15. _finalize_reply : action exécutée, résumé collé, navigation
        fake_exec_calls = []

        def fake_exec(action):
            fake_exec_calls.append(action)
            return {"ok": True, "summary": "Mission lancée : test.",
                    "navigate": "prospection"}

        raw = ('Je lance ça.\n'
               '[ACTION:{"do":"start_prospection","source":"pme",'
               '"params":{"metier":"plombier"},"dry_run":true}]')
        out = copilot._finalize_reply(raw, execute=fake_exec)
        check("action détachée et exécutée",
              len(fake_exec_calls) == 1
              and fake_exec_calls[0]["do"] == "start_prospection")
        check("résumé d'action collé au texte",
              "Je lance ça." in out["text"] and "Mission lancée" in out["text"])
        check("navigation remontée", out["navigate"] == "prospection")

        # 16. action au JSON cassé → ignorée sans casse
        out = copilot._finalize_reply('Texte. [ACTION:{do sans json}]',
                                      execute=fake_exec)
        check("JSON d'action cassé ignoré proprement",
              out["text"].startswith("Texte.") and out["action_done"] is None)

        # 17. réponse réduite à un tag → texte de remplacement
        out = copilot._finalize_reply('[ACTION:{"do":"inconnu"}]',
                                      execute=lambda a: {"ok": False,
                                                         "summary": ""})
        check("réponse vide après nettoyage → « … »", out["text"] == "…")

        print("— Tour complet simulé (sans réseau) —")

        # 18. stream_reply de bout en bout avec une fausse IA
        claude_advisor._resolve_ai = lambda s: {"provider": "anthropic",
                                                "model": "claude-test",
                                                "api_key": "sk-test"}
        orig_stream = copilot._stream_anthropic

        def fake_stream(prompt, model, api_key):
            yield "Voici tes brouillons."
            yield "\n[ACTION:"
            yield '{"do":"navigate","view":"drafts"}]'

        copilot._stream_anthropic = fake_stream
        orig_ctx = copilot._context_block
        copilot._context_block = lambda app_state: "ÉTAT (test)"
        try:
            copilot.clear_thread("jordan")
            evts = list(copilot.stream_reply(FakeState(), "jordan",
                                             "montre mes brouillons",
                                             view="morning"))
            deltas = "".join(e.get("text", "") for e in evts
                             if e["type"] == "delta")
            done = next((e for e in evts if e["type"] == "done"), None)
            check("deltas streamés sans fuite de tag",
                  "Voici tes brouillons." in deltas
                  and "ACTION" not in deltas)
            check("événement final avec navigation",
                  done is not None and done.get("navigate") == "drafts"
                  and done.get("action_done") is True)
            thread = copilot.load_thread("jordan")
            check("tour persisté dans le fil",
                  len(thread) == 2
                  and thread[0]["content"] == "montre mes brouillons"
                  and "Voici tes brouillons." in thread[1]["content"])
        finally:
            copilot._stream_anthropic = orig_stream
            copilot._context_block = orig_ctx
            claude_advisor._resolve_ai = orig_resolve

        print("— Le carnet (mémoire longue durée) —")

        # 19. add/load/delete + dédoublonnage + troncature
        copilot.save_memory("jordan", [])
        n1 = copilot.add_note("jordan", "  Préfère les réponses courtes  ")
        n_dup = copilot.add_note("jordan", "préfère les réponses courtes")
        check("note ajoutée et dédoublonnée",
              n1 is not None and n_dup is not None
              and n_dup["id"] == n1["id"]
              and len(copilot.load_memory("jordan")) == 1)
        n2 = copilot.add_note("jordan", "x" * 900)
        check("note monstre tronquée",
              n2 is not None and len(n2["text"]) == copilot.MAX_NOTE_CHARS)
        check("suppression d'une note",
              copilot.delete_note("jordan", n2["id"])
              and len(copilot.load_memory("jordan")) == 1)
        check("suppression d'un id inconnu refusée sans casse",
              copilot.delete_note("jordan", "zzz") is False)

        # 20. cap du carnet
        for i in range(80):
            copilot.add_note("jordan", f"note numero {i}")
        check(f"carnet borné à {copilot.MAX_NOTES} notes",
              len(copilot.load_memory("jordan")) == copilot.MAX_NOTES)

        # 21. les tags mémoire du modèle
        copilot.save_memory("jordan", [])
        text, meta = copilot._apply_memory_tags(
            "jordan", 'Noté !\n[MEMOIRE:{"note":"Jamais de mails le week-end"}]')
        notes = copilot.load_memory("jordan")
        check("[MEMOIRE:…] crée la note et disparaît du texte",
              text == "Noté !" and meta.get("memorized")
              and len(notes) == 1
              and notes[0]["text"] == "Jamais de mails le week-end")
        text, meta = copilot._apply_memory_tags(
            "jordan", 'Je l’oublie.\n[OUBLIE:{"n":1}]')
        check("[OUBLIE:{n:1}] supprime la bonne note",
              meta.get("forgotten") is True
              and copilot.load_memory("jordan") == [])
        text, meta = copilot._apply_memory_tags(
            "jordan", 'Rien.\n[OUBLIE:{"n":99}]')
        check("[OUBLIE] hors bornes ignoré proprement",
              "forgotten" not in meta and text == "Rien.")

        # 22. nouvelle discussion : fil et résumé vidés, carnet conservé
        copilot.add_note("jordan", "Le carnet survit")
        copilot.append_turn("jordan", "a", "b")
        copilot.save_thread("jordan", copilot.load_thread("jordan"),
                            summary="vieux résumé")
        copilot.clear_thread("jordan")
        check("clear : fil et résumé vidés, carnet conservé",
              copilot.load_thread("jordan") == []
              and copilot.load_summary("jordan") == ""
              and len(copilot.load_memory("jordan")) == 1)

        print("— Condensation des vieux échanges —")

        # 23. le résumé se range et se relit
        copilot.save_thread("jordan", [], summary="résumé de test")
        check("résumé persisté et relu",
              copilot.load_summary("jordan") == "résumé de test")

        # 24. _condense_now avec une fausse IA
        orig_sum = copilot._summarize_with_ai
        copilot._summarize_with_ai = (
            lambda app_state, prev, old: f"FUSION({prev}|{len(old)} msgs)")
        try:
            ok = copilot._condense_now(FakeState(), "jordan",
                                       "résumé de test",
                                       [{"role": "user", "content": "x"}] * 6)
            check("condensation : résumé fusionné rangé",
                  ok and "FUSION(résumé de test|6 msgs)"
                  == copilot.load_summary("jordan"))
        finally:
            copilot._summarize_with_ai = orig_sum

        # 25. condensation en échec → résumé existant conservé
        copilot._summarize_with_ai = (lambda *a: (_ for _ in ()).throw(
            copilot.CopilotError("pas d'IA")))
        try:
            ok = copilot._condense_now(FakeState(), "jordan", "garde-moi", [])
            check("condensation en échec : rien de cassé",
                  ok is False and "FUSION" in copilot.load_summary("jordan"))
        finally:
            copilot._summarize_with_ai = orig_sum

        # 26. le prompt embarque carnet + résumé + règles du carnet
        orig_ctx = copilot._context_block
        copilot._context_block = lambda app_state: "ÉTAT (test)"
        try:
            copilot.save_memory("jordan", [])
            copilot.add_note("jordan", "Tutoiement obligatoire")
            copilot.save_thread("jordan", [], summary="il bosse sur X")
            prompt = copilot.build_prompt(FakeState(), "jordan", [],
                                          "salut", view="")
            check("prompt : carnet numéroté injecté",
                  "1. Tutoiement obligatoire" in prompt)
            check("prompt : résumé des vieux échanges injecté",
                  "il bosse sur X" in prompt)
            check("prompt : règles du carnet présentes",
                  "[MEMOIRE:" in prompt and "[OUBLIE:" in prompt)
        finally:
            copilot._context_block = orig_ctx

        print("— Le point du jour (briefing) —")

        # 27. briefing_due : jamais fait → oui ; tout frais → non
        copilot._doc_write(copilot._state_key("jordan"),
                           copilot._LOCAL_STATE_FILE, "jordan", {})
        check("briefing dû quand jamais fait", copilot.briefing_due("jordan"))
        from datetime import datetime as _dt
        copilot.save_state("jordan", last_briefing_at=_dt.now().isoformat(
            timespec="seconds"))
        check("pas de briefing si déjà fait il y a peu",
              copilot.briefing_due("jordan") is False)

        # 28. thread_for_ui : signale briefing_due et pose last_seen
        copilot._doc_write(copilot._state_key("jordan"),
                           copilot._LOCAL_STATE_FILE, "jordan", {})
        ui = copilot.thread_for_ui("jordan")
        check("thread_for_ui signale le briefing dû",
              ui.get("briefing_due") is True)
        check("le passage est horodaté",
              bool(copilot.load_state("jordan")["last_seen_at"]))

        # 29. stream_briefing simulé : en-tête, persistance, tags neutralisés
        claude_advisor._resolve_ai = lambda s: {"provider": "anthropic",
                                                "model": "claude-test",
                                                "api_key": "sk-test"}
        orig_stream = copilot._stream_anthropic

        def fake_brief(prompt, model, api_key):
            yield "Tout roule : 2 réponses à traiter."
            yield '\n[ACTION:{"do":"navigate","view":"replies"}]'

        copilot._stream_anthropic = fake_brief
        copilot._context_block = lambda app_state: "ÉTAT (test)"
        try:
            copilot.clear_thread("jordan")
            copilot.append_turn("jordan", "salut", "salut !")
            evts = list(copilot.stream_briefing(FakeState(), "jordan",
                                                view="morning"))
            done = next((e for e in evts if e["type"] == "done"), None)
            deltas = "".join(e.get("text", "") for e in evts
                             if e["type"] == "delta")
            check("briefing : en-tête « Le point » streamé",
                  deltas.startswith("☀️ **Le point**"))
            check("briefing : tag ACTION neutralisé (pas de navigation)",
                  done is not None and "navigate" not in done
                  and "[ACTION" not in done["text"])
            thread = copilot.load_thread("jordan")
            check("briefing persisté dans le fil",
                  len(thread) == 3 and thread[-1]["role"] == "assistant"
                  and "Le point" in thread[-1]["content"])
            check("briefing : plus dû juste après",
                  copilot.briefing_due("jordan") is False)
        finally:
            copilot._stream_anthropic = orig_stream
            copilot._context_block = orig_ctx
            claude_advisor._resolve_ai = orig_resolve

        print("— Initiative : préférences, pastille, évènements —")

        # 30. niveau d'initiative : défaut, réglage, refus
        check("initiative par défaut : normal",
              copilot.get_prefs("jordan")["initiative"] == "normal")
        r = copilot.set_prefs("jordan", "bavard")
        check("réglage bavard accepté et relu",
              r.get("ok") and copilot.get_prefs("jordan")["initiative"] == "bavard")
        r = copilot.set_prefs("jordan", "hurleur")
        check("niveau inconnu refusé en français",
              r.get("ok") is False and "off" in (r.get("error") or ""))
        copilot.set_prefs("jordan", "normal")

        # 31. dépôt d'évènement : fil + kind/nav + pastille
        copilot.clear_thread("jordan")
        copilot.save_state("jordan", unseen=0)
        ok1 = copilot.deposit_event_message("jordan", "🔔 Test évènement",
                                            nav="replies")
        thread = copilot.load_thread("jordan")
        check("évènement déposé avec kind et destination",
              ok1 and len(thread) == 1 and thread[0].get("kind") == "event"
              and thread[0].get("nav") == "replies")
        check("pastille : compteur non-lu à 1",
              copilot.get_unseen("jordan") == 1)
        copilot.thread_for_ui("jordan")
        check("volet ouvert → pastille éteinte",
              copilot.get_unseen("jordan") == 0)

        # 32. nav vicieuse rejetée par l'hygiène des messages
        m = copilot._clean_message({"role": "assistant", "content": "x",
                                    "kind": "event",
                                    "nav": "../etc; rm -rf"})
        check("destination malpropre écartée",
              m is not None and "nav" not in m)

        print("— Le guetteur (détection d'évènements) —")

        BASE = {"replies_unhandled": 2, "drafts_pending": 1,
                "prospects_total": 100, "prospects_new": 10,
                "autopilot_enabled": True, "workers_error": 0,
                "missions": {"m1": {"status": "hunting", "label": "PME 56",
                                    "counts": {}}}}

        # 33. premier passage : silence (on pose la base)
        check("premier passage : aucun évènement",
              copilot_watch.detect_events(None, BASE) == [])

        # 34. rien ne bouge : silence
        check("rien ne bouge : aucun évènement",
              copilot_watch.detect_events(BASE, dict(BASE)) == [])

        # 35. une réponse arrive → évènement chaud vers Réponses
        cur = dict(BASE, replies_unhandled=3)
        evts = copilot_watch.detect_events(BASE, cur)
        check("réponse de prospect → évènement chaud",
              len(evts) == 1 and evts[0]["hot"] is True
              and evts[0]["nav"] == "replies")

        # 36. chasse terminée → évènement doux avec le compte versé
        cur = dict(BASE, missions={"m1": {"status": "handed", "label": "PME 56",
                                          "counts": {"pushed": 7}}})
        evts = copilot_watch.detect_events(BASE, cur)
        check("chasse finie → « 7 prospect(s) versés », sans push",
              len(evts) == 1 and evts[0]["hot"] is False
              and "7" in evts[0]["text"])

        # 37. mission en erreur → chaud
        cur = dict(BASE, missions={"m1": {"status": "error", "label": "PME 56",
                                          "counts": {}}})
        evts = copilot_watch.detect_events(BASE, cur)
        check("mission en erreur → évènement chaud",
              len(evts) == 1 and evts[0]["hot"] is True)

        # 38. robots en panne → déposé mais PAS chaud (le watchdog pushe déjà)
        cur = dict(BASE, workers_error=2)
        evts = copilot_watch.detect_events(BASE, cur)
        check("robots en panne → fil oui, push non",
              len(evts) == 1 and evts[0]["hot"] is False
              and evts[0]["nav"] == "health")

        # 39. brouillons/prospects → mineurs (mode bavard uniquement)
        cur = dict(BASE, drafts_pending=3, prospects_total=104)
        evts = copilot_watch.detect_events(BASE, cur)
        check("brouillons et prospects → évènements mineurs",
              len(evts) == 2 and all(e["minor"] for e in evts))

        print("— Le guetteur (rappels quotidiens) —")

        from datetime import datetime as _dt2
        daily = {}
        # 40. avant l'heure : rien
        evts = copilot_watch.daily_checks(BASE, daily,
                                          now=_dt2(2026, 6, 11, 7, 0))
        check("pas de rappel avant l'heure", evts == [])
        # 41. après l'heure : rappel réponses en attente, une fois par jour
        evts = copilot_watch.daily_checks(BASE, daily,
                                          now=_dt2(2026, 6, 11, 10, 0))
        check("rappel du matin : réponses en attente",
              any(e["key"] == "daily_replies" for e in evts))
        evts2 = copilot_watch.daily_checks(BASE, daily,
                                           now=_dt2(2026, 6, 11, 15, 0))
        check("pas de second rappel le même jour", evts2 == [])
        evts3 = copilot_watch.daily_checks(BASE, daily,
                                           now=_dt2(2026, 6, 12, 10, 0))
        check("le rappel revient le lendemain",
              any(e["key"] == "daily_replies" for e in evts3))
        # 42. Auto-pilote éteint + prospects qui attendent
        cur = dict(BASE, autopilot_enabled=False, prospects_new=9)
        evts = copilot_watch.daily_checks(cur, {},
                                          now=_dt2(2026, 6, 11, 10, 0))
        check("rappel Auto-pilote éteint + prospects en attente",
              any(e["key"] == "daily_autopilot" for e in evts))

        print("— Le guetteur (dépôt selon le niveau) —")

        HOT = {"key": "k1", "text": "chaud", "nav": "replies",
               "hot": True, "minor": False}
        MINOR = {"key": "k2", "text": "mineur", "nav": "",
                 "hot": False, "minor": True}

        def run_deposit(level):
            copilot.set_prefs("jordan", level)
            copilot.set_prefs("thomas", "off")  # isole jordan
            dropped, pushed = [], []
            st = {"pushes": []}
            copilot_watch.deposit(
                [HOT, MINOR], st, users=("jordan", "thomas"),
                deposit_fn=lambda u, t, n: dropped.append((u, t)) or True,
                push_fn=lambda u, t, n: pushed.append((u, t)) or True,
                now_ts=1000.0)
            return dropped, pushed

        d, p = run_deposit("off")
        check("niveau coupé : rien du tout", d == [] and p == [])
        d, p = run_deposit("discret")
        check("discret : fil oui (sans le mineur), téléphone non",
              len(d) == 1 and d[0][1] == "chaud" and p == [])
        d, p = run_deposit("normal")
        check("normal : fil + téléphone pour le chaud",
              len(d) == 1 and len(p) == 1)
        d, p = run_deposit("bavard")
        check("bavard : tout dans le fil, téléphone pour le chaud",
              len(d) == 2 and len(p) == 1)
        copilot.set_prefs("jordan", "normal")
        copilot.set_prefs("thomas", "normal")

        # 43. ceinture anti-rafale de notifications
        st = {"pushes": []}
        sent = []
        copilot_watch.deposit(
            [dict(HOT, key=f"k{i}") for i in range(10)], st,
            users=("jordan",),
            deposit_fn=lambda u, t, n: True,
            push_fn=lambda u, t, n: sent.append(t) or True,
            now_ts=2000.0)
        check(f"jamais plus de {copilot_watch.PUSH_CAP_PER_HOUR} notifs/heure",
              len(sent) == copilot_watch.PUSH_CAP_PER_HOUR, str(len(sent)))

        print("— Étape 4 : le registre des actions —")

        # 45. chaque action déclare famille/risque/libellé/exécuteur
        bad = [do for do, s in copilot_actions.ACTIONS.items()
               if s.get("risk") not in ("lecture", "reversible", "sensible")
               or s.get("family") not in (None, "prospection", "notes",
                                          "mails")
               or not s.get("label") or not callable(s.get("run"))
               or not callable(s.get("title"))]
        check("registre : 13 actions complètes",
              len(copilot_actions.ACTIONS) == 13 and not bad, str(bad))
        historiques = {"navigate", "start_prospection", "toggle_autopilot",
                       "cancel_mission"}
        check("les 4 actions historiques sont au registre",
              historiques <= set(copilot_actions.ACTIONS))

        # 46. action inconnue → refus, jamais d'exception
        r = copilot_actions.execute_action({"do": "format_disque"},
                                           user_id="jordan")
        check("action inconnue refusée proprement",
              r.get("ok") is False and "inconnue" in r.get("summary", ""))

        print("— Étape 4 : le curseur de confiance —")

        # 47. défauts « équilibrés » + plafond mails
        copilot._doc_write(copilot._prefs_key("jordan"),
                           copilot._LOCAL_PREFS_FILE, "jordan", {})
        t = copilot_actions.get_trust("jordan")
        check("défauts : prospection seul, notes seul, mails demande",
              t == {"prospection": "solo", "notes": "solo", "mails": "ask"},
              str(t))
        check("plafond : un envoi de mail n'est jamais « seul »",
              copilot_actions.effective_trust("jordan", "approve_draft")
              == "ask")
        check("lecture toujours permise (hors curseur)",
              copilot_actions.effective_trust("jordan", "view_prospect")
              == "solo"
              and copilot_actions.effective_trust("jordan", "navigate")
              == "solo")
        r = copilot.set_prefs("jordan", trust={"mails": "solo"})
        check("réglage mails=seul refusé en français",
              r.get("ok") is False and "validation" in (r.get("error") or ""))
        check("clean_trust répare une base trafiquée",
              copilot_actions.clean_trust({"mails": "solo"})["mails"] == "ask")
        r = copilot.set_prefs("jordan", trust={"droids": "solo"})
        check("famille inconnue refusée",
              r.get("ok") is False and "inconnue" in (r.get("error") or ""))

        # 48. prefs fusionnées : initiative et confiance cohabitent
        copilot.set_prefs("jordan", "bavard")
        copilot.set_prefs("jordan", trust={"prospection": "ask"})
        p = copilot.get_prefs("jordan")
        check("initiative conservée quand on règle la confiance",
              p["initiative"] == "bavard"
              and p["trust"]["prospection"] == "ask")
        copilot.set_prefs("jordan", "normal",
                          trust={"prospection": "solo"})

        print("— Étape 4 : propositions (demander d'abord) —")

        # 49. famille mails (ask) → proposition, RIEN exécuté
        ran = []
        orig_run = copilot_actions.ACTIONS["reject_draft"]["run"]
        copilot_actions.ACTIONS["reject_draft"]["run"] = (
            lambda a: ran.append(a) or {"ok": True, "summary": "Refusé."})
        try:
            r = copilot_actions.execute_action(
                {"do": "reject_draft", "id": "d1", "source": "prospect"},
                user_id="jordan")
            prop = r.get("proposed") or {}
            check("curseur « demande » → proposition, rien exécuté",
                  r.get("ok") is True and prop.get("status") == "pending"
                  and ran == [])
            check("la proposition est listée pour le volet",
                  prop.get("id") in copilot_actions.list_proposals("jordan"))

            # 50. confirmation → exécute LA version stockée + journal
            res = copilot_actions.confirm_proposal("jordan", prop["id"])
            check("confirmation : action exécutée depuis le serveur",
                  res.get("ok") is True and len(ran) == 1
                  and ran[0]["id"] == "d1")
            check("statut passé à « fait »",
                  copilot_actions.list_proposals("jordan")[prop["id"]]
                  ["status"] == "done")
            res2 = copilot_actions.confirm_proposal("jordan", prop["id"])
            check("double confirmation refusée",
                  res2.get("ok") is False and len(ran) == 1)

            # 51. annulation → close, rien exécuté
            r = copilot_actions.execute_action(
                {"do": "reject_draft", "id": "d2"}, user_id="jordan")
            pid2 = r["proposed"]["id"]
            d = copilot_actions.dismiss_proposal("jordan", pid2)
            check("annulation : close sans exécution",
                  d.get("ok") is True and len(ran) == 1
                  and copilot_actions.list_proposals("jordan")[pid2]
                  ["status"] == "dismissed")

            # 52. expiration : une proposition trop vieille ne s'exécute plus
            r = copilot_actions.execute_action(
                {"do": "reject_draft", "id": "d3"}, user_id="jordan")
            pid3 = r["proposed"]["id"]
            with copilot_actions._PROPS_LOCK:
                items = copilot_actions._load_props("jordan")
                for it in items:
                    if it.get("id") == pid3:
                        it["expires_at"] = "2000-01-01T00:00:00"
                copilot_actions._save_props("jordan", items)
            res = copilot_actions.confirm_proposal("jordan", pid3)
            check("proposition expirée → refus, rien exécuté",
                  res.get("ok") is False and len(ran) == 1
                  and "expir" in res.get("summary", "").lower())

            # 53. proposition inconnue
            res = copilot_actions.confirm_proposal("jordan", "zzz")
            check("proposition inconnue → refus propre",
                  res.get("ok") is False)

            # 54. le curseur re-vérifié AU CLIC (passé à jamais entre-temps)
            r = copilot_actions.execute_action(
                {"do": "reject_draft", "id": "d4"}, user_id="jordan")
            pid4 = r["proposed"]["id"]
            copilot.set_prefs("jordan", trust={"mails": "never"})
            res = copilot_actions.confirm_proposal("jordan", pid4)
            check("« jamais » posé après coup → la confirmation refuse",
                  res.get("ok") is False and len(ran) == 1)
            copilot.set_prefs("jordan", trust={"mails": "ask"})

            # 55. famille en « jamais » → refus poli, pas de proposition
            copilot.set_prefs("jordan", trust={"prospection": "never"})
            r = copilot_actions.execute_action(
                {"do": "cancel_mission", "id": "m1"}, user_id="jordan")
            check("famille « jamais » → refus poli sans proposition",
                  r.get("ok") is False and not r.get("proposed")
                  and "réglages" in r.get("summary", ""))
            copilot.set_prefs("jordan", trust={"prospection": "solo"})

            # 56. cap : les vieilles propositions sont bornées
            with copilot_actions._PROPS_LOCK:
                many = [{"id": f"p{i}", "do": "reject_draft", "action": {},
                         "title": f"t{i}", "preview": None,
                         "status": "dismissed",
                         "created_at": "2026-01-01T00:00:00",
                         "expires_at": "2026-01-02T00:00:00",
                         "result_summary": ""}
                        for i in range(50)]
                copilot_actions._save_props("jordan", many)
            check(f"propositions bornées à {copilot_actions.MAX_PROPOSALS}",
                  len(copilot_actions._load_props("jordan"))
                  == copilot_actions.MAX_PROPOSALS)
        finally:
            copilot_actions.ACTIONS["reject_draft"]["run"] = orig_run

        print("— Étape 4 : aperçu obligatoire avant envoi —")

        # 57. approuver un brouillon sans aperçu fiable → refus (pas de
        # confirmation à l'aveugle) — ici Supabase est coupé donc pas
        # d'aperçu possible.
        r = copilot_actions.execute_action(
            {"do": "approve_draft", "id": "d9", "source": "prospect"},
            user_id="jordan")
        check("envoi sans aperçu → refus « pas à l'aveugle »",
              r.get("ok") is False and not r.get("proposed")
              and "aveugle" in r.get("summary", ""))

        print("— Étape 4 : le journal des actes —")

        # 58. les actes tracés : direct, confirmé, annulé — antichrono
        copilot_actions._doc_write(copilot_actions.JOURNAL_SETTING_PREFIX,
                                   copilot_actions._LOCAL_JOURNAL_FILE,
                                   "jordan", {"items": []})
        copilot_actions.add_journal_entry(
            "jordan", do="cancel_mission", label="Abandonner une mission",
            origin="direct", ok=True, summary="Mission abandonnée.")
        copilot_actions.add_journal_entry(
            "jordan", do="reject_draft", label="Refuser le brouillon",
            origin="confirme", ok=True, summary="Refusé.")
        copilot_actions.add_journal_entry(
            "jordan", do="approve_draft", label="Envoyer le brouillon",
            origin="annule", ok=None, summary="Annulée par toi.")
        j = copilot_actions.journal_for_ui("jordan")
        check("journal : 3 actes, plus récent en premier",
              j.get("ok") and len(j["entries"]) == 3
              and j["entries"][0]["origin"] == "annule"
              and j["entries"][2]["origin"] == "direct")
        check("journal : famille et risque déclarés présents",
              j["entries"][0]["family"] == "mails"
              and j["entries"][0]["risk"] == "sensible")

        # 59. cap du journal
        with copilot_actions._JOURNAL_LOCK:
            copilot_actions._doc_write(
                copilot_actions.JOURNAL_SETTING_PREFIX,
                copilot_actions._LOCAL_JOURNAL_FILE, "jordan",
                {"items": [{"at": "x", "do": "d", "label": "l",
                            "family": "", "risk": "", "origin": "direct",
                            "ok": True, "summary": ""}] * 230})
        copilot_actions.add_journal_entry(
            "jordan", do="cancel_mission", label="encore", origin="direct",
            ok=True, summary="")
        with copilot_actions._JOURNAL_LOCK:
            doc = copilot_actions._doc_read(
                copilot_actions.JOURNAL_SETTING_PREFIX,
                copilot_actions._LOCAL_JOURNAL_FILE, "jordan")
        check(f"journal borné à {copilot_actions.MAX_JOURNAL} entrées",
              len(doc.get("items") or []) == copilot_actions.MAX_JOURNAL)

        # 60. une exécution directe écrit au journal (origin=direct)
        copilot_actions._doc_write(copilot_actions.JOURNAL_SETTING_PREFIX,
                                   copilot_actions._LOCAL_JOURNAL_FILE,
                                   "jordan", {"items": []})
        orig_run = copilot_actions.ACTIONS["cancel_mission"]["run"]
        copilot_actions.ACTIONS["cancel_mission"]["run"] = (
            lambda a: {"ok": True, "summary": "Mission abandonnée."})
        try:
            copilot_actions.execute_action({"do": "cancel_mission",
                                            "id": "m1"}, user_id="jordan")
        finally:
            copilot_actions.ACTIONS["cancel_mission"]["run"] = orig_run
        j = copilot_actions.journal_for_ui("jordan")
        check("exécution directe tracée au journal",
              len(j["entries"]) == 1 and j["entries"][0]["origin"] == "direct"
              and j["entries"][0]["ok"] is True)

        # 61. une lecture (view_prospect/navigate) n'encombre PAS le journal
        copilot_actions.execute_action({"do": "navigate",
                                        "view": "drafts"}, user_id="jordan")
        j = copilot_actions.journal_for_ui("jordan")
        check("navigation non tracée (le journal = les vrais actes)",
              len(j["entries"]) == 1)

        print("— Navigation : tous les écrans du site —")

        # 61bis. L'écran GEO est ouvrable (bug du 11/06/2026 : « écran
        # inconnu » alors que l'écran existe depuis des semaines).
        r = copilot_actions.execute_action({"do": "navigate", "view": "geo"},
                                           user_id="jordan")
        check("navigate geo : accepté",
              r.get("ok") is True and r.get("navigate") == "geo", repr(r))
        r = copilot_actions.execute_action({"do": "navigate",
                                            "view": "piscine"},
                                           user_id="jordan")
        check("navigate vue fantaisiste : refusé",
              r.get("ok") is False and "inconnu" in (r.get("summary") or ""))

        # 61ter. Anti-divergence : la liste blanche Python reflète EXACTEMENT
        # le routeur du site (KNOWN_VIEWS dans app.js), sauf les vues à
        # paramètre obligatoire. Un écran ajouté au site sans mise à jour
        # de la liste → ce contrôle casse, exprès.
        import re as _re
        app_js = (Path(__file__).resolve().parents[1] / "triskell_command"
                  / "web" / "ui" / "scripts" / "app.js").read_text(
                      encoding="utf-8")
        m_views = _re.search(r"const KNOWN_VIEWS = \[(.*?)\];", app_js,
                             _re.DOTALL)
        known = set(_re.findall(r"'([^']+)'", m_views.group(1) if m_views
                                else ""))
        attendu = claude_advisor._ALLOWED_NAV_VIEWS | {"prospect_timeline"}
        check("navigation alignée sur le routeur du site",
              bool(known) and known == attendu,
              f"site-seulement={sorted(known - attendu)} "
              f"python-seulement={sorted(attendu - known)}")
        check("prompt : l'écran geo est annoncé comme ouvrable",
              "geo" in copilot_actions.build_actions_prompt("jordan"))

        print("— Étape 4 : garde-fous métier —")

        # 62. le garde-fou « envoi AUTO ne s'allume pas d'ici » est INTACT
        import triskell_command.web.api as _webapi

        class _FakeApi:
            def autopilot_get_stage_modes(self):
                return {"modes": {"send": "auto"}}

        orig_get_inst = _webapi.get_api_instance
        _webapi.get_api_instance = lambda: _FakeApi()
        try:
            r = copilot_actions._run_toggle_autopilot({"enabled": True})
            check("envoi AUTO → l'assistant refuse d'allumer l'Auto-pilote",
                  r.get("ok") is False and "AUTOMATIQUE" in r["summary"]
                  and r.get("navigate") == "prospection")
        finally:
            _webapi.get_api_instance = orig_get_inst

        # 63. update_prospect : validations en français
        r = copilot_actions._run_update_prospect({"email": "pas-un-mail",
                                                  "note": "x"})
        check("fiche : email invalide refusé",
              r.get("ok") is False and "adresse mail" in r["summary"])
        r = copilot_actions._run_update_prospect({"email": "a@b.fr",
                                                  "status": "zinzin"})
        check("fiche : statut inconnu refusé avec la liste",
              r.get("ok") is False and "interested" in r["summary"])
        r = copilot_actions._run_update_prospect({"email": "a@b.fr"})
        check("fiche : rien à changer → refus clair",
              r.get("ok") is False and "Rien à changer" in r["summary"])

        # 64. view_prospect : demande vide refusée
        r = copilot_actions._run_view_prospect({})
        check("fiche : recherche vide → question posée",
              r.get("ok") is False and "quel prospect" in r["summary"])

        print("— Étape 4 : prompt généré + canaux —")

        # 65. le prompt généré reflète le curseur (✋ sur les mails,
        # 🚫 quand une famille est sur jamais)
        pr = copilot_actions.build_actions_prompt("jordan")
        check("prompt : les envois portent le marqueur confirmation",
              "LE MAIL PART" in pr and "✋" in pr
              and '"do":"approve_draft"' in pr)
        check("prompt : toutes les actions du registre documentées",
              all(f'"do":"{do}"' in pr
                  for do in copilot_actions.ACTIONS))
        copilot.set_prefs("jordan", trust={"prospection": "never"})
        pr2 = copilot_actions.build_actions_prompt("jordan")
        check("prompt : famille « jamais » marquée interdite",
              "🚫" in pr2)
        copilot.set_prefs("jordan", trust={"prospection": "solo"})

        # 66. build_prompt (volet) : protocole généré + prénom remplacé
        orig_ctx = copilot._context_block
        copilot._context_block = lambda app_state: "ÉTAT (test)"
        try:
            prompt = copilot.build_prompt(FakeState(), "jordan", [],
                                          "salut", view="")
            check("prompt du volet : actions étape 4 présentes",
                  '"do":"reply_prospect"' in prompt
                  and "{PRENOM}" not in prompt)
        finally:
            copilot._context_block = orig_ctx

        # 67. le canal vocal : une action « à confirmer » dépose la carte
        # dans le fil + pastille + annonce parlée (rien d'exécuté)
        copilot.clear_thread("jordan")
        copilot.save_state("jordan", unseen=0)
        ran2 = []
        orig_run = copilot_actions.ACTIONS["reject_draft"]["run"]
        copilot_actions.ACTIONS["reject_draft"]["run"] = (
            lambda a: ran2.append(a) or {"ok": True, "summary": "fait"})
        try:
            r = claude_advisor.execute_assistant_action(
                {"do": "reject_draft", "id": "d5"})
            th = copilot.load_thread("jordan")
            check("vocal : carte déposée au fil, pastille allumée",
                  r.get("ok") is True and "volet" in r.get("summary", "")
                  and ran2 == [] and th
                  and th[-1].get("kind") == "proposal"
                  and bool(th[-1].get("pid"))
                  and copilot.get_unseen("jordan") == 1)
        finally:
            copilot_actions.ACTIONS["reject_draft"]["run"] = orig_run

        # 68. _finalize_reply : tag ACTION famille mails → proposed,
        # pas de « action refusée », texte par défaut si réponse nue
        out = copilot._finalize_reply(
            '[ACTION:{"do":"reject_draft","id":"d6"}]', user_id="jordan")
        check("fin de tour : proposition remontée à l'appelant",
              out.get("proposed") and out["action_done"] is None
              and "confirme" in out["text"].lower())

        # 69. stream_reply bout en bout : réponse PUIS carte dans le fil
        claude_advisor._resolve_ai = lambda s: {"provider": "anthropic",
                                                "model": "claude-test",
                                                "api_key": "sk-test"}
        orig_stream = copilot._stream_anthropic

        def fake_stream_prop(prompt, model, api_key):
            yield "Je te prépare le refus."
            yield '\n[ACTION:{"do":"reject_draft","id":"d7"}]'

        copilot._stream_anthropic = fake_stream_prop
        copilot._context_block = lambda app_state: "ÉTAT (test)"
        try:
            copilot.clear_thread("jordan")
            evts = list(copilot.stream_reply(FakeState(), "jordan",
                                             "refuse le brouillon d7"))
            done = next((e for e in evts if e["type"] == "done"), None)
            th = copilot.load_thread("jordan")
            check("tour streamé : done porte la proposition",
                  done is not None and (done.get("proposed") or {})
                  .get("status") == "pending")
            check("fil : réponse puis carte, dans l'ordre",
                  len(th) == 3 and th[1]["role"] == "assistant"
                  and th[2].get("kind") == "proposal")
            check("volet : thread_for_ui sert cartes + curseur",
                  done["proposed"]["id"]
                  in copilot.thread_for_ui("jordan")["proposals"]
                  and copilot.thread_for_ui("jordan")["trust"]["mails"]
                  == "ask")
        finally:
            copilot._stream_anthropic = orig_stream
            copilot._context_block = orig_ctx
            claude_advisor._resolve_ai = orig_resolve

        print("— Étape 5 : motifs et normalisation —")

        from datetime import datetime as _dt5, timedelta as _td5

        # 71. clés de motifs : rejouable vs cible unique, insensible à la casse
        k1 = copilot_habits.action_key({"do": "start_prospection",
                                        "source": "pme",
                                        "params": {"metier": "Plombier",
                                                   "departement": "56"}})
        k2 = copilot_habits.action_key({"do": "start_prospection",
                                        "source": "pme",
                                        "params": {"departement": "56",
                                                   "metier": "plombier "}})
        check("même prospection (casse/ordre) → même motif",
              k1 is not None and k1 == k2, f"{k1} vs {k2}")
        check("action à cible unique → jamais un motif",
              copilot_habits.action_key({"do": "approve_draft",
                                         "id": "x"}) is None)
        check("question normalisée (casse, ponctuation)",
              copilot_habits.normalize_question("  Où en est MA chasse ?? ")
              == "où en est ma chasse")
        check("question trop longue écartée",
              copilot_habits.normalize_question("x" * 200) is None)
        check("libellé auto parlant",
              copilot_habits.auto_label(
                  {"do": "start_prospection",
                   "params": {"metier": "plombier", "departement": "56"}})
              == "Prospection plombier (56)")

        print("— Étape 5 : comptage et proposition sobre —")

        # 72. 2 fois = silence ; 3 fois = mûr
        ACT = {"do": "start_prospection", "source": "pme",
               "params": {"metier": "plombier", "departement": "56"},
               "dry_run": False}
        copilot_habits._doc_write(copilot_habits.HABITS_SETTING_PREFIX,
                                  copilot_habits._LOCAL_HABITS_FILE,
                                  "jordan", {})
        copilot_habits._doc_write(copilot_habits.SHORTCUTS_SETTING_PREFIX,
                                  copilot_habits._LOCAL_SHORTCUTS_FILE,
                                  "jordan", {})
        copilot_habits.record_action("jordan", ACT)
        copilot_habits.record_action("jordan", ACT)
        check("2 répétitions → pas encore de suggestion",
              copilot_habits.ripe_motif("jordan") is None)
        copilot_habits.record_action("jordan", ACT)
        ripe = copilot_habits.ripe_motif("jordan")
        check("3 répétitions → suggestion mûre",
              ripe is not None and ripe["count"] == 3
              and "plombier" in ripe["label"])

        # 73. les vieux passages sortent de la fenêtre de 30 jours
        with copilot_habits._HABITS_LOCK:
            motifs = copilot_habits._load_motifs("jordan")
            old = (_dt5.now() - _td5(days=45)).isoformat(timespec="seconds")
            motifs[0]["times"] = [old, old, old]
            copilot_habits._save_motifs("jordan", motifs)
        check("3 passages trop vieux → plus de suggestion",
              copilot_habits.ripe_motif("jordan") is None)

        # 74. une fois proposée : plus jamais (et 1 proposition max/24 h)
        for _ in range(3):
            copilot_habits.record_action("jordan", ACT)
        ripe = copilot_habits.ripe_motif("jordan")
        copilot_habits.mark_proposed("jordan", ripe["id"])
        check("motif proposé → silence définitif sur ce motif",
              copilot_habits.ripe_motif("jordan") is None)
        OTHER = {"do": "view_prospect", "query": "boulangerie martin"}
        for _ in range(3):
            copilot_habits.record_action("jordan", OTHER)
        check("autre motif mûr MAIS moins de 24 h depuis la dernière "
              "proposition → il attend",
              copilot_habits.ripe_motif("jordan") is None)

        # 75. refus définitif + carte d'état
        st = copilot_habits.habit_card_state("jordan", ripe["id"])
        check("carte 💡 : état pending tant que pas tranché",
              st["status"] == "pending" and st["label"] == ripe["label"])
        copilot_habits.dismiss_habit("jordan", ripe["id"])
        check("« non merci » → motif refusé pour toujours",
              copilot_habits.habit_card_state("jordan",
                                              ripe["id"])["status"]
              == "dismissed")

        # 76. le rythme hebdo : 3 lundis → rendez-vous suggéré
        lundi = _dt5(2026, 6, 1, 9, 12)   # un lundi
        times = [(lundi + _td5(days=7 * i)).isoformat(timespec="seconds")
                 for i in range(3)]
        r = copilot_habits.weekly_rhythm(times)
        check("3 lundis matin → rendez-vous « chaque lundi à 9 h »",
              r == {"days": [0], "hour": 9, "minute": 0}
              and copilot_habits.schedule_label(r) == "chaque lundi à 9 h")
        check("3 jours différents → pas de rythme",
              copilot_habits.weekly_rhythm(
                  [_dt5(2026, 6, 1).isoformat(),
                   _dt5(2026, 6, 2).isoformat(),
                   _dt5(2026, 6, 3).isoformat()]) is None)

        print("— Étape 5 : les raccourcis —")

        # 77. création : validations en français
        r = copilot_habits.create_shortcut("jordan", label="",
                                           question="q")
        check("raccourci sans nom refusé", r["ok"] is False)
        r = copilot_habits.create_shortcut(
            "jordan", label="Brouillon X",
            action={"do": "approve_draft", "id": "x"})
        check("action à cible unique refusée en raccourci",
              r["ok"] is False and "cible unique" in r["error"])
        r = copilot_habits.create_shortcut(
            "jordan", label="Question planifiée", question="quoi de neuf",
            schedule={"days": [0], "hour": 9})
        check("rendez-vous sur une question refusé",
              r["ok"] is False and "question" in r["error"])
        r = copilot_habits.create_shortcut(
            "jordan", label="Prospection lundi", action=dict(ACT),
            schedule={"days": [0], "hour": 9, "minute": 0})
        check("raccourci d'action planifié créé",
              r["ok"] and r["shortcut"]["schedule_label"]
              == "chaque lundi à 9 h")
        sid = r["shortcut"]["id"]
        r2 = copilot_habits.create_shortcut(
            "jordan", label="Doublon", action=dict(ACT))
        check("raccourci équivalent refusé (même motif)",
              r2["ok"] is False and "existe déjà" in r2["error"])
        r3 = copilot_habits.create_shortcut(
            "jordan", label="Le point", question="Où en est ma chasse ?")
        check("raccourci-question créé",
              r3["ok"] and r3["shortcut"]["kind"] == "question")

        # 78. pause / reprise / suppression / usage
        copilot_habits.record_run("jordan", sid)
        copilot_habits.record_run("jordan", sid)
        sc = [s for s in copilot_habits.list_shortcuts("jordan")
              if s["id"] == sid][0]
        check("usage compté (tri de la barre)", sc["runs"] == 2)
        check("pause posée et relue",
              copilot_habits.set_paused("jordan", sid, True)["ok"]
              and copilot_habits.list_shortcuts("jordan")[0]["paused"])
        copilot_habits.set_paused("jordan", sid, False)
        check("suppression d'un raccourci",
              copilot_habits.delete_shortcut("jordan", r3["shortcut"]["id"])
              ["ok"] and len(copilot_habits.list_shortcuts("jordan")) == 1)

        # 79. accepter une habitude → raccourci créé depuis le motif
        copilot_habits._doc_write(copilot_habits.HABITS_SETTING_PREFIX,
                                  copilot_habits._LOCAL_HABITS_FILE,
                                  "jordan", {})
        ACT2 = {"do": "view_prospect", "query": "garage dupont"}
        for _ in range(3):
            copilot_habits.record_action("jordan", ACT2)
        ripe2 = copilot_habits.ripe_motif("jordan")
        res = copilot_habits.accept_habit("jordan", ripe2["id"])
        check("habitude acceptée → raccourci au nom du motif",
              res["ok"] and "garage dupont" in res["shortcut"]["label"]
              and copilot_habits.habit_card_state(
                  "jordan", ripe2["id"])["status"] == "accepted")

        print("— Étape 5 : les rendez-vous (préparer, jamais lancer) —")

        # 80. dû au bon moment seulement
        lundi_9h05 = _dt5(2026, 6, 1, 9, 5)
        due = copilot_habits.due_scheduled("jordan", lundi_9h05)
        check("rendez-vous dû le lundi 9 h 05",
              len(due) == 1 and due[0]["id"] == sid)
        check("pas dû un mardi",
              copilot_habits.due_scheduled("jordan",
                                           _dt5(2026, 6, 2, 9, 5)) == [])
        check("pas dû une heure après (fenêtre de grâce passée)",
              copilot_habits.due_scheduled("jordan",
                                           _dt5(2026, 6, 1, 10, 5)) == [])
        copilot_habits.mark_scheduled_fired("jordan", sid, lundi_9h05)
        check("déjà déclenché aujourd'hui → plus dû",
              copilot_habits.due_scheduled("jordan", lundi_9h05) == [])
        copilot_habits.set_paused("jordan", sid, True)
        check("en pause → jamais dû",
              copilot_habits.due_scheduled(
                  "jordan", _dt5(2026, 6, 8, 9, 5)) == [])
        copilot_habits.set_paused("jordan", sid, False)

        # 81. le guetteur prépare la carte (et pousse selon le niveau)
        copilot.clear_thread("jordan")
        copilot.set_prefs("jordan", "normal")
        copilot.set_prefs("thomas", "off")
        pushes = []
        st_watch = {"pushes": []}
        res = copilot_watch.fire_scheduled(
            st_watch, now=_dt5(2026, 6, 8, 9, 5),
            push_fn=lambda u, t, n: pushes.append((u, t)) or True,
            now_ts=3000.0)
        th = copilot.load_thread("jordan")
        props = copilot_actions.list_proposals("jordan")
        prop_msg = next((m for m in th if m.get("kind") == "proposal"), None)
        check("rendez-vous dû → carte Confirmer/Annuler dans le fil",
              res["fired"] == 1 and prop_msg is not None
              and prop_msg.get("pid") in props
              and props[prop_msg["pid"]]["status"] == "pending")
        check("rien n'est exécuté : c'est une proposition",
              props[prop_msg["pid"]]["title"].startswith("📅"))
        check("notification envoyée (niveau normal)",
              res["pushed"] == 1 and pushes
              and "prêt" in pushes[0][1])
        check("pastille allumée pour le rendez-vous",
              copilot.get_unseen("jordan") == 1)
        res2 = copilot_watch.fire_scheduled(
            st_watch, now=_dt5(2026, 6, 8, 9, 6),
            push_fn=lambda u, t, n: True, now_ts=3001.0)
        check("anti-double : pas de seconde carte le même jour",
              res2["fired"] == 0)
        copilot.set_prefs("thomas", "normal")

        print("— Étape 5 : intégration aux canaux —")

        # 82. une exécution réussie nourrit le compteur (via le registre)
        copilot_habits._doc_write(copilot_habits.HABITS_SETTING_PREFIX,
                                  copilot_habits._LOCAL_HABITS_FILE,
                                  "jordan", {})
        orig_run5 = copilot_actions.ACTIONS["start_prospection"]["run"]
        copilot_actions.ACTIONS["start_prospection"]["run"] = (
            lambda a: {"ok": True, "summary": "Mission lancée."})
        try:
            copilot_actions.execute_action(dict(ACT), user_id="jordan")
        finally:
            copilot_actions.ACTIONS["start_prospection"]["run"] = orig_run5
        with copilot_habits._HABITS_LOCK:
            motifs = copilot_habits._load_motifs("jordan")
        check("exécution réussie comptée comme habitude (sans champ "
              "interne)",
              len(motifs) == 1 and len(motifs[0]["times"]) == 1
              and "_user" not in (motifs[0].get("action") or {}))

        # 83. create_shortcut via le protocole d'action (famille notes →
        # exécution directe) + le prompt le documente
        r = copilot_actions.execute_action(
            {"do": "create_shortcut", "label": "Fiche Garage",
             "action": {"do": "view_prospect", "query": "garage dupont 2"}},
            user_id="jordan")
        check("le copilote crée un raccourci par le tag",
              r.get("ok") is True and "Raccourci" in r.get("summary", ""))
        pr5 = copilot_actions.build_actions_prompt("jordan")
        check("prompt : create_shortcut documenté avec ses limites",
              '"do":"create_shortcut"' in pr5
              and "0=lundi" in pr5 and "rien ne se lance jamais" in pr5)

        # 84. une question répétée (sans action) est comptée au fil des
        # tours streamés
        claude_advisor._resolve_ai = lambda s: {"provider": "anthropic",
                                                "model": "claude-test",
                                                "api_key": "sk-test"}
        orig_stream5 = copilot._stream_anthropic
        copilot._stream_anthropic = (
            lambda p, m, k: iter(["Tout roule, 2 réponses."]))
        orig_ctx5 = copilot._context_block
        copilot._context_block = lambda app_state: "ÉTAT (test)"
        try:
            copilot.clear_thread("jordan")
            for _ in range(3):
                list(copilot.stream_reply(FakeState(), "jordan",
                                          "Combien de réponses cette semaine ?"))
        finally:
            copilot._stream_anthropic = orig_stream5
            copilot._context_block = orig_ctx5
            claude_advisor._resolve_ai = orig_resolve
        with copilot_habits._HABITS_LOCK:
            motifs = copilot_habits._load_motifs("jordan")
        qmotif = next((m for m in motifs if m.get("kind") == "question"),
                      None)
        check("question posée 3 fois → motif mûr",
              qmotif is not None and len(qmotif["times"]) == 3)

        # 85. l'ouverture du volet dépose la carte 💡 (une seule fois) et
        # sert raccourcis + états
        copilot_habits._set_last_proposed_at("jordan", "")
        ui5 = copilot.thread_for_ui("jordan")
        hmsg = next((m for m in ui5["messages"]
                     if m.get("kind") == "habit"), None)
        check("volet ouvert → carte 💡 déposée avec son état pending",
              hmsg is not None and hmsg.get("hid") in ui5["habits"]
              and ui5["habits"][hmsg["hid"]]["status"] == "pending")
        check("volet : raccourcis servis pour la barre ⚡",
              isinstance(ui5.get("shortcuts"), list)
              and len(ui5["shortcuts"]) >= 1)
        ui6 = copilot.thread_for_ui("jordan")
        check("pas de seconde carte 💡 à la réouverture",
              sum(1 for m in ui6["messages"]
                  if m.get("kind") == "habit") == 1)

        print("— Surface API web —")

        # 86. les méthodes existent sur la classe Api (sans l'instancier)
        from triskell_command.web.api import Api
        missing = [m for m in ("copilot_thread", "copilot_send",
                               "copilot_clear", "copilot_append",
                               "copilot_memory", "copilot_memory_add",
                               "copilot_memory_delete", "copilot_prefs",
                               "copilot_prefs_set", "copilot_action_confirm",
                               "copilot_action_dismiss", "copilot_journal",
                               "copilot_shortcuts", "copilot_shortcut_create",
                               "copilot_shortcut_delete",
                               "copilot_shortcut_pause",
                               "copilot_shortcut_run", "copilot_habit_accept",
                               "copilot_habit_dismiss",
                               "_with_copilot_unseen",
                               "set_active_view") if not hasattr(Api, m)]
        check("méthodes copilote exposées", not missing, str(missing))

    finally:
        claude_advisor._client = orig_client
        copilot._LOCAL_FALLBACK_FILE = orig_file
        copilot._LOCAL_MEMORY_FILE = orig_mem_file
        copilot._LOCAL_STATE_FILE = orig_state_file
        copilot._LOCAL_PREFS_FILE = orig_prefs_file
        copilot_actions._LOCAL_PROPS_FILE = orig_props_file
        copilot_actions._LOCAL_JOURNAL_FILE = orig_journal_file
        copilot_habits._LOCAL_HABITS_FILE = orig_habits_file
        copilot_habits._LOCAL_SHORTCUTS_FILE = orig_sc_file

    print()
    total = PASS + FAIL
    print(f"{PASS}/{total} contrôles passés" + ("" if not FAIL else
          f" — {FAIL} ÉCHEC(S)"))
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
