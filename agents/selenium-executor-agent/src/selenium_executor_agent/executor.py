import time

from selenium import webdriver
from selenium.common.exceptions import NoSuchElementException, WebDriverException
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import Select, WebDriverWait

from selenium_executor_agent.config import get_settings


def _build_driver(grid_url: str) -> webdriver.Remote:
    options = Options()
    options.add_argument("--headless=new")
    # Classic `goog:loggingPrefs` + driver.get_log("browser") was removed from
    # the Selenium 4 client entirely (AttributeError, not just empty results)
    # — this project's console_logs field was silently empty on every job
    # until switching to BiDi console message events instead.
    options.web_socket_url = True
    return webdriver.Remote(command_executor=grid_url, options=options)


def _find_element(driver: webdriver.Remote, selector: str, wait_seconds: float):
    return WebDriverWait(driver, wait_seconds).until(
        EC.presence_of_element_located((By.CSS_SELECTOR, selector))
    )


def _run_step(driver: webdriver.Remote, step: dict, wait_seconds: float, default_wait_ms: float) -> None:
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


def _empty_evidence(url: str) -> dict:
    return {
        "screenshots": [],
        "dom_diffs": [],
        "console_logs": [],
        "network_log_path": None,
        "url_before": url,
        "url_after": url,
        "cookies_before": {},
        "cookies_after": {},
        "deterministic_signals": {},
    }


def execute_scenario(job_id: str, target_url: str, scenario: dict) -> dict:
    settings = get_settings()
    scenario_dir = settings.screenshot_root / job_id / "execution" / scenario["scenario_id"]

    try:
        driver = _build_driver(settings.selenium_grid_url)
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

    try:
        driver.get(target_url)
        url_before = driver.current_url
        cookies_before = {cookie["name"]: cookie["value"] for cookie in driver.get_cookies()}
        screenshots.append(_screenshot(driver, scenario_dir / "before.png"))

        for index, step in enumerate(scenario["steps"]):
            try:
                _run_step(driver, step, settings.element_wait_seconds, settings.default_wait_ms)
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
        "dom_diffs": [],
        "console_logs": console_logs,
        "network_log_path": None,
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
    }

    return {
        "scenario_id": scenario["scenario_id"],
        "status": status,
        "evidence": evidence,
        "error_message": error_message,
    }
