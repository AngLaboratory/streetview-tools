import json
from pathlib import Path
from urllib.parse import quote

import requests

from ._downloader import (
    download_tiles_image,
    equirect_to_face,
    adjust_face_angle,
    save_image,
    save_pano_info_json,
    normalize_size,
    select_zoom,
)
from ._geometry import add_spot_info
from ._http import REQUEST_HEADERS

_CACHE = {}
_IMG_BLOCK_SIZE = 512
_FACE_DIRECTIONS = "lfrbdu"


def get_pano_info(panoid, *, spot=False):
    """Return Google Street View metadata for ``panoid``.

    Args:
        panoid: Google panorama identifier.
        spot: Include nearby panorama information when ``True``.
    """
    panoid = str(panoid).strip()
    if not panoid:
        raise ValueError("panoid must not be empty")

    if panoid in _CACHE and (not spot or _CACHE[panoid].get("spot")):
        return _CACHE[panoid]

    response = requests.get(
        _get_url(panoid, spot=spot),
        headers=REQUEST_HEADERS,
        timeout=10,
    )

    response.raise_for_status()

    panorama = _parse_response(response.text, panoid=panoid)
    _CACHE[panoid] = panorama
    return panorama

def get_img(
    panoid,
    *,
    width=None,
    height=None,
):
    """Return a Google equirectangular panorama as a PIL image.

    ``width`` selects the smallest source zoom that is at least as wide as
    requested, then the image is resized to the requested 2:1 dimensions.
    When ``width`` is omitted, Google's default zoom is used.
    """
    panoid = str(panoid).strip()
    zoom_seed = get_pano_info(panoid)["others"]["zoom_seed"]

    zoom = select_zoom(
        width,
        {level: zoom_seed * (2 ** level) * 2 for level in range(6)},
        default_zoom=3,
    )

    y_size = zoom_seed * (2 ** zoom)
    x_size = y_size * 2
    tiles = [
        {"x": x * _IMG_BLOCK_SIZE, "y": y * _IMG_BLOCK_SIZE,
         "src": _tile_url(panoid, zoom, x, y)}
        for y in range((y_size + _IMG_BLOCK_SIZE - 1) // _IMG_BLOCK_SIZE)
        for x in range((x_size + _IMG_BLOCK_SIZE - 1) // _IMG_BLOCK_SIZE)
    ]
    image = download_tiles_image(tiles, crop_box=[0, 0, x_size, y_size])
    target_size = normalize_size(width, height)
    if target_size:
        image = image.resize(target_size)
    return image


def save_img(
    panoid,
    *,
    file_name=None,
    width=None,
    height=None,
    save_json=False,
):
    """Download and save a Google panorama PNG, optionally with JSON metadata."""
    panoid = str(panoid).strip()
    image = get_img(
        panoid,
        width=width,
        height=height,
    )
    output_path = save_image(image, file_name or f"{panoid}.png")
    if save_json:
        save_pano_info_json(get_pano_info(panoid), output_path)
    return output_path


def get_img_face(
    panoid,
    direction,
    *,
    width=None,
):
    """Return square Google panorama faces as PIL images.

    ``direction`` may be one direction or a sequence of ``l``, ``f``, ``r``,
    ``b``, ``d``, and ``u``. ``width`` selects the smallest face source zoom
    at least that wide; omitted width uses Google's default zoom.
    """
    panoid = str(panoid).strip()
    directions = _normalize_directions(direction)
    zoom_seed = get_pano_info(panoid)["others"]["zoom_seed"]

    zoom = select_zoom(
        width,
        {level: zoom_seed * (2 ** level) // 2 for level in range(6)},
        default_zoom=3,
    )

    panorama_height = zoom_seed * (2 ** zoom)
    panorama_width = panorama_height * 2
    tiles = [
        {"x": x * _IMG_BLOCK_SIZE, "y": y * _IMG_BLOCK_SIZE,
         "src": _tile_url(panoid, zoom, x, y)}
        for y in range((panorama_height + _IMG_BLOCK_SIZE - 1) // _IMG_BLOCK_SIZE)
        for x in range((panorama_width + _IMG_BLOCK_SIZE - 1) // _IMG_BLOCK_SIZE)
    ]
    panorama = download_tiles_image(tiles, crop_box=[0, 0, panorama_width, panorama_height])

    images = [equirect_to_face(panorama, item) for item in directions]
    if width is not None:
        target_size = normalize_size(width)[0]
        images = [image.resize((target_size, target_size)) for image in images]
    return images


def save_img_face(
    panoid,
    direction,
    *,
    file_name=None,
    width=None,
    save_json=False,
):
    """Download and save square Google panorama face PNG files."""
    directions = _normalize_directions(direction)
    images = get_img_face(
        panoid, directions, width=width
    )
    pano_info = get_pano_info(panoid) if save_json else None
    output_paths = []
    for item, image in zip(directions, images):
        output_path = save_image(
            image, _face_file_name(panoid, item, file_name, len(directions))
        )
        if pano_info is not None:
            save_pano_info_json(adjust_face_angle(pano_info, item), output_path)
        output_paths.append(output_path)
    return output_paths


def _normalize_directions(direction):
    directions = [direction] if isinstance(direction, str) else list(direction)
    directions = [str(item).lower().strip() for item in directions]
    if not directions or any(item not in _FACE_DIRECTIONS for item in directions):
        raise ValueError("direction must contain only: l, f, r, b, d, u")
    return directions


def _face_file_name(panoid, direction, file_name, count):
    if not file_name:
        return f"{panoid}_{direction}.png"
    if count == 1:
        return file_name
    path = Path(file_name)
    return path.with_name(f"{path.stem}_{direction}{path.suffix or '.png'}")


def _get_url(panoid, *, spot):
    spot_call = "!1e6" if spot else "!1e1"
    e_code = "10" if len(panoid) in (43, 44) else "2"
    
    return (
        "https://www.google.com/maps/photometa/v1?authuser=0&hl=en&gl=us&pb="
        "!1m4!1smaps_sv.tactile!11m2!2m1!1b1!2m2!1sen!2sus"
        f"!3m3!1m2!1e{e_code}!2s{quote(panoid)}"
        f"!4m57!1e1!1e2!1e4!1e1!1e1!1e1!1e1{spot_call}"
        "!2m1!1e1!4m1!1i48!5m1!1e1!5m1!1e2!6m1!1e1!6m1!1e2"
        "!9m36!1m3!1e6!2b0!3e0!1m3!1e6!2b0!3e1!1m3!1e6!2b0!3e2"
        "!1m3!1e6!2b0!3e3!1m3!1e6!2b0!3e4!1m3!1e6!2b0!3e5"
        "!1m3!1e6!2b0!3e6!1m3!1e6!2b0!3e7!1m3!1e6!2b0!3e8"
    )


def _parse_response(text, panoid=""):
    try:
        parsed = json.loads(text[5:])
        data = parsed[1][0]
    except (json.JSONDecodeError, IndexError, TypeError):
        raise ValueError(f"Invalid response from Google Street View for '{panoid}'")

    if not data or len(data) < 6 or data[2] is None or data[5] is None:
        target_id = panoid or (data[1][1] if len(data) > 1 and len(data[1]) > 1 else "unknown")
        raise ValueError(f"Google Street View panorama not found or unavailable: '{target_id}'")

    addresses = data[3][2] if data[3] is not None and len(data[3]) > 2 else []
    date_str = ""
    if len(data) > 6 and data[6] and len(data[6]) > 7 and data[6][7]:
        date_str = f"{data[6][7][0]}-{data[6][7][1]:02d}-01"

    panorama = {
        "id": data[1][1],
        "date": date_str,
        "lon": float(data[5][0][1][0][3]),
        "lat": float(data[5][0][1][0][2]),
        "angle": round(float(data[5][0][1][2][0]), 1),
        "addr1": addresses[1][0] if len(addresses) > 1 else (addresses[0][0] if addresses else ""),
        "addr2": addresses[0][0] if len(addresses) > 1 else "",
        "others": {"zoom_seed": data[2][3][0][0][0][0]},
        "spot": [],
    }
    if len(data[5][0]) > 3 and data[5][0][3]:
        for item in data[5][0][3][0]:
            if len(item) >= 3 and item[0][1] != panorama["id"] and item[2] is not None:
                panorama["spot"].append({
                    "id": item[0][1],
                    "lon": item[2][0][3],
                    "lat": item[2][0][2],
                    "x": item[2][0][3],
                    "y": item[2][0][2],
                })
    return add_spot_info(panorama)


def _tile_url(panoid, zoom, x, y):
    return f"https://streetviewpixels-pa.googleapis.com/v1/tile?cb_client=maps_sv.tactile&zoom={zoom}&panoid={panoid}&x={x}&y={y}"