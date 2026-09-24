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

All three services also provide `get_img_face()` / `save_img_face()` for
extracting a single perspective view from the panorama, aimed with `yaw`
(left/right, degrees, 0 = forward, positive = right) and `pitch` (up/down,
degrees, positive = up):

```python
from streetview_tools import naver

image = naver.get_img_face(
	panoid="PANORAMA_ID",
	yaw=45,
	pitch=10,
	width=800,
)
path = naver.save_img_face(
	panoid="PANORAMA_ID",
	yaw=45,
	pitch=10,
	width=800,
)
# PANORAMA_ID.png
```

There is no `fov` argument; the field of view is derived from `width`/`height`
instead:

- Both omitted: the panorama's default face size is returned (usually
  1024x1024).
- Only `width`: a `width` x `width` square is returned.
- Both `width` and `height`: a `width` x `height` rectangle is returned. The
  horizontal field of view stays fixed and the vertical field of view expands
  or shrinks to match the requested aspect ratio, so a taller output captures
  more sky/ground rather than stretching the image.

`get_img_face()` returns one PIL image and `save_img_face()` returns one
output path — there is no direction list/array form.

`get_img_face()` / `save_img_face()` only download the source tiles (or, for
Naver cubic panoramas, the direction faces) that overlap the requested view,
plus a small safety margin, instead of the whole panorama. Skipped areas play
no part in the output.

The same `get_img_face()` / `save_img_face()` functions can convert Naver
equirectangular images by passing `proj_type="equirect"` (cubic is the
default). For cubic panoramas, the six direction tiles are stitched into an
equirectangular image internally before the perspective view is extracted.
Google and Kakao panoramas are already equirectangular and are used directly.

`get_img()` / `save_img()` take separate `width`/`height` arguments (see
above) that always produce a 2:1 equirectangular image. If either is
provided, the output is always 2:1. When both are provided, `width` takes
precedence. For example, `width=1024, height=900` produces a `1024 x 512`
image, while `height=512` produces a `1024 x 512` image. An odd width is
rounded down to the nearest even width so the final image can remain exactly
2:1.

When `width` is provided, the smallest available zoom that is at least as wide
as the requested output is downloaded first, then resized to the final size.
Without `width`, each service's default zoom is used. `zoom` is an internal
implementation detail and is not part of the public function arguments.

This package accesses public web endpoints used by each map service. Endpoint
formats and availability may change independently of this package.

Pass `save_json=True` to `save_img()` or `save_img_face()` to save the
`get_pano_info()` result beside the image. For example, `pano.png` produces
`pano.json`.

For `save_img_face()`, the JSON `angle` is adjusted by adding `yaw` degrees and
normalizing to 0-360 degrees.