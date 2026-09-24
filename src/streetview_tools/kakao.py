import requests

from ._downloader import (
    download_tiles_image,
    equirect_to_perspective,
    resolve_output_size,
    select_visible_tiles,
    adjust_pano_angle,
    save_image,
    save_pano_info_json,
    normalize_size,
    select_zoom,
)
from ._geometry import add_spot_info
from ._http import REQUEST_HEADERS

_CACHE = {}


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
        "service": "kakao",
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


def get_img_face(panoid, *, yaw=0.0, pitch=0.0, width=None, height=None):
    """Return a perspective view of a Kakao Roadview panorama as a PIL image.

    ``yaw`` is the left/right viewing angle in degrees (0 = forward, positive
    = right) and ``pitch`` is the up/down viewing angle in degrees (positive
    = up). ``width``/``height`` control the output size; the field of view is
    derived from them automatically instead of being given directly: with
    both omitted, the panorama's default face size (1024x1024) is used; with
    only ``width``, a ``width``x``width`` square is returned; with both, the
    horizontal field of view stays fixed and the vertical field of view
    expands to fit the requested aspect ratio.
    """
    panoid = str(panoid).strip()
    image_path = get_pano_info(panoid)["others"]["img_path"]

    rows, cols, tile_size = 4, 8, 512
    width, height = resolve_output_size(width, height, rows * tile_size)
    needed = select_visible_tiles(rows, cols, yaw, pitch, width, height)

    tiles = [
        {"x": col * tile_size, "y": row * tile_size,
         "src": _tile_url(image_path, row * cols + col + 1)}
        for row in range(rows) for col in range(cols)
        if (row, col) in needed
    ]

    panorama_image = download_tiles_image(
        tiles, canvas_size=(cols * tile_size, rows * tile_size)
    )
    return equirect_to_perspective(panorama_image, yaw, pitch, width=width, height=height)


def save_img_face(panoid, *, yaw=0.0, pitch=0.0, file_name=None, width=None, height=None, save_json=False):
    """Download and save a Kakao Roadview perspective view PNG."""
    image = get_img_face(panoid, yaw=yaw, pitch=pitch, width=width, height=height)
    output_path = save_image(image, file_name or f"{panoid}.png")
    if save_json:
        save_pano_info_json(adjust_pano_angle(get_pano_info(panoid), yaw), output_path)
    return output_path


def _tile_url(image_path, tile_number):
    suffix = image_path[image_path.rfind("/"):]
    return f"https://map.kakaocdn.net/map_roadview{image_path}{suffix}_{tile_number:02d}.jpg"
