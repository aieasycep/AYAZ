"""Unit tests for ``ayaz.services.channels`` — label mapping + source-type split.

``source_type`` is the foundation of the "kaynak-tipi mutabakatı" fix: it
tells the metric layer whether a channel is an ad platform (has spend, self-
attributed conversions) or an analytics source (no spend, measures real
on-site activity). Getting this classification wrong or missing a connector
silently reintroduces the double-counting bug, so every registered connector
key is checked explicitly here (locked against ``ConnectorRegistry``).
"""

from __future__ import annotations

import logging

import pytest

from ayaz.services.channels import channel_label, source_type


class TestChannelLabel:
    def test_known_key(self) -> None:
        assert channel_label("google_ads") == "Google Ads"

    def test_case_insensitive(self) -> None:
        assert channel_label("GOOGLE_ADS") == "Google Ads"

    def test_unknown_key_passes_through(self) -> None:
        assert channel_label("some_new_channel") == "some_new_channel"

    def test_none_returns_genel(self) -> None:
        assert channel_label(None) == "genel"

    def test_empty_string_returns_genel(self) -> None:
        assert channel_label("") == "genel"


class TestSourceType:
    """Every ad platform channel must classify as 'ad'; analytics sources as
    'analytics'. This list mirrors the registered connector keys (see
    ayaz/connectors/__init__.py / ConnectorRegistry.list_keys())."""

    @pytest.mark.parametrize(
        "key",
        [
            "google_ads",
            "meta_ads",
            "tiktok_ads",
            "linkedin_ads",
            "microsoft_ads",
            "criteo",
            "pinterest_ads",
            "sample",
        ],
    )
    def test_ad_channels(self, key: str) -> None:
        assert source_type(key) == "ad"

    @pytest.mark.parametrize("key", ["ga4", "search_console"])
    def test_analytics_channels(self, key: str) -> None:
        assert source_type(key) == "analytics"

    def test_case_insensitive(self) -> None:
        assert source_type("GA4") == "analytics"
        assert source_type("Google_Ads") == "ad"

    def test_unknown_key_defaults_to_ad(self) -> None:
        assert source_type("some_new_connector") == "ad"

    def test_none_defaults_to_ad(self) -> None:
        assert source_type(None) == "ad"

    def test_empty_string_defaults_to_ad(self) -> None:
        assert source_type("") == "ad"

    def test_unknown_key_logs_warning(self, caplog: pytest.LogCaptureFixture) -> None:
        """An unclassified connector key must not fail silently — it should
        emit a warning so a forgotten classification is noticed."""
        with caplog.at_level(logging.WARNING, logger="ayaz.services.channels"):
            source_type("brand_new_platform")
        assert any(
            "brand_new_platform" in record.message for record in caplog.records
        )

    def test_known_ad_key_does_not_log_warning(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        with caplog.at_level(logging.WARNING, logger="ayaz.services.channels"):
            source_type("google_ads")
        assert len(caplog.records) == 0

    def test_matches_connector_registry(self) -> None:
        """Every registered connector key must be classified as either 'ad'
        or 'analytics' — none should silently fall through to the unknown-key
        warning path (which would indicate a forgotten classification)."""
        from ayaz.connectors import ConnectorRegistry
        import ayaz.connectors  # noqa: F401 — ensure self-registration ran

        known_ad = {
            "google_ads", "meta_ads", "tiktok_ads", "linkedin_ads",
            "microsoft_ads", "criteo", "pinterest_ads", "sample",
        }
        known_analytics = {"ga4", "search_console"}
        for key in ConnectorRegistry.list_keys():
            assert key in known_ad or key in known_analytics, (
                f"Connector key {key!r} is registered but not classified in "
                "ayaz/services/channels.py's _AD_CHANNELS/_ANALYTICS_CHANNELS "
                "— it will silently default to 'ad' with a warning log."
            )
