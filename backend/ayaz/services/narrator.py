"""Insight narrator — generates Turkish (title, body) for a DetectorResult.

Design
------
The :class:`InsightNarrator` is a simple interface: one method ``narrate``
that accepts a :class:`~ayaz.services.insights.DetectorResult` and returns a
``(title, body)`` tuple of Turkish strings.

Two implementations are provided:

``TemplateNarrator`` (default, no network)
    Deterministic templates for every insight category.  Used in tests and as
    the fallback when no Anthropic API key is configured.  Covers the "ne
    oldu" headline and the "neden / ne yapmalı" recommendation body.

``ClaudeNarrator`` (optional, requires ANTHROPIC_API_KEY)
    Calls the Claude API via raw ``httpx`` (no anthropic SDK dep) to produce
    a richer, contextually-aware Turkish summary.  Falls back to
    ``TemplateNarrator`` on any error (missing key, network timeout, non-200
    response, JSON parse failure).  Fully mockable via dependency injection
    in tests.

Both classes are safe to construct with no arguments.
"""

from __future__ import annotations

import json
import logging
from abc import ABC, abstractmethod
from typing import Any

logger = logging.getLogger(__name__)

# ── Interface ─────────────────────────────────────────────────────────────────


class InsightNarrator(ABC):
    """Abstract narrator interface.

    All concrete implementations must override :meth:`narrate`.
    """

    @abstractmethod
    def narrate(self, result: Any) -> tuple[str, str]:
        """Return ``(title, body)`` in Turkish for the given DetectorResult.

        Parameters
        ----------
        result:
            A :class:`~ayaz.services.insights.DetectorResult` instance.

        Returns
        -------
        tuple[str, str]
            ``(title, body)`` where:

            - ``title`` is a short Turkish headline (≤ 120 chars) answering
              "ne oldu?" (what happened?).
            - ``body`` is a 2–4 sentence Turkish paragraph answering
              "neden?" (why?) and "ne yapmalı?" (what to do?).
        """


# ── Template narrator (deterministic, no network) ─────────────────────────────


def _fmt_pct(fraction: float) -> str:
    """Format a fraction as a percentage string, e.g. 0.25 -> '%25'."""
    return f"%{fraction * 100:.1f}"


def _fmt_num(value: float, decimals: int = 2) -> str:
    """Format a float with the given number of decimal places."""
    return f"{value:.{decimals}f}"


