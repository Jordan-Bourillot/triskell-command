"""« L'œil » — juge visuel de site (capture + IA qui REGARDE).

Pourquoi (essai du 16/06/2026) : le « moche mais qui marche » ne se voit
PAS dans le HTML — un beau site et un laid ont le même code vu de
l'intérieur. Les signaux texte (site_quality.py) attrapent les sites
techniquement cassés/vieux ; le design daté ou amateur, lui, ne se juge
qu'à l'ŒIL. Donc : on prend une CAPTURE de la page d'accueil et on demande
à une IA qui regarde si le design est assez vieux/bricolé pour qu'un petit
pro gagne clairement à le refaire.

🚨 RÈGLE ABSOLUE (Jordan : « on n'a pas le droit à l'erreur ») —
PRÉCISION D'ABORD. Dire « à refaire » à quelqu'un de fier de son site
nous grille. Donc l'IA est priée d'être SÉVÈRE AVEC ELLE-MÊME : au
moindre doute → « non ». Et côté code on ne retient que les verdicts
FRANCS ET CONFIANTS (confiance ≥ seuil). Simple/épuré ≠ à refaire.

Coût maîtrisé : Gemini Flash en premier (vision la moins chère), repli
Claude puis OpenAI. Capture via Playwright (déjà installé — cf.
apercu_site.py), toujours dans un thread dédié (la boucle asyncio du
serveur empêche sync_playwright de démarrer dans le thread courant).
"""
from __future__ import annotations

import base64
import json
import logging
import re
import threading

logger = logging.getLogger(__name__)

# Tag de la famille « repéré à l'œil » (en plus du REDO_TAG commun).
VISION_CATEGORY = "redo_visuel"
# Tag du 2e niveau « à vérifier par Jordan » (ne déclenche PAS le REDO_TAG).
VERIFY_CATEGORY = "a_verifier_look"

# DEUX NIVEAUX (idée d'origine de Jordan, validée à l'essai du 16/06/2026 :
# l'œil a noté 90 les sites franchement datés, 85 les « basiques/limites ») :
#   - confiance ≥ 90  → « à refaire » SÛR (on peut s'appuyer dessus)
#   - confiance 75-89 → « à vérifier » (Jordan confirme d'un coup d'œil)
#   - confiance < 75  → on ne dit rien (précision d'abord)
SURE_CONFIDENCE = 90
VERIFY_CONFIDENCE = 75
MIN_CONFIDENCE = VERIFY_CONFIDENCE  # compat (seuil plancher)

# Traceurs/pubs : inutiles à la capture, parfois lents → bloqués.
_BLOCK_FRAGMENTS = (
    "googlesyndication", "googleadservices", "google-analytics",
    "googletagmanager", "doubleclick", "facebook.net", "connect.facebook",
    "fbevents", "hotjar", "clarity.ms", "cookiebot", "axeptio",
)

# Fait défiler la page de haut en bas puis remonte : déclenche le lazy-load
# (Divi, parallax, images au défilement) qui laissait le hero GRIS sinon
# (leçon Foubert 16/06/2026).
_SCROLL_TRIGGER_JS = r"""async () => {
  const h = Math.min(document.body.scrollHeight || 0, 6000);
  for (let y = 0; y < h; y += 500) {
    window.scrollTo(0, y);
    await new Promise(r => setTimeout(r, 130));
  }
  window.scrollTo(0, 0);
  await new Promise(r => setTimeout(r, 500));
}"""

# Attend que les IMAGES (y compris le fond du hero en CSS) soient chargées,
# sinon on capture du gris/blanc → faux « à refaire » (leçon Foubert,
# 16/06/2026 : hero pas chargé = site moderne pris pour un site vide).
_WAIT_IMAGES_JS = r"""async () => {
  const wait = (p) => Promise.race([p, new Promise(r => setTimeout(r, 6000))]);
  const imgs = Array.from(document.images || []);
  await Promise.all(imgs.map(im => im.complete ? null : wait(new Promise(r => {
    im.onload = r; im.onerror = r;
  }))));
  const bgs = [];
  for (const el of document.querySelectorAll('*')) {
    if (el.getBoundingClientRect().height < 200) continue;
    const b = getComputedStyle(el).backgroundImage;
    const m = b && b.match(/url\("?(.*?)"?\)/);
    if (m && m[1] && !m[1].startsWith('data:')) bgs.push(m[1]);
  }
  await Promise.all(bgs.slice(0, 8).map(src => wait(new Promise(r => {
    const i = new Image(); i.onload = r; i.onerror = r; i.src = src;
  }))));
}"""


