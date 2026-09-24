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


def download_tiles_image(tile_sources, crop_box=None, canvas_size=None, max_workers=8):
    """Download and merge tiles into a PIL image without saving it.

    ``canvas_size`` fixes the ``(width, height)`` of the canvas instead of
    inferring it from ``tile_sources``; pass it whenever ``tile_sources`` may
    be a partial subset of the full tile grid (e.g. after
    :func:`select_visible_tiles` trims tiles outside a requested view), so
    the untouched area is filled with a plain background instead of shrinking
    the canvas. Tiles are pasted in list order, so when duplicate positions
    occur, later entries take precedence.
    """
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        images = list(executor.map(_load_image, (item["src"] for item in tile_sources)))

    if canvas_size is not None:
        canvas_width, canvas_height = canvas_size
    else:
        canvas_width = max(item["x"] + image.width for item, image in zip(tile_sources, images))
        canvas_height = max(item["y"] + image.height for item, image in zip(tile_sources, images))
    canvas = Image.new("RGB", (canvas_width, canvas_height))

    for item, image in zip(tile_sources, images):
        canvas.paste(image.convert("RGB"), (item["x"], item["y"]))

    if crop_box:
        canvas = canvas.crop(tuple(crop_box))
    return canvas


def resolve_output_size(width, height, source_height):
    """Resolve the ``(width, height)`` of a perspective output.

    Applies the same defaulting rules as :func:`equirect_to_perspective` but
    only needs the source panorama's height, so it can run before any tiles
    are downloaded (to decide which tiles are actually needed).
    """
    if width is None and height is None:
        width = height = source_height // 2
    elif height is None:
        height = width
    elif width is None:
        width = height
    return _validate_dimension(width, "width"), _validate_dimension(height, "height")


def equirect_to_perspective(image, yaw=0.0, pitch=0.0, *, width=None, height=None, fov=90.0):
    """Convert an equirectangular PIL image into a perspective view.

    ``yaw`` is the left/right viewing angle in degrees (0 = forward, positive
    = right) and ``pitch`` is the up/down viewing angle in degrees (0 =
    level, positive = up). The field of view is derived from ``width`` and
    ``height`` instead of being given directly: when both are omitted, the
    source resolution is used for a square output; when only ``width`` is
    given, a ``width``x``width`` square is returned; when both are given,
    the horizontal field of view stays fixed at ``fov`` while the vertical
    field of view scales with the aspect ratio, so extra sky/ground is
    captured instead of the image being stretched.
    """
    if image.width != image.height * 2:
        raise ValueError("equirectangular image must have a 2:1 aspect ratio")

    width, height = resolve_output_size(width, height, image.height)

    v_fov = fov * height / width
    perspective = py360convert.e2p(
        np.asarray(image.convert("RGB")),
        fov_deg=(fov, v_fov),
        u_deg=yaw,
        v_deg=pitch,
        out_hw=(height, width),
        mode="bilinear",
    )
    return Image.fromarray(perspective.astype(np.uint8), mode="RGB")


def select_visible_tiles(rows, cols, yaw, pitch, width, height, *, fov=90.0):
    """Return the ``{(row, col), ...}`` tile indices of a ``rows`` x ``cols``
    grid of equal tiles spanning a full equirectangular panorama that are
    needed to render the perspective view described by ``yaw``/``pitch`` and
    output ``width``/``height`` (using the same field-of-view rule as
    :func:`equirect_to_perspective`).

    Visibility is determined by feeding a tiny placeholder image, where each
    pixel holds its own tile index, through the exact same
    :func:`py360convert.e2p` call the real render will use (nearest-neighbor
    sampling), so the result matches the real sampling exactly. The raw hit
    set is then dilated by one tile in every direction (columns wrap around)
    as a safety margin for bilinear interpolation and for the coarseness of
    the sampling grid, without touching the field of view itself (padding
    the field of view instead can blow up or wrap the whole sphere as it
    approaches 180 degrees).
    """
    v_fov = fov * height / width
    tile_ids = np.arange(rows * cols, dtype=np.float32).reshape(rows, cols, 1)
    sampled = py360convert.e2p(
        tile_ids,
        fov_deg=(fov, v_fov),
        u_deg=yaw,
        v_deg=pitch,
        out_hw=(128, 256),
        mode="nearest",
    )
    hits = {(int(tile_id) // cols, int(tile_id) % cols) for tile_id in np.unique(sampled)}
    return {
        (min(max(row + dr, 0), rows - 1), (col + dc) % cols)
        for row, col in hits
        for dr in (-1, 0, 1)
        for dc in (-1, 0, 1)
    }


def select_visible_faces(yaw, pitch, width, height, *, fov=90.0, margin_deg=10.0):
    """Return the subset of ``l``, ``f``, ``r``, ``b``, ``d``, ``u`` cubemap
    faces needed to render the perspective view described by ``yaw``/
    ``pitch`` and output ``width``/``height``.

    Mirrors :func:`select_visible_tiles`, but for a cubemap that will be
    stitched with :func:`cubemap_to_equirect` before the perspective is
    sampled: constant-valued faces are merged into an equirectangular "face
    id" image with the same :func:`py360convert.c2e` call the real render
    uses, then sampled with :func:`py360convert.e2p` (nearest-neighbor) to
    see which ids are visible. ``margin_deg`` pads the queried field of view
    on top of that (a face is either fully needed or not, so there is no
    per-tile dilation to fall back on), clamped well below 180 degrees so it
    can never make the padded field of view wrap or blow up.
    """
    letters = "frblud"
    face_ids = [np.full((4, 4, 1), index, dtype=np.float32) for index in range(len(letters))]
    equirect_ids = py360convert.c2e(face_ids, h=64, w=128, mode="nearest", cube_format="list")

    v_fov = fov * height / width
    h_fov = min(fov + 2 * margin_deg, 170.0)
    v_fov = min(v_fov + 2 * margin_deg, 170.0)
    sampled = py360convert.e2p(
        equirect_ids,
        fov_deg=(h_fov, v_fov),
        u_deg=yaw,
        v_deg=pitch,
        out_hw=(64, 128),
        mode="nearest",
    )
    return {letters[int(index)] for index in np.unique(sampled)}


def cubemap_to_equirect(faces, height):
    """Convert cubemap faces keyed by ``l``, ``f``, ``r``, ``b``, ``d``, ``u``
    (all the same square size) into an equirectangular PIL image."""
    face_arrays = [np.asarray(faces[letter].convert("RGB")) for letter in "frblud"]
    equirect = py360convert.c2e(
        face_arrays, h=height, w=height * 2, mode="bilinear", cube_format="list"
    )
    return Image.fromarray(equirect.astype(np.uint8), mode="RGB")


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


def adjust_pano_angle(pano_info, yaw):
    """Return metadata with its camera angle adjusted by ``yaw`` degrees."""
    adjusted_info = deepcopy(pano_info)
    angle = float(adjusted_info.get("angle", 0))
    adjusted_info["angle"] = round((angle + yaw) % 360, 1)
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