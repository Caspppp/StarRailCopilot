"""
Utilities to read relic filter entries by locating the checkbox template
and OCR-ing the text to its left.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import List, Sequence, Tuple

import cv2
import numpy as np

import module.config.server as server
from module.logger import logger
from module.ocr.models import OCR_MODEL

PanelArea = Tuple[int, int, int, int]
Box = Tuple[int, int, int, int]


@dataclass
class FilterRow:
    name: str
    checkbox: Box
    text_area: Box
    score: float

    def to_serializable(self) -> dict:
        return {
            "name": self.name,
            "checkbox": tuple(int(v) for v in self.checkbox),
            "text_area": tuple(int(v) for v in self.text_area),
            "score": float(self.score),
        }


class FilterPanelReader:
    """
    Detects checkbox positions inside the filter list and OCRs the text
    block that sits to the left of each checkbox.
    """

    def __init__(
        self,
        panel_area: PanelArea,
        checkbox_template,
        *,
        detection_threshold: float = 0.82,
        text_left_offset: int = 300,
        text_right_offset: int = 70,
    ):
        self.panel_area = panel_area
        self.checkbox_template = checkbox_template
        self.detection_threshold = detection_threshold
        self.text_left_offset = text_left_offset
        self.text_right_offset = text_right_offset

        self.template_size = (0, 0)
        if checkbox_template is not None:
            h, w = checkbox_template.shape[:2]
            self.template_size = (w, h)
        else:
            logger.warning("Checkbox template missing; filter OCR will be skipped")

        self.ocr_model = OCR_MODEL.get_by_lang(server.lang)

    def extract_rows(self, image) -> List[FilterRow]:
        boxes = self._detect_checkboxes(image)
        rows: List[FilterRow] = []
        for box in boxes:
            text_area = self._text_area_for_box(box, image.shape[1], image.shape[0])
            name, score = self._ocr_area(image, text_area)
            rows.append(
                FilterRow(
                    name=name,
                    checkbox=box,
                    text_area=text_area,
                    score=score,
                )
            )
        return rows

    # Internal helpers -------------------------------------------------
    def _detect_checkboxes(self, image) -> List[Box]:
        if self.checkbox_template is None:
            return []
        x1, y1, x2, y2 = self.panel_area
        crop = image[y1:y2, x1:x2]
        crop_gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)
        res = cv2.matchTemplate(crop_gray, self.checkbox_template, cv2.TM_CCOEFF_NORMED)
        loc = np.where(res >= self.detection_threshold)
        boxes: List[Box] = []
        w, h = self.template_size
        for px, py in zip(*loc[::-1]):
            left = px + x1
            top = py + y1
            boxes.append((left, top, left + w, top + h))
        boxes = self._suppress_duplicates(boxes, radius=12)
        boxes.sort(key=lambda box: (box[1], box[0]))
        return boxes

    def _text_area_for_box(self, box: Box, max_width: int, max_height: int) -> Box:
        left = max(self.panel_area[0], box[0] - self.text_left_offset)
        right = min(self.panel_area[2], max(left + 5, box[0] - self.text_right_offset))
        top = max(self.panel_area[1], box[1])
        bottom = min(self.panel_area[3], max(top + 5, box[3]))
        return (left, top, right, bottom)

    def _ocr_area(self, image, area: Box) -> Tuple[str, float]:
        x1, y1, x2, y2 = area
        x1 = max(0, min(x1, image.shape[1]))
        x2 = max(0, min(x2, image.shape[1]))
        y1 = max(0, min(y1, image.shape[0]))
        y2 = max(0, min(y2, image.shape[0]))
        if x2 - x1 < 4 or y2 - y1 < 4:
            return "", 0.0
        region = image[y1:y2, x1:x2]
        try:
            text, score = self.ocr_model.ocr_single_line(region)
        except Exception as exc:  # pragma: no cover - OCR failures should not break flow
            logger.warning("OCR failed on area %s: %s", area, exc)
            return "", 0.0
        if text is None:
            return "", float(score or 0.0)
        return text.strip(), float(score or 0.0)

    @staticmethod
    def _suppress_duplicates(boxes: Sequence[Box], radius: int = 10) -> List[Box]:
        filtered: List[Box] = []
        centers: List[Tuple[int, int]] = []
        for box in boxes:
            cx = (box[0] + box[2]) // 2
            cy = (box[1] + box[3]) // 2
            if any(abs(cx - px) <= radius and abs(cy - py) <= radius for px, py in centers):
                continue
            filtered.append(box)
            centers.append((cx, cy))
        return filtered
