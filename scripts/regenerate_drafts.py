# -*- coding: utf-8 -*-
"""Régénère les brouillons de prospection avec les MODÈLES améliorés, en
RÉUTILISANT l'aperçu déjà rendu dans chaque brouillon (l'image du site démo)
+ les liens déjà calculés — donc sans relancer de capture (lent + indispo en
local) et sans perdre l'aperçu.

Pour chaque brouillon dont le modèle fait partie des 4 retravaillés :
  - on extrait du HTML actuel : le bloc <img> de l'aperçu, et les liens
    « page métier » / « démo » déjà rendus ;
  - on prend le nouveau modèle et on remplit nom / ville / métier + on réinjecte
    l'aperçu et les liens extraits ;
  - on RENOTE le mail (bascule auto entre IA) ;
  - on met à jour le brouillon (sujet, texte, HTML, note). N'ENVOIE rien.

Usage :
    python -X utf8 scripts/regenerate_drafts.py            # TEST (montre, n'écrit pas)
    python -X utf8 scripts/regenerate_drafts.py --apply     # régénère + renote
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT.parent / "triskell-core"))

from triskell_core.db import get_client  # noqa: E402
from triskell_core.prospect.quality_reviewer import review_email  # noqa: E402
from triskell_command.integrations import shared_secrets  # noqa: E402

APPLY = "--apply" in sys.argv
_ALL = ("anthropic", "openai", "google", "mistral", "xai", "deepseek")
_KEYS = ("prosp_pp_pro_commerce", "prosp_pp_pro_artisan",
         "prosp_pp_pro_artisan_2", "prosp_pp_pro_artisan_3")

_RE_IMG = re.compile(r'<img[^>]*alt="Aper[^"]*"[^>]*>', re.IGNORECASE)
_RE_METIER = re.compile(r'href="([^"]+)"[^>]*>\s*Découvrir Pixel Pros', re.IGNORECASE)
_RE_DEMO = re.compile(r'href="([^"]+)"[^>]*>\s*Voir un exemple', re.IGNORECASE)


def _fill(text: str, repl: dict) -> str:
    for k, v in repl.items():
        text = text.replace(k, v)
    return text


def main() -> int:
    c = get_client()
    if not getattr(c, "is_authenticated", False):
        try:
            c.restore_session()
        except Exception:
            pass
    if not getattr(c, "is_authenticated", False):
        print("Pas connecté à la base."); return 2
    sb = c.raw

    api_keys = shared_secrets.get_ai_keys(client=c) or {}
    import json as _json
    _sp = Path.home() / ".triskell-command" / "settings.json"
    if _sp.exists():
        try:
            _local = ((_json.loads(_sp.read_text(encoding="utf-8")).get("ai")
                       or {}).get("api_keys") or {})
            for p in _ALL:
                if not (api_keys.get(p) or "").strip() and (_local.get(p) or "").strip():
                    api_keys[p] = _local[p]
        except Exception:
            pass

    # Modèles améliorés (par clé)
    tpls = {}
    for k in _KEYS:
        rr = (sb.table("triskell_email_templates")
              .select("key, subject, body_text, body_html").eq("key", k)
              .limit(1).execute().data)
        if rr:
            tpls[k] = rr[0]

    drafts = (sb.table("prospect_drafts")
              .select("id, subject, body, body_html, template_key, review_score, "
                      "prospects:prospect_id(name, legal_name, city, industry)")
              .eq("status", "pending").limit(500).execute().data or [])

    print("MODE : ECRITURE REELLE" if APPLY else "MODE : TEST (rien ecrit)")
    print("-" * 78)
    done = skipped = 0
    for d in drafts:
        key = d.get("template_key") or ""
        if key not in tpls:
            skipped += 1
            continue
        old_html = d.get("body_html") or ""
        mimg = _RE_IMG.search(old_html)
        mmet = _RE_METIER.search(old_html)
        mdem = _RE_DEMO.search(old_html)
        if not (mimg and mmet and mdem):
            # On ne sait pas réinjecter proprement -> on laisse ce brouillon tel quel.
            skipped += 1
            print(f"  ~ {(d.get('subject') or '')[:40]:40} : apercu/liens introuvables, laisse tel quel")
            continue
        pr = d.get("prospects") or {}
        name = (pr.get("name") or pr.get("legal_name") or "").strip()
        city = (pr.get("city") or "").strip()
        biz = (pr.get("industry") or "").strip()
        repl_txt = {"{{name}}": name, "{{city}}": city, "{{business_type}}": biz,
                    "{{page_demo}}": mdem.group(1)}
        repl_html = dict(repl_txt)
        repl_html["{{apercu_site}}"] = mimg.group(0)
        repl_html["{{page_metier}}"] = mmet.group(1)
        tpl = tpls[key]
        subj = _fill(tpl.get("subject") or "", repl_txt)
        body = _fill(tpl.get("body_text") or "", repl_txt)
        html = _fill(tpl.get("body_html") or "", repl_html)
        # garde-fou : aucun placeholder ne doit rester
        leftover = re.findall(r"\{\{[a-z_]+\}\}", subj + " " + body + " " + html)
        if leftover:
            skipped += 1
            print(f"  ! {name[:34]:34} : placeholder non rempli {set(leftover)} -> laisse tel quel")
            continue
        # renote le mail régénéré
        ctx = f"Nom: {name}\nVille: {city}\nSecteur: {biz}\nDescription: "
        review = review_email(subject=subj, body=body, prospect_context=ctx,
                              provider="anthropic", model="claude-sonnet-4-5",
                              api_keys=api_keys, audience="")
        engine_down = bool(review.get("engine_down")) or str(review.get("comment") or "").startswith("reviewer ")
        sc = "?" if engine_down else f"{int(review.get('score') or 0)}/10 [{review.get('verdict')}]"
        old = d.get("review_score")
        print(f"  - {name[:32]:32} | {biz[:12]:12} {city[:12]:12} | "
              f"{('--' if old is None else str(old)+'/10'):>6} -> {sc}")
        if APPLY:
            upd = {"subject": subj, "body": body, "body_html": html}
            if not engine_down:
                upd["review_score"] = int(review.get("score") or 0)
                upd["review_verdict"] = str(review.get("verdict") or "")
                upd["review_comment"] = str(review.get("comment") or "")[:300]
            try:
                sb.table("prospect_drafts").update(upd).eq("id", d.get("id")).execute()
                done += 1
            except Exception as e:
                print(f"      ! ecriture KO : {e}")
        else:
            done += 1

    print("-" * 78)
    verb = "régénéré(s)" if APPLY else "à régénérer"
    print(f"{done} brouillon(s) {verb}, {skipped} laissé(s) tel(s) quel(s).")
    if not APPLY:
        print("(TEST : rien ecrit. --apply pour régénérer.)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
