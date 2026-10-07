import json
import os
import re
import sys
import time
from urllib.parse import urljoin, urlsplit, urlunsplit, parse_qsl, urlencode

from playwright.sync_api import sync_playwright


if sys.stdout.encoding != "utf-8":
    try:
        sys.stdout.reconfigure(
            encoding="utf-8",
            errors="replace",
        )
    except Exception:
        pass


PORTAL_URL = "https://me-portal.qureo.education/login"
PORTAL_HOME = "https://me-portal.qureo.education/"
BASE = "https://me-tp.qureo.education"

JSON_HEADERS = {
    "Content-Type": "application/json",
}

SCRIPT_DIR = os.path.dirname(
    os.path.abspath(__file__)
)

ANSWER_FILE = os.path.join(
    SCRIPT_DIR,
    "answers.json",
)

STUDENT_ID = ""
PASSWORD = ""

COURSES = [
    "Python",
    "JavaScript",
]

PROGRESS = None
SHOULD_STOP = None


# ----------------------------------------------------------------------
# Browser fingerprint / request headers
# ----------------------------------------------------------------------

BROWSER_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/154.0.0.0 Safari/537.36"
)

BROWSER_ACCEPT_LANGUAGE = (
    "en-US,en;q=0.9,ar;q=0.8,ar-SA;q=0.7"
)


# ----------------------------------------------------------------------
# Optional Qureo proxy
#
# مهم:
# لو QUREO_PROXY_SERVER غير موجود أو فاضي، لن يتم استخدام Proxy.
# ----------------------------------------------------------------------

QUREO_PROXY_SERVER = os.getenv(
    "QUREO_PROXY_SERVER",
    "",
).strip()

QUREO_PROXY_USERNAME = os.getenv(
    "QUREO_PROXY_USERNAME",
    "",
).strip()

QUREO_PROXY_PASSWORD = os.getenv(
    "QUREO_PROXY_PASSWORD",
    "",
)


def build_qureo_proxy():
    """
    Builds Playwright proxy configuration from environment variables.

    Required:
        QUREO_PROXY_SERVER

    Optional:
        QUREO_PROXY_USERNAME
        QUREO_PROXY_PASSWORD
    """

    if not QUREO_PROXY_SERVER:
        return None

    proxy = {
        "server": QUREO_PROXY_SERVER,
    }

    if QUREO_PROXY_USERNAME:
        proxy["username"] = QUREO_PROXY_USERNAME

    if QUREO_PROXY_PASSWORD:
        proxy["password"] = QUREO_PROXY_PASSWORD

    return proxy


def emit_progress(
    course,
    done,
    total,
    label="",
):
    if PROGRESS:
        try:
            PROGRESS(
                course,
                done,
                total,
                label,
            )
        except Exception:
            pass


def stop_requested():
    if SHOULD_STOP:
        try:
            return bool(
                SHOULD_STOP()
            )
        except Exception:
            return False

    return False


