from pathlib import Path

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
_FACE_DIRECTIONS = "lfrbdu"


def get_pano_info(panoid, *, spot=False):
    """Return Kakao Roadview metadata for ``panoid``.

    Args:
        panoid: Kakao panorama identifier.
        spot: Include nearby panorama information when ``True``.
    """
    panoid = str(panoid).strip()
    if not panoid:
        raise ValueError("panoid must not be empty")
    if panoid in _CACHE and (not spot or _CACHE[panoid].get("spot")):
        return _CACHE[panoid]

    response = requests.get(
        f"https://rv.map.kakao.com/roadview-search/v2/node/{panoid}",
        headers=REQUEST_HEADERS,
        timeout=10,
    )
    response.raise_for_status()
    data = response.json()["street_view"]["street"]
    panorama = {
        "id": data["id"], "date": data["shot_date"],
        "lon": float(data["wgsx"]), "lat": float(data["wgsy"]),
        "angle": float(data["angle"]), "addr1": data["addr"],
        "addr2": data["st_name"], "others": {"img_path": data["img_path"]}, "spot": [],
    }
    for spot in data.get("spot", []):
        if spot["id"] != panorama["id"]:
            panorama["spot"].append({"id": spot["id"], "lon": spot["wgsx"], "lat": spot["wgsy"]})
    panorama = add_spot_info(panorama)
    _CACHE[panoid] = panorama
    return panorama


def get_img(
    panoid,
    *,
    width=None,
    height=None,
):
    """Return a Kakao Roadview panorama as a PIL image.

    ``width`` selects the smallest source zoom at least as wide as requested;
    without it, Kakao's default zoom is used.
    """
    panorama = get_pano_info(panoid)
    zoom = select_zoom(
        width,
        {0: 1280, 1: 4096},
        default_zoom=1,
    )
    image_path = panorama["others"]["img_path"]
    if zoom == 0:
        tiles = [{"x": 0, "y": 0, "src": f"https://map.kakaocdn.net/map_roadview{image_path}.jpg"}]
        crop_box = [0, 0, 1280, 640]
    else:
        tiles = [{"x": x * 512, "y": y * 512,
                  "src": _tile_url(image_path, tile_number)}
                 for tile_number, (y, x) in enumerate(
                     ((y, x) for y in range(4) for x in range(8)), 1
                 )]
        crop_box = [0, 0, 4096, 2048]
    image = download_tiles_image(
        tiles,
        crop_box,
    )
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
    """Download and save a Kakao panorama PNG, optionally with JSON metadata."""
    image = get_img(panoid, width=width, height=height)
    output_path = save_image(image, file_name or f"{panoid}.png")
    if save_json:
        save_pano_info_json(get_pano_info(panoid), output_path)
    return output_path


def get_img_face(panoid, direction, *, width=None):
    """Return Kakao panorama direction faces as PIL images.

    ``direction`` may be one direction or a sequence of ``l``, ``f``, ``r``,
    ``b``, ``d``, and ``u``. ``width`` controls the final square face size.
    """
    panoid = str(panoid).strip()
    directions = [direction] if isinstance(direction, str) else list(direction)
    directions = [str(item).lower().strip() for item in directions]
    if not directions or any(item not in _FACE_DIRECTIONS for item in directions):
        raise ValueError("direction must contain only: l, f, r, b, d, u")
    panorama_width, panorama_height = 4096, 2048
    face_size = panorama_width // 4
    image_path = get_pano_info(panoid)["others"]["img_path"]

    tiles = [
        {"x": x * 512, "y": y * 512,
         "src": _tile_url(image_path, tile_number)}
        for tile_number, (y, x) in enumerate(
            ((y, x) for y in range(4) for x in range(8)), 1
        )
    ]

    panorama_image = download_tiles_image(tiles)
    images = [
        equirect_to_face(panorama_image, item, face_size=face_size)
        for item in directions
    ]
    if width is not None:
        images = [image.resize((width, width)) for image in images]
    return images


def save_img_face(panoid, direction, *, file_name=None, width=None, save_json=False):
    """Download and save Kakao panorama face PNG files."""
    directions = [direction] if isinstance(direction, str) else list(direction)
    directions = [str(item).lower().strip() for item in directions]
    images = get_img_face(panoid, directions, width=width)
    pano_info = get_pano_info(panoid) if save_json else None
    output_paths = []
    for item, image in zip(directions, images):
        if file_name and len(directions) == 1:
            output_name = file_name
        elif file_name:
            path = Path(file_name)
            output_name = path.with_name(f"{path.stem}_{item}{path.suffix or '.png'}")
        else:
            output_name = f"{panoid}_{item}.png"
        output_path = save_image(image, output_name)
        if pano_info is not None:
            save_pano_info_json(adjust_face_angle(pano_info, item), output_path)
        output_paths.append(output_path)
    return output_paths


def _tile_url(image_path, tile_number):
    suffix = image_path[image_path.rfind("/"):]
    return f"https://map.kakaocdn.net/map_roadview{image_path}{suffix}_{tile_number:02d}.jpg"
