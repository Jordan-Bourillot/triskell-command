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

from triskell_command.integrations import claude_advisor, copilot

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
    claude_advisor._client = lambda: None
    tmpdir = tempfile.mkdtemp(prefix="copilot_smoke_")
    copilot._LOCAL_FALLBACK_FILE = Path(tmpdir) / "threads.json"
    copilot._LOCAL_MEMORY_FILE = Path(tmpdir) / "memory.json"
    copilot._LOCAL_STATE_FILE = Path(tmpdir) / "state.json"
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

        print("— Surface API web —")

        # 30. les méthodes existent sur la classe Api (sans l'instancier)
        from triskell_command.web.api import Api
        missing = [m for m in ("copilot_thread", "copilot_send",
                               "copilot_clear", "copilot_append",
                               "copilot_memory", "copilot_memory_add",
                               "copilot_memory_delete",
                               "set_active_view") if not hasattr(Api, m)]
        check("méthodes copilote exposées", not missing, str(missing))

    finally:
        claude_advisor._client = orig_client
        copilot._LOCAL_FALLBACK_FILE = orig_file
        copilot._LOCAL_MEMORY_FILE = orig_mem_file
        copilot._LOCAL_STATE_FILE = orig_state_file

    print()
    total = PASS + FAIL
    print(f"{PASS}/{total} contrôles passés" + ("" if not FAIL else
          f" — {FAIL} ÉCHEC(S)"))
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
