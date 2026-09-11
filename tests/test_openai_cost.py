from __future__ import annotations

from types import SimpleNamespace

from app.costing import (
    JobCostMeter,
    cost_meter_scope,
    estimate_miss_cost_cents,
    record_chat_usage,
    record_transcription_usage,
)
from app.config import settings


def test_chat_cost_from_prompt_and_completion_tokens():
    usage = SimpleNamespace(
        prompt_tokens=2_000_000,
        completion_tokens=500_000,
        prompt_tokens_details=SimpleNamespace(cached_tokens=0),
    )
    with cost_meter_scope() as meter:
        added = meter.add_chat(SimpleNamespace(usage=usage))
    expected = round((2.0 * settings.openai_chat_input_usd_per_mtok + 0.5 * settings.openai_chat_output_usd_per_mtok) * 100, 4)
    assert added == expected
    assert meter.cents == expected
    assert meter.openai_called


def test_chat_cost_accounts_for_cached_tokens():
    usage = SimpleNamespace(
        prompt_tokens=1_000_000,
        completion_tokens=0,
        prompt_tokens_details=SimpleNamespace(cached_tokens=400_000),
    )
    with cost_meter_scope() as meter:
        meter.add_chat(SimpleNamespace(usage=usage))
    expected = round(
        (
            0.6 * settings.openai_chat_input_usd_per_mtok
            + 0.4 * settings.openai_chat_cached_input_usd_per_mtok
        )
        * 100,
        4,
    )
    assert meter.cents == expected


def test_transcription_cost_from_audio_tokens():
    usage = SimpleNamespace(
        input_tokens=1_000_000,
        output_tokens=100_000,
        input_token_details=SimpleNamespace(audio_tokens=900_000, text_tokens=100_000),
    )
    with cost_meter_scope() as meter:
        meter.add_transcription(SimpleNamespace(usage=usage), duration_seconds=60)
    expected = round(
        (
            1.0 * settings.openai_transcribe_input_usd_per_mtok
            + 0.1 * settings.openai_transcribe_output_usd_per_mtok
        )
        * 100,
        4,
    )
    assert meter.cents == expected


def test_transcription_falls_back_to_duration_minutes():
    with cost_meter_scope() as meter:
        meter.add_transcription(SimpleNamespace(usage=None), duration_seconds=120)
    expected = round(2.0 * settings.openai_transcribe_usd_per_min * 100, 4)
    assert meter.cents == expected


def test_record_helpers_use_active_meter():
    with cost_meter_scope() as meter:
        record_chat_usage(
            SimpleNamespace(
                usage=SimpleNamespace(
                    prompt_tokens=0,
                    completion_tokens=0,
                    prompt_tokens_details=None,
                )
            ),
            fallback_cents=0.1,
        )
        record_transcription_usage(SimpleNamespace(usage=None), duration_seconds=60)
    assert meter.chat_calls == 1
    assert meter.transcribe_calls == 1
    assert meter.cents > 0


def test_estimate_still_used_for_reservation_math():
    assert estimate_miss_cost_cents(frame_count=10) == round(
        settings.cost_text_cents_per_extract + 10 * settings.cost_ocr_cents_per_slide,
        4,
    )


def test_dashboard_overview_sums_job_costs_including_failures():
    from app import dashboard_stats

    week_jobs = [
        {"status": "completed", "cache_hit": False, "cost_cents": 1.5, "created_at": "2099-01-01"},
        {"status": "failed", "cache_hit": False, "cost_cents": 0.75, "created_at": "2099-01-02"},
        {"status": "completed", "cache_hit": True, "cost_cents": 0, "created_at": "2099-01-03"},
        {"status": "pending", "cache_hit": False, "cost_cents": 9, "created_at": "2099-01-04"},
    ]

    def fake_fetch_all(sql, params=None):
        if "from extract_jobs" in sql:
            return week_jobs
        return []

    def fake_fetch_one(sql, params=None):
        if "pg_database_size" in sql:
            return {
                "db_name": "reciapp",
                "db_pretty": "12 MB",
                "db_bytes": 12_582_912,
                "app_pretty": "200 kB",
                "app_bytes": 204_800,
                "catalog_pretty": "11 MB",
                "catalog_bytes": 12_378_112,
                "cluster_pretty": "20 MB",
                "cluster_bytes": 20_971_520,
            }
        if "sum(cost_cents)" in sql:
            return {"total": 2.25}
        return {"count": 0}

    original_fetch_all = dashboard_stats.fetch_all
    original_fetch_one = dashboard_stats.fetch_one
    original_defaults = dashboard_stats.get_app_defaults
    dashboard_stats.fetch_all = fake_fetch_all
    dashboard_stats.fetch_one = fake_fetch_one
    dashboard_stats.get_app_defaults = lambda: SimpleNamespace(
        default_pro_monthly_price_cents=999,
        pro_margin_ratio=0.5,
    )
    try:
        overview = dashboard_stats.dashboard_overview()
    finally:
        dashboard_stats.fetch_all = original_fetch_all
        dashboard_stats.fetch_one = original_fetch_one
        dashboard_stats.get_app_defaults = original_defaults

    assert overview["cost_cents_week"] == 2.25
    assert overview["cost_usd_week"] == 0.0225
    assert overview["db_size_pretty"] == "12 MB"
    assert overview["app_size_pretty"] == "200 kB"
