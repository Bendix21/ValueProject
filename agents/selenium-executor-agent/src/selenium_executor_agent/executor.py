import difflib
import logging
import time

from selenium import webdriver
from selenium.common.exceptions import NoSuchElementException, TimeoutException, WebDriverException
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import Select, WebDriverWait

from selenium_executor_agent.config import get_settings

logger = logging.getLogger(__name__)

COOKIE_ALLOWED_KEYS = {"name", "value", "path", "domain", "secure", "httpOnly", "expiry", "sameSite"}

CHATBOT_ACTIONS = {
    "send_message",
    "wait_for_response",
    "assert_response",
    "stop_generation",
    "regenerate",
}


def _is_chatbot_scenario(scenario: dict) -> bool:
    return any(step["action"] in CHATBOT_ACTIONS for step in scenario["steps"])


def _build_driver(grid_url: str, headless: bool) -> webdriver.Remote:
    options = Options()
    if headless:
        options.add_argument("--headless=new")
    else:
        # Headed sessions are for chatbot targets where a human needs to
        # clear an anti-bot challenge (Cloudflare Turnstile, hCaptcha) via
        # noVNC. Those don't just check the click - they continuously score
        # the browser's automation fingerprint, and Selenium's defaults leave
        # obvious markers (navigator.webdriver, an "automation controlled"
        # infobar) that keep even a real human's click from passing. This
        # removes the most common ones; it is not guaranteed against more
        # sophisticated fingerprinting, and is not meant to automate past the
        # challenge - a human still has to actually clear it.
        options.add_argument("--disable-blink-features=AutomationControlled")
        options.add_experimental_option("excludeSwitches", ["enable-automation"])
        options.add_experimental_option("useAutomationExtension", False)
    # Classic `goog:loggingPrefs` + driver.get_log("browser") was removed from
    # the Selenium 4 client entirely (AttributeError, not just empty results)
    # — this project's console_logs field was silently empty on every job
    # until switching to BiDi console message events instead.
    options.web_socket_url = True
    driver = webdriver.Remote(command_executor=grid_url, options=options)
    if not headless:
        try:
            driver.execute_cdp_cmd(
                "Page.addScriptToEvaluateOnNewDocument",
                {
                    "source": (
                        "Object.defineProperty(navigator, 'webdriver', "
                        "{get: () => undefined});"
                    )
                },
            )
        except WebDriverException:
            pass  # best-effort - some grid setups don't expose CDP
    return driver


def _find_element(driver: webdriver.Remote, selector: str, wait_seconds: float):
    return WebDriverWait(driver, wait_seconds).until(
        EC.presence_of_element_located((By.CSS_SELECTOR, selector))
    )


def _find_chat_input_fallback(driver: webdriver.Remote):
    """discovery-agent and the executor open separate Selenium sessions, so a
    selector built from a client-generated id (React's useId() and similar)
    can be valid at discovery time and gone by execution time - observed on
    chatgpt.com, whose composer id was not stable across sessions. When the
    exact selector isn't there, fall back to what a human would do: find the
    biggest visible text box on the page."""
    candidates = driver.find_elements(By.CSS_SELECTOR, "textarea, [contenteditable='true']")
    visible = [el for el in candidates if el.is_displayed()]
    if not visible:
        return None
    return max(visible, key=lambda el: el.size["width"] * el.size["height"])


def _restore_session_cookies(driver: webdriver.Remote, session_cookies: list[dict]) -> None:
    """Best-effort: this is a fresh Selenium session with its own empty
    profile (no cookies survive between discovery's session and any
    scenario's own session), so a chatbot login done once during discovery's
    grace pause would otherwise have to be redone by hand for every single
    scenario. Restoring the cookies captured then avoids that. Individual
    cookies are skipped rather than aborting the whole restore - a stale
    `expiry` type or a domain mismatch for one cookie shouldn't cost the rest."""
    restored = 0
    for cookie in session_cookies:
        clean = {k: v for k, v in cookie.items() if k in COOKIE_ALLOWED_KEYS}
        if "expiry" in clean and clean["expiry"] is not None:
            clean["expiry"] = int(clean["expiry"])
        try:
            driver.add_cookie(clean)
            restored += 1
        except WebDriverException:
            continue
    logger.info("executor: restored %d/%d session cookies", restored, len(session_cookies))


