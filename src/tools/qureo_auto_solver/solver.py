import json
import os
import re
import sys
import time

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
JSON_HEADERS = {"Content-Type": "application/json"}

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
ANSWER_FILE = os.path.join(SCRIPT_DIR, "answers.json")

STUDENT_ID = ""
PASSWORD = ""
COURSES = ["Python", "JavaScript"]

# خطّافات اختيارية تستخدمها الواجهة
PROGRESS = None
SHOULD_STOP = None


def emit_progress(course, done, total, label=""):
    if PROGRESS:
        try:
            PROGRESS(course, done, total, label)
        except Exception:
            pass


def stop_requested():
    if SHOULD_STOP:
        try:
            return bool(SHOULD_STOP())
        except Exception:
            return False
    return False


class QureoSolver:
    def __init__(self, headless=True, courses=None):
        self.headless = headless
        self.courses = courses or COURSES

        self.playwright = None
        self.browser = None
        self.context = None
        self.page = None
        self.current_course = ""

    # ------------------------------------------------------------------
    # browser
    # ------------------------------------------------------------------

    def start(self):
        print(
            "🚀 جاري تشغيل المتصفح في الخلفية...",
            flush=True,
        )

        self.playwright = sync_playwright().start()

        try:
            self.browser = self.playwright.chromium.launch(
                headless=True,
            )

            print(
                "🌐 تم تشغيل Playwright Chromium في الخلفية.",
                flush=True,
            )

        except Exception as e:
            raise RuntimeError(
                "تعذّر تشغيل Chromium على Railway. "
                "تأكد من تثبيت Playwright Chromium."
            ) from e

        self.context = self.browser.new_context(
            viewport={
                "width": 1280,
                "height": 800,
            },
            locale="en-US",
            timezone_id="Africa/Cairo",
        )

        self.page = self.context.new_page()

        self.page.on(
            "console",
            lambda msg: print(
                f"🖥️ CONSOLE [{msg.type}]: {msg.text}",
                flush=True,
            )
            if msg.type in {"error", "warning"}
            else None,
        )

        self.page.on(
            "pageerror",
            lambda exc: print(
                f"💥 PAGE ERROR: {exc}",
                flush=True,
            ),
        )

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
                        f"FRAME[{index}] URL: {frame.url}",
                        flush=True,
                    )

                    body = frame.locator("body")

                    if body.count() > 0:
                        text = body.inner_text(
                            timeout=3000,
                        )

                        print(
                            f"FRAME[{index}] BODY:\n"
                            f"{text[:3000]}",
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

    def _find_in_all_frames(self, selector):
        """
        يرجع أول locator موجود للـselector
        في الصفحة أو أحد الـiframes.
        """

        for frame in self.page.frames:
            try:
                locator = frame.locator(selector)

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
        deadline = time.time() + (
            timeout_ms / 1000
        )

        while time.time() < deadline:
            locator = self._find_in_all_frames(
                selector,
            )

            if locator is not None:
                try:
                    if locator.is_visible():
                        return locator
                except Exception:
                    return locator

            self.page.wait_for_timeout(500)

        return None

    # ------------------------------------------------------------------
    # login
    # ------------------------------------------------------------------

    def login(
        self,
        student_id=None,
        password=None,
    ):
        """
        تسجيل الدخول مع دعم حالتين:

        1. ظهور زر Learning Login.
        2. فتح نموذج الدخول مباشرة.

        ويتم البحث في الصفحة وكل الـiframes.
        """

        student_id = student_id or STUDENT_ID
        password = password or PASSWORD

        if not student_id or not password:
            raise RuntimeError(
                "لازم تدخل اسم المستخدم وكلمة المرور."
            )

        print(
            "🔑 جاري تسجيل الدخول تلقائيًا...",
            flush=True,
        )

        # --------------------------------------------------------------
        # فتح صفحة الدخول
        # --------------------------------------------------------------

        try:
            response = self.page.goto(
                PORTAL_URL,
                wait_until="domcontentloaded",
                timeout=60000,
            )

            if response is not None:
                print(
                    f"🌐 HTTP STATUS: {response.status}",
                    flush=True,
                )

                try:
                    print(
                        f"📦 CONTENT-TYPE: "
                        f"{response.headers.get('content-type', '')}",
                        flush=True,
                    )
                except Exception:
                    pass

        except Exception as e:
            self._print_page_diagnostics()

            raise RuntimeError(
                f"فشل فتح صفحة Qureo: {e}"
            ) from e

        print(
            f"🌐 صفحة الدخول: {self.page.url}",
            flush=True,
        )

        try:
            print(
                f"📄 TITLE: {self.page.title()}",
                flush=True,
            )
        except Exception:
            pass

        # نعطي JavaScript / hydration فرصة للعمل.
        self.page.wait_for_timeout(3000)

        # --------------------------------------------------------------
        # أولًا: هل زر Learning Login موجود؟
        # --------------------------------------------------------------

        learning_selector = (
            "button.portal-selection-button."
            "portal-selection-button-secondary"
        )

        print(
            "🔎 جاري البحث عن زر Learning Login "
            "في الصفحة والـiframes...",
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
                    "🔘 تم العثور على زر Learning Login.",
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
                    "✅ تم الضغط على Go to Learning Login.",
                    flush=True,
                )

                self.page.wait_for_timeout(1500)

            except Exception as e:
                print(
                    f"⚠️ تعذر الضغط على زر Learning Login: "
                    f"{e}",
                    flush=True,
                )

        else:
            print(
                "ℹ️ زر Learning Login غير موجود.",
                flush=True,
            )

            print(
                "ℹ️ سيتم البحث عن نموذج الدخول مباشرة.",
                flush=True,
            )

        # --------------------------------------------------------------
        # ثانيًا: البحث عن student_id في كل frames
        # --------------------------------------------------------------

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
                "لم يتم العثور على نموذج تسجيل الدخول في Qureo. "
                "لا يوجد #student_id في الصفحة أو الـiframes. "
                f"URL={self.page.url} | "
                f"TITLE={self.page.title()}"
            )

        print(
            "✅ تم العثور على نموذج تسجيل الدخول.",
            flush=True,
        )

        # --------------------------------------------------------------
        # تحديد الـframe الذي يحتوي على الفورم
        # --------------------------------------------------------------

        login_frame = None

        for frame in self.page.frames:
            try:
                if frame.locator(
                    "#student_id"
                ).count() > 0:
                    login_frame = frame
                    break
            except Exception:
                continue

        if login_frame is None:
            login_frame = self.page.main_frame

        print(
            f"🧩 Login frame: {login_frame.url}",
            flush=True,
        )

        # --------------------------------------------------------------
        # إدخال بيانات الدخول
        # --------------------------------------------------------------

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
                f"تم العثور على الفورم لكن تعذر إدخال البيانات: {e}"
            ) from e

        print(
            "📝 تم إدخال بيانات تسجيل الدخول.",
            flush=True,
        )

        # --------------------------------------------------------------
        # زر Login
        # --------------------------------------------------------------

        login_button = None

        selectors = [
            "button.login-button",
            "button[type='submit']",
            "input[type='submit']",
        ]

        for selector in selectors:
            try:
                candidate = login_frame.locator(
                    selector
                ).first

                if candidate.count() > 0:
                    login_button = candidate
                    break

            except Exception:
                continue

        if login_button is None:
            self._print_page_diagnostics()

            raise RuntimeError(
                "تم العثور على نموذج تسجيل الدخول "
                "لكن لم يتم العثور على زر الإرسال."
            )

        try:
            login_button.click(
                force=True,
                timeout=15000,
            )

        except Exception as e:
            raise RuntimeError(
                f"تعذر الضغط على زر تسجيل الدخول: {e}"
            ) from e

        print(
            "🔐 تم إرسال بيانات تسجيل الدخول.",
            flush=True,
        )

        # --------------------------------------------------------------
        # انتظار انتهاء عملية الدخول
        # --------------------------------------------------------------

        try:
            login_frame.locator(
                "#student_id"
            ).wait_for(
                state="detached",
                timeout=30000,
            )

        except Exception:
            # أحيانًا الفورم لا يختفي لكن الصفحة تنتقل.
            self.page.wait_for_timeout(2000)

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
                    "فشل تسجيل الدخول أو بقي نموذج الدخول "
                    "ظاهرًا بعد إرسال البيانات."
                )

        self.page.wait_for_timeout(1000)

        print(
            f"📍 بعد تسجيل الدخول: {self.page.url}",
            flush=True,
        )

        print(
            "✅ تم تسجيل الدخول.",
            flush=True,
        )

    # ------------------------------------------------------------------
    # course navigation
    # ------------------------------------------------------------------

    def enter_course(self, name):
        print(
            f"📥 جاري الدخول إلى مسار {name}...",
            flush=True,
        )

        self.page.goto(
            PORTAL_HOME,
            wait_until="domcontentloaded",
            timeout=60000,
        )

        self.page.wait_for_timeout(1500)

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

        self.page.wait_for_timeout(800)

        print(
            f"✅ تم الدخول إلى مسار {name}: "
            f"{self.page.url}",
            flush=True,
        )

    # ------------------------------------------------------------------
    # api helpers
    # ------------------------------------------------------------------

    def _req(self, method, path, body=None):
        url = BASE + path
        req = self.context.request

        if method == "GET":
            return req.get(url)

        data = json.dumps(
            body if body is not None else {}
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

    def api_get_json(self, path, default=None):
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

    def fetch_many(self, reqs):
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

        code = me.get("course_code")

        if not code:
            return None

        course = self.api_get_json(
            f"/api/study/courses/{code}",
            {},
        ) or {}

        basic = course.get(
            "basic_section"
        ) or {}

        return basic.get("id")

    def resolve_section_id(self):
        deadline = time.time() + 120

        while time.time() < deadline:
            if stop_requested():
                raise RuntimeError(
                    "تم إيقاف التشغيل بواسطة المستخدم"
                )

            section_id = self._section_from_course()

            if section_id:
                return section_id

            match = re.search(
                r"/section/(\d+)",
                self.page.url,
            )

            if match:
                return int(match.group(1))

            match = re.search(
                r"/chapter/(\d+)",
                self.page.url,
            )

            if match:
                data = self.api_get_json(
                    f"/api/study/chapters/{match.group(1)}"
                )

                if (
                    data
                    and data.get("section")
                ):
                    return data["section"]["id"]

            time.sleep(1)

        raise RuntimeError(
            "تعذّر تحديد القسم الحالي."
        )

    # ------------------------------------------------------------------
    # lectures
    # ------------------------------------------------------------------

    def complete_lecture(self, lecture_id):
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
                f"/api/study/students/chapters/"
                f"{chapter_id}/lectures",
                [],
            ) or []

        if chapter is None:
            chapter = self.api_get_json(
                f"/api/study/chapters/{chapter_id}",
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
                f"/api/study/students/lectures/"
                f"{lecture_id}",
                {},
            )

            response = self._req(
                "PUT",
                f"/api/study/students/lectures/"
                f"{lecture_id}/complete",
                {},
            )

            if response.status == 200:
                print(
                    f"   📗 محاضرة "
                    f"{lecture.get('seq')}: "
                    f"{lecture.get('title', '')} — تم",
                    flush=True,
                )
            else:
                print(
                    f"   ⚠️ تعذّر إكمال المحاضرة "
                    f"{lecture_id} "
                    f"({response.status})",
                    flush=True,
                )

    # ------------------------------------------------------------------
    # safe course inspection
    # ------------------------------------------------------------------

    def inspect_course(self):
        """
        يجلب بنية المسار والفصول والأسئلة الموجودة
        لأغراض التشخيص فقط، بدون إرسال إجابات للاختبارات.
        """

        section_id = self.resolve_section_id()

        section = self.api_get_json(
            f"/api/study/sections/{section_id}",
            {},
        ) or {}

        chapters = section.get(
            "chapters",
            [],
        )

        progress = self.api_get_json(
            f"/api/study/students/sections/"
            f"{section_id}/chapters",
            [],
        ) or []

        pmap = {
            item.get("chapter_id"): item
            for item in progress
        }

        print(
            f"📚 القسم الحالي: {section_id}",
            flush=True,
        )

        print(
            f"📚 عدد الفصول: {len(chapters)}",
            flush=True,
        )

        emit_progress(
            self.current_course,
            0,
            len(chapters),
            "",
        )

        results = []

        for index, chapter in enumerate(chapters):
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

            current_progress = pmap.get(
                chapter_id,
                {},
            ) or {}

            best = current_progress.get(
                "best_correct_count",
                0,
            )

            print(
                f"▶️ الفصل {chapter.get('seq')}: "
                f"{name} ({chapter_id}) — "
                f"أسئلة: {question_count} — "
                f"أفضل نتيجة: {best}",
                flush=True,
            )

            results.append(
                {
                    "id": chapter_id,
                    "name": name,
                    "question_count": question_count,
                    "best_correct_count": best,
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

                self.enter_course(name)

                self.current_course = name

                chapters = self.inspect_course()

                print(
                    "=" * 60,
                    flush=True,
                )

                print(
                    f"✨ اكتمل فحص مسار {name}! "
                    f"عدد الفصول: {len(chapters)}",
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
                        f"\n🖐️ سيتم إغلاق المتصفح خلال "
                        f"{close_pause} ثوانٍ...",
                        flush=True,
                    )

                    time.sleep(close_pause)

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