def _is_blank(png: bytes) -> bool:
    """Vrai si la capture est quasi unie OU dominée par une teinte NEUTRE
    (gris/blanc) = page PAS vraiment chargée (hero en lazy-load, contenu
    manquant). Filet anti-faux-positif : précision avant tout (mieux vaut
    ne pas juger qu'accuser à tort). Sans Pillow : renvoie False."""
    try:
        import io
        from PIL import Image
        im = Image.open(io.BytesIO(png)).convert("RGB").resize(
            (64, 64), Image.NEAREST)
        colors = im.getcolors(64 * 64) or []
        if not colors:
            return False
        cnt, (r, g, b) = max(colors, key=lambda c: c[0])
        frac = cnt / float(64 * 64)
        if frac > 0.92:            # quasi uniforme = page vide / erreur / blanche
            return True
        # Hero NON chargé = placeholder GRIS MOYEN dominant (ni blanc, ni noir).
        # On NE saute PAS le blanc : un site normal a un fond blanc (leçon
        # lelievre 16/06 — bon site zappé à tort). Seul le gris moyen trahit
        # une image de fond pas encore chargée.
        lum = (r + g + b) / 3.0
        neutral = (max(r, g, b) - min(r, g, b)) < 22
        return neutral and 105 <= lum <= 205 and frac > 0.48
    except Exception:
        return False


# ---------------------------------------------------------------------------
# 1) Capture d'écran de la page d'accueil
# ---------------------------------------------------------------------------
def _in_thread(fn, *args):
    box: dict = {}

    def _run():
        try:
            box["v"] = fn(*args)
        except Exception as exc:  # pragma: no cover - filet
            box["e"] = exc

    t = threading.Thread(target=_run, daemon=True)
    t.start()
    t.join()
    if "e" in box:
        logger.warning("site_vision : capture (thread) échouée : %s", box["e"])
        return None
    return box.get("v")


def _shoot(url: str, timeout_ms: int) -> bytes | None:
    try:
        from playwright.sync_api import sync_playwright
    except Exception:
        logger.info("site_vision : Playwright absent — capture sautée.")
        return None
    # Toujours https d'abord, puis http en repli (un vieux site sans cadenas
    # — comme on en cherche — ne répond souvent QU'en http).
    host = url.split("//", 1)[-1]
    candidates = ["https://" + host, "http://" + host]
    png = None
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch()
            try:
                page = browser.new_page(
                    viewport={"width": 1280, "height": 900},
                    device_scale_factor=1)

                def _route(route):
                    u = route.request.url
                    if any(s in u for s in _BLOCK_FRAGMENTS):
                        route.abort()
                    else:
                        route.continue_()
                page.route("**/*", _route)

                ok = False
                for cand in candidates:
                    try:
                        resp = page.goto(cand, wait_until="domcontentloaded",
                                         timeout=timeout_ms)
                        # On NE capture PAS une page d'erreur (403 anti-robot,
                        # 404, 500…) : l'IA jugerait l'erreur, pas le vrai site.
                        # Précision d'abord → on saute (site non jugé).
                        if resp is not None and resp.status >= 400:
                            continue
                        ok = True
                        break
                    except Exception:
                        continue
                if not ok:
                    return None
                # Tout doit être chargé avant de capturer (sinon gris/blanc) :
                try:
                    page.wait_for_load_state("load", timeout=12000)
                except Exception:
                    pass
                try:
                    page.evaluate("async () => { await document.fonts.ready; }")
                except Exception:
                    pass
                try:
                    page.evaluate(_SCROLL_TRIGGER_JS)  # déclenche le lazy-load
                except Exception:
                    pass
                try:
                    page.evaluate(_WAIT_IMAGES_JS)
                except Exception:
                    pass
                page.wait_for_timeout(1800)  # laisse apparaître hero/bandeaux
                # On capture le HAUT (hero + 1re section) — le plus parlant
                # pour juger un design, et net même sur les pages très longues.
                h = page.evaluate(
                    "() => Math.min(document.body.scrollHeight||1200, 1500)")
                png = page.screenshot(
                    clip={"x": 0, "y": 0, "width": 1280,
                          "height": max(700, min(int(h or 1200), 1500))})
            finally:
                browser.close()
    except Exception as exc:
        logger.warning("site_vision : capture %s échouée : %s", url, exc)
        return None
    return png