def _wait_for_stable_text(
    driver: webdriver.Remote,
    before_text: str,
    timeout_ms: float,
    poll_interval_ms: float,
    stable_cycles: int,
) -> str:
    """Poll the page's visible text until it stops changing (a streaming reply
    finished) or the timeout elapses. There is no reliable selector-based
    signal for "the bot is done typing" across different chatbot UIs, so this
    treats DOM-text stability itself as the completion signal - the same
    text-diff primitive already used for dom_diffs, just polled instead of
    sampled once before/after."""
    deadline = time.monotonic() + timeout_ms / 1000
    last = _dom_text(driver)
    stable_count = 0
    while time.monotonic() < deadline:
        time.sleep(poll_interval_ms / 1000)
        current = _dom_text(driver)
        if current == last:
            stable_count += 1
            if stable_count >= stable_cycles and current != before_text:
                return current
        else:
            stable_count = 0
            last = current
    return last


def _extract_new_text(before: str, after: str) -> str:
    diffs = _dom_diff(before, after, limit=200)
    added = [d["text"] for d in diffs if d["op"] == "added"]
    return "\n".join(added)


def _run_step(
    driver: webdriver.Remote,
    step: dict,
    wait_seconds: float,
    default_wait_ms: float,
    chat_ctx: dict | None,
    settings,
) -> None:
    action = step["action"]
    target_selector = step.get("target_selector")
    value = step.get("value")

    if action == "wait":
        duration_ms = float(value) if value else default_wait_ms
        time.sleep(duration_ms / 1000)
        return

    if action == "scroll":
        if target_selector:
            element = _find_element(driver, target_selector, wait_seconds)
            driver.execute_script("arguments[0].scrollIntoView();", element)
        else:
            driver.execute_script("window.scrollBy(0, window.innerHeight);")
        return

    if action == "send_message":
        try:
            element = _find_element(driver, target_selector, wait_seconds)
        except TimeoutException:
            element = _find_chat_input_fallback(driver)
            if element is None:
                raise
        element.clear()
        element.send_keys(value)
        element.send_keys(Keys.RETURN)
        chat_ctx["conversation_transcript"].append({"role": "user", "text": value})
        chat_ctx["prev_text"] = _dom_text(driver)
        return

    if action == "wait_for_response":
        timeout_ms = float(value) if value else settings.response_timeout_ms
        after_text = _wait_for_stable_text(
            driver,
            chat_ctx["prev_text"],
            timeout_ms,
            settings.response_poll_interval_ms,
            settings.response_stable_cycles,
        )
        response_text = _extract_new_text(chat_ctx["prev_text"], after_text)
        chat_ctx["conversation_transcript"].append({"role": "assistant", "text": response_text})
        chat_ctx["last_response_text"] = response_text
        chat_ctx["prev_text"] = after_text
        return

    if action == "assert_response":
        response_text = chat_ctx.get("last_response_text", "")
        if not response_text.strip():
            raise AssertionError("no response text was captured before the timeout")
        if value and value.lower() not in response_text.lower():
            raise AssertionError(
                f"response does not contain '{value}' (actual: '{response_text[:200]}')"
            )
        return

    if action in ("stop_generation", "regenerate"):
        element = _find_element(driver, target_selector, wait_seconds)
        element.click()
        return

    element = _find_element(driver, target_selector, wait_seconds)

    if action == "click":
        element.click()
    elif action == "type":
        element.clear()
        element.send_keys(value)
    elif action == "select":
        select = Select(element)
        try:
            select.select_by_visible_text(value)
        except NoSuchElementException:
            select.select_by_value(value)
    elif action == "assert":
        if not element.is_displayed():
            raise AssertionError(f"element '{target_selector}' is not displayed")
        if value and value not in element.text:
            raise AssertionError(
                f"element '{target_selector}' text does not contain '{value}' "
                f"(actual: '{element.text}')"
            )
    elif action == "assert_in_viewport":
        rect = driver.execute_script(
            "const r = arguments[0].getBoundingClientRect();"
            "return {top: r.top, bottom: r.bottom, height: window.innerHeight};",
            element,
        )
        in_viewport = rect["bottom"] > 0 and rect["top"] < rect["height"]
        if not in_viewport:
            raise AssertionError(
                f"element '{target_selector}' is not within the viewport after scrolling "
                f"(top={rect['top']}, bottom={rect['bottom']}, viewport height={rect['height']})"
            )


