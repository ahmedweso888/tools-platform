import json
import os
import re
import sys
import time
from playwright.sync_api import sync_playwright

if sys.stdout.encoding != 'utf-8':
    try:
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')
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

# خطّافات اختيارية تستخدمها الواجهة: التقدّم + طلب الإيقاف
PROGRESS = None      # دالة(course, done, total, label)
SHOULD_STOP = None   # دالة() -> bool


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
    def __init__(self, headless=False, courses=None):
        self.headless = headless
        self.courses = courses or COURSES
        self.playwright = None
        self.browser = None
        self.context = None
        self.page = None

    def start(self):
        print("🚀 جاري تشغيل المتصفح في الخلفية...", flush=True)
        self.playwright = sync_playwright().start()

        try:
            self.browser = self.playwright.chromium.launch(
                headless=True
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
            viewport={"width": 1280, "height": 800}
        )
        self.page = self.context.new_page()

    def login(self, student_id=None, password=None):
        """تسجيل الدخول سواء ظهرت صفحة اختيار البوابة أو نموذج الدخول مباشرة."""
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

        self.page.goto(
            PORTAL_URL,
            wait_until="domcontentloaded",
        )

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

        learning_button = self.page.locator(
            "button.portal-selection-button.portal-selection-button-secondary"
        )

        student_field = self.page.locator(
            "#student_id"
        )

        try:
            # ندي الصفحة وقت للهيدريشن/JavaScript
            self.page.wait_for_timeout(1500)

            button_count = learning_button.count()

            print(
                f"🔎 عدد أزرار Learning Login في DOM: "
                f"{button_count}",
                flush=True,
            )

            # ----------------------------------------------------------
            # الحالة الأولى:
            # زر Learning Login موجود في الصفحة
            # ----------------------------------------------------------
            if button_count > 0:
                try:
                    print(
                        f"🔘 نص الزر: "
                        f"{learning_button.first.inner_text().strip()}",
                        flush=True,
                    )
                except Exception:
                    pass

                try:
                    # force=True لأن الزر قد يكون موجودًا في DOM
                    # لكن Playwright لا يعتبره visible أثناء الانتقال.
                    learning_button.first.click(
                        force=True,
                        timeout=10000,
                    )
                except Exception as button_error:
                    print(
                        f"⚠️ الضغط العادي/القسري على زر "
                        f"Learning Login لم ينجح: "
                        f"{button_error}",
                        flush=True,
                    )

                print(
                    "✅ تم الضغط على Go to Learning Login.",
                    flush=True,
                )

            # ----------------------------------------------------------
            # الحالة الثانية:
            # الزر غير موجود — يمكن أن يكون نموذج الدخول مفتوحًا
            # مباشرة على Railway.
            # ----------------------------------------------------------
            else:
                print(
                    "ℹ️ زر Learning Login غير موجود — "
                    "نفترض أن نموذج تسجيل الدخول مفتوح مباشرة.",
                    flush=True,
                )

            # في الحالتين ننتظر نموذج الدخول.
            student_field.wait_for(
                state="visible",
                timeout=30000,
            )

        except Exception as e:
            # تشخيص فعلي لما تعرضه الصفحة على Railway
            try:
                body_text = self.page.locator(
                    "body"
                ).inner_text()

                print(
                    f"📄 BODY TEXT:\n{body_text[:4000]}",
                    flush=True,
                )
            except Exception:
                pass

            raise RuntimeError(
                "لم يتم الوصول إلى نموذج تسجيل الدخول في Qureo. "
                "لم يظهر زر Learning Login ولم يظهر #student_id. "
                f"URL={self.page.url} | "
                f"TITLE={self.page.title()}"
            ) from e

        print(
            "📝 نموذج تسجيل الدخول جاهز، جاري إدخال البيانات...",
            flush=True,
        )

        self.page.fill(
            "#student_id",
            student_id,
        )

        self.page.fill(
            "#password",
            password,
        )

        self.page.locator(
            "button.login-button"
        ).first.click()

        print(
            "🔐 تم إرسال بيانات تسجيل الدخول.",
            flush=True,
        )

        # الموقع قد لا يغيّر الرابط بعد الدخول،
        # لذلك نتحقق من اختفاء نموذج تسجيل الدخول.
        try:
            self.page.wait_for_selector(
                "#student_id",
                state="detached",
                timeout=30000,
            )
        except Exception:
            raise RuntimeError(
                "فشل تسجيل الدخول — "
                "تأكد من اسم المستخدم وكلمة المرور."
            )

        time.sleep(0.4)

        print(
            "✅ تم تسجيل الدخول.",
            flush=True,
        )

    def enter_course(self, name):
        """اختيار مسار معيّن من صفحة البوابة."""
        print(
            f"📥 جاري الدخول إلى مسار {name}...",
            flush=True,
        )

        self.page.goto(
            PORTAL_HOME,
            wait_until="domcontentloaded",
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
            f"✅ تم الدخول إلى مسار {name}: {self.page.url}",
            flush=True,
        )

    # -------------------------------------------------------------------- api
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
        r = self._req("GET", path)

        if r.status != 200:
            return default

        try:
            return r.json()
        except Exception:
            return default

    # إرسال عدة طلبات متوازية من داخل الصفحة
    _FETCH_JS = """
    async (reqs) => {
        const out = new Array(reqs.length);

        await Promise.all(
            reqs.map(async (r, i) => {
                try {
                    const opts = {
                        method: r.method,
                        credentials: 'include',
                        headers: {}
                    };

                    if (r.body !== null && r.body !== undefined) {
                        opts.headers['Content-Type'] = 'application/json';
                        opts.body = JSON.stringify(r.body);
                    }

                    const res = await fetch(r.path, opts);

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
        """يرسل قائمة طلبات متوازية ويعيد النتائج بنفس الترتيب."""
        if not reqs:
            return []

        return self.page.evaluate(
            self._FETCH_JS,
            reqs,
        )

    # -------------------------------------------------------------- discovery
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

        basic = course.get("basic_section") or {}

        return basic.get("id")

    def resolve_section_id(self):
        deadline = time.time() + 120

        while time.time() < deadline:
            sid = self._section_from_course()

            if sid:
                return sid

            m = re.search(
                r"/section/(\d+)",
                self.page.url,
            )

            if m:
                return int(m.group(1))

            m = re.search(
                r"/chapter/(\d+)",
                self.page.url,
            )

            if m:
                data = self.api_get_json(
                    f"/api/study/chapters/{m.group(1)}"
                )

                if data and data.get("section"):
                    return data["section"]["id"]

            time.sleep(1)

        raise RuntimeError(
            "تعذّر تحديد القسم الحالي."
        )

    # --------------------------------------------------------------- lectures
    def complete_lecture(self, lid):
        self._req(
            "PUT",
            f"/api/study/students/lectures/{lid}",
        )

        r = self._req(
            "PUT",
            f"/api/study/students/lectures/{lid}/complete",
        )

        return r.status == 200

    def complete_chapter_lectures(
        self,
        cid,
        chapter=None,
        progress=None,
    ):
        if progress is None:
            progress = self.api_get_json(
                f"/api/study/students/chapters/{cid}/lectures",
                [],
            ) or []

        if chapter is None:
            chapter = self.api_get_json(
                f"/api/study/chapters/{cid}",
                {},
            ) or {}

        done = {
            p.get("lecture_id")
            for p in progress
            if p.get("completed_at")
        }

        todo = [
            lec
            for lec in chapter.get("lectures", [])
            if lec["id"] not in done
        ]

        if not todo:
            return

        for lec in todo:
            if stop_requested():
                raise RuntimeError(
                    "تم إيقاف التشغيل بواسطة المستخدم"
                )

            self._req(
                "PUT",
                f"/api/study/students/lectures/{lec['id']}",
                {},
            )

            r = self._req(
                "PUT",
                f"/api/study/students/lectures/{lec['id']}/complete",
                {},
            )

            if r.status == 200:
                print(
                    f"   📗 محاضرة {lec.get('seq')}: "
                    f"{lec.get('title', '')} — تم",
                    flush=True,
                )
            else:
                print(
                    f"   ⚠️ تعذّر إكمال المحاضرة "
                    f"{lec['id']} ({r.status})",
                    flush=True,
                )

    # ------------------------------------------------------------------ tests
    def _start_test(self, cid):
        return self._req(
            "PUT",
            f"/api/study/students/chapters/{cid}/test",
        ).status

    def _result_path(self, cid, test_type):
        if test_type == "test":
            return (
                f"/api/study/students/chapters/"
                f"{cid}/test/result"
            )

        return (
            f"/api/study/students/chapters/"
            f"{cid}/review/result"
        )

    def _answer_base(self, test_type):
        return (
            "test-questions"
            if test_type == "test"
            else "review-questions"
        )

    @staticmethod
    def _extract_key(result):
        key = {}

        for cr in (
            result or {}
        ).get("choice_results", []) or []:
            qid = cr.get("question_id")

            correct = [
                c["choice"]["id"]
                for c in (cr.get("choices") or [])
                if c.get("correct")
            ]

            if qid and correct:
                key[qid] = (
                    "choice",
                    correct[0],
                )

        for dr in (
            result or {}
        ).get("description_results", []) or []:
            qid = dr.get("question_id")

            if (
                qid
                and dr.get("model_answer") is not None
            ):
                key[qid] = (
                    "description",
                    dr["model_answer"],
                )

        return key

    # ------------------------------------------------------------ answer bank
    def _load_answers(self):
        try:
            with open(
                ANSWER_FILE,
                encoding="utf-8",
            ) as f:
                return json.load(f)
        except Exception:
            return {}

    def _save_answers(self):
        with open(
            ANSWER_FILE,
            "w",
            encoding="utf-8",
        ) as f:
            json.dump(
                self.answers,
                f,
                ensure_ascii=False,
                indent=1,
            )

    def _stored_key(self, cid):
        """الإجابات المحفوظة لفصل معيّن بصيغة {qid: (kind, value)}."""
        raw = self.answers.get(
            str(cid),
            {},
        )

        return {
            int(q): (
                v[0],
                v[1],
            )
            for q, v in raw.items()
        }

    def _save_key(self, cid, key):
        if not key:
            return

        merged = self.answers.get(
            str(cid),
            {},
        )

        merged.update(
            {
                str(q): [
                    k,
                    v,
                ]
                for q, (k, v) in key.items()
            }
        )

        self.answers[str(cid)] = merged

        self._save_answers()

    def _bank_covers(self, ch):
        """هل بنك الإجابات يغطّي كل أسئلة الفصل؟"""
        qc = ch.get(
            "question_count",
            0,
        )

        return (
            bool(qc)
            and len(
                self.answers.get(
                    str(ch["id"]),
                    {},
                )
            ) >= qc
        )

    def _harvest_chapter(self, cid):
        """يقرأ نتيجة محاولة سابقة لفصل واحد ويحدّث البنك."""
        key = {}

        for path in (
            f"/api/study/students/chapters/{cid}/review/result",
            f"/api/study/students/chapters/{cid}/test/result",
        ):
            data = self.api_get_json(
                path,
                None,
            )

            if not isinstance(data, dict):
                continue

            if isinstance(
                data.get("result"),
                dict,
            ):
                data = data["result"]

            key.update(
                self._extract_key(data)
            )

        if key:
            self._save_key(
                cid,
                key,
            )

        return len(key)

    def harvest_course(self):
        """يحدّث البنك من نتائج المحاولات السابقة."""
        section_id = self.resolve_section_id()

        section = self.api_get_json(
            f"/api/study/sections/{section_id}",
            {},
        ) or {}

        progress = self.api_get_json(
            f"/api/study/students/sections/{section_id}/chapters",
            [],
        ) or []

        pmap = {
            p.get("chapter_id"): p
            for p in progress
        }

        found = 0

        for ch in section.get(
            "chapters",
            [],
        ):
            if self._bank_covers(ch):
                continue

            if (
                pmap.get(
                    ch["id"],
                    {},
                ) or {}
            ).get(
                "best_correct_count",
                0,
            ) <= 0:
                continue

            found += self._harvest_chapter(
                ch["id"]
            )

        print(
            f"🗄️ بنك الإجابات: تم تحديث {found} إجابة.",
            flush=True,
        )

    def _answer_q(
        self,
        base,
        qid,
        kind,
        payload,
    ):
        return self._req(
            "PUT",
            f"/api/study/students/{base}/{qid}/answer/{kind}",
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
        """يبدأ محاولة جديدة ويرسل الإجابات بالترتيب."""
        self._start_test(cid)

        for item in questions:
            qid = item["question"]["id"]

            if item.get("choices"):
                val = key.get(
                    qid,
                    (
                        "choice",
                        item["choices"][0]["id"],
                    ),
                )[1]

                self._answer_q(
                    base,
                    qid,
                    "choice",
                    {
                        "choice_id": val
                    },
                )
            else:
                val = key.get(
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
                        "answer_code": val
                    },
                )

        result = self.api_get_json(
            result_path,
            {},
        ) or {}

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
        questions = self.api_get_json(
            f"/api/study/chapters/{cid}/test",
            [],
        ) or []

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

        key = self._stored_key(cid)

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
            self._extract_key(result)
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
                    f"محاولة 1: {last_correct}/{total}",
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
                self._extract_key(result)
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
            "perfect": last_correct >= total,
        }

    # ----------------------------------------------------------------- course
    def solve_course(self):
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
            f"/api/study/students/sections/{section_id}/chapters",
            [],
        ) or []

        pmap = {
            p.get("chapter_id"): p
            for p in progress
        }

        print(
            f"📚 القسم الحالي: {section_id} — "
            f"عدد الفصول: {len(chapters)}\n",
            flush=True,
        )

        todo = [
            ch
            for ch in chapters
            if not (
                ch.get("question_count")
                and pmap.get(
                    ch["id"],
                    {},
                ).get(
                    "best_correct_count",
                    0,
                ) >= ch.get(
                    "question_count"
                )
            )
        ]

        detail_map, lec_map = {}, {}

        if todo:
            details = self.fetch_many(
                [
                    {
                        "method": "GET",
                        "path": (
                            f"/api/study/chapters/"
                            f"{ch['id']}"
                        ),
                    }
                    for ch in todo
                ]
            )

            lec_prog = self.fetch_many(
                [
                    {
                        "method": "GET",
                        "path": (
                            f"/api/study/students/chapters/"
                            f"{ch['id']}/lectures"
                        ),
                    }
                    for ch in todo
                ]
            )

            for i, ch in enumerate(todo):
                detail_map[ch["id"]] = (
                    details[i] or {}
                ).get("data") or None

                lec_map[ch["id"]] = (
                    lec_prog[i] or {}
                ).get("data") or None

        solved = []

        total_ch = len(chapters)

        emit_progress(
            self.current_course,
            0,
            total_ch,
            "",
        )

        for i, ch in enumerate(chapters):
            if stop_requested():
                raise RuntimeError(
                    "تم إيقاف التشغيل بواسطة المستخدم"
                )

            cid = ch["id"]
            name = ch.get("name", "")
            qcount = ch.get(
                "question_count",
                0,
            )
            test_type = ch.get(
                "test_type",
                "review",
            )

            emit_progress(
                self.current_course,
                i,
                total_ch,
                name,
            )

            print(
                f"▶️ الفصل {ch.get('seq')}: "
                f"{name} ({cid}) — أسئلة: "
                f"{qcount} [{test_type}]",
                flush=True,
            )

            if (
                qcount
                and pmap.get(
                    cid,
                    {},
                ).get(
                    "best_correct_count",
                    0,
                ) >= qcount
            ):
                print(
                    "   ✅ مُكتمل بالفعل — تخطّي",
                    flush=True,
                )

                solved.append(
                    (
                        name,
                        qcount,
                        qcount,
                    )
                )

                print(
                    "",
                    flush=True,
                )

                continue

            if (
                not self._bank_covers(ch)
                and pmap.get(
                    cid,
                    {},
                ).get(
                    "best_correct_count",
                    0,
                ) > 0
            ):
                self._harvest_chapter(cid)

            self.complete_chapter_lectures(
                cid,
                detail_map.get(cid),
                lec_map.get(cid),
            )

            if qcount:
                res = self.solve_test(
                    cid,
                    test_type,
                )

                if res.get("ok"):
                    mark = (
                        "💎"
                        if res["perfect"]
                        else "✔️"
                    )

                    print(
                        f"   {mark} الاختبار: "
                        f"{res['correct']}/{res['total']}",
                        flush=True,
                    )

                    solved.append(
                        (
                            name,
                            res["correct"],
                            res["total"],
                        )
                    )
                else:
                    print(
                        f"   ⏭️ تخطّي الاختبار: "
                        f"{res.get('reason')}",
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
            total_ch,
            total_ch,
            "تم",
        )

        return solved

    # ------------------------------------------------------------------ main
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
                print(
                    "\n" + "=" * 60,
                    flush=True,
                )

                self.enter_course(name)

                self.current_course = name

                solved = self.solve_course()

                perfect = sum(
                    1
                    for _, c, t in solved
                    if t and c == t
                )

                print(
                    "=" * 60,
                    flush=True,
                )

                print(
                    f"✨ اكتمل مسار {name}! "
                    f"الفصول المنجزة: {len(solved)} "
                    f"(كاملة: {perfect})",
                    flush=True,
                )

                print(
                    "=" * 60,
                    flush=True,
                )

        finally:
            if close_pause:
                print(
                    f"\n🖐️ سيتم إغلاق المتصفح خلال "
                    f"{close_pause} ثوانٍ...",
                    flush=True,
                )

                time.sleep(close_pause)

            self.browser.close()
            self.playwright.stop()


if __name__ == "__main__":
    QureoSolver(
        headless=True
    ).run()