def screenshot_site(url: str, timeout_ms: int = 30000) -> bytes | None:
    """Capture PNG de la page d'accueil (haut de page). None si échec.
    Toujours rendu dans un thread dédié (cf. apercu_site)."""
    if not (url or "").strip():
        return None
    png = _in_thread(_shoot, url.strip(), timeout_ms)
    if png and _is_blank(png):
        return None  # capture quasi vide (page pas chargée) → on ne juge pas
    return png


# ---------------------------------------------------------------------------
# 2) L'IA qui regarde
# ---------------------------------------------------------------------------
def _prompt(name: str, metier: str) -> str:
    qui = name or "ce professionnel"
    job = f" ({metier})" if metier else ""
    return f"""Tu es directeur artistique web. Tu regardes la CAPTURE de la \
page d'accueil du site de « {qui} »{job}, un petit professionnel.

QUESTION : ce site a-t-il un design DATÉ ou AMATEUR au point qu'il gagnerait \
clairement à être refait par un pro ?

Sois TRÈS prudent et SÉVÈRE AVEC TOI-MÊME. Au MOINDRE doute, réponds \
"a_refaire": false. On ne veut JAMAIS dire « à refaire » à quelqu'un dont le \
site est correct — ça nous grillerait.

Réponds true SEULEMENT si c'est visiblement vieux ou bricolé, par ex. :
- mise en page en désordre, éléments mal alignés ou qui se chevauchent
- typographie d'un autre temps, couleurs criardes ou qui jurent
- images étirées / pixelisées / déformées, logo amateur
- look « années 2000-2010 », dégradés et boutons en relief old-school
- page quasi vide, manifestement inachevée ou cassée

Réponds false si le site est propre/moderne, MÊME s'il est simple, sobre ou \
minimaliste. Simple ≠ à refaire. Épuré et net = false.
Si la capture est blanche, illisible, vide, une page d'erreur, ou si elle \
montre SURTOUT une fenêtre de cookies/consentement (tu ne vois donc pas le \
vrai site) → réponds false (on ne juge pas).

CALIBRE bien ta confiance : mets ≥ 90 UNIQUEMENT si c'est FLAGRANT (vraiment \
vieux, cassé ou amateur — un propriétaire honnête l'admettrait). Si le site \
est seulement « un peu daté » ou « banal mais correct », mets 80-85 (il \
passera en « à vérifier », pas en « sûr »).

Réponds en UN SEUL bloc JSON, rien avant ni après :
{{"a_refaire": true|false, "confiance": 0-100, "style": "2-4 mots (ex: \
moderne et propre / daté années 2010 / amateur bricolé)", "raison": "UNE \
phrase en français simple, ce que le propriétaire verrait lui-même"}}"""


# Quand Google répond 429 (quota épuisé), inutile de le retaper à chaque
# site pendant le même run : on le met en pause pour ce processus.
_google_dead = False