def _screenshot(driver: webdriver.Remote, path) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    driver.save_screenshot(str(path))
    return str(path)


def _register_console_logs(driver: webdriver.Remote) -> list[str]:
    """Must be called before driver.get() so page-load console output is
    captured too. BiDi delivers messages via callback as they happen, so the
    returned list fills in live rather than being polled after the fact."""
    logs: list[str] = []
    driver.script.add_console_message_handler(
        lambda entry: logs.append(f"[{entry.level}] {entry.text}")
    )
    return logs


def _register_network_errors(driver: webdriver.Remote) -> list[str]:
    """Must be called before driver.get(). Uses the passive `response_completed`
    event, not `add_response_handler` — the latter intercepts every response
    and auto-continues it, and was observed to hang the whole BiDi connection
    (`Timed out waiting for response to BiDi command`) rather than just log."""
    errors: list[str] = []

    def _on_response(event) -> None:
        response = event.response or {}
        status = response.get("status")
        if status is not None and status >= 400:
            errors.append(f"{status} {response.get('url', '')}")

    driver.network.add_event_handler("response_completed", _on_response)
    return errors


def _dom_text(driver: webdriver.Remote) -> str:
    try:
        return driver.execute_script("return document.body.innerText") or ""
    except WebDriverException:
        return ""


def _dom_diff(before: str, after: str, limit: int = 50) -> list[dict]:
    """Line-level diff of visible page text, not markup — markup diffs on a
    real site are mostly framework noise (re-rendered attributes, reordered
    wrapper divs) that swamps the signal QA actually cares about: text that
    appeared or disappeared (an error banner, a newly revealed element)."""
    before_lines = [line.strip() for line in before.splitlines() if line.strip()]
    after_lines = [line.strip() for line in after.splitlines() if line.strip()]
    diffs: list[dict] = []
    for line in difflib.ndiff(before_lines, after_lines):
        if line.startswith("+ "):
            diffs.append({"op": "added", "text": line[2:]})
        elif line.startswith("- "):
            diffs.append({"op": "removed", "text": line[2:]})
        if len(diffs) >= limit:
            break
    return diffs


def _empty_evidence(url: str) -> dict:
    return {
        "screenshots": [],
        "dom_diffs": [],
        "console_logs": [],
        "network_errors": [],
        "url_before": url,
        "url_after": url,
        "cookies_before": {},
        "cookies_after": {},
        "deterministic_signals": {},
        "conversation_transcript": [],
    }


