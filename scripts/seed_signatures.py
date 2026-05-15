"""Crée 4 signatures HTML belles, attribuées chacune à son adresse mail.
Lance une fois pour seeder les signatures.
"""
from __future__ import annotations
import sys, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
sys.path.insert(0, r'C:\Users\jorda\Triskell\triskell-core')
sys.path.insert(0, r'C:\Users\jorda\Triskell\triskell-command')

from triskell_command.web.api import Api
api = Api()

LOGO_URL = 'https://rmaafrrseafghptlsgdz.supabase.co/storage/v1/object/public/chat-images/triskell-logo.png'

def sig_triskell():
    return f'''<table cellpadding="0" cellspacing="0" border="0" style="font-family:-apple-system,Segoe UI,Helvetica,Arial,sans-serif;font-size:13px;line-height:1.5;color:#1a1a20;border-collapse:collapse;margin-top:18px;">
  <tr>
    <td valign="top" style="padding-right:18px;border-right:2px solid #5b5fd6;">
      <img src="{LOGO_URL}" alt="Triskell Studio" width="64" height="64" style="display:block;width:64px;height:64px;border-radius:12px;"/>
    </td>
    <td valign="top" style="padding-left:18px;">
      <div style="font-size:15px;font-weight:700;color:#1a1a20;letter-spacing:0.2px;">Jordan Bourillot</div>
      <div style="font-size:11px;color:#7a7a82;letter-spacing:1.5px;text-transform:uppercase;font-weight:600;margin:2px 0 8px;">Fondateur &middot; Triskell Studio</div>
      <div style="font-size:12px;color:#4a4a55;line-height:1.65;">
        <a href="mailto:contact@triskell-studio.fr" style="color:#4a4a55;text-decoration:none;">&#9993; contact@triskell-studio.fr</a><br>
        <a href="tel:+33000000000" style="color:#4a4a55;text-decoration:none;">&#9742; 06 00 00 00 00</a><br>
        <a href="https://triskell-studio.fr" style="color:#5b5fd6;text-decoration:none;font-weight:600;">&#8599; triskell-studio.fr</a>
      </div>
    </td>
  </tr>
</table>
<div style="font-family:-apple-system,Segoe UI,Helvetica,Arial,sans-serif;font-size:10px;color:#a8a8b8;letter-spacing:0.5px;margin-top:12px;">
  🌊 Bretagne &middot; 100 % français &middot;
  <a href="https://lagriffe-studio.fr" style="color:#a8a8b8;">Lagriffe</a> &middot;
  <a href="https://rankus.fr" style="color:#a8a8b8;">RankUs</a> &middot;
  <a href="https://studio-wow.fr" style="color:#a8a8b8;">WoW</a>
</div>'''

def sig_lagriffe():
    return '''<table cellpadding="0" cellspacing="0" border="0" style="font-family:-apple-system,Segoe UI,Helvetica,Arial,sans-serif;font-size:13px;line-height:1.5;color:#1a1a20;border-collapse:collapse;margin-top:18px;">
  <tr>
    <td valign="top" style="padding-right:18px;border-right:2px solid #d4af37;">
      <table cellpadding="0" cellspacing="0" border="0"><tr><td align="center" valign="middle" style="background:linear-gradient(135deg,#0f172a 0%,#1e293b 100%);width:64px;height:64px;border-radius:12px;color:#d4af37;font-size:32px;font-weight:700;font-family:Georgia,serif;line-height:64px;letter-spacing:-1px;">L</td></tr></table>
    </td>
    <td valign="top" style="padding-left:18px;">
      <div style="font-size:15px;font-weight:700;color:#0f172a;letter-spacing:0.2px;">Jordan Bourillot</div>
      <div style="font-size:11px;color:#d4af37;letter-spacing:1.5px;text-transform:uppercase;font-weight:700;margin:2px 0 8px;">Lagriffe Studio</div>
      <div style="font-size:12px;color:#4a4a55;line-height:1.65;">
        <a href="mailto:contact@lagriffe-studio.fr" style="color:#4a4a55;text-decoration:none;">&#9993; contact@lagriffe-studio.fr</a><br>
        <a href="tel:+33000000000" style="color:#4a4a55;text-decoration:none;">&#9742; 06 00 00 00 00</a><br>
        <a href="https://lagriffe-studio.fr" style="color:#d4af37;text-decoration:none;font-weight:600;">&#8599; lagriffe-studio.fr</a>
      </div>
    </td>
  </tr>
</table>
<div style="font-family:-apple-system,Segoe UI,Helvetica,Arial,sans-serif;font-size:10px;color:#a8a8b8;letter-spacing:0.5px;margin-top:12px;">
  Sites web sur-mesure &middot; Une marque <a href="https://triskell-studio.fr" style="color:#a8a8b8;">Triskell Studio</a>
</div>'''