def _vision_call(prompt: str, png_b64: str, keys: dict) -> tuple[str, str]:
    """Envoie image+texte à une IA qui voit, avec bascule automatique :
    Gemini Flash (le moins cher) → Mistral Pixtral → Claude → GPT-4o.
    Renvoie (texte, provider). Lève RuntimeError si aucune n'a répondu.

    Au 16/06/2026 : Google souvent en quota (429) et Claude sans crédit →
    c'est Mistral qui porte. La bascule rend ça transparent et le système
    se répare tout seul dès qu'une IA redevient disponible."""
    global _google_dead
    import requests
    errors = []

    g = (keys.get("google") or "").strip()
    if g and not _google_dead:
        try:
            url = ("https://generativelanguage.googleapis.com/v1beta/models/"
                   f"gemini-2.5-flash:generateContent?key={g}")
            r = requests.post(url, timeout=90, json={
                "contents": [{"parts": [
                    {"text": prompt},
                    {"inline_data": {"mime_type": "image/png", "data": png_b64}},
                ]}],
                "generationConfig": {"temperature": 0},
            })
            if r.status_code < 400:
                data = r.json()
                txt = "".join(
                    p.get("text", "")
                    for p in data["candidates"][0]["content"]["parts"])
                if txt.strip():
                    return txt, "google"
            if r.status_code == 429:
                _google_dead = True  # quota épuisé : on arrête de le taper
            errors.append(f"google {r.status_code}: {r.text[:120]}")
        except Exception as exc:
            errors.append(f"google {exc}")

    ms = (keys.get("mistral") or "").strip()
    if ms:
        import time
        # Mistral limite la cadence (429 « rate_limited ») : on patiente et on
        # retente, plutôt que d'abandonner le site.
        for attempt in range(4):
            try:
                r = requests.post(
                    "https://api.mistral.ai/v1/chat/completions", timeout=90,
                    headers={"Authorization": f"Bearer {ms}",
                             "Content-Type": "application/json"},
                    json={"model": "pixtral-large-latest", "temperature": 0,
                          "messages": [{"role": "user", "content": [
                              {"type": "text", "text": prompt},
                              {"type": "image_url",
                               "image_url": f"data:image/png;base64,{png_b64}"}]}]})
                if r.status_code < 400:
                    txt = r.json()["choices"][0]["message"]["content"]
                    if (txt or "").strip():
                        return txt, "mistral"
                    errors.append("mistral réponse vide")
                    break
                if r.status_code == 429 and attempt < 3:
                    time.sleep(3 + 3 * attempt)  # 3s, 6s, 9s
                    continue
                errors.append(f"mistral {r.status_code}: {r.text[:120]}")
                break
            except Exception as exc:
                errors.append(f"mistral {exc}")
                break

    a = (keys.get("anthropic") or "").strip()
    if a:
        try:
            r = requests.post(
                "https://api.anthropic.com/v1/messages", timeout=90,
                headers={"x-api-key": a, "anthropic-version": "2023-06-01",
                         "content-type": "application/json"},
                json={"model": "claude-3-5-sonnet-latest", "max_tokens": 700,
                      "messages": [{"role": "user", "content": [
                          {"type": "image", "source": {
                              "type": "base64", "media_type": "image/png",
                              "data": png_b64}},
                          {"type": "text", "text": prompt}]}]})
            if r.status_code < 400:
                data = r.json()
                txt = "".join(p.get("text", "") for p in data.get("content", [])
                              if p.get("type") == "text")
                if txt.strip():
                    return txt, "anthropic"
            errors.append(f"anthropic {r.status_code}: {r.text[:120]}")
        except Exception as exc:
            errors.append(f"anthropic {exc}")

    o = (keys.get("openai") or "").strip()
    if o:
        try:
            r = requests.post(
                "https://api.openai.com/v1/chat/completions", timeout=90,
                headers={"Authorization": f"Bearer {o}",
                         "Content-Type": "application/json"},
                json={"model": "gpt-4o-mini", "temperature": 0,
                      "messages": [{"role": "user", "content": [
                          {"type": "text", "text": prompt},
                          {"type": "image_url", "image_url": {
                              "url": f"data:image/png;base64,{png_b64}"}}]}]})
            if r.status_code < 400:
                txt = r.json()["choices"][0]["message"]["content"]
                if (txt or "").strip():
                    return txt, "openai"
            errors.append(f"openai {r.status_code}: {r.text[:120]}")
        except Exception as exc:
            errors.append(f"openai {exc}")

    raise RuntimeError(("aucune IA visuelle — " + " | ".join(errors))
                       if errors else "aucune clé IA visuelle")


