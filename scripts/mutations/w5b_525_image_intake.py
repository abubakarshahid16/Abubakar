"""#525: a scan sent as an image file takes the PDF path. Ids M5701-M5711."""
from __future__ import annotations

from ._base import APP, FRONTEND_SRC, Mutation

_T = "tests/test_w5b_525_image_intake.py"
_U = APP / "upload.py"
_TAG = ("w5b", "intake")


def _m(i, desc, anchor, repl, kw=None, path=_U):
    return Mutation(id=f"M{i}", phase=i, description=desc, path=path, anchor=anchor,
                    replacement=repl, target=_T, keyword=kw, tags=_TAG)


MUTATIONS: tuple[Mutation, ...] = (
    _m(5701, "an image is refused at the first block",
       "                        or (image_accepted() and image_kind(block))):", "                        ):",
       "accepted_and_queued or same_chunks"),
    _m(5702, "an image is stored but never indexed",
       "    indexed = indexed or kind in IMAGE_KINDS", "    indexed = indexed",
       "accepted_and_queued"),
    _m(5703, "the image flag is ignored",
       "    return bool(settings.image_input_enabled)", "    return True", "input_is_off"),
    _m(5704, "an image upload is not validated",
       "        if kind in IMAGE_KINDS:\n            validate_image(temp_path)\n", "",
       "only_starts_like or pixel_limit or too_many_pages or every_frame"),
    _m(5705, "the pixel limit is not applied",
       "if width < 1 or height < 1 or width * height > MAX_IMAGE_PIXELS:",
       "if width < 1 or height < 1:", "pixel_limit"),
    _m(5706, "the frame limit is not applied",
       "            if frames > MAX_IMAGE_FRAMES:", "            if False:", "too_many_pages"),
    _m(5707, "only the first TIFF frame is checked",
       "            for index in range(frames):", "            for index in range(1):", "every_frame"),
    _m(5708, "an image is stored under a .pdf name",
       "                    KIND_PNG: \".png\", KIND_JPEG: \".jpg\", KIND_TIFF: \".tif\"}", "}",
       "accepted_and_queued"),
    _m(5709, "the refusal hint still says PDF and Word only",
       "    \"This system reads PDF, Word (.docx) and scanned images (PNG, JPEG, TIFF). Save the \"",
       "    \"This system reads PDF and Word (.docx). Save the \"", "hint_names_images"),
    _m(5710, "an original scan is served as a download of unknown type",
       "    \".png\": \"image/png\",\n", "", "served_as_an_image", path=APP / "main.py"),
)

MUTATIONS = MUTATIONS + (
    Mutation(id="M5711", phase=5711, runner="vitest",
             description="the uploader does not offer scanned images",
             path=FRONTEND_SRC / "components" / "Uploader.tsx",
             anchor="image/png,.png,image/jpeg,.jpg,.jpeg,image/tiff,.tif,.tiff,", replacement="",
             target="src/components/Uploader.word.test.tsx", keyword="offers scanned images", tags=_TAG),
)
