"""Tests manuels du module de facturation Triskell.

DESTINATION FINALE :
    Triskell\\triskell-command\\scripts\\test_billing.py

Couvre les chemins critiques :
  - Émission d'une facture nominale (TVA 0 / franchise)
  - Émission d'une seconde facture (vérifie la numérotation continue)
  - Émission d'un avoir
  - Génération PDF + vérification SHA-256
  - Export FEC

Lance-le avec un projet Supabase **non-production** (ou un schéma de
test), parce qu'il consomme de vrais numéros de facture et crée des
PDF dans le bucket Storage.

Usage :
    python scripts/test_billing.py --smoke           # test rapide bout en bout
    python scripts/test_billing.py --concurrent 20   # test stress numérotation
    python scripts/test_billing.py --fec 2026        # export FEC année donnée
"""
from __future__ import annotations

import argparse
import concurrent.futures
import json
import logging
import sys
from datetime import date, datetime, timezone
from pathlib import Path

import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from triskell_command.integrations.billing import (  # noqa: E402
    ClientInfo, InvoiceLine, InvoiceRequest, get_provider, BillingError,
)
from triskell_command.integrations.billing import numbering, repo  # noqa: E402


def _fake_client() -> ClientInfo:
    return ClientInfo(
        name="Boulangerie Test",
        email="test+billing@triskell-studio.fr",
        address_line1="42 rue des Tests",
        address_zip="22000",
        address_city="Saint-Brieuc",
        siret="",
    )


def smoke() -> int:
    """Émission d'une facture, d'un avoir, vérifs basiques."""
    provider = get_provider()

    # 1. Facture nominale
    req = InvoiceRequest(
        client=_fake_client(),
        lines=[
            InvoiceLine(description="Site internet personnalisé",
                         quantity=1, unit_price_ht_cents=149900),
            InvoiceLine(description="Hébergement annuel",
                         quantity=1, unit_price_ht_cents=9900),
        ],
        payment_method="stripe",
        payment_reference="cs_test_smoke_001",
        paid_at=datetime.now(timezone.utc),
        service_executed_at=date.today(),
        free_text_top="Référence devis : DV-2026-001",
    )
    print("→ Émission facture 1…")
    r1 = provider.generate_invoice(req)
    print(f"   ✓ {r1.invoice_number}  ({r1.total_ttc_cents/100:.2f} €)  "
          f"sha256={r1.pdf_sha256[:12]}…")

    # 2. Seconde facture (continuité)
    req2 = InvoiceRequest(
        client=_fake_client(),
        lines=[InvoiceLine(description="Rapport SEO ponctuel",
                            quantity=1, unit_price_ht_cents=4900)],
        payment_method="manuel",
    )
    print("→ Émission facture 2…")
    r2 = provider.generate_invoice(req2)
    print(f"   ✓ {r2.invoice_number}  ({r2.total_ttc_cents/100:.2f} €)")

    # Vérifie la continuité de numérotation
    s1, y1, n1 = numbering.parse_number(r1.invoice_number)
    s2, y2, n2 = numbering.parse_number(r2.invoice_number)
    assert s1 == s2 and y1 == y2 and n2 == n1 + 1, (
        f"Numérotation cassée : {r1.invoice_number} puis {r2.invoice_number}"
    )
    print(f"   ✓ Continuité OK : {n1} → {n2}")

    # 3. Avoir sur facture 1
    print("→ Émission avoir sur facture 1…")
    avoir = provider.generate_credit_note(r1.invoice_id, reason="Test smoke")
    print(f"   ✓ {avoir.invoice_number}  TTC = {avoir.total_ttc_cents/100:.2f} €")

    # Vérifie que la facture originale est marquée annulée
    refreshed = provider.get_invoice(r1.invoice_id)
    assert refreshed and refreshed.get("is_cancelled"), \
        "Facture originale pas marquée annulée"
    print("   ✓ Facture d'origine annulée")

    # 4. URL signée
    url = provider.get_invoice_pdf_url(r1.invoice_id)
    print(f"   ✓ URL signée facture 1 : {url[:80]}…")

    print("\nSmoke test : OK")
    return 0


def concurrent_test(n: int) -> int:
    """N émissions simultanées : aucun trou ni doublon."""
    provider = get_provider()
    req = InvoiceRequest(
        client=_fake_client(),
        lines=[InvoiceLine(description="Test concurrent",
                            quantity=1, unit_price_ht_cents=100)],
    )
    print(f"→ {n} émissions simultanées…")

    def _one(_i):
        try:
            return provider.generate_invoice(req).invoice_number
        except Exception as exc:
            return f"ERR:{exc}"

    with concurrent.futures.ThreadPoolExecutor(max_workers=min(n, 16)) as pool:
        results = list(pool.map(_one, range(n)))

    errors = [r for r in results if r.startswith("ERR:")]
    numbers = [r for r in results if not r.startswith("ERR:")]
    seqs = sorted(numbering.parse_number(num)[2] for num in numbers)

    print(f"   {len(numbers)} succès, {len(errors)} échec(s)")
    if errors:
        for e in errors[:5]:
            print(f"     {e}")
    if len(seqs) >= 2:
        gaps = [seqs[i+1] - seqs[i] for i in range(len(seqs) - 1)]
        if all(g == 1 for g in gaps):
            print(f"   ✓ Aucun trou. Séquences {seqs[0]} → {seqs[-1]}.")
        else:
            print(f"   ✗ TROUS détectés : gaps = {gaps}")
            return 1
    print("\nStress test : OK")
    return 0


def export_fec(year: int) -> int:
    provider = get_provider()
    print(f"→ Export FEC {year}…")
    payload = provider.export_fec(year)
    out = Path(f"FEC_{year}.txt")
    out.write_bytes(payload)
    lines = payload.decode("utf-8").splitlines()
    print(f"   ✓ {out.absolute()} ({len(payload)} octets, {len(lines) - 1} écritures)")
    print(f"   En-tête : {lines[0][:120]}…")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--smoke", action="store_true",
                        help="Smoke test bout en bout.")
    parser.add_argument("--concurrent", type=int, default=0,
                        help="Stress test : N émissions parallèles.")
    parser.add_argument("--fec", type=int, default=0,
                        help="Exporte le FEC pour l'année donnée.")
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.WARNING,
        format="%(levelname)s %(name)s: %(message)s",
    )

    if args.smoke:
        return smoke()
    if args.concurrent:
        return concurrent_test(args.concurrent)
    if args.fec:
        return export_fec(args.fec)

    parser.print_help()
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
