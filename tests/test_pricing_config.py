"""R3-09: the pricing config matches the chosen Phase-2 model
(company/docs/finance/BUDGET.md §6: Plus $15/mo or $150/yr with 100 credits/mo;
packs $12/$30/$60 for 50/150/400 credits) and stays display-data only — no
template renders a price while payments are off."""

import pathlib
import re

from web.app.config import WebConfig, config

TEMPLATES = pathlib.Path(__file__).resolve().parents[1] / "web" / "app" / "templates"


def test_credit_packs_match_the_phase2_model():
    packs = [(p["name"], p["credits"], p["usd"]) for p in config.credit_packs]
    assert packs == [("Starter", 50, 12), ("Value", 150, 30), ("Pro", 400, 60)]
    # volume discount: $/credit falls with pack size (the pricing rationale)
    per_credit = [p["usd"] / p["credits"] for p in config.credit_packs]
    assert per_credit == sorted(per_credit, reverse=True)
    assert [p["name"] for p in config.credit_packs if p.get("anchor")] == ["Value"]


def test_plus_plan_matches_the_phase2_model():
    assert config.plus_plan == {"name": "JBHNTR Plus", "usd_month": 15,
                                "usd_year": 150, "credits_month": 100}


def test_legacy_month_plans_are_gone():
    # $30/$50/$60 for 1/2/3 months contradicted the chosen pricing and had no reader.
    assert not hasattr(config, "plans")
    assert "plans" not in WebConfig.__dataclass_fields__


def test_payments_stay_off_by_default():
    assert config.payments_enabled is False


def test_no_template_renders_a_price_or_the_legacy_allowance_table():
    """Prices are config data for a future purchase flow, not copy: no template
    may read them, and the dead Free/Premium doc-allowance table is gone."""
    srcs = {p: p.read_text(encoding="utf-8") for p in TEMPLATES.rglob("*.html")}
    assert len(srcs) >= 20, len(srcs)                 # really scanning templates
    pat = re.compile(r"config\.(plans|credit_packs|plus_plan)\b")
    offenders = [str(p.relative_to(TEMPLATES)) for p, s in srcs.items() if pat.search(s)]
    assert not offenders, offenders
    assert not (TEMPLATES / "partials" / "_compare.html").exists()
