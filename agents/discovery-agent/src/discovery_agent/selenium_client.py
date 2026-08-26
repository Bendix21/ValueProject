import time
from urllib.parse import urljoin, urlparse, urlunparse

from selenium import webdriver
from selenium.webdriver.chrome.options import Options

from discovery_agent.config import get_settings

VIEWPORTS = [
    ("desktop", 1920, 1080),
    ("tablet", 768, 1024),
    ("mobile", 375, 812),
]

MAX_SCROLL_STEPS = 20
SCROLL_WAIT_SECONDS = 0.3
MAX_PAGE_HEIGHT = 15000

ELEMENT_QUERY_JS = """
const selectorFor = (el) => {
    if (el.id) return '#' + CSS.escape(el.id);
    const parts = [];
    let node = el;
    while (node && node.nodeType === 1 && node !== document.body) {
        let part = node.tagName.toLowerCase();
        const parent = node.parentElement;
        if (parent) {
            const siblings = Array.from(parent.children).filter(c => c.tagName === node.tagName);
            if (siblings.length > 1) {
                part += ':nth-of-type(' + (siblings.indexOf(node) + 1) + ')';
            }
        }
        parts.unshift(part);
        node = parent;
    }
    return parts.join(' > ');
};

const roleFor = (el) => {
    const role = el.getAttribute('role');
    if (role) return role;
    const tag = el.tagName.toLowerCase();
    if (tag === 'a') return 'link';
    if (tag === 'button') return 'button';
    if (tag === 'input') return (el.getAttribute('type') || 'text') + '_input';
    if (tag === 'select') return 'select';
    if (tag === 'textarea') return 'textbox';
    return tag;
};

const isVisible = (el, rect) => {
    const style = window.getComputedStyle(el);
    if (style.display === 'none' || style.visibility === 'hidden' || parseFloat(style.opacity) === 0) return false;
    return rect.width > 0 && rect.height > 0;
};

const selector = 'a[href], button, input, select, textarea, [role="button"], [role="link"], [role="checkbox"], [role="radio"], [onclick], [tabindex]:not([tabindex="-1"])';
const elements = Array.from(document.querySelectorAll(selector));

return elements.map((el) => {
    const rect = el.getBoundingClientRect();
    return {
        selector: selectorFor(el),
        dom_role: roleFor(el),
        x: Math.round(rect.left + window.scrollX),
        y: Math.round(rect.top + window.scrollY),
        width: Math.round(rect.width),
        height: Math.round(rect.height),
        visible: isVisible(el, rect),
        href: el.tagName === 'A' ? el.href : null,
    };
});
"""

# Detects a bot-challenge / CAPTCHA page so it can be reported as a discovery
# result instead of scraped as if it were the real page. Detection only —
# no attempt is made to solve or bypass what it finds.
CHALLENGE_DETECTION_JS = """
const title = (document.title || '').toLowerCase();
const bodyText = (document.body ? document.body.innerText : '').slice(0, 3000).toLowerCase();
const combined = title + ' ' + bodyText;

const domChecks = [
    ['cloudflare_challenge', '#challenge-running, .cf-browser-verification, #cf-wrapper, [data-cf-challenge], #cf-challenge-stage'],
    ['hcaptcha', 'iframe[src*="hcaptcha.com"], .h-captcha'],
    ['recaptcha', 'iframe[src*="recaptcha"], .g-recaptcha, #recaptcha'],
    ['perimeterx', '#px-captcha, [id*="perimeterx" i], [class*="perimeterx" i]'],
    ['datadome', '[id*="datadome" i], [class*="datadome" i]'],
    ['generic_captcha', '[data-sitekey]'],
];
for (const [reason, selector] of domChecks) {
    if (document.querySelector(selector)) return reason;
}

const textMarkers = [
    ['cloudflare_challenge', ['just a moment', 'checking your browser', 'ddos protection by cloudflare']],
    ['generic_bot_check', ['are you a robot', 'please verify you are a human', 'access denied', 'unusual traffic detected', 'automated queries']],
];
for (const [reason, markers] of textMarkers) {
    if (markers.some((marker) => combined.includes(marker))) return reason;
}

return null;
"""


def _build_driver(grid_url: str) -> webdriver.Remote:
    options = Options()
    options.add_argument("--headless=new")
    return webdriver.Remote(command_executor=grid_url, options=options)