class TemplateNarrator(InsightNarrator):
    """Deterministic Turkish template narrator.

    Each insight category has a dedicated ``_narrate_<category>`` method.
    All text is in Turkish.  No external calls are made.

    Template philosophy
    -------------------
    * ``title``: answers "ne oldu?" in 10–15 words.
    * ``body``: 2–4 sentences covering "neden olabilir?" and "ne yapmalı?",
      including the key numbers for context.
    """

    def narrate(self, result: Any) -> tuple[str, str]:
        """Dispatch to the appropriate category template."""
        method_name = f"_narrate_{result.category}"
        method = getattr(self, method_name, self._narrate_generic)
        return method(result)

    # ── Category templates ────────────────────────────────────────────────

    def _narrate_roas_drop(self, result: Any) -> tuple[str, str]:
        channel = result.channel or "tüm kanallar"
        data = result.data
        current = _fmt_num(data.get("current_roas", 0))
        prior = _fmt_num(data.get("prior_roas", 0))
        pct = _fmt_pct(data.get("pct_drop", 0))
        title = f"{channel.replace('_', ' ').title()} kanalında ROAS {pct} düştü"
        body = (
            f"{channel.replace('_', ' ').title()} kanalında reklam harcama getirisi "
            f"(ROAS) önceki döneme kıyasla {pct} oranında geriledi "
            f"(önceki: {prior}x, güncel: {current}x). "
            f"Bu düşüş; tıklama maliyetlerinin artması, dönüşüm oranının azalması "
            f"veya gelir değerinin düşmesinden kaynaklanıyor olabilir. "
            f"Kampanya tekliflerini, hedef kitle ayarlarını ve açılış sayfası "
            f"performansını inceleyiniz. Düşük performanslı reklam gruplarını "
            f"duraklatarak bütçeyi yüksek ROAS'lı kampanyalara yönlendirmeyi "
            f"değerlendiriniz."
        )
        return title, body

    def _narrate_spend_spike(self, result: Any) -> tuple[str, str]:
        channel = result.channel or "tüm kanallar"
        data = result.data
        current = _fmt_num(data.get("current_spend", 0))
        prior = _fmt_num(data.get("prior_spend", 0))
        pct = _fmt_pct(data.get("pct_rise", 0))
        title = f"{channel.replace('_', ' ').title()} kanalında harcama {pct} arttı"
        body = (
            f"{channel.replace('_', ' ').title()} kanalındaki reklam harcaması "
            f"önceki döneme kıyasla {pct} oranında yükseldi "
            f"(önceki: {prior}, güncel: {current}). "
            f"Bu ani artış; otomatik teklif optimizasyonları, bütçe sınırı değişiklikleri "
            f"veya rakip artışlarından kaynaklanıyor olabilir. "
            f"Kampanya bütçe sınırlarını kontrol ediniz ve harcama hızını izleyiniz. "
            f"Harcama artışının dönüşüm artışıyla orantılı olup olmadığını doğrulayınız."
        )
        return title, body

    def _narrate_zero_conversions(self, result: Any) -> tuple[str, str]:
        channel = result.channel or "tüm kanallar"
        data = result.data
        spend = _fmt_num(data.get("spend", 0))
        title = (
            f"{channel.replace('_', ' ').title()} kanalında harcama var "
            f"ancak dönüşüm yok"
        )
        body = (
            f"{channel.replace('_', ' ').title()} kanalında son dönemde "
            f"{spend} harcama gerçekleştirilmesine rağmen hiç dönüşüm kaydedilmedi. "
            f"Piksel veya dönüşüm izleme kodunun çalışıp çalışmadığını kontrol ediniz. "
            f"Açılış sayfasında teknik sorun, hedefleme uyumsuzluğu veya teklif "
            f"stratejisinde bir sorun olabilir. Kampanya duraklat/yeniden başlat "
            f"döngüsü uygulamak veya dönüşüm izlemeyi sıfırlamak faydalı olabilir."
        )
        return title, body

    def _narrate_ctr_drop(self, result: Any) -> tuple[str, str]:
        channel = result.channel or "tüm kanallar"
        data = result.data
        current = _fmt_num(data.get("current_ctr", 0) * 100)
        prior = _fmt_num(data.get("prior_ctr", 0) * 100)
        pct = _fmt_pct(data.get("pct_drop", 0))
        title = (
            f"{channel.replace('_', ' ').title()} kanalında tıklama oranı "
            f"{pct} geriledi"
        )
        body = (
            f"{channel.replace('_', ' ').title()} kanalında tıklama oranı (CTR) "
            f"önceki dönemin {prior}% seviyesinden {current}%'e geriledi ({pct} düşüş). "
            f"Reklam metinlerinin ve görsellerin eskimiş veya hedef kitleyle "
            f"uyumsuz hale gelmiş olması olası bir nedendir. "
            f"A/B testi ile yeni reklam varyantları oluşturmanızı, "
            f"başlık ve açıklama metinlerini güncellemenizi öneririz."
        )
        return title, body

    def _narrate_cpc_rise(self, result: Any) -> tuple[str, str]:
        channel = result.channel or "tüm kanallar"
        data = result.data
        current = _fmt_num(data.get("current_cpc", 0))
        prior = _fmt_num(data.get("prior_cpc", 0))
        pct = _fmt_pct(data.get("pct_rise", 0))
        title = (
            f"{channel.replace('_', ' ').title()} kanalında tıklama başı "
            f"maliyet {pct} arttı"
        )
        body = (
            f"{channel.replace('_', ' ').title()} kanalında tıklama başı maliyet "
            f"(CPC) önceki {prior} seviyesinden {current}'e yükseldi ({pct} artış). "
            f"Artmış rekabet, geniş hedefleme veya Kalite Puanındaki düşüş "
            f"bu artışın olası nedenleri arasındadır. "
            f"Anahtar kelime tekliflerini ve Kalite Puanı bileşenlerini "
            f"(alaka düzeyi, açılış sayfası deneyimi, beklenen TTO) gözden geçiriniz. "
            f"Düşük dönüşüm sağlayan pahalı anahtar kelimeleri negatif listeye "
            f"almayı değerlendiriniz."
        )
        return title, body

    def _narrate_cvr_drop(self, result: Any) -> tuple[str, str]:
        channel = result.channel or "tüm kanallar"
        data = result.data
        current = _fmt_num(data.get("current_cvr", 0) * 100)
        prior = _fmt_num(data.get("prior_cvr", 0) * 100)
        pct = _fmt_pct(data.get("pct_drop", 0))
        title = (
            f"{channel.replace('_', ' ').title()} kanalında dönüşüm oranı "
            f"{pct} geriledi"
        )
        body = (
            f"{channel.replace('_', ' ').title()} kanalında dönüşüm oranı (CVR) "
            f"önceki dönemin %{prior} seviyesinden %{current}'e geriledi ({pct} düşüş). "
            f"Açılış sayfası deneyimi, teklif teklifleme stratejisi veya hedef kitle "
            f"uyumsuzluğu bu düşüşün olası nedenleri arasındadır. "
            f"Dönüşüm hunisinin her adımını inceleyiniz; özellikle tıklama sonrası "
            f"sayfa yükleme süresi ve form/ödeme akışını kontrol ediniz. "
            f"Yüksek tıklama alan ancak düşük dönüşüm sağlayan reklam gruplarını "
            f"duraklatmayı değerlendiriniz."
        )
        return title, body

    def _narrate_positive_movement(self, result: Any) -> tuple[str, str]:
        channel = result.channel or "tüm kanallar"
        data = result.data
        trigger = data.get("trigger", "roas")
        pct = _fmt_pct(data.get("pct_gain", 0))

        if trigger == "roas":
            current = _fmt_num(data.get("current_roas", 0))
            prior = _fmt_num(data.get("prior_roas", 0))
            title = (
                f"\U0001f389 {channel.replace('_', ' ').title()} kanalinda ROAS "
                f"{pct} yukseldi"
            )
            body = (
                f"{channel.replace('_', ' ').title()} kanalinda reklam harcama getirisi "
                f"(ROAS) onceki doneme kiyasla {pct} oraninda artti "
                f"(onceki: {prior}x, guncel: {current}x). "
                f"Bu olumlu gelisme; kampanya optimizasyonlarinin, hedef kitle "
                f"iyilestirmelerinin veya sezon etkisinin sonucu olabilir. "
                f"Basarili stratejileri diger kanallara veya kampanyalara tasimayi "
                f"degerlendiriniz ve bu performansi surdurmek icin butce artisini gozden geciriniz."
            )
        else:
            current = _fmt_num(data.get("current_conversions", 0), decimals=0)
            prior = _fmt_num(data.get("prior_conversions", 0), decimals=0)
            title = (
                f"\U0001f389 {channel.replace('_', ' ').title()} kanalinda "
                f"donusumler {pct} yukseldi"
            )
            body = (
                f"{channel.replace('_', ' ').title()} kanalinda donusum sayisi "
                f"onceki doneme kiyasla {pct} artti "
                f"(onceki: {prior}, guncel: {current}). "
                f"Bu hafta donusumler belirgin sekilde yukseldi — bu olumlu ivmeyi "
                f"korumak icin yuksek performansli reklam gruplarinin butcesini "
                f"artirmayi degerlendiriniz."
            )
        return title, body

    def _narrate_budget_pacing(self, result: Any) -> tuple[str, str]:
        channel = result.channel or "tüm kanallar"
        title = f"{channel.replace('_', ' ').title()} kanalında bütçe hızı sorunu tespit edildi"
        body = (
            f"{channel.replace('_', ' ').title()} kanalındaki mevcut harcama hızı, "
            f"dönem sonuna kadar bütçenin tükeneceğine ya da tam kullanılamayacağına "
            f"işaret etmektedir. "
            f"Günlük bütçe sınırlarını ve teklif stratejisini kontrol ediniz. "
            f"Otomatik bütçe dağılımı kullanılıyorsa kampanya öncelik ayarlarını "
            f"inceleyiniz."
        )
        return title, body

    def _narrate_anomaly(self, result: Any) -> tuple[str, str]:
        channel = result.channel or "tüm kanallar"
        data = result.data
        metric = result.metric
        direction = data.get("direction", "")
        z = _fmt_num(abs(data.get("z_score", 0)))
        candidate_val = _fmt_num(data.get("candidate_value", 0))
        mean_val = _fmt_num(data.get("history_mean", 0))

        metric_tr = {
            "spend": "harcama",
            "roas": "ROAS",
            "ctr": "tıklama oranı",
            "cpc": "tıklama başı maliyet",
            "conversions": "dönüşüm",
        }.get(metric, metric)

        direction_tr = "yüksek" if direction == "yuksek" else "düşük"

        title = (
            f"{channel.replace('_', ' ').title()} kanalında {metric_tr} "
            f"beklenmedik ölçüde {direction_tr}"
        )
        body = (
            f"{channel.replace('_', ' ').title()} kanalındaki {metric_tr} değeri "
            f"({candidate_val}), geçmiş ortalamanın ({mean_val}) "
            f"{z} standart sapma {direction_tr}inde seyretmektedir — bu istatistiksel "
            f"bir anomali sinyalidir. "
            f"Kampanya değişiklikleri, sezon etkisi, veri kalitesi sorunu ya da "
            f"rekabet hareketleri bu anomaliye neden olmuş olabilir. "
            f"Hesap değişiklik geçmişini inceleyiniz ve veri doğruluğunu "
            f"platform arayüzünden doğrulayınız."
        )
        return title, body

    def _narrate_generic(self, result: Any) -> tuple[str, str]:
        """Fallback for any category without a dedicated template."""
        channel = result.channel or "tüm kanallar"
        metric = result.metric
        severity_tr = {
            "info": "bilgilendirme",
            "warning": "uyarı",
            "critical": "kritik",
        }.get(result.severity, result.severity)
        title = (
            f"{channel.replace('_', ' ').title()} kanalında "
            f"{metric} metriği için {severity_tr} sinyali"
        )
        body = (
            f"{channel.replace('_', ' ').title()} kanalında {metric} metriğinde "
            f"dikkat gerektiren bir durum tespit edildi. "
            f"İlgili kampanya ve reklam gruplarını inceleyerek gerekli düzenlemeleri "
            f"yapmanız önerilir."
        )
        return title, body


