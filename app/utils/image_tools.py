import os
from PIL import Image, ImageOps

ALLOWED_EXT = {"jpg", "jpeg", "png", "webp"}

def compress_product_image(
    input_path: str,
    output_path: str,
    max_size=(900, 900),   # good for product cards
    quality=78,            # 70-85 is usually great
    to_webp=True
):
    """
    - Fix EXIF rotation
    - Resize (keep ratio)
    - Convert to WebP (recommended) OR keep JPEG
    - Save optimized
    """
    img = Image.open(input_path)
    img = ImageOps.exif_transpose(img)  # fixes rotated phone images

    # Convert RGBA/PNG to RGB when saving to web formats
    if img.mode in ("RGBA", "P"):
        img = img.convert("RGB")

    # Resize
    img.thumbnail(max_size)

    if to_webp:
        # force .webp output
        if not output_path.lower().endswith(".webp"):
            output_path = os.path.splitext(output_path)[0] + ".webp"

        img.save(output_path, "WEBP", quality=quality, method=6)
        return output_path

    # else: keep jpeg
    img.save(output_path, "JPEG", quality=quality, optimize=True, progressive=True)
    return output_path