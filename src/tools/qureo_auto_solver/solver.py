import json
import os
import re
import sys
import time

from playwright.sync_api import sync_playwright


# ============================================================
# UTF-8
# ============================================================

if sys.stdout.encoding != "utf-8":
    try:
        sys.stdout.reconfigure(
            encoding="utf-8",
            errors="replace",
        )
    except Exception:
        pass


# ============================================================
# CONFIG
# ============================================================

PORTAL_URL = os.getenv(
    "QUREO_PORTAL_LOGIN_URL",
    "https://me-portal.qureo.education/login",
)

PORTAL_HOME = os.getenv(
    "QUREO_PORTAL_HOME_URL",
    "https://me-portal.qureo.education/",
)

BASE = os.getenv(
    "QUREO_BASE_URL",
    "https://me-tp.qureo.education",
).rstrip("/")

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


# ============================================================
# OPTIONAL HOOKS
# ============================================================

PROGRESS = None
SHOULD_STOP = None


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


# ============================================================
# SOLVER
# ============================================================

class QureoSolver:

    def __init__(
        self,
        headless=False,
        courses=None,
    ):
        self.headless = headless

        self.courses = (
            courses
            if courses
            else COURSES
        )

        self.playwright = None
        self.browser = None
        self.context = None
        self.page = None

        self.answers = (
            self._load_answers()
        )

        self.current_course = ""

    # ========================================================
    # BROWSER
    # ========================================================

    def start(self):
        print(
            "🚀 جاري تشغيل المتصفح...",
            flush=True,
        )

        self.playwright = (
            sync_playwright().start()
        )

        last_error = None

        for channel in (
            "chrome",
            "msedge",
        ):
            try:
                self.browser = (
                    self.playwright.chromium.launch(
                        headless=self.headless,
                        channel=channel,
                    )
                )

                print(
                    f"🌐 تم تشغيل المتصفح: {channel}",
                    flush=True,
                )

                break

            except Exception as exc:
                last_error = exc

        if self.browser is None:
            try:
                self.browser = (
                    self.playwright.chromium.launch(
                        headless=self.headless,
                    )
                )

                print(
                    "🌐 تم تشغيل Playwright Chromium.",
                    flush=True,
                )

            except Exception as exc:
                last_error = exc

                raise RuntimeError(
                    "تعذّر تشغيل Chromium على Railway. "
                    "تأكد من تثبيت Playwright Chromium."
                ) from last_error

        self.context = (
            self.browser.new_context(
                viewport={
                    "width": 1280,
                    "height": 800,
                }
            )
        )

        self.page = (
            self.context.new_page()
        )

        self.page.set_default_timeout(
            30000
        )

        self.page.set_default_navigation_timeout(
            60000
        )

    
        # ----------------------------------------------------
        # اختيار زر تسجيل الدخول للتعلم
        #
        # Qureo يعرض زرين في صفحة البورتال.
        # المطلوب هو الزر الثاني تحديدًا:
        #
        # Go to Learning Login
        # /انتقل إلى تسجيل الدخول للتعلم
        #
        # لذلك لا نستخدم أول عنصر مطابق.
        # ----------------------------------------------------

        learning_login = None

        # أول محاولة:
        # نفس مجموعة أزرار البورتال، لكن نأخذ الزر الثاني.
        try:
            portal_buttons = self.page.locator(
                ".portal-selection-button-secondary"
            )

            count = portal_buttons.count()

            print(
                f"🔎 عدد أزرار اختيار البورتال: {count}",
                flush=True,
            )

            if count >= 2:
                learning_login = portal_buttons.nth(1)

                learning_login.wait_for(
                    state="visible",
                    timeout=10000,
                )

                print(
                    "🎯 تم تحديد الزر الثاني في صفحة البورتال.",
                    flush=True,
                )

        except Exception:
            learning_login = None

        # ----------------------------------------------------
        # Fallback:
        # لو الـ class اختلف، ابحث عن أزرار البورتال كلها
        # وخذ الزر الثاني الظاهر.
        # ----------------------------------------------------

        if learning_login is None:
            try:
                portal_buttons = self.page.locator(
                    "[class*='portal-selection-button']"
                )

                count = portal_buttons.count()

                print(
                    f"🔎 عدد عناصر portal-selection-button: {count}",
                    flush=True,
                )

                visible_buttons = []

                for index in range(count):
                    try:
                        candidate = portal_buttons.nth(index)

                        if candidate.is_visible(timeout=1000):
                            visible_buttons.append(candidate)

                            try:
                                button_text = (
                                    candidate.inner_text(
                                        timeout=1000
                                    )
                                )

                                button_text = re.sub(
                                    r"\s+",
                                    " ",
                                    button_text,
                                ).strip()

                                print(
                                    f"   [{len(visible_buttons)}] "
                                    f"{button_text}",
                                    flush=True,
                                )

                            except Exception:
                                pass

                    except Exception:
                        continue

                if len(visible_buttons) >= 2:
                    learning_login = visible_buttons[1]

                    print(
                        "🎯 تم اختيار الزر الثاني الظاهر.",
                        flush=True,
                    )

            except Exception:
                learning_login = None

        # ----------------------------------------------------
        # Fallback أخير:
        # ابحث عن النص نفسه، لكن لا نستخدمه إلا لو لم نستطع
        # تحديد الزر الثاني بالطريقة السابقة.
        # ----------------------------------------------------

        if learning_login is None:
            try:
                candidates = self.page.get_by_text(
                    re.compile(
                        r"Go\s*to\s*Learning\s*Login"
                        r".*"
                        r"انتقل\s*إلى\s*تسجيل\s*الدخول\s*للتعلم",
                        re.IGNORECASE,
                    )
                )

                count = candidates.count()

                print(
                    f"🔎 عناصر النص المطابق: {count}",
                    flush=True,
                )

                for index in range(count):
                    try:
                        candidate = candidates.nth(index)

                        if candidate.is_visible(timeout=1000):
                            learning_login = candidate
                            break

                    except Exception:
                        continue

            except Exception:
                learning_login = None

        # ----------------------------------------------------
        # لو لم نجد الزر
        # ----------------------------------------------------

        if learning_login is None:

            current_url = self.page.url

            try:
                title = self.page.title()
            except Exception:
                title = ""

            try:
                body = self.page.locator(
                    "body"
                ).inner_text(
                    timeout=5000
                )

                body = re.sub(
                    r"\s+",
                    " ",
                    body,
                ).strip()

                if len(body) > 2500:
                    body = body[:2500]

            except Exception:
                body = ""

            raise RuntimeError(
                "لم يتم العثور على الزر الثاني "
                "'Go to Learning Login /انتقل إلى تسجيل الدخول للتعلم' "
                "في Qureo. "
                f"URL={current_url} | "
                f"TITLE={title} | "
                f"PAGE={body}"
            )

        # ----------------------------------------------------
        # الضغط على الزر الثاني
        # ----------------------------------------------------

        print(
            "🖱️ جاري الضغط على الزر الثاني "
            "'Go to Learning Login /انتقل إلى تسجيل الدخول للتعلم'...",
            flush=True,
        )

        try:
            learning_login.scroll_into_view_if_needed(
                timeout=10000
            )
        except Exception:
            pass

        old_url = self.page.url

        try:
            learning_login.click(
                timeout=15000
            )

        except Exception:
            try:
                learning_login.click(
                    timeout=15000,
                    force=True,
                )
            except Exception as exc:
                raise RuntimeError(
                    "تعذّر الضغط على الزر الثاني "
                    "'Go to Learning Login /انتقل إلى تسجيل الدخول للتعلم'."
                ) from exc

        print(
            "✅ تم الضغط على الزر الثاني.",
            flush=True,
        )

        # ----------------------------------------------------
        # انتظار انتقال الصفحة / ظهور نموذج الدخول
        # ----------------------------------------------------

        self.page.wait_for_timeout(
            1500
        )

        try:
            self.page.wait_for_load_state(
                "domcontentloaded",
                timeout=10000,
            )
        except Exception:
            pass

        try:
            self.page.wait_for_load_state(
                "networkidle",
                timeout=10000,
            )
        except Exception:
            pass

        print(
            f"📄 بعد الضغط على الزر الثاني: "
            f"{self.page.url}",
            flush=True,
        )

        if self.page.url != old_url:
            print(
                "➡️ تم الانتقال إلى صفحة جديدة.",
                flush=True,
            )

        # ====================================================
        # LOGIN FORM
        # ====================================================

        student = self.page.locator(
            "#student_id"
        )

        try:
            student.wait_for(
                state="visible",
                timeout=30000,
            )

        except Exception as exc:

            current_url = self.page.url

            try:
                title = self.page.title()
            except Exception:
                title = ""

            try:
                body = self.page.locator(
                    "body"
                ).inner_text(
                    timeout=5000
                )

                body = re.sub(
                    r"\s+",
                    " ",
                    body,
                ).strip()

                if len(body) > 2500:
                    body = body[:2500]

            except Exception:
                body = ""

            raise RuntimeError(
                "تم الضغط على الزر الثاني "
                "'Go to Learning Login' "
                "لكن نموذج تسجيل الدخول لم يظهر. "
                f"URL={current_url} | "
                f"TITLE={title} | "
                f"PAGE={body}"
            ) from exc

        print(
            "✅ ظهر نموذج تسجيل الدخول.",
            flush=True,
        )


        # ----------------------------------------------------
        # الضغط على الزر المطلوب.
        # لو الضغط يعمل navigation ننتظره،
        # ولو يعمل JavaScript بدون navigation نكمل عادي.
        # ----------------------------------------------------

        try:
            with self.page.expect_navigation(
                wait_until="domcontentloaded",
                timeout=15000,
            ):
                learning_login.click(
                    timeout=15000
                )

        except Exception:

            try:
                learning_login.click(
                    timeout=15000,
                    force=True,
                )
            except Exception as exc:
                raise RuntimeError(
                    "تعذّر الضغط على زر "
                    "'Go to Learning Login /انتقل إلى تسجيل الدخول للتعلم'."
                ) from exc

        print(
            "✅ تم الضغط على Go to Learning Login.",
            flush=True,
        )

        # ----------------------------------------------------
        # انتظار الصفحة الجديدة / JavaScript
        # ----------------------------------------------------

        self.page.wait_for_timeout(
            1500
        )

        try:
            self.page.wait_for_load_state(
                "domcontentloaded",
                timeout=10000,
            )
        except Exception:
            pass

        try:
            self.page.wait_for_load_state(
                "networkidle",
                timeout=10000,
            )
        except Exception:
            pass

        print(
            f"📄 بعد Go to Learning Login: "
            f"{self.page.url}",
            flush=True,
        )

        # ====================================================
        # LOGIN FORM
        # ====================================================

        student = self.page.locator(
            "#student_id"
        )

        try:
            student.wait_for(
                state="visible",
                timeout=30000,
            )

        except Exception as exc:

            current_url = self.page.url

            try:
                title = self.page.title()
            except Exception:
                title = ""

            try:
                body = (
                    self.page.locator(
                        "body"
                    ).inner_text(
                        timeout=5000
                    )
                )

                body = re.sub(
                    r"\s+",
                    " ",
                    body,
                ).strip()

                if len(body) > 2500:
                    body = body[:2500]

            except Exception:
                body = ""

            raise RuntimeError(
                "تم الضغط على "
                "'Go to Learning Login' "
                "لكن نموذج تسجيل الدخول لم يظهر. "
                f"URL={current_url} | "
                f"TITLE={title} | "
                f"PAGE={body}"
            ) from exc

        print(
            "✅ ظهر نموذج تسجيل الدخول.",
            flush=True,
        )

        # ====================================================
        # FILL CREDENTIALS
        # ====================================================

        student.fill(
            student_id
        )

        password_input = self.page.locator(
            "#password"
        )

        password_input.wait_for(
            state="visible",
            timeout=10000,
        )

        password_input.fill(
            password
        )

        print(
            "✍️ تم إدخال بيانات الحساب.",
            flush=True,
        )

        # ====================================================
        # LOGIN BUTTON
        # ====================================================

        login_button = None

        button_selectors = [
            "button.login-button",
            "button[type='submit']",
            "input[type='submit']",
        ]

        for selector in button_selectors:

            try:
                candidate = self.page.locator(
                    selector
                ).first

                candidate.wait_for(
                    state="visible",
                    timeout=3000,
                )

                login_button = candidate
                break

            except Exception:
                continue

        if login_button is None:
            raise RuntimeError(
                "لم يتم العثور على زر تسجيل الدخول."
            )

        print(
            "🖱️ جاري الضغط على تسجيل الدخول...",
            flush=True,
        )

        login_button.click(
            timeout=15000
        )

        # ====================================================
        # LOGIN RESULT
        # ====================================================

        success = False

        try:
            self.page.wait_for_selector(
                "#student_id",
                state="detached",
                timeout=30000,
            )

            success = True

        except Exception:
            pass

        if not success:

            try:
                if not self.page.locator(
                    "#student_id"
                ).is_visible(
                    timeout=3000
                ):
                    success = True

            except Exception:
                pass

        if not success:

            try:
                current_url = (
                    self.page.url.lower()
                )

                if (
                    "login" not in current_url
                    and "auth" not in current_url
                ):
                    success = True

            except Exception:
                pass

        if not success:

            current_url = self.page.url

            try:
                title = self.page.title()
            except Exception:
                title = ""

            try:
                body = (
                    self.page.locator(
                        "body"
                    ).inner_text(
                        timeout=5000
                    )
                )

                body = re.sub(
                    r"\s+",
                    " ",
                    body,
                ).strip()

                if len(body) > 2000:
                    body = body[:2000]

            except Exception:
                body = ""

            raise RuntimeError(
                "فشل تسجيل الدخول — "
                "تأكد من اسم المستخدم وكلمة المرور. "
                f"URL={current_url} | "
                f"TITLE={title} | "
                f"PAGE={body}"
            )

        time.sleep(1)

        print(
            "✅ تم تسجيل الدخول.",
            flush=True,
        )

    # ========================================================
    # COURSE
    # ========================================================

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

        self.page.wait_for_selector(
            f"text={name}",
            timeout=30000,
        )

        self.page.locator(
            f"text={name}"
        ).first.click()

        self.page.wait_for_url(
            "**/me-tp.qureo.education/**",
            timeout=30000,
        )

        time.sleep(0.8)

        print(
            f"✅ تم الدخول إلى مسار {name}: "
            f"{self.page.url}",
            flush=True,
        )

    # ========================================================
    # API
    # ========================================================

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
            return default

        try:
            return response.json()
        except Exception:
            return default

    # ========================================================
    # PARALLEL FETCH
    # ========================================================

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

                        opts.body =
                            JSON.stringify(r.body);
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

    # ========================================================
    # DISCOVERY
    # ========================================================

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

        return basic.get("id")

    def resolve_section_id(self):
        deadline = (
            time.time() + 120
        )

        while time.time() < deadline:

            sid = (
                self._section_from_course()
            )

            if sid:
                return sid

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

            if stop_requested():
                raise RuntimeError(
                    "تم إيقاف التشغيل بواسطة المستخدم"
                )

            time.sleep(1)

        raise RuntimeError(
            "تعذّر تحديد القسم الحالي."
        )

    # ========================================================
    # LECTURES
    # ========================================================

    def complete_lecture(self, lid):
        self._req(
            "PUT",
            f"/api/study/students/"
            f"lectures/{lid}",
        )

        response = self._req(
            "PUT",
            f"/api/study/students/"
            f"lectures/{lid}/complete",
        )

        return response.status == 200

    def complete_chapter_lectures(
        self,
        cid,
        chapter=None,
        progress=None,
    ):
        if progress is None:
            progress = (
                self.api_get_json(
                    f"/api/study/students/"
                    f"chapters/{cid}/lectures",
                    [],
                )
                or []
            )

        if chapter is None:
            chapter = (
                self.api_get_json(
                    f"/api/study/chapters/{cid}",
                    {},
                )
                or {}
            )

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

        if not todo:
            return

        for lecture in todo:

            if stop_requested():
                raise RuntimeError(
                    "تم إيقاف التشغيل بواسطة المستخدم"
                )

            self._req(
                "PUT",
                f"/api/study/students/lectures/{lecture['id']}",
                {},
            )

            response = self._req(
                "PUT",
                f"/api/study/students/"
                f"lectures/{lecture['id']}/complete",
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
                    f"{lecture['id']} "
                    f"({response.status})",
                    flush=True,
                )

    # ========================================================
    # TESTS
    # ========================================================

    def _start_test(self, cid):
        return self._req(
            "PUT",
            f"/api/study/students/"
            f"chapters/{cid}/test",
        ).status

    def _result_path(
        self,
        cid,
        test_type,
    ):
        if test_type == "test":
            return (
                f"/api/study/students/"
                f"chapters/{cid}/test/result"
            )

        return (
            f"/api/study/students/"
            f"chapters/{cid}/review/result"
        )

    def _answer_base(
        self,
        test_type,
    ):
        if test_type == "test":
            return "test-questions"

        return "review-questions"

    @staticmethod
    def _extract_key(result):
        key = {}

        for choice_result in (
            result or {}
        ).get(
            "choice_results",
            [],
        ) or []:

            qid = choice_result.get(
                "question_id"
            )

            correct = [
                choice["choice"]["id"]
                for choice in (
                    choice_result.get(
                        "choices"
                    )
                    or []
                )
                if choice.get("correct")
            ]

            if qid and correct:
                key[qid] = (
                    "choice",
                    correct[0],
                )

        for description_result in (
            result or {}
        ).get(
            "description_results",
            [],
        ) or []:

            qid = description_result.get(
                "question_id"
            )

            if (
                qid
                and description_result.get(
                    "model_answer"
                ) is not None
            ):
                key[qid] = (
                    "description",
                    description_result[
                        "model_answer"
                    ],
                )

        return key

    # ========================================================
    # ANSWER BANK
    # ========================================================

    def _load_answers(self):
        try:
            with open(
                ANSWER_FILE,
                encoding="utf-8",
            ) as file:
                return json.load(file)

        except Exception:
            return {}

    def _save_answers(self):
        with open(
            ANSWER_FILE,
            "w",
            encoding="utf-8",
        ) as file:
            json.dump(
                self.answers,
                file,
                ensure_ascii=False,
                indent=1,
            )

    def _stored_key(self, cid):
        raw = self.answers.get(
            str(cid),
            {},
        )

        result = {}

        for question_id, value in raw.items():
            try:
                result[int(question_id)] = (
                    value[0],
                    value[1],
                )
            except Exception:
                continue

        return result

    def _save_key(
        self,
        cid,
        key,
    ):
        if not key:
            return

        merged = self.answers.get(
            str(cid),
            {},
        )

        merged.update(
            {
                str(question_id): [
                    kind,
                    value,
                ]
                for question_id, (
                    kind,
                    value,
                ) in key.items()
            }
        )

        self.answers[str(cid)] = merged

        self._save_answers()

    def _bank_covers(self, chapter):
        question_count = chapter.get(
            "question_count",
            0,
        )

        return (
            bool(question_count)
            and len(
                self.answers.get(
                    str(chapter["id"]),
                    {},
                )
            ) >= question_count
        )

    def _harvest_chapter(self, cid):
        key = {}

        paths = [
            (
                f"/api/study/students/"
                f"chapters/{cid}/review/result"
            ),
            (
                f"/api/study/students/"
                f"chapters/{cid}/test/result"
            ),
        ]

        for path in paths:

            data = self.api_get_json(
                path,
                None,
            )

            if not isinstance(
                data,
                dict,
            ):
                continue

            if isinstance(
                data.get("result"),
                dict,
            ):
                data = data["result"]

            key.update(
                self._extract_key(
                    data
                )
            )

        if key:
            self._save_key(
                cid,
                key,
            )

        return len(key)

    def harvest_course(self):
        section_id = (
            self.resolve_section_id()
        )

        section = (
            self.api_get_json(
                f"/api/study/sections/"
                f"{section_id}",
                {},
            )
            or {}
        )

        progress = (
            self.api_get_json(
                f"/api/study/students/"
                f"sections/{section_id}/chapters",
                [],
            )
            or []
        )

        progress_map = {
            item.get("chapter_id"): item
            for item in progress
        }

        found = 0

        for chapter in section.get(
            "chapters",
            [],
        ):

            if self._bank_covers(
                chapter
            ):
                continue

            chapter_progress = (
                progress_map.get(
                    chapter["id"],
                    {},
                )
                or {}
            )

            if (
                chapter_progress.get(
                    "best_correct_count",
                    0,
                )
                <= 0
            ):
                continue

            found += (
                self._harvest_chapter(
                    chapter["id"]
                )
            )

        print(
            f"🗄️ بنك الإجابات: تم تحديث "
            f"{found} إجابة.",
            flush=True,
        )

    # ========================================================
    # ANSWERING
    # ========================================================

    def _answer_q(
        self,
        base,
        qid,
        kind,
        payload,
    ):
        return self._req(
            "PUT",
            f"/api/study/students/"
            f"{base}/{qid}/answer/{kind}",
            payload,
        )

    def _submit_attempt(
        self,
        cid,
        questions,
        base,
        result_path,
        key,
    ):
        self._start_test(cid)

        for item in questions:

            if stop_requested():
                raise RuntimeError(
                    "تم إيقاف التشغيل بواسطة المستخدم"
                )

            question = item["question"]

            qid = question["id"]

            if item.get("choices"):

                default_choice = (
                    item["choices"][0]["id"]
                )

                value = key.get(
                    qid,
                    (
                        "choice",
                        default_choice,
                    ),
                )[1]

                self._answer_q(
                    base,
                    qid,
                    "choice",
                    {
                        "choice_id": value
                    },
                )

            else:

                value = key.get(
                    qid,
                    (
                        "description",
                        "print(1)",
                    ),
                )[1]

                self._answer_q(
                    base,
                    qid,
                    "description",
                    {
                        "answer_code": value
                    },
                )

        result = (
            self.api_get_json(
                result_path,
                {},
            )
            or {}
        )

        if isinstance(
            result.get("result"),
            dict,
        ):
            result = result["result"]

        return result

    def solve_test(
        self,
        cid,
        test_type="review",
    ):
        questions = (
            self.api_get_json(
                f"/api/study/chapters/"
                f"{cid}/test",
                [],
            )
            or []
        )

        if not questions:
            return {
                "ok": False,
                "reason": "لا توجد أسئلة",
            }

        base = self._answer_base(
            test_type
        )

        result_path = self._result_path(
            cid,
            test_type,
        )

        total = len(questions)

        key = self._stored_key(
            cid
        )

        cached_complete = all(
            item["question"]["id"] in key
            for item in questions
        )

        result = self._submit_attempt(
            cid,
            questions,
            base,
            result_path,
            key,
        )

        last_correct = result.get(
            "correct_count",
            0,
        )

        key.update(
            self._extract_key(
                result
            )
        )

        self._save_key(
            cid,
            key,
        )

        if cached_complete:
            if last_correct >= total:
                print(
                    f"      💎 محاولة أولى كاملة: "
                    f"{last_correct}/{total}",
                    flush=True,
                )
            else:
                print(
                    f"      ⚠️ البنك غير مطابق — "
                    f"محاولة 1: "
                    f"{last_correct}/{total}",
                    flush=True,
                )
        else:
            print(
                f"      🔁 محاولة 1: "
                f"{last_correct}/{total}",
                flush=True,
            )

        attempt = 1

        while (
            last_correct < total
            and attempt < 3
        ):

            if stop_requested():
                raise RuntimeError(
                    "تم إيقاف التشغيل بواسطة المستخدم"
                )

            attempt += 1

            time.sleep(0.3)

            result = self._submit_attempt(
                cid,
                questions,
                base,
                result_path,
                key,
            )

            last_correct = result.get(
                "correct_count",
                0,
            )

            key.update(
                self._extract_key(
                    result
                )
            )

            self._save_key(
                cid,
                key,
            )

            print(
                f"      🔁 محاولة {attempt}: "
                f"{last_correct}/{total}",
                flush=True,
            )

        return {
            "ok": True,
            "correct": last_correct,
            "total": total,
            "perfect": (
                last_correct >= total
            ),
        }

    # ========================================================
    # COURSE SOLVER
    # ========================================================

    def solve_course(self):
        section_id = (
            self.resolve_section_id()
        )

        section = (
            self.api_get_json(
                f"/api/study/sections/"
                f"{section_id}",
                {},
            )
            or {}
        )

        chapters = section.get(
            "chapters",
            [],
        )

        progress = (
            self.api_get_json(
                f"/api/study/students/"
                f"sections/{section_id}/chapters",
                [],
            )
            or []
        )

        progress_map = {
            item.get("chapter_id"): item
            for item in progress
        }

        print(
            f"📚 القسم الحالي: {section_id} "
            f"— عدد الفصول: "
            f"{len(chapters)}\n",
            flush=True,
        )

        todo = [
            chapter
            for chapter in chapters
            if not (
                chapter.get(
                    "question_count"
                )
                and progress_map.get(
                    chapter["id"],
                    {},
                ).get(
                    "best_correct_count",
                    0,
                )
                >= chapter.get(
                    "question_count"
                )
            )
        ]

        detail_map = {}
        lecture_map = {}

        if todo:

            details = self.fetch_many(
                [
                    {
                        "method": "GET",
                        "path": (
                            f"/api/study/chapters/"
                            f"{chapter['id']}"
                        ),
                    }
                    for chapter in todo
                ]
            )

            lecture_progress = (
                self.fetch_many(
                    [
                        {
                            "method": "GET",
                            "path": (
                                f"/api/study/students/"
                                f"chapters/"
                                f"{chapter['id']}/lectures"
                            ),
                        }
                        for chapter in todo
                    ]
                )
            )

            for index, chapter in enumerate(
                todo
            ):
                detail_map[
                    chapter["id"]
                ] = (
                    details[index] or {}
                ).get(
                    "data"
                ) or None

                lecture_map[
                    chapter["id"]
                ] = (
                    lecture_progress[index]
                    or {}
                ).get(
                    "data"
                ) or None

        solved = []

        total_chapters = len(
            chapters
        )

        emit_progress(
            self.current_course,
            0,
            total_chapters,
            "",
        )

        for index, chapter in enumerate(
            chapters
        ):

            if stop_requested():
                raise RuntimeError(
                    "تم إيقاف التشغيل بواسطة المستخدم"
                )

            cid = chapter["id"]

            name = chapter.get(
                "name",
                "",
            )

            question_count = chapter.get(
                "question_count",
                0,
            )

            test_type = chapter.get(
                "test_type",
                "review",
            )

            emit_progress(
                self.current_course,
                index,
                total_chapters,
                name,
            )

            print(
                f"▶️ الفصل "
                f"{chapter.get('seq')}: "
                f"{name} ({cid}) — "
                f"أسئلة: "
                f"{question_count} "
                f"[{test_type}]",
                flush=True,
            )

            chapter_progress = (
                progress_map.get(
                    cid,
                    {},
                )
                or {}
            )

            if (
                question_count
                and chapter_progress.get(
                    "best_correct_count",
                    0,
                )
                >= question_count
            ):
                print(
                    "   ✅ مُكتمل بالفعل — تخطّي",
                    flush=True,
                )

                solved.append(
                    (
                        name,
                        question_count,
                        question_count,
                    )
                )

                print(
                    "",
                    flush=True,
                )

                continue

            if (
                not self._bank_covers(
                    chapter
                )
                and chapter_progress.get(
                    "best_correct_count",
                    0,
                )
                > 0
            ):
                self._harvest_chapter(
                    cid
                )

            self.complete_chapter_lectures(
                cid,
                detail_map.get(cid),
                lecture_map.get(cid),
            )

            if question_count:

                result = self.solve_test(
                    cid,
                    test_type,
                )

                if result.get("ok"):

                    mark = (
                        "💎"
                        if result["perfect"]
                        else "✔️"
                    )

                    print(
                        f"   {mark} الاختبار: "
                        f"{result['correct']}/"
                        f"{result['total']}",
                        flush=True,
                    )

                    solved.append(
                        (
                            name,
                            result["correct"],
                            result["total"],
                        )
                    )

                else:

                    print(
                        f"   ⏭️ تخطّي الاختبار: "
                        f"{result.get('reason')}",
                        flush=True,
                    )

            else:

                print(
                    "   ℹ️ لا يوجد اختبار لهذا الفصل",
                    flush=True,
                )

            print(
                "",
                flush=True,
            )

        emit_progress(
            self.current_course,
            total_chapters,
            total_chapters,
            "تم",
        )

        return solved

    # ========================================================
    # MAIN
    # ========================================================

    def run(
        self,
        student_id=None,
        password=None,
        courses=None,
        close_pause=0,
    ):
        if courses:
            self.courses = courses

        self.start()

        try:

            self.login(
                student_id,
                password,
            )

            for course_name in self.courses:

                if stop_requested():
                    raise RuntimeError(
                        "تم إيقاف التشغيل بواسطة المستخدم"
                    )

                print(
                    "\n" + "=" * 60,
                    flush=True,
                )

                self.enter_course(
                    course_name
                )

                self.current_course = (
                    course_name
                )

                solved = (
                    self.solve_course()
                )

                perfect = sum(
                    1
                    for _, correct, total
                    in solved
                    if total
                    and correct == total
                )

                print(
                    "=" * 60,
                    flush=True,
                )

                print(
                    f"✨ اكتمل مسار "
                    f"{course_name}! "
                    f"الفصول المنجزة: "
                    f"{len(solved)} "
                    f"(كاملة: {perfect})",
                    flush=True,
                )

                print(
                    "=" * 60,
                    flush=True,
                )

            return True

        finally:

            if (
                close_pause
                and close_pause > 0
            ):
                print(
                    f"\n🖐️ سيتم إغلاق المتصفح "
                    f"خلال {close_pause} ثوانٍ...",
                    flush=True,
                )

                time.sleep(
                    close_pause
                )

            if self.browser is not None:
                try:
                    self.browser.close()
                except Exception:
                    pass

            if self.playwright is not None:
                try:
                    self.playwright.stop()
                except Exception:
                    pass


# ============================================================
# LOCAL RUN
# ============================================================

if __name__ == "__main__":
    QureoSolver(
        headless=False
    ).run()