def judge_design(png: bytes, name: str = "", metier: str = "",
                 keys: dict | None = None) -> dict:
    """Fait juger une capture par l'IA. Renvoie :
      {ok, to_redo, confidence, style, reason, provider, error}
    to_redo n'est VRAI que si l'IA dit oui AVEC une confiance ≥ seuil."""
    out = {"ok": False, "to_redo": False, "to_verify": False, "tier": "non",
           "confidence": 0, "style": "", "reason": "", "provider": "",
           "error": ""}
    if not png:
        out["error"] = "pas de capture"
        return out
    if keys is None:
        try:
            from . import shared_secrets
            keys = shared_secrets.get_ai_keys() or {}
        except Exception:
            keys = {}
    b64 = base64.b64encode(png).decode("ascii")
    try:
        text, provider = _vision_call(_prompt(name, metier), b64, keys)
    except Exception as exc:
        out["error"] = str(exc)[:200]
        return out
    out["provider"] = provider
    m = re.search(r"\{[\s\S]*\}", text or "")
    if not m:
        out["error"] = f"pas de JSON: {(text or '')[:120]}"
        return out
    try:
        data = json.loads(m.group(0))
    except Exception as exc:
        out["error"] = f"JSON invalide: {exc}"
        return out
    out["ok"] = True
    conf = data.get("confiance")
    try:
        conf = int(conf)
    except Exception:
        conf = 0
    out["confidence"] = max(0, min(100, conf))
    out["style"] = (data.get("style") or "").strip()
    out["reason"] = (data.get("raison") or "").strip()
    said_redo = bool(data.get("a_refaire"))
    conf = out["confidence"]
    # Deux niveaux selon la confiance (précision d'abord).
    if said_redo and conf >= SURE_CONFIDENCE:
        out["tier"] = "sur"
    elif said_redo and conf >= VERIFY_CONFIDENCE:
        out["tier"] = "verifier"
    else:
        out["tier"] = "non"
    out["to_redo"] = out["tier"] == "sur"        # « à refaire » certain
    out["to_verify"] = out["tier"] == "verifier"  # « à vérifier » par Jordan
    return out


# ---------------------------------------------------------------------------
# 3) Orchestration : URL → verdict complet
# ---------------------------------------------------------------------------
def assess_visually(url: str, name: str = "", metier: str = "",
                    keys: dict | None = None) -> dict:
    """Capture + jugement. Renvoie un verdict homogène avec site_quality :
      {to_redo, category, label, reasons, score, confidence, style,
       provider, ok, error, png_len}"""
    base = {"to_redo": False, "to_verify": False, "tier": "non",
            "category": "", "label": "", "reasons": [], "score": 0,
            "confidence": 0, "style": "", "provider": "", "ok": False,
            "error": "", "png_len": 0}
    png = screenshot_site(url)
    if not png:
        base["error"] = "capture impossible"
        return base
    base["png_len"] = len(png)
    verdict = judge_design(png, name, metier, keys)
    base.update({"confidence": verdict["confidence"], "tier": verdict["tier"],
                 "style": verdict["style"], "provider": verdict["provider"],
                 "ok": verdict["ok"], "error": verdict["error"]})
    reason = verdict["reason"] or "design daté / amateur (vu à l'œil)"
    if verdict["to_redo"]:                       # niveau « sûr »
        base.update({
            "to_redo": True, "category": VISION_CATEGORY,
            "label": "Site à refaire (look)", "reasons": [reason],
            "score": max(70, min(95, verdict["confidence"]))})
    elif verdict["to_verify"]:                   # niveau « à vérifier »
        base.update({
            "to_verify": True, "category": VERIFY_CATEGORY,
            "label": "À vérifier (look)", "reasons": [reason],
            "score": verdict["confidence"]})
    return base


__all__ = ["screenshot_site", "judge_design", "assess_visually",
           "VISION_CATEGORY", "VERIFY_CATEGORY", "MIN_CONFIDENCE",
           "SURE_CONFIDENCE", "VERIFY_CONFIDENCE"]