def _scroll_and_collect(driver: webdriver.Remote) -> list[dict]:
    collected: dict[str, dict] = {}
    last_scroll_y = -1
    for _ in range(MAX_SCROLL_STEPS):
        scroll_y = driver.execute_script("return window.scrollY;")
        if scroll_y == last_scroll_y:
            break
        last_scroll_y = scroll_y
        time.sleep(SCROLL_WAIT_SECONDS)
        for element in driver.execute_script(ELEMENT_QUERY_JS):
            collected.setdefault(element["selector"], element)
        driver.execute_script("window.scrollBy(0, window.innerHeight);")
    return list(collected.values())


def _normalize_url(url: str) -> str:
    parsed = urlparse(url)
    return urlunparse((parsed.scheme, parsed.netloc, parsed.path.rstrip("/") or "/", "", "", ""))


def _same_origin_links(raw_elements: list[dict], page_url: str) -> list[str]:
    origin = urlparse(page_url).netloc
    links = []
    for item in raw_elements:
        href = item.get("href")
        if not href:
            continue
        absolute = urljoin(page_url, href)
        parsed = urlparse(absolute)
        if parsed.scheme not in ("http", "https") or parsed.netloc != origin:
            continue
        links.append(_normalize_url(absolute))
    return links


def _capture_page(
    driver: webdriver.Remote, job_id: str, page_url: str, page_index: int, settings
) -> tuple[dict, list[str]]:
    viewports = []
    discovered_links: list[str] = []
    block_reason: str | None = None

    for name, width, height in VIEWPORTS:
        driver.set_window_size(width, height)
        driver.get(page_url)
        time.sleep(SCROLL_WAIT_SECONDS)

        if block_reason is None:
            block_reason = driver.execute_script(CHALLENGE_DETECTION_JS)

        full_page_height = driver.execute_script(
            "return Math.max(document.body.scrollHeight, "
            "document.documentElement.scrollHeight);"
        )
        capture_height = min(max(height, full_page_height), MAX_PAGE_HEIGHT)
        if capture_height != height:
            driver.set_window_size(width, capture_height)
            time.sleep(SCROLL_WAIT_SECONDS)

        screenshot_dir = settings.screenshot_root / job_id / f"page-{page_index}"
        screenshot_dir.mkdir(parents=True, exist_ok=True)
        screenshot_path = screenshot_dir / f"{name}.png"
        driver.save_screenshot(str(screenshot_path))

        if block_reason:
            # Challenge page: screenshot kept as evidence, but its DOM isn't the
            # real site — don't scrape elements or follow links out of it.
            elements: list[dict] = []
        else:
            raw_elements = _scroll_and_collect(driver)
            discovered_links.extend(_same_origin_links(raw_elements, page_url))
            elements = [
                {
                    "element_id": f"page{page_index}-{name}-{index}",
                    "selector": item["selector"],
                    "bbox": {
                        "x": item["x"],
                        "y": item["y"],
                        "width": item["width"],
                        "height": item["height"],
                    },
                    "dom_role": item["dom_role"],
                    "ocr_text": None,
                    "visual_role": None,
                    "confidence_score": 1.0,
                    "visible": item["visible"],
                    "rendering_mismatch": False,
                }
                for index, item in enumerate(raw_elements)
            ]
        viewports.append(
            {
                "viewport_name": name,
                "width": width,
                "height": capture_height,
                "screenshot_path": str(screenshot_path),
                "elements": elements,
            }
        )

    discovery_result = {
        "target_url": page_url,
        "viewports": viewports,
        "dom_snapshot_path": None,
        "blocked": block_reason is not None,
        "block_reason": block_reason,
    }
    return discovery_result, discovered_links


def crawl(job_id: str, target_url: str, max_pages: int | None = None) -> list[dict]:
    settings = get_settings()
    max_pages = max_pages or settings.max_pages

    driver = _build_driver(settings.selenium_grid_url)
    pages: list[dict] = []
    visited: set[str] = set()
    queue: list[str] = [target_url]

    try:
        while queue and len(pages) < max_pages:
            page_url = queue.pop(0)
            normalized = _normalize_url(page_url)
            if normalized in visited:
                continue
            visited.add(normalized)

            discovery_result, links = _capture_page(driver, job_id, page_url, len(pages), settings)
            pages.append(discovery_result)

            for link in links:
                if link not in visited and link not in queue:
                    queue.append(link)
    finally:
        driver.quit()

    return pages