def sig_wow():
    return '''<table cellpadding="0" cellspacing="0" border="0" style="font-family:Georgia,Times,serif;font-size:13px;line-height:1.5;color:#1a1a20;border-collapse:collapse;margin-top:18px;">
  <tr>
    <td valign="top" style="padding-right:20px;border-right:1px solid #c9a572;">
      <table cellpadding="0" cellspacing="0" border="0"><tr><td align="center" valign="middle" style="background:#0B0B0F;width:64px;height:64px;border-radius:50%;color:#F4EFE6;font-size:14px;font-weight:600;font-family:Georgia,serif;line-height:64px;letter-spacing:2px;">WoW</td></tr></table>
    </td>
    <td valign="top" style="padding-left:20px;">
      <div style="font-size:16px;font-weight:400;color:#0B0B0F;letter-spacing:0.3px;font-family:Georgia,serif;">Jordan Bourillot</div>
      <div style="font-size:10px;color:#7A7A82;letter-spacing:3px;text-transform:uppercase;font-weight:600;margin:4px 0 10px;font-family:-apple-system,Helvetica,sans-serif;">Studio WoW &middot; Direction</div>
      <div style="font-size:12px;color:#4a4a55;line-height:1.7;font-family:-apple-system,Helvetica,sans-serif;">
        <a href="mailto:contact@studio-wow.fr" style="color:#4a4a55;text-decoration:none;">&#9993; contact@studio-wow.fr</a><br>
        <a href="tel:+33000000000" style="color:#4a4a55;text-decoration:none;">&#9742; 06 00 00 00 00</a><br>
        <a href="https://studio-wow.fr" style="color:#C9A572;text-decoration:none;font-weight:600;letter-spacing:0.5px;">&#8599; studio-wow.fr</a>
      </div>
    </td>
  </tr>
</table>
<div style="font-family:Georgia,serif;font-size:10px;color:#7A7A82;letter-spacing:2px;text-transform:uppercase;margin-top:14px;font-style:italic;">
  Studio web premium &middot; Une marque <a href="https://triskell-studio.fr" style="color:#7A7A82;text-decoration:none;">Triskell</a>
</div>'''

def sig_rankus():
    return '''<table cellpadding="0" cellspacing="0" border="0" style="font-family:-apple-system,Segoe UI,Helvetica,Arial,sans-serif;font-size:13px;line-height:1.5;color:#1a1a20;border-collapse:collapse;margin-top:18px;">
  <tr>
    <td valign="top" style="padding-right:18px;border-right:2px solid #10b981;">
      <table cellpadding="0" cellspacing="0" border="0"><tr><td align="center" valign="middle" style="background:linear-gradient(135deg,#10b981 0%,#0ea5e9 100%);width:64px;height:64px;border-radius:14px;color:#fff;font-size:24px;font-weight:800;font-family:-apple-system,Helvetica,sans-serif;line-height:64px;letter-spacing:-1px;">R&uarr;</td></tr></table>
    </td>
    <td valign="top" style="padding-left:18px;">
      <div style="font-size:15px;font-weight:700;color:#1a1a20;letter-spacing:0.2px;">Jordan Bourillot</div>
      <div style="font-size:11px;color:#10b981;letter-spacing:1.5px;text-transform:uppercase;font-weight:700;margin:2px 0 8px;">RankUs Studio &middot; SEO</div>
      <div style="font-size:12px;color:#4a4a55;line-height:1.65;">
        <a href="mailto:contact@rankus.fr" style="color:#4a4a55;text-decoration:none;">&#9993; contact@rankus.fr</a><br>
        <a href="tel:+33000000000" style="color:#4a4a55;text-decoration:none;">&#9742; 06 00 00 00 00</a><br>
        <a href="https://rankus.fr" style="color:#10b981;text-decoration:none;font-weight:600;">&#8599; rankus.fr</a>
      </div>
    </td>
  </tr>
</table>
<div style="font-family:-apple-system,Segoe UI,Helvetica,Arial,sans-serif;font-size:10px;color:#a8a8b8;letter-spacing:0.5px;margin-top:12px;">
  SEO sur-mesure pour sites Triskell &middot; Une marque <a href="https://triskell-studio.fr" style="color:#a8a8b8;">Triskell Studio</a>
</div>'''

signatures = [
    {'id': 'sig-triskell', 'name': 'Triskell Studio · officielle',
     'body_text': 'Jordan Bourillot — Fondateur, Triskell Studio\ncontact@triskell-studio.fr · 06 00 00 00 00\ntriskell-studio.fr\n🌊 Bretagne · 100 % français',
     'body_html': sig_triskell(), 'account_ids': ['primary']},
    {'id': 'sig-lagriffe', 'name': 'Lagriffe Studio',
     'body_text': 'Jordan Bourillot — Lagriffe Studio\ncontact@lagriffe-studio.fr · 06 00 00 00 00\nlagriffe-studio.fr',
     'body_html': sig_lagriffe(), 'account_ids': ['lagriffe']},
    {'id': 'sig-wow', 'name': 'Studio WoW · premium',
     'body_text': 'Jordan Bourillot — Studio WoW\ncontact@studio-wow.fr · 06 00 00 00 00\nstudio-wow.fr',
     'body_html': sig_wow(), 'account_ids': ['wow']},
    {'id': 'sig-rankus', 'name': 'RankUs Studio · SEO',
     'body_text': 'Jordan Bourillot — RankUs Studio\ncontact@rankus.fr · 06 00 00 00 00\nrankus.fr',
     'body_html': sig_rankus(), 'account_ids': ['rankus']},
]

for s in signatures:
    r = api.signature_save({'signature': s})
    print(f'  {s["name"]:<35}: {"OK" if r.get("ok") else "FAIL: " + str(r.get("error"))}')

print('\nVerif final :')
r = api.signatures_list()
for s in r.get('signatures', []):
    print(f'  - {s.get("name")} (comptes: {s.get("account_ids")})')
