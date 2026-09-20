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


def get_pano_info(panoid, *, spot=False):
    """Return Naver Roadview metadata for ``panoid``.

    Args:
        panoid: Naver panorama identifier.
        spot: Include nearby panorama information when ``True``.
    """
    panoid = str(panoid).strip()
    if not panoid:
        raise ValueError("panoid must not be empty")
    if panoid in _CACHE and (not spot or _CACHE[panoid].get("spot")):
        return _CACHE[panoid]

    response = requests.get(
        f"https://panorama.map.naver.com/metadataV3/basic/{panoid}?lang=ko",
        headers=REQUEST_HEADERS,
        timeout=10,
    )
    response.raise_for_status()
    data = response.json()
    panorama = {
        "id": data["id"], "date": data["info"]["photodate"],
        "lon": float(data["longitude"]), "lat": float(data["latitude"]),
        "angle": float(data["camera_angle"][1]),
        "addr1": data["info"]["description"], "addr2": data["info"]["title"],
        "others": {"proj_type": data["proj_type"]}, "spot": [],
    }
    for link in data.get("links", []):
        if link["id"] != panorama["id"]:
            panorama["spot"].append({"id": link["id"], "lon": link["longitude"], "lat": link["latitude"]})
    panorama = add_spot_info(panorama)
    _CACHE[panoid] = panorama
    return panorama


def get_img(
    panoid,
    *,
    proj_type="cubic",
    width=None,
    height=None,
):
    """Return a Naver panorama as a PIL image.

    ``width`` selects the smallest available source zoom at least as wide as
    requested. When omitted, the default zoom for the selected projection is
    used.
    """
    panoid = str(panoid).strip()
    pano_info = None
    if proj_type == "equirect":
        pano_info = get_pano_info(panoid)
        if pano_info["others"]["proj_type"] != "equirect":
            raise ValueError("This panorama does not support equirect projection")
        zoom = select_zoom(
            width,
            {0: 1024, 1: 2048, 2: 4096, 3: 8192},
            default_zoom=2,
        )
        if zoom == 0:
            tiles = [{"x": 0, "y": 0, "src": _equirect_url(panoid, zoom, None, None)}]
        else:
            tiles = [{"x": x * 512, "y": y * 512, "src": _equirect_url(panoid, zoom, x, y)}
                     for y in range(2 ** zoom) for x in range(2 ** (zoom + 1))]
        size = (1024 * 2 ** zoom, 512 * 2 ** zoom)
    else:
        zoom = select_zoom(
            width,
            {0: 1536, 1: 6144},
            default_zoom=1,
        )
        if zoom == 0:
            tiles, size = [{"x": 0, "y": 0, "src": _cubic_url(panoid, zoom, None, None, None)}], (1536, 256)
        else:
            faces = "lfrbdu"
            tiles = [{"x": x * 512 + face_index * 1024, "y": y * 512,
                      "src": _cubic_url(panoid, zoom, face, x, y)}
                     for face_index, face in enumerate(faces) for y in range(2) for x in range(2)]
            size = (6144, 1024)
    image = download_tiles_image(
        tiles,
        [0, 0, *size],
    )
    target_size = normalize_size(width, height)
    if target_size:
        image = image.resize(target_size)
    return image


def save_img(
    panoid,
    *,
    file_name=None,
    proj_type="cubic",
    width=None,
    height=None,
    save_json=False,
):
    """Download and save a Naver panorama PNG, optionally with JSON metadata."""
    image = get_img(
        panoid, proj_type=proj_type, width=width, height=height
    )
    output_path = save_image(image, file_name or f"{panoid}.png")
    if save_json:
        save_pano_info_json(get_pano_info(panoid), output_path)
    return output_path


def get_img_face(
    panoid,
    direction,
    *,
    proj_type="cubic",
    width=None,
):
    """Return Naver panorama direction faces as PIL images.

    ``direction`` must be one of ``l``, ``f``, ``r``, ``b``, ``d``, or ``u``.
    Cubic panoramas use their direction-specific tiles; equirectangular
    panoramas are converted to a cubemap face with the common converter.
    """
    panoid = str(panoid).strip()
    directions = [direction] if isinstance(direction, str) else list(direction)
    directions = [str(item).lower().strip() for item in directions]
    if not directions or any(item not in "lfrbdu" for item in directions):
        raise ValueError("direction must contain only: l, f, r, b, d, u")

    if proj_type == "equirect":
        pano_info = get_pano_info(panoid)
        if pano_info["others"]["proj_type"] != "equirect":
            raise ValueError("This panorama does not support equirect projection")
        zoom = select_zoom(width, {level: 512 * 2 ** level for level in range(4)}, 2)
        tiles = (
            [{"x": 0, "y": 0, "src": _equirect_url(panoid, zoom, None, None)}]
            if zoom == 0
            else [
                {"x": x * 512, "y": y * 512,
                 "src": _equirect_url(panoid, zoom, x, y)}
                for y in range(2 ** zoom)
                for x in range(2 ** (zoom + 1))
            ]
        )
        panorama = download_tiles_image(tiles)
        images = [
            equirect_to_face(panorama, item, face_size=panorama.height // 2)
            for item in directions
        ]
        if width is not None:
            images = [image.resize((width, width)) for image in images]
        return images

    zoom = 1
    images = []
    for item in directions:
        tiles = [
            {"x": x * 512, "y": y * 512, "src": _cubic_url(panoid, zoom, item, x, y)}
            for y in range(2)
            for x in range(2)
        ]
        image = download_tiles_image(tiles, crop_box=[0, 0, 1024, 1024])
        images.append(image.resize((width, width)) if width else image)
    return images


def save_img_face(
    panoid,
    direction,
    *,
    file_name=None,
    proj_type="cubic",
    width=None,
    save_json=False,
):
    """Download and save Naver panorama face PNG files."""
    directions = [direction] if isinstance(direction, str) else list(direction)
    directions = [str(item).lower().strip() for item in directions]
    images = get_img_face(panoid, directions, proj_type=proj_type, width=width)
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


def _equirect_url(panoid, zoom, x, y):
    if zoom == 0:
        return f"https://panorama.pstatic.net/imageV3/{panoid}/P"
    return f"https://panorama.pstatic.net/imageV3/{panoid}/{zoom - 1}/{x + 1}/{y + 1}"


def _cubic_url(panoid, zoom, face, x, y):
    if zoom == 0:
        return f"https://panorama.pstatic.net/image/{panoid}/512/P"
    return f"https://panorama.pstatic.net/image/{panoid}/512/M/{face}/{x + 1}/{y + 1}"