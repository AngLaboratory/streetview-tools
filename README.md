# streetview-tools

Retrieve panorama metadata and download panorama images from Google Street View,
Naver Roadview, and Kakao Roadview.

## Installation

```bash
pip install streetview-tools
```

## Usage

```python
from streetview_tools import google

pano = google.get_pano_info(panoid="PANORAMA_ID")
google.save_img(
	panoid="PANORAMA_ID",
	file_name="output.png",
	width=2048,
)
```

The same functions are available from `streetview_tools.naver` and
`streetview_tools.kakao`.

Google and Kakao also provide `save_img_face()` for saving a square direction
crop from their equirectangular panorama images. The supported directions are
`l`, `f`, `r`, `b`, `d`, and `u`, and the default filename is
`PANORAMA_ID_<direction>.png`.

For Naver cubic panoramas, a single direction can be saved as a square image:

```python
from streetview_tools import naver

naver.save_img_face(
	panoid="PANORAMA_ID",
	direction="u",
	width=800,
)
# PANORAMA_ID_u.png
```

Valid directions are `l`, `f`, `r`, `b`, `d`, and `u`. A direction can also be
provided as a list, which returns or saves one image per direction:

```python
images = naver.get_img_face(
	panoid="PANORAMA_ID",
	direction=["l", "f", "r"],
	width=800,
)
paths = naver.save_img_face(
	panoid="PANORAMA_ID",
	direction=["l", "f", "r"],
	width=800,
)
```

Each function returns a list for face requests. `get_img()` returns one PIL
image, while `save_img()` returns one output path.

The same `save_img_face()` function can convert Naver equirectangular images by
passing `proj_type="equirect"`. Google and Kakao use the same common
equirectangular-to-cubemap conversion internally.

`width` and `height` are optional. If either is provided, the output is always
2:1. When both are provided, `width` takes precedence. For example,
`width=1024, height=900` produces a `1024 x 512` image, while `height=512`
produces a `1024 x 512` image. An odd width is rounded down to the nearest
even width so the final image can remain exactly 2:1.

When `width` is provided, the smallest available zoom that is at least as wide
as the requested output is downloaded first, then resized to the final size.
Without `width`, each service's default zoom is used. `zoom` is an internal
implementation detail and is not part of the public function arguments.

This package accesses public web endpoints used by each map service. Endpoint
formats and availability may change independently of this package.

Pass `save_json=True` to `save_img()` or `save_img_face()` to save the
`get_pano_info()` result beside the image. For example, `pano.png` produces
`pano.json`.

For `save_img_face()`, the JSON `angle` is adjusted for the selected direction:
`f` keeps the original angle, `r` adds 90 degrees, `l` subtracts 90 degrees,
and `b` adds 180 degrees. Angles are normalized to 0-360 degrees; `u` and `d`
keep the original horizontal angle.