# ── Claude narrator (optional, requires API key) ──────────────────────────────


class ClaudeNarrator(InsightNarrator):
    """Optional narrator that calls the Claude API for richer Turkish text.

    Dependencies
    ------------
    - ``httpx`` (already in the project's deps for HTTP calls)
    - ``settings.anthropic_api_key`` (must be non-empty)

    Fallback
    --------
    If the API key is missing, the HTTP call fails, or the response cannot be
    parsed, this class falls back to :class:`TemplateNarrator` transparently.

    Mockability
    -----------
    Inject ``http_client`` (any object with a ``.post()`` method matching the
    httpx interface) in tests to avoid live network calls::

        narrator = ClaudeNarrator(http_client=mock_client)

    Model
    -----
    Defaults to ``claude-opus-4-8`` (configurable via ``model`` parameter).
    """

    DEFAULT_MODEL = "claude-opus-4-8"

    def __init__(
        self,
        api_key: str | None = None,
        model: str | None = None,
        http_client: Any = None,
    ) -> None:
        from ayaz.config import settings

        self._api_key = api_key or settings.anthropic_api_key
        self._model = model or self.DEFAULT_MODEL
        self._http_client = http_client  # None → create lazily
        self._fallback = TemplateNarrator()

    def narrate(self, result: Any) -> tuple[str, str]:
        """Call Claude API; fall back to templates on any failure."""
        if not self._api_key:
            logger.debug("[ClaudeNarrator] No API key — using TemplateNarrator")
            return self._fallback.narrate(result)

        # Build the prompt from the detector result
        prompt = self._build_prompt(result)

        try:
            response_text = self._call_api(prompt)
            title, body = self._parse_response(response_text)
            return title, body
        except Exception as exc:
            logger.warning(
                "[ClaudeNarrator] API call failed (%s) — falling back to templates",
                exc,
            )
            return self._fallback.narrate(result)

    def _build_prompt(self, result: Any) -> str:
        """Compose a structured prompt for the Claude API."""
        data_summary = json.dumps(result.data, ensure_ascii=False, default=str)
        return (
            "Sen bir dijital pazarlama analisti asistanısın. "
            "Aşağıdaki insight sinyali için Türkçe bir analiz yaz.\n\n"
            f"Kategori: {result.category}\n"
            f"Önem: {result.severity}\n"
            f"Metrik: {result.metric}\n"
            f"Kanal: {result.channel or 'tüm kanallar'}\n"
            f"Dönem: {result.period_start} - {result.period_end}\n"
            f"Veriler: {data_summary}\n\n"
            "Lütfen şu formatta yanıt ver (JSON):\n"
            '{"title": "<Kısa başlık - ne oldu?>", '
            '"body": "<2-4 cümle - neden oldu ve ne yapmalı?>"}\n\n'
            "Yanıt yalnızca JSON olsun, başka hiçbir şey ekleme."
        )

    def _call_api(self, prompt: str) -> str:
        """Make the HTTP call to the Anthropic Messages API."""
        import httpx

        client = self._http_client

        payload = {
            "model": self._model,
            "max_tokens": 512,
            "messages": [{"role": "user", "content": prompt}],
        }
        headers = {
            "x-api-key": self._api_key,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        }

        if client is not None:
            # Injected client (tests or custom)
            resp = client.post(
                "https://api.anthropic.com/v1/messages",
                json=payload,
                headers=headers,
                timeout=20.0,
            )
        else:
            with httpx.Client() as c:
                resp = c.post(
                    "https://api.anthropic.com/v1/messages",
                    json=payload,
                    headers=headers,
                    timeout=20.0,
                )

        if resp.status_code != 200:
            raise RuntimeError(
                f"Anthropic API returned {resp.status_code}: {resp.text[:200]}"
            )

        body = resp.json()
        # Standard Anthropic response: content[0].text
        return body["content"][0]["text"]

    def _parse_response(self, text: str) -> tuple[str, str]:
        """Extract (title, body) from Claude's JSON response."""
        parsed = json.loads(text.strip())
        title = str(parsed["title"])
        body = str(parsed["body"])
        return title, body
