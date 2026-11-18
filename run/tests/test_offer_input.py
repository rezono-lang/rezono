from input_contract_cases import DIGEST, verify


def test_exact_price_line_shape():
    base = dict(sku="small", currency="EUR", period_seconds=3600,
                period_price_micros=120001, setup_price_micros=0, source_sha256=DIGEST)
    bad = [
        dict(sku=""), dict(currency="EUR\n"), dict(currency="eur"), dict(extra=1),
        dict(period_seconds=0), dict(period_seconds=True), dict(period_seconds=0.5),
        dict(period_price_micros=-1), dict(period_price_micros=0.5),
        dict(setup_price_micros=-1), dict(setup_price_micros=True),
        dict(source_sha256=DIGEST + "\n"), dict(source_sha256="x" * 64),
    ]
    verify("offer.json", [base, base | dict(period_price_micros=0, setup_price_micros=1)],
           [base | patch for patch in bad])
