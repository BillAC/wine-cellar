'''[
Create one printable sheet of 160 SpartanIndustrial® R001 labels with QR codes for wine bottles.
Each label is 1" x 0.5". Sheet is standard US Letter (8.5" x 11").
]
'''

import argparse
import json
import re
import textwrap
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont
import qrcode

from env_settings import get_settings, load_app_env

load_app_env()

TEMPLATE_NAME = "SpartanIndustrial® R001"
PAGE_WIDTH_IN = 8.5
PAGE_HEIGHT_IN = 11.0
LABEL_WIDTH_IN = 1.0
LABEL_HEIGHT_IN = 0.5
COLUMNS = 8
ROWS = 20
LABEL_COUNT = COLUMNS * ROWS  # 160
LEFT_MARGIN_IN = 0.25         # 1/4 in
TOP_MARGIN_IN = 0.5           # 1/2 in
HORIZONTAL_GAP_IN = 0.0       # horizontal pitch = 1.0 in (no inter-label gap)
VERTICAL_GAP_IN = 0.0         # vertical pitch = 0.5 in (no inter-label gap)
DPI = 300
DEFAULT_OUTPUT_DIR = get_settings().qr_labels_dir
HISTORY_FILENAME = "used_label_numbers.json"


def parse_starting_label(value: str) -> tuple[str, int, int]:
    val = value.strip()
    match = re.fullmatch(r"(.*?)(\d+)", val)
    if match is None:
        raise ValueError("The starting label must end with a number, such as 1000 or Basement-Rack1-1000.")

    prefix, number = match.groups()
    return prefix, int(number), len(number)


def fit_label_text(
    label: str, max_width: int, max_height: int
) -> tuple[list[str], ImageFont.ImageFont]:
    draw = ImageDraw.Draw(Image.new("RGB", (1, 1)))
    # Try single line first from largest to smallest
    for font_size in range(48, 13, -2):
        font = ImageFont.load_default(size=font_size)
        bbox = draw.textbbox((0, 0), label, font=font)
        if (bbox[2] - bbox[0]) <= max_width and (bbox[3] - bbox[1]) <= max_height:
            return [label], font

    # Try multi-line wrap if single-line doesn't fit
    for font_size in range(32, 11, -1):
        font = ImageFont.load_default(size=font_size)
        chars = max(1, int(max_width / (font_size * 0.55)))
        lines = textwrap.wrap(
            label,
            width=chars,
            break_long_words=True,
            break_on_hyphens=True,
        ) or [label]
        bbox = draw.multiline_textbbox((0, 0), "\n".join(lines), font=font)
        if (bbox[2] - bbox[0]) <= max_width and (bbox[3] - bbox[1]) <= max_height:
            return lines, font

    font = ImageFont.load_default(size=11)
    return [label], font


def create_label_pdf(
    starting_label: str,
    output_path: Path,
    base_url: str = None,
) -> tuple[str, str]:
    prefix, start_number, number_width = parse_starting_label(starting_label)
    labels = [
        f"{prefix}{number:0{number_width}d}"
        for number in range(start_number, start_number + LABEL_COUNT)
    ]

    page_width = round(PAGE_WIDTH_IN * DPI)
    page_height = round(PAGE_HEIGHT_IN * DPI)
    label_w = round(LABEL_WIDTH_IN * DPI)
    label_h = round(LABEL_HEIGHT_IN * DPI)
    qr_size = round(0.40 * DPI)
    qr_pad_left = round(0.04 * DPI)
    text_gap = round(0.03 * DPI)
    text_pad_right = round(0.04 * DPI)

    if base_url is None:
        base_url = get_settings().public_base_url or "http://localhost:8000"
    else:
        base_url = base_url.rstrip("/")

    output_path.parent.mkdir(parents=True, exist_ok=True)
    page = Image.new("RGB", (page_width, page_height), "white")
    draw = ImageDraw.Draw(page)

    for index, label in enumerate(labels):
        row, column = divmod(index, COLUMNS)
        lx = round(LEFT_MARGIN_IN * DPI + column * (LABEL_WIDTH_IN + HORIZONTAL_GAP_IN) * DPI)
        ly = round(TOP_MARGIN_IN * DPI + row * (LABEL_HEIGHT_IN + VERTICAL_GAP_IN) * DPI)

        qr = qrcode.QRCode(
            error_correction=qrcode.constants.ERROR_CORRECT_M,
            box_size=10,
            border=1,
        )
        qr.add_data(f"{base_url}/wines/{label}")
        qr.make(fit=True)
        qr_image = qr.make_image(fill_color="black", back_color="white").convert("RGB")
        qr_image = qr_image.resize((qr_size, qr_size), Image.Resampling.NEAREST)

        qr_x = lx + qr_pad_left
        qr_y = ly + (label_h - qr_size) // 2
        page.paste(qr_image, (qr_x, qr_y))

        tx_start = qr_x + qr_size + text_gap
        max_tw = (lx + label_w - text_pad_right) - tx_start
        max_th = label_h - 2 * round(0.04 * DPI)

        lines, font = fit_label_text(label, max_tw, max_th)
        text_cx = tx_start + max_tw // 2
        text_cy = ly + label_h // 2
        draw.multiline_text(
            (text_cx, text_cy),
            "\n".join(lines),
            font=font,
            fill="black",
            anchor="mm",
            align="center",
        )

    page.save(output_path, "PDF", resolution=DPI)
    return labels[0], labels[-1]


