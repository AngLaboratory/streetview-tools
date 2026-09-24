import requests
from PIL import Image

from ._downloader import (
    download_tiles_image,
    equirect_to_perspective,
    cubemap_to_equirect,
    resolve_output_size,
    select_visible_tiles,
    select_visible_faces,
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
        "service": "naver",
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
    *,
    yaw=0.0,
    pitch=0.0,
    proj_type="cubic",
    width=None,
    height=None,
):
    """Return a perspective view of a Naver panorama as a PIL image.

    ``yaw`` is the left/right viewing angle in degrees (0 = forward, positive
    = right) and ``pitch`` is the up/down viewing angle in degrees (positive
    = up). ``width``/``height`` control the output size; the field of view is
    derived from them automatically instead of being given directly: with
    both omitted, the panorama's default size (1024x1024) is used; with only
    ``width``, a ``width``x``width`` square is returned; with both, the
    horizontal field of view stays fixed and the vertical field of view
    expands to fit the requested aspect ratio. Cubic panoramas are stitched
    from their six direction tiles into an equirectangular image first;
    equirectangular panoramas are used directly.
    """
    panoid = str(panoid).strip()

    if proj_type == "equirect":
        pano_info = get_pano_info(panoid)
        if pano_info["others"]["proj_type"] != "equirect":
            raise ValueError("This panorama does not support equirect projection")
        zoom = select_zoom(width, {level: 512 * 2 ** level for level in range(4)}, 2)
        if zoom == 0:
            panorama = download_tiles_image(
                [{"x": 0, "y": 0, "src": _equirect_url(panoid, zoom, None, None)}]
            )
            width, height = resolve_output_size(width, height, panorama.height)
        else:
            rows, cols = 2 ** zoom, 2 ** (zoom + 1)
            width, height = resolve_output_size(width, height, rows * 512)
            needed = select_visible_tiles(rows, cols, yaw, pitch, width, height)
            tiles = [
                {"x": x * 512, "y": y * 512, "src": _equirect_url(panoid, zoom, x, y)}
                for y in range(rows) for x in range(cols)
                if (y, x) in needed
            ]
            panorama = download_tiles_image(tiles, canvas_size=(cols * 512, rows * 512))
    else:
        zoom = 1
        face_size = 1024
        width, height = resolve_output_size(width, height, face_size * 2)
        needed_faces = select_visible_faces(yaw, pitch, width, height)
        faces = {}
        for letter in "lfrbdu":
            if letter in needed_faces:
                tiles = [
                    {"x": x * 512, "y": y * 512, "src": _cubic_url(panoid, zoom, letter, x, y)}
                    for y in range(2)
                    for x in range(2)
                ]
                faces[letter] = download_tiles_image(tiles, crop_box=[0, 0, face_size, face_size])
            else:
                faces[letter] = Image.new("RGB", (face_size, face_size))
        panorama = cubemap_to_equirect(faces, face_size * 2)

    return equirect_to_perspective(panorama, yaw, pitch, width=width, height=height)


def save_img_face(
    panoid,
    *,
    yaw=0.0,
    pitch=0.0,
    file_name=None,
    proj_type="cubic",
    width=None,
    height=None,
    save_json=False,
):
    """Download and save a Naver panorama perspective view PNG."""
    image = get_img_face(panoid, yaw=yaw, pitch=pitch, proj_type=proj_type, width=width, height=height)
    output_path = save_image(image, file_name or f"{panoid}.png")
    if save_json:
        save_pano_info_json(adjust_pano_angle(get_pano_info(panoid), yaw), output_path)
    return output_path


def _equirect_url(panoid, zoom, x, y):
    if zoom == 0:
        return f"https://panorama.pstatic.net/imageV3/{panoid}/P"
    return f"https://panorama.pstatic.net/imageV3/{panoid}/{zoom - 1}/{x + 1}/{y + 1}"


def _cubic_url(panoid, zoom, face, x, y):
    if zoom == 0:
        return f"https://panorama.pstatic.net/image/{panoid}/512/P"
    return f"https://panorama.pstatic.net/image/{panoid}/512/M/{face}/{x + 1}/{y + 1}"