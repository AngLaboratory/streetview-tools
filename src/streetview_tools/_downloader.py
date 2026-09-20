from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from io import BytesIO
import json
from pathlib import Path

import requests
import numpy as np
import py360convert
from PIL import Image

from ._http import REQUEST_HEADERS


def download_tiles(
    tile_sources,
    output_path,
    crop_box=None,
    width=None,
    height=None,
    max_workers=8,
):
    canvas = download_tiles_image(tile_sources, crop_box=crop_box)

    target_size = normalize_size(width, height)
    if target_size:
        canvas = canvas.resize(target_size, Image.Resampling.LANCZOS)

    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    canvas.save(output_path, "PNG")
    return output_path


def download_tiles_image(tile_sources, crop_box=None, max_workers=8):
    """Download and merge tiles into a PIL image without saving it."""
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        images = list(executor.map(_load_image, (item["src"] for item in tile_sources)))

    canvas_width = max(item["x"] + image.width for item, image in zip(tile_sources, images))
    canvas_height = max(item["y"] + image.height for item, image in zip(tile_sources, images))
    canvas = Image.new("RGB", (canvas_width, canvas_height))

    for item, image in zip(tile_sources, images):
        canvas.paste(image.convert("RGB"), (item["x"], item["y"]))

    if crop_box:
        canvas = canvas.crop(tuple(crop_box))
    return canvas


def equirect_to_face(image, direction, face_size=None):
    """Convert an equirectangular PIL image into one cubemap face."""
    direction = str(direction).lower().strip()
    if direction not in "lfrbdu" or len(direction) != 1:
        raise ValueError("direction must be one of: l, f, r, b, d, u")

    if face_size is None:
        face_size = image.height // 2
    if face_size <= 0:
        raise ValueError("face_size must be positive")
    if image.width != image.height * 2:
        raise ValueError("equirectangular image must have a 2:1 aspect ratio")

    faces = py360convert.e2c(
        np.asarray(image.convert("RGB")),
        face_w=face_size,
        mode="bilinear",
        cube_format="list",
    )
    face_index = {"f": 0, "r": 1, "b": 2, "l": 3, "u": 4, "d": 5}[direction]
    return Image.fromarray(faces[face_index].astype(np.uint8), mode="RGB")


def save_image(image, output_path):
    """Save a PIL image and create its parent directory when needed."""
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    image.save(output_path, "PNG")
    return output_path


def save_pano_info_json(pano_info, image_path):
    """Save panorama metadata beside an image using the same file stem."""
    json_path = Path(image_path).with_suffix(".json")
    json_path.parent.mkdir(parents=True, exist_ok=True)
    with json_path.open("w", encoding="utf-8") as file:
        json.dump(pano_info, file, ensure_ascii=False, indent=2)
    return json_path


def adjust_face_angle(pano_info, direction):
    """Return metadata with its camera angle adjusted for a face direction."""
    direction = str(direction).lower().strip()
    offsets = {"f": 0, "r": 90, "b": 180, "l": -90, "u": 0, "d": 0}
    if direction not in offsets:
        raise ValueError("direction must be one of: l, f, r, b, d, u")

    adjusted_info = deepcopy(pano_info)
    angle = float(adjusted_info.get("angle", 0))
    adjusted_info["angle"] = round((angle + offsets[direction]) % 360, 1)
    return adjusted_info


def normalize_size(width=None, height=None):
    """Return a 2:1 output size, using width as the source of truth."""
    if width is None and height is None:
        return None

    if width is not None:
        width = _validate_dimension(width, "width")
        width -= width % 2
        width = max(2, width)
        return width, width // 2

    height = _validate_dimension(height, "height")
    return height * 2, height


def select_zoom(width, zoom_sizes, default_zoom):
    """Choose the smallest zoom whose source width meets ``width``."""
    if width is None:
        return default_zoom

    target_width = _validate_dimension(width, "width")
    for zoom, source_width in sorted(zoom_sizes.items()):
        if source_width >= target_width:
            return zoom
    return max(zoom_sizes)


def _validate_dimension(value, name):
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ValueError(f"{name} must be a positive integer")
    return value


def _load_image(url):
    response = requests.get(url, headers=REQUEST_HEADERS, timeout=10)
    response.raise_for_status()
    if not response.headers.get("Content-Type", "").startswith("image/"):
        raise ValueError(f"Response is not an image: {url}")
    with Image.open(BytesIO(response.content)) as image:
        return image.copy()