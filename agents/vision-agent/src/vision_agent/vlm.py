import base64
import io

import httpx
from PIL import Image
from qa_swarm_common.json_utils import parse_json_object
from qa_swarm_common.ollama_client import OllamaClient
from qa_swarm_common.schemas import DiscoveryResult, ViewportCapture

from vision_agent.config import get_settings

VIEWPORT_PROMPT = """You are analyzing a screenshot of a web page for automated QA testing.
Respond with ONLY a single JSON object, no other text, in this exact shape:
{"page_summary": "one sentence describing the page", "elements": [{"label": "short name", \
"role": "functional role, e.g. button/input/link/nav", "x_pct": 45.2, "y_pct": 10.0, \
"width_pct": 12.5, "height_pct": 4.0}]}
x_pct/y_pct/width_pct/height_pct are numbers between 0 and 100 (percentage of the image \
width/height, top-left origin) - NOT fractions between 0 and 1. For example an element \
centered horizontally and near the top should have x_pct around 45-55, not 0.45-0.55. \
List only elements a user could interact with (buttons, links, inputs, menus)."""

CROP_PROMPT = "Describe this UI element and its likely function in a few words."


def _encode_image(path: str) -> str:
    with open(path, "rb") as file:
        return base64.b64encode(file.read()).decode()


def _normalize_pct(value: float) -> float:
    # LLaVA sometimes ignores the 0-100 instruction and returns a 0-1 fraction instead.
    return value * 100 if value <= 1.5 else value


def _pct_to_pixels(item: dict, width: int, height: int) -> dict:
    return {
        "x": round(_normalize_pct(float(item["x_pct"])) / 100 * width),
        "y": round(_normalize_pct(float(item["y_pct"])) / 100 * height),
        "width": round(_normalize_pct(float(item["width_pct"])) / 100 * width),
        "height": round(_normalize_pct(float(item["height_pct"])) / 100 * height),
    }


def _iou(a: dict, b: dict) -> float:
    ax1, ay1, ax2, ay2 = a["x"], a["y"], a["x"] + a["width"], a["y"] + a["height"]
    bx1, by1, bx2, by2 = b["x"], b["y"], b["x"] + b["width"], b["y"] + b["height"]
    inter_w = max(0, min(ax2, bx2) - max(ax1, bx1))
    inter_h = max(0, min(ay2, by2) - max(ay1, by1))
    intersection = inter_w * inter_h
    if intersection == 0:
        return 0.0
    union = (a["width"] * a["height"]) + (b["width"] * b["height"]) - intersection
    return intersection / union if union else 0.0


async def _call_vlm_for_viewport(
    client: OllamaClient, settings, viewport: ViewportCapture
) -> dict | None:
    image_b64 = _encode_image(viewport.screenshot_path)
    try:
        raw = await client.generate(settings.vlm_model, VIEWPORT_PROMPT, images=[image_b64])
    except httpx.HTTPError:
        return None
    parsed = parse_json_object(raw)
    if parsed is None:
        return None
    elements = []
    for item in parsed.get("elements", []):
        try:
            elements.append(
                {
                    "label": str(item["label"]),
                    "role": str(item.get("role", "")),
                    "bbox": _pct_to_pixels(item, viewport.width, viewport.height),
                }
            )
        except (KeyError, TypeError, ValueError):
            continue
    return {"page_summary": parsed.get("page_summary"), "elements": elements}


def _reconcile_iou(
    accumulator: dict[str, dict],
    viewport: ViewportCapture,
    vlm_elements: list[dict],
    threshold: float,
) -> None:
    for dom_element in viewport.elements:
        bbox = dom_element.bbox
        if bbox.y + bbox.height > viewport.height:
            continue
        dom_bbox = {"x": bbox.x, "y": bbox.y, "width": bbox.width, "height": bbox.height}
        best = None
        best_iou = 0.0
        for vlm_element in vlm_elements:
            score = _iou(dom_bbox, vlm_element["bbox"])
            if score > best_iou:
                best_iou = score
                best = vlm_element
        if best is None or best_iou <= threshold:
            continue
        entry = accumulator[dom_element.selector]
        if not entry.get("visual_role"):
            entry["visual_role"] = best["label"]
        if not dom_element.visible:
            entry["rendering_mismatch"] = True


def _find_source_viewport(selector: str, discovery: DiscoveryResult) -> ViewportCapture | None:
    for viewport in discovery.viewports:
        for element in viewport.elements:
            if element.selector == selector:
                return viewport
    return None


async def _call_vlm_for_crop(
    client: OllamaClient, settings, viewport: ViewportCapture, bbox: dict
) -> str | None:
    image = Image.open(viewport.screenshot_path)
    padding_x = max(4, round(bbox["width"] * 0.1))
    padding_y = max(4, round(bbox["height"] * 0.1))
    left = max(0, bbox["x"] - padding_x)
    top = max(0, bbox["y"] - padding_y)
    right = min(image.width, bbox["x"] + bbox["width"] + padding_x)
    bottom = min(image.height, bbox["y"] + bbox["height"] + padding_y)
    crop = image.crop((left, top, right, bottom))

    if crop.width < 64 or crop.height < 64:
        scale = max(64 / max(crop.width, 1), 64 / max(crop.height, 1))
        crop = crop.resize((round(crop.width * scale), round(crop.height * scale)), Image.LANCZOS)

    buffer = io.BytesIO()
    crop.save(buffer, format="PNG")
    image_b64 = base64.b64encode(buffer.getvalue()).decode()

    try:
        raw = await client.generate(settings.vlm_model, CROP_PROMPT, images=[image_b64])
    except httpx.HTTPError:
        return None
    return raw.strip() or None


async def _run_vlm_pass(discovery: DiscoveryResult, ocr_result: dict, client: OllamaClient, settings) -> dict:
    accumulator = {element["selector"]: element for element in ocr_result["enriched_elements"]}
    page_summary = ocr_result["page_summary"]

    for index, viewport in enumerate(discovery.viewports):
        parsed = await _call_vlm_for_viewport(client, settings, viewport)
        if parsed is None:
            continue
        if index == 0 and parsed.get("page_summary"):
            page_summary = parsed["page_summary"]
        _reconcile_iou(accumulator, viewport, parsed["elements"], settings.vlm_iou_threshold)

    ambiguous = [
        element
        for element in accumulator.values()
        if not element.get("ocr_text") and not element.get("visual_role")
    ][: settings.vlm_max_crop_calls]

    for element in ambiguous:
        viewport = _find_source_viewport(element["selector"], discovery)
        if viewport is None:
            continue
        label = await _call_vlm_for_crop(client, settings, viewport, element["bbox"])
        if label:
            element["visual_role"] = label

    return {
        "page_summary": page_summary,
        "vision_mode": "full",
        "enriched_elements": list(accumulator.values()),
    }


async def enrich_with_vlm(discovery: DiscoveryResult, ocr_result: dict) -> dict:
    settings = get_settings()
    client = OllamaClient(settings.ollama_host, timeout=settings.vlm_timeout)

    if not await client.health_check(settings.vlm_model):
        return ocr_result

    try:
        return await _run_vlm_pass(discovery, ocr_result, client, settings)
    except Exception:
        return ocr_result
