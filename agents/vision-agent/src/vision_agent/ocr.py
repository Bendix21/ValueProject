from dataclasses import dataclass

import pytesseract
from PIL import Image
from pytesseract import Output
from qa_swarm_common.schemas import BBox, DiscoveryResult, ElementInfo

from vision_agent.config import get_settings


@dataclass
class OcrWord:
    text: str
    x: int
    y: int
    width: int
    height: int
    confidence: float


def _preprocess(image: Image.Image, upscale_factor: int) -> Image.Image:
    grayscale = image.convert("L")
    upscaled = grayscale.resize(
        (grayscale.width * upscale_factor, grayscale.height * upscale_factor),
        Image.LANCZOS,
    )
    return upscaled.point(lambda p: 255 if p > 150 else 0)


def _extract_words(screenshot_path: str) -> list[OcrWord]:
    settings = get_settings()
    image = Image.open(screenshot_path)
    preprocessed = _preprocess(image, settings.ocr_upscale_factor)
    data = pytesseract.image_to_data(
        preprocessed,
        lang=settings.ocr_lang,
        config=f"--psm {settings.ocr_psm}",
        output_type=Output.DICT,
    )

    words = []
    for i, raw_text in enumerate(data["text"]):
        text = raw_text.strip()
        confidence = float(data["conf"][i])
        if not text or confidence < settings.ocr_confidence_threshold:
            continue
        words.append(
            OcrWord(
                text=text,
                x=data["left"][i] // settings.ocr_upscale_factor,
                y=data["top"][i] // settings.ocr_upscale_factor,
                width=data["width"][i] // settings.ocr_upscale_factor,
                height=data["height"][i] // settings.ocr_upscale_factor,
                confidence=confidence / 100.0,
            )
        )
    return words


def _overlap_ratio(word: OcrWord, bbox: BBox) -> float:
    word_area = word.width * word.height
    if word_area == 0:
        return 0.0
    x_overlap = max(0, min(word.x + word.width, bbox.x + bbox.width) - max(word.x, bbox.x))
    y_overlap = max(0, min(word.y + word.height, bbox.y + bbox.height) - max(word.y, bbox.y))
    return (x_overlap * y_overlap) / word_area


def _match_elements(
    elements: list[ElementInfo], words: list[OcrWord], viewport_height: int
) -> dict[str, dict]:
    matched = {}
    for element in elements:
        bbox = element.bbox
        if bbox.y + bbox.height > viewport_height:
            continue
        hits = [word for word in words if _overlap_ratio(word, bbox) > 0.5]
        if not hits:
            continue
        hits.sort(key=lambda w: (w.y, w.x))
        text = " ".join(word.text for word in hits)
        confidence = sum(word.confidence for word in hits) / len(hits)
        matched[element.selector] = {"ocr_text": text, "confidence_score": confidence}
    return matched


def run_ocr(discovery: DiscoveryResult) -> dict:
    accumulator: dict[str, dict] = {}
    for viewport in discovery.viewports:
        for element in viewport.elements:
            accumulator.setdefault(element.selector, element.model_dump())

        words = _extract_words(viewport.screenshot_path)
        matches = _match_elements(viewport.elements, words, viewport.height)
        for selector, match in matches.items():
            entry = accumulator[selector]
            if entry.get("ocr_text"):
                continue
            entry.update(match)

    enriched_elements = list(accumulator.values())
    matched_count = sum(1 for element in enriched_elements if element.get("ocr_text"))

    return {
        "page_summary": (
            f"OCR pass - {len(enriched_elements)} elements detected, "
            f"{matched_count} enriched with OCR text."
        ),
        "vision_mode": "ocr_only",
        "enriched_elements": enriched_elements,
    }