class QureoSolver:
    def __init__(
        self,
        headless=True,
        courses=None,
    ):
        self.headless = headless
        self.courses = courses or COURSES

        self.playwright = None
        self.browser = None
        self.context = None
        self.page = None

        self.current_course = ""

        self.asset_results = []
        self.frontend_broken = False

        self.proxy = build_qureo_proxy()

    # ------------------------------------------------------------------
    # browser
    # ------------------------------------------------------------------

    def start(self):
        print(
            "🚀 جاري تشغيل المتصفح في الخلفية...",
            flush=True,
        )

        self.playwright = sync_playwright().start()

        if self.proxy:
            print(
                "🌍 Qureo Proxy: مفعّل",
                flush=True,
            )

            print(
                f"🌍 Proxy Server: "
                f"{self.proxy.get('server', '')}",
                flush=True,
            )

            if self.proxy.get("username"):
                print(
                    "🔐 Proxy Authentication: مفعّلة",
                    flush=True,
                )

        else:
            print(
                "🌍 Qureo Proxy: غير مفعّل",
                flush=True,
            )

        try:
            launch_options = {
                "headless": self.headless,
            }

            if self.proxy:
                launch_options["proxy"] = self.proxy

            self.browser = self.playwright.chromium.launch(
                **launch_options,
            )

            print(
                "🌐 تم تشغيل Playwright Chromium في الخلفية.",
                flush=True,
            )

        except Exception as e:
            raise RuntimeError(
                "تعذّر تشغيل Chromium على Railway. "
                "تأكد من تثبيت Playwright Chromium "
                "وصحة إعدادات الـ Proxy إن وُجدت."
            ) from e

        self.context = self.browser.new_context(
            viewport={
                "width": 1280,
                "height": 800,
            },
            locale="en-US",
            timezone_id="Africa/Cairo",
            user_agent=BROWSER_USER_AGENT,
            extra_http_headers={
                "Accept-Language": BROWSER_ACCEPT_LANGUAGE,
            },
        )

        self.page = self.context.new_page()

        # --------------------------------------------------------------
        # request diagnostics
        # --------------------------------------------------------------

        def on_request(request):
            try:
                url = request.url

                if (
                    "/assets/" not in url
                    and request.resource_type
                    not in {
                        "script",
                        "stylesheet",
                    }
                ):
                    return

                headers = request.all_headers()

                print(
                    "➡️ REQUEST: "
                    f"{request.method} | "
                    f"{request.resource_type} | "
                    f"{url}",
                    flush=True,
                )

                print(
                    "   UA: "
                    f"{headers.get('user-agent', '')[:180]}",
                    flush=True,
                )

                print(
                    "   Accept: "
                    f"{headers.get('accept', '')[:180]}",
                    flush=True,
                )

                print(
                    "   Origin: "
                    f"{headers.get('origin', '')}",
                    flush=True,
                )

                print(
                    "   Referer: "
                    f"{headers.get('referer', '')}",
                    flush=True,
                )

                print(
                    "   Sec-Fetch-Dest: "
                    f"{headers.get('sec-fetch-dest', '')}",
                    flush=True,
                )

                print(
                    "   Sec-Fetch-Mode: "
                    f"{headers.get('sec-fetch-mode', '')}",
                    flush=True,
                )

                print(
                    "   Sec-Fetch-Site: "
                    f"{headers.get('sec-fetch-site', '')}",
                    flush=True,
                )

            except Exception:
                pass

        self.page.on(
            "request",
            on_request,
        )

        # --------------------------------------------------------------
        # request failures
        # --------------------------------------------------------------

        def on_request_failed(request):
            try:
                url = request.url

                if (
                    "/assets/" in url
                    or request.resource_type in {
                        "script",
                        "stylesheet",
                    }
                ):
                    print(
                        "❌ REQUEST FAILED: "
                        f"{request.resource_type} | "
                        f"{request.failure} | "
                        f"{url}",
                        flush=True,
                    )

            except Exception:
                pass

        self.page.on(
            "requestfailed",
            on_request_failed,
        )

        # --------------------------------------------------------------
        # asset responses
        # --------------------------------------------------------------

        def on_response(response):
            try:
                url = response.url

                resource_type = (
                    response.request.resource_type
                )

                content_type = (
                    response.headers.get(
                        "content-type",
                        "",
                    )
                    or ""
                )

                is_asset = (
                    "/assets/" in url
                    or resource_type in {
                        "script",
                        "stylesheet",
                    }
                )

                if not is_asset:
                    return

                result = {
                    "url": url,
                    "status": response.status,
                    "resource_type": resource_type,
                    "content_type": content_type,
                    "server": response.headers.get(
                        "server",
                        "",
                    ),
                    "x_cache": response.headers.get(
                        "x-cache",
                        "",
                    ),
                    "cf_pop": response.headers.get(
                        "x-amz-cf-pop",
                        "",
                    ),
                }

                self.asset_results.append(
                    result
                )

                print(
                    "📦 ASSET RESPONSE: "
                    f"{response.status} | "
                    f"{resource_type} | "
                    f"{content_type} | "
                    f"{url}",
                    flush=True,
                )

                server = response.headers.get(
                    "server",
                    "",
                )

                cache = response.headers.get(
                    "x-cache",
                    "",
                )

                pop = response.headers.get(
                    "x-amz-cf-pop",
                    "",
                )

                if server:
                    print(
                        f"   SERVER: {server}",
                        flush=True,
                    )

                if cache:
                    print(
                        f"   X-CACHE: {cache}",
                        flush=True,
                    )

                if pop:
                    print(
                        f"   CF-POP: {pop}",
                        flush=True,
                    )

                if (
                    resource_type == "script"
                    and "javascript"
                    not in content_type.lower()
                    and "ecmascript"
                    not in content_type.lower()
                ):
                    print(
                        "⚠️ SCRIPT MIME TYPE غير صحيح: "
                        f"{content_type} | {url}",
                        flush=True,
                    )

                    self.frontend_broken = True

            except Exception:
                pass

        self.page.on(
            "response",
            on_response,
        )

        # --------------------------------------------------------------
        # console
        # --------------------------------------------------------------

        def on_console(msg):
            try:
                if msg.type in {
                    "error",
                    "warning",
                }:
                    print(
                        f"🖥️ CONSOLE [{msg.type}]: "
                        f"{msg.text}",
                        flush=True,
                    )
            except Exception:
                pass

        self.page.on(
            "console",
            on_console,
        )

        # --------------------------------------------------------------
        # page errors
        # --------------------------------------------------------------

        def on_page_error(exc):
            try:
                print(
                    f"💥 PAGE ERROR: {exc}",
                    flush=True,
                )
            except Exception:
                pass

        self.page.on(
            "pageerror",
            on_page_error,
        )

        # --------------------------------------------------------------
        # proxy/IP diagnostic
        # --------------------------------------------------------------

        self._check_outbound_ip()

    # ------------------------------------------------------------------
    # outbound IP diagnostic
    # ------------------------------------------------------------------

    def _check_outbound_ip(self):
        print(
            "\n========== OUTBOUND IP TEST ==========",
            flush=True,
        )

        try:
            response = self.context.request.get(
                "https://api.ipify.org?format=json",
                timeout=20000,
                headers={
                    "Accept": "application/json",
                    "User-Agent": BROWSER_USER_AGENT,
                    "Accept-Language": BROWSER_ACCEPT_LANGUAGE,
                },
            )

            print(
                f"STATUS: {response.status}",
                flush=True,
            )

            content_type = (
                response.headers.get(
                    "content-type",
                    "",
                )
                or ""
            )

            print(
                f"CONTENT-TYPE: {content_type}",
                flush=True,
            )

            try:
                data = response.json()

                ip = data.get(
                    "ip",
                    "",
                )

                if ip:
                    print(
                        f"🌍 OUTBOUND IP: {ip}",
                        flush=True,
                    )
                else:
                    print(
                        f"BODY: {str(data)[:500]}",
                        flush=True,
                    )

            except Exception:
                try:
                    print(
                        "BODY: "
                        f"{response.text()[:500]}",
                        flush=True,
                    )
                except Exception:
                    pass

        except Exception as e:
            print(
                f"❌ OUTBOUND IP TEST FAILED: {e}",
                flush=True,
            )

        print(
            "========== END OUTBOUND IP TEST ==========\n",
            flush=True,
        )

    # ------------------------------------------------------------------
    # DIRECT NETWORK DIAGNOSTIC
    # ------------------------------------------------------------------

    def _direct_asset_diagnostic(
        self,
        url,
        referer=None,
    ):
        print(
            "\n"
            "========== DIRECT QUREO ASSET TEST ==========",
            flush=True,
        )

        print(
            f"🎯 URL: {url}",
            flush=True,
        )

        try:
            headers = {
                "User-Agent": BROWSER_USER_AGENT,
                "Accept": "*/*",
                "Accept-Language": (
                    BROWSER_ACCEPT_LANGUAGE
                ),
                "Origin": PORTAL_HOME.rstrip("/"),
                "Sec-Fetch-Dest": "script",
                "Sec-Fetch-Mode": "cors",
                "Sec-Fetch-Site": "same-origin",
                "Cache-Control": "no-cache",
                "Pragma": "no-cache",
            }

            if referer:
                headers["Referer"] = referer

            response = self.context.request.get(
                url,
                timeout=30000,
                headers=headers,
            )

            content_type = (
                response.headers.get(
                    "content-type",
                    "",
                )
                or ""
            )

            print(
                f"STATUS: {response.status}",
                flush=True,
            )

            print(
                f"CONTENT-TYPE: {content_type}",
                flush=True,
            )

            print(
                f"FINAL-URL: {response.url}",
                flush=True,
            )

            print(
                "SERVER: "
                f"{response.headers.get('server', '')}",
                flush=True,
            )

            print(
                "X-CACHE: "
                f"{response.headers.get('x-cache', '')}",
                flush=True,
            )

            print(
                "CF-POP: "
                f"{response.headers.get('x-amz-cf-pop', '')}",
                flush=True,
            )

            print(
                "CACHE-CONTROL: "
                f"{response.headers.get('cache-control', '')}",
                flush=True,
            )

            print(
                "AGE: "
                f"{response.headers.get('age', '')}",
                flush=True,
            )

            print(
                "ETAG: "
                f"{response.headers.get('etag', '')}",
                flush=True,
            )

            print(
                "LOCATION: "
                f"{response.headers.get('location', '')}",
                flush=True,
            )

            print(
                "\n---------- FIRST 2000 BYTES ----------",
                flush=True,
            )

            try:
                body = response.body()

                preview = body[:2000].decode(
                    "utf-8",
                    errors="replace",
                )

                print(
                    preview,
                    flush=True,
                )

            except Exception as body_error:
                print(
                    f"تعذر قراءة body: {body_error}",
                    flush=True,
                )

            print(
                "========== END DIRECT ASSET TEST ==========\n",
                flush=True,
            )

            return {
                "status": response.status,
                "content_type": content_type,
                "url": response.url,
                "x_cache": response.headers.get(
                    "x-cache",
                    "",
                ),
                "cf_pop": response.headers.get(
                    "x-amz-cf-pop",
                    "",
                ),
            }

        except Exception as e:
            print(
                "\n❌ DIRECT ASSET TEST FAILED",
                flush=True,
            )

            print(
                f"ERROR: {repr(e)}",
                flush=True,
            )

            print(
                "========== END DIRECT ASSET TEST ==========\n",
                flush=True,
            )

            return {
                "status": 0,
                "content_type": "",
                "url": url,
                "error": str(e),
            }

    # ------------------------------------------------------------------
    # CloudFront multi-test diagnostic
    # ------------------------------------------------------------------

    def _cloudfront_asset_diagnostic(
        self,
        asset_url,
        referer=None,
    ):
        """
        يفحص نفس الـ asset بثلاث طرق:

        1. NORMAL
        2. CACHE_BYPASS
        3. QUERY_BYPASS

        الهدف معرفة هل CloudFront يعيد HTML
        بسبب cache / POP / routing.
        """

        print(
            "\n"
            "========== CLOUD FRONT ASSET DIAGNOSTIC ==========",
            flush=True,
        )

        print(
            f"🎯 ORIGINAL URL: {asset_url}",
            flush=True,
        )

        parsed = urlsplit(asset_url)

        base_headers = {
            "User-Agent": BROWSER_USER_AGENT,
            "Accept": "*/*",
            "Accept-Language": BROWSER_ACCEPT_LANGUAGE,
            "Origin": PORTAL_HOME.rstrip("/"),
            "Sec-Fetch-Dest": "script",
            "Sec-Fetch-Mode": "cors",
            "Sec-Fetch-Site": "same-origin",
        }

        if referer:
            base_headers["Referer"] = referer

        query_items = parse_qsl(
            parsed.query,
            keep_blank_values=True,
        )

        query_items.append(
            (
                "__wiso_cache_bypass",
                str(int(time.time() * 1000)),
            )
        )

        query_bypass_url = urlunsplit(
            (
                parsed.scheme,
                parsed.netloc,
                parsed.path,
                urlencode(query_items),
                parsed.fragment,
            )
        )

        tests = [
            (
                "NORMAL",
                asset_url,
                {
                    **base_headers,
                },
            ),
            (
                "CACHE_BYPASS",
                asset_url,
                {
                    **base_headers,
                    "Cache-Control": (
                        "no-cache, no-store, max-age=0"
                    ),
                    "Pragma": "no-cache",
                },
            ),
            (
                "QUERY_BYPASS",
                query_bypass_url,
                {
                    **base_headers,
                    "Cache-Control": (
                        "no-cache, no-store, max-age=0"
                    ),
                    "Pragma": "no-cache",
                },
            ),
        ]

        results = []

        request = None

        try:
            request = self.playwright.request.new_context(
                ignore_https_errors=False,
                timeout=30000,
            )

            for test_name, test_url, headers in tests:
                print(
                    "\n"
                    f"========== TEST: {test_name} ==========",
                    flush=True,
                )

                print(
                    f"URL: {test_url}",
                    flush=True,
                )

                try:
                    response = request.get(
                        test_url,
                        headers=headers,
                        timeout=30000,
                    )

                    content_type = (
                        response.headers.get(
                            "content-type",
                            "",
                        )
                        or ""
                    )

                    server = (
                        response.headers.get(
                            "server",
                            "",
                        )
                        or ""
                    )

                    x_cache = (
                        response.headers.get(
                            "x-cache",
                            "",
                        )
                        or ""
                    )

                    cf_pop = (
                        response.headers.get(
                            "x-amz-cf-pop",
                            "",
                        )
                        or ""
                    )

                    content_length = (
                        response.headers.get(
                            "content-length",
                            "",
                        )
                        or ""
                    )

                    cache_control = (
                        response.headers.get(
                            "cache-control",
                            "",
                        )
                        or ""
                    )

                    age = (
                        response.headers.get(
                            "age",
                            "",
                        )
                        or ""
                    )

                    etag = (
                        response.headers.get(
                            "etag",
                            "",
                        )
                        or ""
                    )

                    try:
                        body = response.body()
                        body_preview = (
                            body[:500]
                            .decode(
                                "utf-8",
                                errors="replace",
                            )
                            .replace(
                                "\r",
                                " ",
                            )
                            .replace(
                                "\n",
                                " ",
                            )
                        )
                    except Exception:
                        body_preview = ""

                    is_javascript = (
                        "javascript"
                        in content_type.lower()
                        or "ecmascript"
                        in content_type.lower()
                    )

                    is_html = (
                        "text/html"
                        in content_type.lower()
                        or body_preview.lstrip()
                        .lower()
                        .startswith("<!doctype html")
                        or body_preview.lstrip()
                        .lower()
                        .startswith("<html")
                    )

                    result = {
                        "test": test_name,
                        "url": test_url,
                        "status": response.status,
                        "content_type": content_type,
                        "server": server,
                        "x_cache": x_cache,
                        "cf_pop": cf_pop,
                        "content_length": content_length,
                        "cache_control": cache_control,
                        "age": age,
                        "etag": etag,
                        "is_javascript": is_javascript,
                        "is_html": is_html,
                        "body_preview": body_preview,
                    }

                    results.append(
                        result
                    )

                    print(
                        f"STATUS: {response.status}",
                        flush=True,
                    )

                    print(
                        f"CONTENT-TYPE: {content_type}",
                        flush=True,
                    )

                    print(
                        f"CONTENT-LENGTH: "
                        f"{content_length}",
                        flush=True,
                    )

                    print(
                        f"SERVER: {server}",
                        flush=True,
                    )

                    print(
                        f"X-CACHE: {x_cache}",
                        flush=True,
                    )

                    print(
                        f"CF-POP: {cf_pop}",
                        flush=True,
                    )

                    print(
                        f"CACHE-CONTROL: "
                        f"{cache_control}",
                        flush=True,
                    )

                    print(
                        f"AGE: {age}",
                        flush=True,
                    )

                    print(
                        f"ETAG: {etag}",
                        flush=True,
                    )

                    print(
                        f"JAVASCRIPT: "
                        f"{'YES' if is_javascript else 'NO'}",
                        flush=True,
                    )

                    print(
                        f"HTML: "
                        f"{'YES' if is_html else 'NO'}",
                        flush=True,
                    )

                    print(
                        f"BODY PREVIEW: "
                        f"{body_preview}",
                        flush=True,
                    )

                    if is_javascript:
                        print(
                            "✅ هذا الاختبار أعاد "
                            "JavaScript صحيح.",
                            flush=True,
                        )

                    elif is_html:
                        print(
                            "❌ هذا الاختبار أعاد "
                            "HTML بدل JavaScript.",
                            flush=True,
                        )

                    else:
                        print(
                            "⚠️ الاستجابة ليست "
                            "JavaScript ولا HTML واضحًا.",
                            flush=True,
                        )

                except Exception as test_error:
                    print(
                        f"❌ TEST FAILED [{test_name}]: "
                        f"{type(test_error).__name__}: "
                        f"{test_error}",
                        flush=True,
                    )

                    results.append(
                        {
                            "test": test_name,
                            "url": test_url,
                            "status": 0,
                            "content_type": "",
                            "error": str(test_error),
                            "is_javascript": False,
                            "is_html": False,
                        }
                    )

        except Exception as e:
            print(
                "❌ تعذر إنشاء Request Context "
                f"للتشخيص: {e}",
                flush=True,
            )

        finally:
            if request is not None:
                try:
                    request.dispose()
                except Exception:
                    pass

        javascript_results = [
            item
            for item in results
            if item.get("is_javascript")
        ]

        html_results = [
            item
            for item in results
            if item.get("is_html")
        ]

        print(
            "\n========== CLOUD FRONT DIAGNOSTIC RESULT ==========",
            flush=True,
        )

        if javascript_results:
            print(
                "🎯 تم العثور على استجابة "
                "JavaScript صحيحة في أحد الاختبارات.",
                flush=True,
            )

            for item in javascript_results:
                print(
                    "   ✅ "
                    f"{item.get('test')} | "
                    f"{item.get('content_type')} | "
                    f"CF-POP={item.get('cf_pop')} | "
                    f"X-CACHE={item.get('x_cache')}",
                    flush=True,
                )

        elif html_results:
            print(
                "❌ كل الاختبارات التي استجابت "
                "بشكل واضح أعادت HTML بدل JavaScript.",
                flush=True,
            )

            for item in html_results:
                print(
                    "   ❌ "
                    f"{item.get('test')} | "
                    f"{item.get('content_type')} | "
                    f"CF-POP={item.get('cf_pop')} | "
                    f"X-CACHE={item.get('x_cache')}",
                    flush=True,
                )

        else:
            print(
                "⚠️ لم يتم الحصول على استجابة "
                "JavaScript أو HTML واضحة.",
                flush=True,
            )

        print(
            "========== END CLOUD FRONT DIAGNOSTIC ==========\n",
            flush=True,
        )

        return {
            "asset_url": asset_url,
            "results": results,
            "has_javascript": bool(
                javascript_results
            ),
            "has_html": bool(
                html_results
            ),
        }

    # ------------------------------------------------------------------
    # diagnostics
    # ------------------------------------------------------------------

    def _print_page_diagnostics(self):
        print(
            "\n========== QUREO PAGE DIAGNOSTICS ==========",
            flush=True,
        )

        try:
            print(
                f"URL: {self.page.url}",
                flush=True,
            )
        except Exception:
            pass

        try:
            print(
                f"TITLE: {self.page.title()}",
                flush=True,
            )
        except Exception:
            pass

        try:
            frames = self.page.frames

            print(
                f"FRAMES: {len(frames)}",
                flush=True,
            )

            for index, frame in enumerate(frames):
                try:
                    print(
                        f"FRAME[{index}] URL: "
                        f"{frame.url}",
                        flush=True,
                    )

                    body = frame.locator(
                        "body"
                    )

                    if body.count() > 0:
                        body_text = body.inner_text(
                            timeout=3000
                        )

                        print(
                            f"FRAME[{index}] BODY:\n"
                            f"{body_text[:3000]}",
                            flush=True,
                        )

                except Exception as frame_error:
                    print(
                        f"FRAME[{index}] ERROR: "
                        f"{frame_error}",
                        flush=True,
                    )

        except Exception as e:
            print(
                f"تعذر قراءة الـframes: {e}",
                flush=True,
            )

        try:
            html = self.page.content()

            print(
                "\n---------- HTML PREVIEW ----------",
                flush=True,
            )

            print(
                html[:12000],
                flush=True,
            )

        except Exception as e:
            print(
                f"تعذر قراءة HTML: {e}",
                flush=True,
            )

        print(
            "========== END DIAGNOSTICS ==========\n",
            flush=True,
        )

    def _find_in_all_frames(
        self,
        selector,
    ):
        for frame in self.page.frames:
            try:
                locator = frame.locator(
                    selector
                )

                if locator.count() > 0:
                    return locator.first

            except Exception:
                continue

        return None

    def _wait_for_selector_in_frames(
        self,
        selector,
        timeout_ms=30000,
    ):
        deadline = (
            time.time()
            + timeout_ms / 1000
        )

        while time.time() < deadline:
            locator = (
                self._find_in_all_frames(
                    selector
                )
            )

            if locator is not None:
                try:
                    if locator.is_visible():
                        return locator
                except Exception:
                    return locator

            self.page.wait_for_timeout(
                500
            )

        return None

    # ------------------------------------------------------------------
    # frontend / assets diagnostics
    # ------------------------------------------------------------------

    def _collect_asset_urls(self):
        urls = []

        try:
            nodes = self.page.locator(
                "link[rel='modulepreload'], "
                "script[type='module'][src], "
                "script[src], "
                "link[rel='stylesheet']"
            )

            count = nodes.count()

            for index in range(
                min(count, 30)
            ):
                try:
                    node = nodes.nth(index)

                    href = (
                        node.get_attribute(
                            "href"
                        )
                        or node.get_attribute(
                            "src"
                        )
                    )

                    if not href:
                        continue

                    absolute = urljoin(
                        self.page.url,
                        href,
                    )

                    if absolute not in urls:
                        urls.append(
                            absolute
                        )

                except Exception:
                    continue

        except Exception as e:
            print(
                "⚠️ تعذر جمع روابط assets: "
                f"{e}",
                flush=True,
            )

        return urls

    def _check_asset_directly(
        self,
        url,
    ):
        try:
            headers = {
                "User-Agent": BROWSER_USER_AGENT,
                "Accept": "*/*",
                "Accept-Language": (
                    BROWSER_ACCEPT_LANGUAGE
                ),
                "Origin": PORTAL_HOME.rstrip("/"),
                "Sec-Fetch-Dest": "script",
                "Sec-Fetch-Mode": "cors",
                "Sec-Fetch-Site": "same-origin",
                "Cache-Control": "no-cache",
                "Pragma": "no-cache",
            }

            response = (
                self.context.request.get(
                    url,
                    timeout=15000,
                    headers=headers,
                )
            )

            content_type = (
                response.headers.get(
                    "content-type",
                    "",
                )
                or ""
            )

            print(
                "🔬 ASSET CHECK: "
                f"{response.status} | "
                f"{content_type} | "
                f"{url}",
                flush=True,
            )

            print(
                "   X-CACHE: "
                f"{response.headers.get('x-cache', '')}",
                flush=True,
            )

            print(
                "   CF-POP: "
                f"{response.headers.get('x-amz-cf-pop', '')}",
                flush=True,
            )

            return {
                "status": response.status,
                "content_type": content_type,
                "url": url,
                "x_cache": response.headers.get(
                    "x-cache",
                    "",
                ),
                "cf_pop": response.headers.get(
                    "x-amz-cf-pop",
                    "",
                ),
            }

        except Exception as e:
            print(
                "❌ ASSET CHECK FAILED: "
                f"{url} | {e}",
                flush=True,
            )

            return {
                "status": 0,
                "content_type": "",
                "url": url,
                "error": str(e),
            }

    def _inspect_frontend_assets(self):
        print(
            "\n🔍 فحص ملفات Qureo Frontend...",
            flush=True,
        )

        urls = self._collect_asset_urls()

        if not urls:
            print(
                "⚠️ لم يتم العثور على أي "
                "JavaScript/CSS assets في HTML.",
                flush=True,
            )

            return False

        print(
            f"📦 تم العثور على {len(urls)} asset(s).",
            flush=True,
        )

        js_assets = [
            url
            for url in urls
            if "/assets/" in url
            and url.lower().endswith(".js")
        ]

        # --------------------------------------------------------------
        # CloudFront diagnostic على أول JS
        # --------------------------------------------------------------

        if js_assets:
            self._direct_asset_diagnostic(
                js_assets[0],
                referer=self.page.url,
            )

            self._cloudfront_asset_diagnostic(
                js_assets[0],
                referer=self.page.url,
            )

        broken = False

        # نفحص أول 12 فقط
        for url in urls[:12]:
            result = (
                self._check_asset_directly(
                    url
                )
            )

            status = result.get(
                "status",
                0,
            )

            content_type = (
                result.get(
                    "content_type",
                    "",
                )
                or ""
            ).lower()

            if (
                "/assets/" in url
                and (
                    status >= 400
                    or (
                        url.lower().endswith(".js")
                        and (
                            "javascript"
                            not in content_type
                            and "ecmascript"
                            not in content_type
                        )
                    )
                )
            ):
                broken = True

        if broken:
            self.frontend_broken = True

            print(
                "\n❌ Qureo Frontend لا يتم تحميل "
                "بشكل صحيح.",
                flush=True,
            )

            print(
                "❌ واحد أو أكثر من ملفات "
                "/assets/*.js يرجع MIME غير JavaScript.",
                flush=True,
            )

            print(
                "⚠️ تم اختبار Browser-like headers "
                "و Cache/Query bypass.",
                flush=True,
            )

            return False

        print(
            "✅ فحص assets الأساسي سليم.",
            flush=True,
        )

        return True

    def _wait_for_frontend(
        self,
        timeout_ms=10000,
    ):
        deadline = (
            time.time()
            + timeout_ms / 1000
        )

        selectors = [
            "#student_id",
            "button.portal-selection-button",
            "input[type='password']",
            "form",
        ]

        while time.time() < deadline:
            for selector in selectors:
                locator = (
                    self._find_in_all_frames(
                        selector
                    )
                )

                if locator is not None:
                    return True

            self.page.wait_for_timeout(
                500
            )

        return False

    def _open_portal_page(
        self,
        url,
    ):
        self.frontend_broken = False
        self.asset_results = []

        print(
            f"\n🌐 جاري فتح: {url}",
            flush=True,
        )

        try:
            response = self.page.goto(
                url,
                wait_until="domcontentloaded",
                timeout=60000,
            )

            if response is not None:
                print(
                    f"🌐 HTTP STATUS: "
                    f"{response.status}",
                    flush=True,
                )

                try:
                    print(
                        "📦 CONTENT-TYPE: "
                        f"{response.headers.get('content-type', '')}",
                        flush=True,
                    )
                except Exception:
                    pass

        except Exception as e:
            print(
                f"❌ فشل فتح الصفحة: {e}",
                flush=True,
            )

            return False

        print(
            f"🌐 الصفحة الحالية: "
            f"{self.page.url}",
            flush=True,
        )

        try:
            print(
                f"📄 TITLE: {self.page.title()}",
                flush=True,
            )
        except Exception:
            pass

        self.page.wait_for_timeout(
            2500
        )

        assets_ok = (
            self._inspect_frontend_assets()
        )

        frontend_ready = (
            self._wait_for_frontend(
                timeout_ms=7000
            )
        )

        if frontend_ready:
            print(
                "✅ Qureo Frontend بدأ "
                "ويظهر به DOM قابل للتفاعل.",
                flush=True,
            )

            return True

        if not assets_ok:
            print(
                "⚠️ الصفحة لم تبدأ لأن "
                "الـassets غير صحيحة.",
                flush=True,
            )

        return False

    # ------------------------------------------------------------------
    # login
    # ------------------------------------------------------------------

    def login(
        self,
        student_id=None,
        password=None,
    ):
        student_id = (
            student_id or STUDENT_ID
        )

        password = (
            password or PASSWORD
        )

        if not student_id or not password:
            raise RuntimeError(
                "لازم تدخل اسم المستخدم "
                "وكلمة المرور."
            )

        print(
            "🔑 جاري تسجيل الدخول تلقائيًا...",
            flush=True,
        )

        frontend_ready = (
            self._open_portal_page(
                PORTAL_URL
            )
        )

        if not frontend_ready:
            print(
                "\n🔁 لم يبدأ التطبيق من /login.",
                flush=True,
            )

            print(
                "🔁 سيتم تجربة الصفحة الرئيسية / ...",
                flush=True,
            )

            frontend_ready = (
                self._open_portal_page(
                    PORTAL_HOME
                )
            )

        if not frontend_ready:
            self._print_page_diagnostics()

            if self.frontend_broken:
                raise RuntimeError(
                    "Qureo Frontend لا يتم تحميله "
                    "من الخادم بشكل صحيح. "
                    "ملفات /assets/*.js لا ترجع "
                    "JavaScript صالحًا. "
                    "تمت تجربة /login و /. "
                    f"URL={self.page.url} | "
                    f"TITLE={self.page.title()}"
                )

            raise RuntimeError(
                "تم فتح Qureo لكن تطبيق Frontend "
                "لم يظهر ولم يتم العثور على نموذج "
                "تسجيل الدخول. "
                f"URL={self.page.url} | "
                f"TITLE={self.page.title()}"
            )

        learning_selector = (
            "button.portal-selection-button."
            "portal-selection-button-secondary"
        )

        print(
            "\n🔎 جاري البحث عن زر "
            "Learning Login في الصفحة "
            "والـiframes...",
            flush=True,
        )

        learning_button = (
            self._wait_for_selector_in_frames(
                learning_selector,
                timeout_ms=10000,
            )
        )

        if learning_button is not None:
            try:
                print(
                    "🔘 تم العثور على زر "
                    "Learning Login.",
                    flush=True,
                )

                try:
                    print(
                        "🔘 نص الزر: "
                        f"{learning_button.inner_text().strip()}",
                        flush=True,
                    )
                except Exception:
                    pass

                learning_button.click(
                    force=True,
                    timeout=15000,
                )

                print(
                    "✅ تم الضغط على "
                    "Go to Learning Login.",
                    flush=True,
                )

                self.page.wait_for_timeout(
                    1500
                )

            except Exception as e:
                print(
                    "⚠️ تعذر الضغط على زر "
                    f"Learning Login: {e}",
                    flush=True,
                )

        else:
            print(
                "ℹ️ زر Learning Login غير موجود.",
                flush=True,
            )

            print(
                "ℹ️ سيتم البحث عن نموذج "
                "الدخول مباشرة.",
                flush=True,
            )

        print(
            "🔎 جاري البحث عن #student_id "
            "في الصفحة والـiframes...",
            flush=True,
        )

        student_locator = (
            self._wait_for_selector_in_frames(
                "#student_id",
                timeout_ms=30000,
            )
        )

        if student_locator is None:
            self._print_page_diagnostics()

            raise RuntimeError(
                "تم تحميل Qureo Frontend لكن "
                "لم يتم العثور على نموذج تسجيل "
                "الدخول. لا يوجد #student_id "
                "في الصفحة أو الـiframes. "
                f"URL={self.page.url} | "
                f"TITLE={self.page.title()}"
            )

        print(
            "✅ تم العثور على نموذج تسجيل الدخول.",
            flush=True,
        )

        login_frame = None

        for frame in self.page.frames:
            try:
                if (
                    frame.locator(
                        "#student_id"
                    ).count()
                    > 0
                ):
                    login_frame = frame
                    break

            except Exception:
                continue

        if login_frame is None:
            login_frame = (
                self.page.main_frame
            )

        print(
            f"🧩 Login frame: "
            f"{login_frame.url}",
            flush=True,
        )

        try:
            login_frame.locator(
                "#student_id"
            ).fill(student_id)

            login_frame.locator(
                "#password"
            ).fill(password)

        except Exception as e:
            self._print_page_diagnostics()

            raise RuntimeError(
                "تم العثور على الفورم لكن "
                "تعذر إدخال البيانات: "
                f"{e}"
            ) from e

        print(
            "📝 تم إدخال بيانات تسجيل الدخول.",
            flush=True,
        )

        login_button = None

        selectors = [
            "button.login-button",
            "button[type='submit']",
            "input[type='submit']",
        ]

        for selector in selectors:
            try:
                candidate = (
                    login_frame.locator(
                        selector
                    ).first
                )

                if candidate.count() > 0:
                    login_button = candidate
                    break

            except Exception:
                continue

        if login_button is None:
            self._print_page_diagnostics()

            raise RuntimeError(
                "تم العثور على نموذج تسجيل "
                "الدخول لكن لم يتم العثور "
                "على زر الإرسال."
            )

        try:
            login_button.click(
                force=True,
                timeout=15000,
            )

        except Exception as e:
            raise RuntimeError(
                "تعذر الضغط على زر "
                f"تسجيل الدخول: {e}"
            ) from e

        print(
            "🔐 تم إرسال بيانات تسجيل الدخول.",
            flush=True,
        )

        try:
            login_frame.locator(
                "#student_id"
            ).wait_for(
                state="detached",
                timeout=30000,
            )

        except Exception:
            self.page.wait_for_timeout(
                2000
            )

            still_there = False

            try:
                still_there = (
                    login_frame.locator(
                        "#student_id"
                    ).count()
                    > 0
                )
            except Exception:
                pass

            if still_there:
                self._print_page_diagnostics()

                raise RuntimeError(
                    "فشل تسجيل الدخول أو بقي "
                    "نموذج الدخول ظاهرًا بعد "
                    "إرسال البيانات."
                )

        self.page.wait_for_timeout(
            1000
        )

        print(
            f"📍 بعد تسجيل الدخول: "
            f"{self.page.url}",
            flush=True,
        )

        print(
            "✅ تم تسجيل الدخول.",
            flush=True,
        )

    # ------------------------------------------------------------------
    # course navigation
    # ------------------------------------------------------------------

    def enter_course(
        self,
        name,
    ):
        print(
            f"📥 جاري الدخول إلى مسار {name}...",
            flush=True,
        )

        self.page.goto(
            PORTAL_HOME,
            wait_until="domcontentloaded",
            timeout=60000,
        )

        self.page.wait_for_timeout(
            1500
        )

        selector = f"text={name}"

        try:
            self.page.wait_for_selector(
                selector,
                timeout=30000,
            )

        except Exception:
            self._print_page_diagnostics()

            raise RuntimeError(
                f"لم يتم العثور على مسار {name}."
            )

        self.page.locator(
            selector
        ).first.click()

        self.page.wait_for_url(
            "**/me-tp.qureo.education/**",
            timeout=30000,
        )

        self.page.wait_for_timeout(
            800
        )

        print(
            f"✅ تم الدخول إلى مسار {name}: "
            f"{self.page.url}",
            flush=True,
        )

    # ------------------------------------------------------------------
    # api
    # ------------------------------------------------------------------

    def _req(
        self,
        method,
        path,
        body=None,
    ):
        url = BASE + path
        req = self.context.request

        if method == "GET":
            return req.get(url)

        data = json.dumps(
            body
            if body is not None
            else {}
        )

        if method == "PUT":
            return req.put(
                url,
                data=data,
                headers=JSON_HEADERS,
            )

        if method == "POST":
            return req.post(
                url,
                data=data,
                headers=JSON_HEADERS,
            )

        raise ValueError(method)

    def api_get_json(
        self,
        path,
        default=None,
    ):
        response = self._req(
            "GET",
            path,
        )

        if response.status != 200:
            print(
                f"⚠️ GET {path} -> "
                f"{response.status}",
                flush=True,
            )

            return default

        try:
            return response.json()
        except Exception:
            return default

    _FETCH_JS = """
    async (reqs) => {
        const out = new Array(reqs.length);

        await Promise.all(
            reqs.map(async (r, i) => {
                try {
                    const opts = {
                        method: r.method,
                        credentials: "include",
                        headers: {}
                    };

                    if (
                        r.body !== null &&
                        r.body !== undefined
                    ) {
                        opts.headers[
                            "Content-Type"
                        ] = "application/json";

                        opts.body = JSON.stringify(
                            r.body
                        );
                    }

                    const res = await fetch(
                        r.path,
                        opts
                    );

                    let data = null;

                    try {
                        data = await res.json();
                    } catch (e) {}

                    out[i] = {
                        status: res.status,
                        data: data
                    };

                } catch (e) {
                    out[i] = {
                        status: 0,
                        data: null,
                        error: String(e)
                    };
                }
            })
        );

        return out;
    }
    """

    def fetch_many(
        self,
        reqs,
    ):
        if not reqs:
            return []

        return self.page.evaluate(
            self._FETCH_JS,
            reqs,
        )

    # ------------------------------------------------------------------
    # discovery
    # ------------------------------------------------------------------

    def _section_from_course(self):
        me = self.api_get_json(
            "/api/study/students/me",
            {},
        ) or {}

        code = me.get(
            "course_code"
        )

        if not code:
            return None

        course = self.api_get_json(
            f"/api/study/courses/{code}",
            {},
        ) or {}

        basic = (
            course.get(
                "basic_section"
            )
            or {}
        )

        return basic.get(
            "id"
        )

    def resolve_section_id(self):
        deadline = (
            time.time() + 120
        )

        while time.time() < deadline:
            if stop_requested():
                raise RuntimeError(
                    "تم إيقاف التشغيل بواسطة المستخدم"
                )

            section_id = (
                self._section_from_course()
            )

            if section_id:
                return section_id

            match = re.search(
                r"/section/(\d+)",
                self.page.url,
            )

            if match:
                return int(
                    match.group(1)
                )

            match = re.search(
                r"/chapter/(\d+)",
                self.page.url,
            )

            if match:
                data = self.api_get_json(
                    f"/api/study/chapters/"
                    f"{match.group(1)}"
                )

                if (
                    data
                    and data.get("section")
                ):
                    return data[
                        "section"
                    ]["id"]

            time.sleep(1)

        raise RuntimeError(
            "تعذّر تحديد القسم الحالي."
        )

    # ------------------------------------------------------------------
    # lectures
    # ------------------------------------------------------------------

    def complete_lecture(
        self,
        lecture_id,
    ):
        self._req(
            "PUT",
            f"/api/study/students/lectures/"
            f"{lecture_id}",
        )

        response = self._req(
            "PUT",
            f"/api/study/students/lectures/"
            f"{lecture_id}/complete",
        )

        return response.status == 200

    def complete_chapter_lectures(
        self,
        chapter_id,
        chapter=None,
        progress=None,
    ):
        if progress is None:
            progress = self.api_get_json(
                f"/api/study/students/"
                f"chapters/{chapter_id}/lectures",
                [],
            ) or []

        if chapter is None:
            chapter = self.api_get_json(
                f"/api/study/chapters/"
                f"{chapter_id}",
                {},
            ) or {}

        done = {
            item.get("lecture_id")
            for item in progress
            if item.get("completed_at")
        }

        todo = [
            lecture
            for lecture in chapter.get(
                "lectures",
                [],
            )
            if lecture["id"] not in done
        ]

        for lecture in todo:
            if stop_requested():
                raise RuntimeError(
                    "تم إيقاف التشغيل بواسطة المستخدم"
                )

            lecture_id = lecture["id"]

            self._req(
                "PUT",
                f"/api/study/students/"
                f"lectures/{lecture_id}",
                {},
            )

            response = self._req(
                "PUT",
                f"/api/study/students/"
                f"lectures/{lecture_id}/complete",
                {},
            )

            if response.status == 200:
                print(
                    f"   📗 محاضرة "
                    f"{lecture.get('seq')}: "
                    f"{lecture.get('title', '')} "
                    f"— تم",
                    flush=True,
                )
            else:
                print(
                    f"   ⚠️ تعذّر إكمال "
                    f"المحاضرة {lecture_id} "
                    f"({response.status})",
                    flush=True,
                )

    # ------------------------------------------------------------------
    # course inspection
    # ------------------------------------------------------------------

    def inspect_course(self):
        section_id = (
            self.resolve_section_id()
        )

        section = self.api_get_json(
            f"/api/study/sections/"
            f"{section_id}",
            {},
        ) or {}

        chapters = section.get(
            "chapters",
            [],
        )

        progress = self.api_get_json(
            f"/api/study/students/"
            f"sections/{section_id}/chapters",
            [],
        ) or []

        pmap = {
            item.get("chapter_id"): item
            for item in progress
        }

        print(
            f"📚 القسم الحالي: "
            f"{section_id}",
            flush=True,
        )

        print(
            f"📚 عدد الفصول: "
            f"{len(chapters)}",
            flush=True,
        )

        emit_progress(
            self.current_course,
            0,
            len(chapters),
            "",
        )

        results = []

        for index, chapter in enumerate(
            chapters
        ):
            if stop_requested():
                raise RuntimeError(
                    "تم إيقاف التشغيل بواسطة المستخدم"
                )

            chapter_id = chapter["id"]

            name = chapter.get(
                "name",
                "",
            )

            question_count = chapter.get(
                "question_count",
                0,
            )

            emit_progress(
                self.current_course,
                index,
                len(chapters),
                name,
            )

            current_progress = (
                pmap.get(
                    chapter_id,
                    {},
                )
                or {}
            )

            best = current_progress.get(
                "best_correct_count",
                0,
            )

            print(
                f"▶️ الفصل "
                f"{chapter.get('seq')}: "
                f"{name} ({chapter_id}) — "
                f"أسئلة: {question_count} — "
                f"أفضل نتيجة: {best}",
                flush=True,
            )

            results.append(
                {
                    "id": chapter_id,
                    "name": name,
                    "question_count": (
                        question_count
                    ),
                    "best_correct_count": (
                        best
                    ),
                }
            )

        emit_progress(
            self.current_course,
            len(chapters),
            len(chapters),
            "تم",
        )

        return results

    # ------------------------------------------------------------------
    # main
    # ------------------------------------------------------------------

    def run(
        self,
        student_id=None,
        password=None,
        courses=None,
        close_pause=5,
    ):
        if courses:
            self.courses = courses

        self.start()

        try:
            self.login(
                student_id,
                password,
            )

            for name in self.courses:
                if stop_requested():
                    raise RuntimeError(
                        "تم إيقاف التشغيل بواسطة المستخدم"
                    )

                print(
                    "\n" + "=" * 60,
                    flush=True,
                )

                self.enter_course(
                    name
                )

                self.current_course = name

                chapters = (
                    self.inspect_course()
                )

                print(
                    "=" * 60,
                    flush=True,
                )

                print(
                    f"✨ اكتمل فحص مسار "
                    f"{name}! "
                    f"عدد الفصول: "
                    f"{len(chapters)}",
                    flush=True,
                )

                print(
                    "=" * 60,
                    flush=True,
                )

        finally:
            if self.browser is not None:
                if close_pause:
                    print(
                        f"\n🖐️ سيتم إغلاق المتصفح "
                        f"خلال {close_pause} ثوانٍ...",
                        flush=True,
                    )

                    time.sleep(
                        close_pause
                    )

                try:
                    self.browser.close()
                except Exception:
                    pass

            if self.playwright is not None:
                try:
                    self.playwright.stop()
                except Exception:
                    pass


if __name__ == "__main__":
    QureoSolver(
        headless=True,
    ).run()