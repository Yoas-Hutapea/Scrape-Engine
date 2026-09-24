"""Detect marketplace anti-bot walls (slider captcha / verify / challenge pages).

The engine does NOT try to solve these. Detection lets callers stop early and
report ``code = captcha_required`` instead of waiting for a timeout, so the
caller can show "Blibli diblokir captcha" and keep results from other sites.
"""

from __future__ import annotations

import re

CAPTCHA_REQUIRED = "captcha_required"

# URL fragments of known challenge / verify pages.
_URL_MARKERS: tuple[str, ...] = (
    "/_____tmd_____/",       # Alibaba / 1688 punish page
    "punish?x5secdata",
    "x5secdata=",
    "/verify/traffic",       # Shopee
    "/verify/captcha",
    "shopee.co.id/verify",
    "/captcha",
    "captcha-delivery.com",  # DataDome
    "/cdn-cgi/challenge-platform",
)

# Strings that only appear on challenge pages (not in normal product pages that
# merely load reCAPTCHA for the login dialog).
_HTML_MARKERS: tuple[str, ...] = (
    "_____tmd_____",
    "x5secdata",
    "nc_1_n1z",              # Alibaba noCaptcha slider knob
    "nc-container",
    "baxia-dialog",
    "punish-component",
    "geetest_",              # GeeTest slider
    "px-captcha",            # PerimeterX
    "captcha-delivery.com",  # DataDome
    "cf-chl-",               # Cloudflare challenge
    "cf-challenge",          # Cloudflare Turnstile interstitial (Blibli)
    "challenge-platform",
    "verify if you're human",
    "verify you are human",
    "verifikasi sedang berjalan",
    "enable javascript and cookies to continue",
    "please slide to verify",
    "slide to verify",
    "geser untuk verifikasi",
    "滑动验证",
    "unusual traffic from your network",
    "pardon our interruption",
)

_ACCESS_DENIED_RE = re.compile(r"<title>\s*access denied\s*</title>", re.I)
_TEXT_RE = re.compile(r"<[^>]+>")


class CaptchaRequiredError(RuntimeError):
    """The marketplace served a captcha / verify wall instead of content."""

    code = CAPTCHA_REQUIRED

    def __init__(self, marketplace: str, url: str, detail: str | None = None) -> None:
        self.marketplace = marketplace
        self.url = url
        self.detail = detail or "captcha/verify"
        super().__init__(
            f"{marketplace.capitalize()} diblokir captcha ({self.detail}). "
            "Marketplace ini dilewati; coba lagi nanti. "
            f"URL: {url}"
        )


def detect_block(html: str | None, url: str | None = None) -> str | None:
    """Return the matched marker when ``html``/``url`` is an anti-bot wall, else ``None``."""
    lowered_url = (url or "").lower()
    for marker in _URL_MARKERS:
        if marker in lowered_url:
            return marker

    if not html:
        return None
    lowered = html.lower()
    for marker in _HTML_MARKERS:
        if marker.lower() in lowered:
            return marker
    if _ACCESS_DENIED_RE.search(html) and "reference #" in lowered:
        return "access denied (akamai)"

    # Small, nearly-empty page that talks about a captcha = challenge interstitial.
    if "captcha" in lowered and len(_TEXT_RE.sub(" ", html).split()) < 120:
        return "captcha"
    return None


def raise_if_blocked(html: str | None, url: str | None, *, marketplace: str, source_url: str) -> None:
    marker = detect_block(html, url)
    if marker:
        raise CaptchaRequiredError(marketplace, source_url, marker)


def error_entry(exc: BaseException, *, url: str, marketplace: str | None = None) -> dict[str, str]:
    """Build the API error dict; captcha walls get ``code`` so clients can label them."""
    entry: dict[str, str] = {"url": url, "error": str(exc)}
    if isinstance(exc, CaptchaRequiredError):
        entry["code"] = CAPTCHA_REQUIRED
        entry["marketplace"] = exc.marketplace
    elif marketplace:
        entry["marketplace"] = marketplace
    return entry