def execute_scenario(
    job_id: str, target_url: str, scenario: dict, session_cookies: list[dict] | None = None
) -> dict:
    settings = get_settings()
    session_cookies = session_cookies or []
    scenario_dir = settings.screenshot_root / job_id / "execution" / scenario["scenario_id"]
    is_chatbot = _is_chatbot_scenario(scenario)

    try:
        # Chatbot targets often sit behind an anti-bot challenge (Cloudflare,
        # reCAPTCHA) that no amount of automation can click through - so these
        # sessions run headed, giving a human the chance to solve it via the
        # Selenium Grid's noVNC viewer during the grace pause below.
        driver = _build_driver(settings.selenium_grid_url, headless=not is_chatbot)
    except WebDriverException as exc:
        return {
            "scenario_id": scenario["scenario_id"],
            "status": "error",
            "evidence": _empty_evidence(target_url),
            "error_message": f"could not start Selenium session: {exc}",
        }

    screenshots: list[str] = []
    status = "success"
    error_message = None
    failed_step_index = None
    console_logs = _register_console_logs(driver)
    network_errors = _register_network_errors(driver)

    chat_ctx = {"conversation_transcript": [], "prev_text": "", "last_response_text": ""}

    try:
        if is_chatbot:
            # Match discovery-agent's "desktop" viewport (see VIEWPORTS in
            # selenium_client.py) - the generator prefers selectors found at
            # that size, so the executor must render at the same size or
            # they simply won't exist in the DOM.
            driver.set_window_size(1920, 1080)
        driver.get(target_url)
        if is_chatbot and session_cookies:
            _restore_session_cookies(driver, session_cookies)
            driver.get(target_url)  # reload so the restored cookies actually apply
        if is_chatbot:
            # Give a human time to solve an anti-bot challenge via noVNC
            # before any step assumes the chat UI is actually reachable.
            # Shorter when cookies were restored - normally only a residual
            # JS challenge remains, not a full login.
            grace = (
                settings.chatbot_reauth_grace_seconds
                if session_cookies
                else settings.chatbot_captcha_grace_seconds
            )
            time.sleep(grace)
        url_before = driver.current_url
        cookies_before = {cookie["name"]: cookie["value"] for cookie in driver.get_cookies()}
        dom_text_before = _dom_text(driver)
        chat_ctx["prev_text"] = dom_text_before
        screenshots.append(_screenshot(driver, scenario_dir / "before.png"))

        for index, step in enumerate(scenario["steps"]):
            try:
                _run_step(
                    driver,
                    step,
                    settings.element_wait_seconds,
                    settings.default_wait_ms,
                    chat_ctx,
                    settings,
                )
            except (WebDriverException, AssertionError) as exc:
                status = "failure"
                reason = str(exc).split("Stacktrace:")[0].replace("Message:", "").strip()
                if not reason:
                    selector = step.get("target_selector")
                    reason = f"{type(exc).__name__} (selector: {selector})" if selector else type(exc).__name__
                error_message = f"step {index + 1} ({step['action']}): {reason}"
                failed_step_index = index
                screenshots.append(
                    _screenshot(driver, scenario_dir / f"failure-step-{index + 1}.png")
                )
                break

        url_after = driver.current_url
        cookies_after = {cookie["name"]: cookie["value"] for cookie in driver.get_cookies()}
        dom_diffs = _dom_diff(dom_text_before, _dom_text(driver))
        screenshots.append(_screenshot(driver, scenario_dir / "after.png"))
    except WebDriverException as exc:
        return {
            "scenario_id": scenario["scenario_id"],
            "status": "error",
            "evidence": _empty_evidence(target_url),
            "error_message": f"executor infrastructure error: {exc}",
        }
    finally:
        driver.quit()

    new_cookie_names = [name for name in cookies_after if name not in cookies_before]
    changed_cookie_names = [
        name
        for name in cookies_after
        if name in cookies_before and cookies_before[name] != cookies_after[name]
    ]

    evidence = {
        "screenshots": screenshots,
        "dom_diffs": dom_diffs,
        "console_logs": console_logs,
        "network_errors": network_errors,
        "url_before": url_before,
        "url_after": url_after,
        "cookies_before": cookies_before,
        "cookies_after": cookies_after,
        "deterministic_signals": {
            "url_changed": url_before != url_after,
            "new_cookie_names": new_cookie_names,
            "changed_cookie_names": changed_cookie_names,
            "failed_step_index": failed_step_index,
        },
        "conversation_transcript": chat_ctx["conversation_transcript"],
    }

    return {
        "scenario_id": scenario["scenario_id"],
        "status": status,
        "evidence": evidence,
        "error_message": error_message,
    }
