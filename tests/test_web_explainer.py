"""The page's model call through Firebase AI Logic, read as text.

The browser code has no test runner, so these read `web/` the way test_web_call.py
does. They pin that the Firebase AI Logic call is there and wired to the socket, and
that the page's constants match the server's. They do not run a browser or a model.
"""

from __future__ import annotations

import re
from typing import get_args

from server.config import WEB_DIR
from server.contracts import MAX_REPLY_CHARS, PageAnswer
from tests.test_web_call import function_body, js_constant

APP_JS = (WEB_DIR / "app.js").read_text(encoding="utf-8")
CALL_JS = (WEB_DIR / "call.js").read_text(encoding="utf-8")
EXPLAINER_JS = (WEB_DIR / "explainer.js").read_text(encoding="utf-8")
INDEX_HTML = (WEB_DIR / "index.html").read_text(encoding="utf-8")
VIEW_JS = (WEB_DIR / "view.js").read_text(encoding="utf-8")
SDK_URL = re.compile(r'"https://www\.gstatic\.com/firebasejs/(\d+\.\d+\.\d+)/(firebase-[a-z-]+\.js)"')


def test_the_firebase_sdk_is_loaded_at_one_pinned_version():
    loaded = SDK_URL.findall(EXPLAINER_JS)

    assert sorted(name for _version, name in loaded) == [
        "firebase-ai.js",
        "firebase-app-check.js",
        "firebase-app.js",
    ]
    assert len({version for version, _name in loaded}) == 1
    for constant in ("FIREBASE_APP", "FIREBASE_APP_CHECK", "FIREBASE_AI"):
        assert f"import({constant})" in EXPLAINER_JS  # loaded, not only named


def test_the_model_is_hybrid_on_device_first_with_a_cloud_fallback():
    set_up = function_body(EXPLAINER_JS, "async function setUp()")

    assert "aiSdk.getAI(app, { backend: new aiSdk.GoogleAIBackend() })" in set_up
    assert "aiSdk.getGenerativeModel(ai, {" in set_up
    assert "mode: aiSdk.InferenceMode.PREFER_ON_DEVICE" in set_up
    # Both models get the same instructions and are held to the same answer schema.
    assert "systemInstruction: config.system" in set_up
    assert 'initialPrompts: [{ role: "system", content: [{ type: "text", value: config.system }] }]' in set_up
    assert "responseSchema: config.reply_schema" in set_up
    assert "responseConstraint: config.reply_schema" in set_up
    # Firebase AI Logic needs App Check, and it has to start before the model is made.
    assert set_up.index("startAppCheck(app, checkSdk)") < set_up.index("aiSdk.getAI(")
    assert "sdk.initializeAppCheck(app, {" in function_body(EXPLAINER_JS, "function startAppCheck(app, sdk)")


def test_the_page_asks_the_model_and_never_claims_the_device_unless_the_sdk_says_so():
    ask = function_body(EXPLAINER_JS, "export async function answer(prompt)")

    assert "await ready.model.generateContent(prompt)" in ask
    assert "result.response.inferenceSource === ON_DEVICE ? ON_DEVICE : IN_CLOUD" in ask
    assert ask.count("return NO_ANSWER;") == 3  # no Firebase, an over-long answer, a failed call
    assert js_constant(EXPLAINER_JS, "MAX_REPLY_CHARS") == MAX_REPLY_CHARS


def test_the_pages_words_for_where_the_model_ran_are_the_servers():
    allowed = set(get_args(PageAnswer.model_fields["source"].annotation))

    assert allowed == {"on_device", "in_cloud", "none"}
    assert 'const ON_DEVICE = "on_device";' in EXPLAINER_JS
    assert 'const IN_CLOUD = "in_cloud";' in EXPLAINER_JS
    assert 'const NO_ANSWER = { text: "", source: "none" };' in EXPLAINER_JS


def test_an_explain_request_is_answered_on_the_socket_of_the_call_that_asked():
    handler = APP_JS.split('case "explain":', 1)[1].split("return;", 1)[0]
    assert "onExplain(event)" in handler

    explain = function_body(APP_JS, "async function onExplain(event)")
    # The socket is taken before the model is asked: a late answer cannot reach the next call.
    assert explain.index("callSocket()") < explain.index("await answer(event.prompt)")
    assert 'sendMessage(socket, { type: "explained", id: event.id, text, source })' in explain

    send = function_body(CALL_JS, "export function sendMessage(socket, message)")
    assert "socket !== callSocket()" in send
    assert "socket.send(JSON.stringify(message))" in send


def test_the_on_device_model_is_woken_inside_the_press_that_starts_a_call():
    # Chrome only starts the model's download after a press, so the wake-up cannot wait.
    begin = function_body(APP_JS, "function beginCall()")
    assert "warmExplainer()" in begin

    start = function_body(APP_JS, "async function onStart()")
    assert start.index("beginCall()") < start.index("await startMicCall(")
    assert "onReset: beginCall" in APP_JS  # the demo console's Play is a press too
    assert "await ready.model.initializeDeviceModel()" in function_body(
        EXPLAINER_JS, "export async function warmExplainer()"
    )
    assert "restExplainer()" in function_body(APP_JS, "function endCall(statusKey)")


def test_the_sheet_says_where_the_line_was_written_only_for_an_answer_the_page_gave():
    assert 'explained_on_device: "Written on this device."' in APP_JS
    assert 'explained_in_cloud: "Written by a cloud model."' in APP_JS

    key = function_body(APP_JS, "function sourceKey(event)")
    assert "event.degraded === true" in key and "event.t_s !== pageAnswer.t_s" in key
    assert "pageAnswer = null;" in function_body(APP_JS, "function beginCall()")

    paint = function_body(VIEW_JS, "function paintSource()")
    assert "note.hidden = state.source === null;" in paint
    # Last in the sheet, after the one button: it never pushes the line to say down.
    footer = INDEX_HTML.split('<footer class="sheet__footer">', 1)[1].split("</footer>", 1)[0]
    assert footer.index('id="real-call"') < footer.index('id="explainer-source"')
    assert 'id="explainer-source" hidden' in footer
