# -*- coding: utf-8 -*-
"""Obtenir le "refresh token" Google Postmaster — a lancer UNE fois.

A quoi ca sert : pour lire la note de reputation que Gmail donne a tes domaines,
Triskell doit avoir une autorisation permanente de ton compte Google. Ce petit
programme te la fait obtenir en 1 minute, sans rien installer.

AVANT de lancer, tu dois avoir (cote Google, gratuit) :
  1. Ajoute tes domaines sur https://postmaster.google.com (bouton +, puis
     verifie chaque domaine — un petit reglage DNS guide par Google).
  2. Sur https://console.cloud.google.com :
     - cree un projet (ou prends-en un existant) ;
     - menu "APIs et services" > "Bibliotheque" > active
       "Gmail Postmaster Tools API" ;
     - menu "Identifiants" > "Creer des identifiants" > "ID client OAuth" >
       type "Application de bureau". Tu obtiens un CLIENT ID et un CLIENT SECRET.

ENSUITE, lance :
    python -X utf8 scripts/postmaster_token.py

Colle le Client ID puis le Client secret quand c'est demande, autorise dans le
navigateur qui s'ouvre, et le programme t'affiche le REFRESH TOKEN a copier dans
Triskell (ecran Sante > Reputation > Activer).
"""
from __future__ import annotations

import http.server
import secrets
import socketserver
import sys
import threading
import time
import urllib.parse
import webbrowser

SCOPE = "https://www.googleapis.com/auth/postmaster.readonly"
AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_URL = "https://oauth2.googleapis.com/token"
PORT = 8765


def main() -> int:
    print("=" * 64)
    print("  Autorisation Google Postmaster — Triskell")
    print("=" * 64)
    client_id = input("Client ID     : ").strip()
    client_secret = input("Client secret : ").strip()
    if not client_id or not client_secret:
        print("Client ID et Client secret obligatoires.")
        return 1

    redirect_uri = f"http://localhost:{PORT}/"
    state = secrets.token_urlsafe(16)
    holder: dict = {}

    class Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self):  # noqa: N802
            params = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
            holder["code"] = (params.get("code") or [None])[0]
            holder["state"] = (params.get("state") or [None])[0]
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write(
                "<h2>C'est bon !</h2><p>Tu peux fermer cet onglet et revenir "
                "au terminal.</p>".encode("utf-8"))

        def log_message(self, *a):  # silence
            pass

    httpd = socketserver.TCPServer(("", PORT), Handler)
    threading.Thread(target=httpd.handle_request, daemon=True).start()

    url = AUTH_URL + "?" + urllib.parse.urlencode({
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "scope": SCOPE,
        "access_type": "offline",
        "prompt": "consent",
        "state": state,
    })
    print()
    print("Ouvre cette adresse (connecte-toi avec le compte Google qui possede")
    print("les domaines, celui de Postmaster) :")
    print()
    print(url)
    print()
    try:
        webbrowser.open(url)
    except Exception:
        pass

    print("En attente de l'autorisation (3 min max)...")
    for _ in range(180):
        if holder.get("code"):
            break
        time.sleep(1)

    code = holder.get("code")
    if not code:
        print("Aucune autorisation recue. Relance et reessaie.")
        return 1
    if holder.get("state") != state:
        print("Securite : etat invalide. Relance et reessaie.")
        return 1

    import requests
    r = requests.post(TOKEN_URL, data={
        "code": code,
        "client_id": client_id,
        "client_secret": client_secret,
        "redirect_uri": redirect_uri,
        "grant_type": "authorization_code",
    }, timeout=20)
    if r.status_code != 200:
        print(f"Echec de l'echange ({r.status_code}) : {r.text[:300]}")
        return 1
    tok = r.json() or {}
    refresh = tok.get("refresh_token")
    if not refresh:
        print("Pas de refresh_token renvoye. Reessaie en revoquant l'acces dans")
        print("ton compte Google, puis relance (le 'prompt=consent' force le renvoi).")
        return 1

    print()
    print("=" * 64)
    print("  REFRESH TOKEN (a coller dans Triskell, ecran Sante > Reputation) :")
    print("=" * 64)
    print(refresh)
    print("=" * 64)
    print("Garde aussi le Client ID et le Client secret : les 3 vont ensemble.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
