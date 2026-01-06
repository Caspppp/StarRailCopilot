import argparse
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import cv2
import numpy as np


METHODS = {
    "ccoeff_normed": cv2.TM_CCOEFF_NORMED,
    "ccorr_normed": cv2.TM_CCORR_NORMED,
}


@dataclass(frozen=True)
class Match:
    x: int
    y: int
    score: float


def pick_peaks(
    response: np.ndarray,
    threshold: float,
    radius: int,
    *,
    max_peaks: int = 20_000,
) -> list[Match]:
    if response.ndim != 2:
        raise ValueError("response must be a 2D array")

    if radius < 0:
        raise ValueError("radius must be >= 0")

    response = np.nan_to_num(response, nan=-1.0)
    work = response.copy()
    height, width = work.shape[:2]

    matches: list[Match] = []
    for _ in range(max_peaks):
        _, max_val, _, max_loc = cv2.minMaxLoc(work)
        if max_val < threshold:
            break

        x, y = max_loc
        matches.append(Match(x=int(x), y=int(y), score=float(max_val)))

        x1 = max(0, x - radius)
        y1 = max(0, y - radius)
        x2 = min(width, x + radius + 1)
        y2 = min(height, y + radius + 1)
        work[y1:y2, x1:x2] = -1.0

    return matches


def draw_matches(image: np.ndarray, matches: list[Match], template_hw: tuple[int, int]) -> np.ndarray:
    vis = image.copy()
    template_h, template_w = template_hw

    for match in matches:
        x1, y1 = match.x, match.y
        x2, y2 = x1 + template_w, y1 + template_h
        cv2.rectangle(vis, (x1, y1), (x2, y2), (0, 0, 255), 1)
        cv2.putText(
            vis,
            f"{match.score:.3f}",
            (x1, max(0, y1 - 4)),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.4,
            (0, 0, 255),
            1,
            cv2.LINE_AA,
        )

    return vis


def parse_thresholds(raw: str) -> list[float]:
    thresholds: list[float] = []
    for part in raw.split(","):
        part = part.strip()
        if not part:
            continue
        thresholds.append(float(part))
    if not thresholds:
        raise ValueError("no thresholds provided")
    return thresholds


def main() -> int:
    parser = argparse.ArgumentParser(description="Template-match a tiny yellow-star crop in a screenshot.")
    parser.add_argument(
        "--image",
        default="screenshots/templates/template_20260101_163612.png",
        help="Path to the full screenshot image (BGR via cv2.imread).",
    )
    parser.add_argument(
        "--template",
        default="screenshots/crops/crop_20260106_213501.png",
        help="Path to the template crop image (BGR via cv2.imread).",
    )
    parser.add_argument(
        "--method",
        default="ccoeff_normed",
        choices=sorted(METHODS.keys()),
        help="OpenCV matchTemplate method.",
    )
    parser.add_argument(
        "--threshold",
        type=float,
        default=0.96,
        help="Similarity threshold (higher means stricter).",
    )
    parser.add_argument(
        "--radius",
        type=int,
        default=-1,
        help="Suppression radius for peak picking (default: max(template_w, template_h)).",
    )
    parser.add_argument(
        "--sweep",
        action="store_true",
        help="Print counts for multiple thresholds (uses the same peak set).",
    )
    parser.add_argument(
        "--sweep-thresholds",
        type=parse_thresholds,
        default=parse_thresholds("0.99,0.98,0.97,0.96,0.95,0.94,0.93,0.92,0.90,0.88,0.85"),
        help="Comma-separated thresholds used by --sweep.",
    )
    parser.add_argument(
        "--out",
        default="",
        help="Output visualization path (default: screenshots/debug/template_match_yellow_star_<ts>.png).",
    )

    args = parser.parse_args()

    image = cv2.imread(args.image)
    if image is None:
        raise SystemExit(f"Failed to read image: {args.image}")

    template = cv2.imread(args.template)
    if template is None:
        raise SystemExit(f"Failed to read template: {args.template}")

    template_h, template_w = template.shape[:2]
    radius = args.radius if args.radius >= 0 else max(template_h, template_w)

    method = METHODS[args.method]
    response = cv2.matchTemplate(image, template, method)
    min_val, max_val, min_loc, max_loc = cv2.minMaxLoc(response)

    print(f"[matchTemplate] method={args.method} template={template_w}x{template_h}")
    print(f"[response] min={min_val:.6f} at {min_loc} | max={max_val:.6f} at {max_loc}")

    thresholds = args.sweep_thresholds if args.sweep else [args.threshold]
    threshold_min = min(thresholds)
    peaks_all = pick_peaks(response, threshold=threshold_min, radius=radius)

    if args.sweep:
        print("[sweep] threshold -> peak_count")
        for thr in thresholds:
            count = sum(1 for m in peaks_all if m.score >= thr)
            print(f"  {thr:.2f} -> {count}")

    selected = [m for m in peaks_all if m.score >= args.threshold]
    print(f"[result] threshold={args.threshold:.3f} radius={radius} matches={len(selected)}")

    vis = draw_matches(image, selected, (template_h, template_w))

    out_path = Path(args.out) if args.out else Path(
        f"screenshots/debug/template_match_yellow_star_{datetime.now().strftime('%Y%m%d_%H%M%S')}.png"
    )
    out_path.parent.mkdir(parents=True, exist_ok=True)
    cv2.imwrite(str(out_path), vis)
    print(f"[saved] {out_path}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
