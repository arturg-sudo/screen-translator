from dataclasses import dataclass
from typing import List, Tuple
import re
from PIL import Image
import winocr


@dataclass
class OcrBlock:
    original_text: str
    x: int
    y: int
    width: int
    height: int
    bg_color: Tuple[int, int, int]
    text_color: Tuple[int, int, int]
    font_size: int


def _sample_bg_color(img: Image.Image, x0: int, y0: int, x1: int, y1: int) -> Tuple[int, int, int]:
    """Sample background color from the outer border of the bounding box."""
    w, h = img.size
    samples = []
    step = max(1, (x1 - x0) // 10)

    for x in range(x0, x1, step):
        top_y = max(0, y0 - 2)
        bottom_y = min(h - 1, y1 + 2)
        samples.append(img.getpixel((x, top_y))[:3])
        samples.append(img.getpixel((x, bottom_y))[:3])

    vstep = max(1, (y1 - y0) // 5)
    for y in range(y0, y1, vstep):
        left_x = max(0, x0 - 2)
        right_x = min(w - 1, x1 + 2)
        samples.append(img.getpixel((left_x, y))[:3])
        samples.append(img.getpixel((right_x, y))[:3])

    if not samples:
        return (30, 30, 30)

    avg_r = int(sum(s[0] for s in samples) / len(samples))
    avg_g = int(sum(s[1] for s in samples) / len(samples))
    avg_b = int(sum(s[2] for s in samples) / len(samples))
    return (avg_r, avg_g, avg_b)


def run_ocr(image: Image.Image, source_lang: str = "auto") -> List[OcrBlock]:
    """
    Run Windows OCR on PIL image with smart language detection.
    When source_lang is 'auto', runs both RU and EN recognizers and selects the most accurate result.
    """
    img_rgb = image.convert("RGB")
    ocr_result = None

    if source_lang == "auto":
        res_ru = None
        res_en = None
        try:
            res_ru = winocr.recognize_pil_sync(img_rgb, lang="ru")
        except Exception:
            pass
        try:
            res_en = winocr.recognize_pil_sync(img_rgb, lang="en")
        except Exception:
            pass

        lines_ru = res_ru.get("lines", []) if res_ru else []
        lines_en = res_en.get("lines", []) if res_en else []
        text_ru = " ".join(l.get("text", "") for l in lines_ru)
        text_en = " ".join(l.get("text", "") for l in lines_en)

        cyr_ru = len(re.findall(r"[а-яА-ЯёЁ]", text_ru))
        lat_ru = len(re.findall(r"[a-zA-Z]", text_ru))

        if cyr_ru > lat_ru:
            ocr_result = res_ru
        elif lines_en:
            ocr_result = res_en
        elif lines_ru:
            ocr_result = res_ru
    else:
        # User specified explicit language
        langs_to_try = [source_lang, "en", "ru"]
        for lang in langs_to_try:
            try:
                res = winocr.recognize_pil_sync(img_rgb, lang=lang)
                if res and res.get("lines"):
                    ocr_result = res
                    break
            except Exception:
                continue

    if not ocr_result or not ocr_result.get("lines"):
        return []

    words_list = []
    for line in ocr_result["lines"]:
        words_list.extend(line.get("words", []))

    if not words_list:
        return []

    # Sort all words top to bottom, then left to right
    words_list.sort(key=lambda w: (w["bounding_rect"]["y"], w["bounding_rect"]["x"]))

    # Cluster words on the same horizontal line by vertical center overlap
    clusters = []
    for w in words_list:
        wy = w["bounding_rect"]["y"]
        wh = w["bounding_rect"]["height"]
        w_center_y = wy + wh / 2.0

        found = False
        for c in clusters:
            cy = c["y_center"]
            ch = c["height"]
            if abs(w_center_y - cy) < ch * 0.6:
                c["words"].append(w)
                c["words"].sort(key=lambda x: x["bounding_rect"]["x"])
                all_ys = [x["bounding_rect"]["y"] for x in c["words"]]
                all_hs = [x["bounding_rect"]["height"] for x in c["words"]]
                min_y = min(all_ys)
                max_y = max(y + h for y, h in zip(all_ys, all_hs))
                c["height"] = max_y - min_y
                c["y_center"] = min_y + c["height"] / 2.0
                found = True
                break
        if not found:
            clusters.append({
                "y_center": w_center_y,
                "height": wh,
                "words": [w]
            })

    # Sort clusters strictly by Y coordinate
    clusters.sort(key=lambda c: c["y_center"])

    blocks: List[OcrBlock] = []
    w_img, h_img = img_rgb.size

    for c in clusters:
        words = c["words"]
        text = " ".join(w.get("text", "").strip() for w in words if w.get("text", "").strip())
        if not text:
            continue

        min_x = int(min(w["bounding_rect"]["x"] for w in words))
        min_y = int(min(w["bounding_rect"]["y"] for w in words))
        max_x = int(max(w["bounding_rect"]["x"] + w["bounding_rect"]["width"] for w in words))
        max_y = int(max(w["bounding_rect"]["y"] + w["bounding_rect"]["height"] for w in words))

        pad = 2
        bx0 = max(0, min_x - pad)
        by0 = max(0, min_y - pad)
        bx1 = min(w_img, max_x + pad)
        by1 = min(h_img, max_y + pad)

        bw = max(1, bx1 - bx0)
        bh = max(1, by1 - by0)

        bg_r, bg_g, bg_b = _sample_bg_color(img_rgb, bx0, by0, bx1, by1)
        lum = 0.299 * bg_r + 0.587 * bg_g + 0.114 * bg_b
        text_color = (255, 255, 255) if lum < 135 else (20, 20, 20)
        font_size = max(9, int(bh * 0.72))

        blocks.append(
            OcrBlock(
                original_text=text,
                x=bx0,
                y=by0,
                width=bw,
                height=bh,
                bg_color=(bg_r, bg_g, bg_b),
                text_color=text_color,
                font_size=font_size,
            )
        )

    return blocks


if __name__ == "__main__":
    from PIL import ImageDraw, ImageFont

    test_img = Image.new("RGB", (350, 80), color="#282a36")
    draw = ImageDraw.Draw(test_img)
    font = ImageFont.truetype("C:/Windows/Fonts/arial.ttf", 22)
    draw.text((20, 25), "Hello OCR Test!", fill="#f8f8f2", font=font)

    blocks = run_ocr(test_img, source_lang="auto")
    assert len(blocks) > 0
    assert blocks[0].original_text == "Hello OCR Test!"
    print(f"Self-check passed: '{blocks[0].original_text}' at ({blocks[0].x}, {blocks[0].y}, {blocks[0].width}x{blocks[0].height})")