def load_used_numbers(history_path: Path, output_dir: Path) -> set[int]:
    used_numbers: set[int] = set()
    if history_path.exists():
        try:
            stored_numbers = json.loads(history_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as error:
            raise RuntimeError(f"Could not read label history at {history_path}: {error}") from error
        if not isinstance(stored_numbers, list) or any(
            not isinstance(number, int) or isinstance(number, bool) or number < 0
            for number in stored_numbers
        ):
            raise RuntimeError(f"Label history at {history_path} must be a JSON list of non-negative integers.")
        used_numbers.update(stored_numbers)

    if output_dir.exists():
        pdf_range_pattern = re.compile(r"(\d+)_to_.+?(\d+)\.pdf$", re.IGNORECASE)
        for pdf_path in output_dir.glob("*.pdf"):
            match = pdf_range_pattern.search(pdf_path.name)
            if match:
                first, last = (int(number) for number in match.groups())
                used_numbers.update(range(first, last + 1))

    return used_numbers


def save_used_numbers(history_path: Path, used_numbers: set[int]) -> None:
    history_path.parent.mkdir(parents=True, exist_ok=True)
    history_path.write_text(
        json.dumps(sorted(used_numbers), indent=2) + "\n",
        encoding="utf-8",
    )


def get_next_starting_label(
    output_dir: Path = None,
    history_path: Path = None,
    db = None,
) -> str:
    out_dir = output_dir or DEFAULT_OUTPUT_DIR
    hist_path = history_path or (out_dir / HISTORY_FILENAME)
    used = load_used_numbers(hist_path, out_dir)

    if db is not None:
        try:
            import models
            entries = db.query(models.WineEntry.qr_id).all()
            for (qid,) in entries:
                if qid and qid.strip().isdigit():
                    used.add(int(qid.strip()))
        except Exception:
            pass

    if not used:
        return "1000"
    return str(max(used) + 1)


def check_label_conflicts(
    starting_label: str,
    output_dir: Path = None,
    history_path: Path = None,
    db = None,
) -> dict:
    prefix, start_num, num_width = parse_starting_label(starting_label)
    last_num = start_num + LABEL_COUNT - 1
    first_label = f"{prefix}{start_num:0{num_width}d}"
    last_label = f"{prefix}{last_num:0{num_width}d}"

    out_dir = output_dir or DEFAULT_OUTPUT_DIR
    hist_path = history_path or (out_dir / HISTORY_FILENAME)
    used = load_used_numbers(hist_path, out_dir)

    if db is not None:
        try:
            import models
            entries = db.query(models.WineEntry.qr_id).all()
            for (qid,) in entries:
                if qid and qid.strip().isdigit():
                    used.add(int(qid.strip()))
        except Exception:
            pass

    requested = set(range(start_num, last_num + 1))
    conflicts = sorted(requested & used)

    return {
        "starting_label": starting_label,
        "first_label": first_label,
        "last_label": last_label,
        "total_count": LABEL_COUNT,
        "prefix": prefix,
        "start_number": start_num,
        "end_number": last_num,
        "conflicts": conflicts,
        "has_conflicts": len(conflicts) > 0,
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description=f"Generate one printable sheet of {LABEL_COUNT} {TEMPLATE_NAME} labels (1\" x 0.5\")."
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help="PDF output path (default: wine-bottle-QR-codes/<first>_to_<last>.pdf)",
    )
    args = parser.parse_args()

    history_path = DEFAULT_OUTPUT_DIR / HISTORY_FILENAME
    used_numbers = load_used_numbers(history_path, DEFAULT_OUTPUT_DIR)
    next_suggested = str(max(used_numbers) + 1) if used_numbers else "1000"

    while True:
        starting_label = input(f"Starting label [default {next_suggested}]: ").strip() or next_suggested
        try:
            prefix, start_number, number_width = parse_starting_label(starting_label)
        except ValueError as error:
            print(error)
            continue

        numbers = set(range(start_number, start_number + LABEL_COUNT))
        previously_used = sorted(numbers & used_numbers)
        if previously_used:
            print(
                "Warning: these numeric label values were used before: "
                + ", ".join(str(number) for number in previously_used)
            )
            response = input("Proceed with these numbers anyway? [y/N]: ").strip().lower()
            if response not in {"y", "yes"}:
                print("Choose a different starting number.")
                continue
        break

    last_number = start_number + LABEL_COUNT - 1
    first_label = f"{prefix}{start_number:0{number_width}d}"
    last_label = f"{prefix}{last_number:0{number_width}d}"
    output_path = args.output
    if output_path is None:
        safe_first = re.sub(r"[^A-Za-z0-9._-]+", "_", first_label).strip("._-")
        safe_last = re.sub(r"[^A-Za-z0-9._-]+", "_", last_label).strip("._-")
        output_path = DEFAULT_OUTPUT_DIR / f"{safe_first}_to_{safe_last}.pdf"

    first_label, last_label = create_label_pdf(starting_label, output_path)
    save_used_numbers(history_path, used_numbers | numbers)
    print(
        f"Created {output_path.resolve()} with {LABEL_COUNT} labels "
        f"({first_label} through {last_label}) using template {TEMPLATE_NAME}."
        f"\nPrint at 100% / actual size on Letter paper."
    )


if __name__ == "__main__":
    main()
