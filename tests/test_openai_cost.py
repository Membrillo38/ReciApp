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


def test_dashboard_threats_flattens_fail2ban_snapshot():
    from app import dashboard_stats

    def fake_fetch_one(sql, params=None):
        return {
            "created_at": "2026-09-11T08:00:00+00:00",
            "metadata": {
                "jails": {
                    "sshd": {
                        "currently_failed": 2,
                        "total_failed": 10,
                        "currently_banned": 1,
                        "total_banned": 4,
                        "banned_ips": ["203.0.113.9"],
                    },
                    "reciapp-probes": {
                        "currently_failed": 1,
                        "total_failed": 5,
                        "currently_banned": 1,
                        "total_banned": 2,
                        "banned_ips": ["203.0.113.9", "198.51.100.7"],
                    },
                },
                "ssh_recent": [{"t": "2026-09-11", "line": "Failed publickey"}],
            },
        }

    def fake_fetch_all(sql, params=None):
        if "from security_events" in sql:
            return [
                {
                    "created_at": "2026-09-11T08:01:00+00:00",
                    "event": "scanner_probe",
                    "ip": "sha256:abc",
                    "metadata": {"path": "/.env", "ip": "198.51.100.7"},
                }
            ]
        return [{"created_at": "t", "method": "GET", "path": "/v1/me", "status_code": 401, "ip": "hash"}]

    original_one = dashboard_stats.fetch_one
    original_all = dashboard_stats.fetch_all
    dashboard_stats.fetch_one = fake_fetch_one
    dashboard_stats.fetch_all = fake_fetch_all
    try:
        threats = dashboard_stats.dashboard_threats()
    finally:
        dashboard_stats.fetch_one = original_one
        dashboard_stats.fetch_all = original_all

    assert threats["currently_banned"] == 2
    assert threats["currently_failed"] == 3
    assert {row["ip"] for row in threats["banned"]} == {"203.0.113.9", "198.51.100.7"}
    assert threats["events"][0]["event"] == "scanner_probe"
    assert "http_hits" not in threats


def test_dashboard_ips_reads_crowdsec_and_whitelist():
    from app import dashboard_stats

    def fake_fetch_one(sql, params=None):
        return {
            "created_at": "2026-09-15T18:00:00+00:00",
            "metadata": {
                "crowdsec": {
                    "decisions_count": 1,
                    "decisions": [
                        {
                            "ip": "203.0.113.50",
                            "reason": "crowdsecurity/ssh-bf",
                            "duration": "3h59m",
                            "origin": "crowdsec",
                        }
                    ],
                },
                "jails": {
                    "sshd": {
                        "banned_ips": ["198.51.100.9"],
                        "currently_banned": 1,
                    }
                },
                "whitelist": {
                    "ips": ["92.189.226.39"],
                    "cidrs": ["100.64.0.0/10"],
                },
            },
        }

    original = dashboard_stats.fetch_one
    dashboard_stats.fetch_one = fake_fetch_one
    try:
        data = dashboard_stats.dashboard_ips()
    finally:
        dashboard_stats.fetch_one = original

    assert data["blacklist_count"] == 2
    assert {row["ip"] for row in data["blacklist"]} == {"203.0.113.50", "198.51.100.9"}
    assert data["whitelist_ips"] == ["92.189.226.39"]
    assert data["whitelist_cidrs"] == ["100.64.0.0/10"]


def test_dashboard_ip_detail_joins_ban_probes_and_requests():
    from app import dashboard_stats
    from app.security import pseudonymous_ip

    ip = "203.0.113.50"
    ip_hash = pseudonymous_ip(ip)

    def fake_fetch_one(sql, params=None):
        return {
            "created_at": "2026-09-15T18:00:00+00:00",
            "metadata": {
                "crowdsec": {
                    "decisions": [
                        {
                            "ip": ip,
                            "reason": "crowdsecurity/ssh-bf",
                            "duration": "4h",
                            "origin": "crowdsec",
                        }
                    ],
                    "alerts": [
                        {
                            "ip": ip,
                            "scenario": "crowdsecurity/ssh-bf",
                            "events_count": 6,
                            "created_at": "2026-09-15T17:50:00+00:00",
                            "start_at": "2026-09-15T17:40:00+00:00",
                            "stop_at": "2026-09-15T17:50:00+00:00",
                        }
                    ],
                },
                "jails": {},
                "whitelist": {"ips": [], "cidrs": []},
                "ssh_recent": [
                    {"t": "2026-09-15T17:49:00", "line": f"Failed password for root from {ip} port 22"}
                ],
            },
        }

    def fake_fetch_all(sql, params=None):
        text = " ".join(sql.split())
        if "scanner_probe" in text:
            return [
                {
                    "created_at": "2026-09-15T17:00:00+00:00",
                    "event": "scanner_probe",
                    "ip": ip_hash,
                    "metadata": {"path": "/.env", "ip": ip},
                }
            ]
        if "api_request_logs" in text:
            assert params == (ip_hash,)
            return [
                {
                    "created_at": "2026-09-15T17:01:00+00:00",
                    "method": "GET",
                    "path": "/.env",
                    "status_code": 404,
                    "duration_ms": 12,
                    "ip": ip_hash,
                }
            ]
        return []

    original_one = dashboard_stats.fetch_one
    original_all = dashboard_stats.fetch_all
    dashboard_stats.fetch_one = fake_fetch_one
    dashboard_stats.fetch_all = fake_fetch_all
    try:
        detail = dashboard_stats.dashboard_ip_detail(ip)
    finally:
        dashboard_stats.fetch_one = original_one
        dashboard_stats.fetch_all = original_all

    assert detail["ban"]["reason"] == "crowdsecurity/ssh-bf"
    assert detail["probes"][0]["metadata"]["path"] == "/.env"
    assert detail["requests"][0]["status_code"] == 404
    assert detail["ssh_hits"]
    assert detail["crowd_alerts"][0]["events_count"] == 6
