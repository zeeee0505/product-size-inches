#!/usr/bin/env python3
"""Preview dual-unit product labels, then export or replace with a backup."""
import argparse
from decimal import Decimal, ROUND_HALF_UP, localcontext
from hashlib import sha256
from io import BytesIO
import json
import os
from pathlib import Path, PurePosixPath
import re
from shutil import copymode
import sys
import tempfile
import unicodedata
import zipfile

try:
    from PIL import Image, ImageChops, ImageColor, ImageDraw, ImageFont, ImageOps
except ImportError:
    sys.exit("Pillow is required. Run: python -m pip install 'Pillow>=10.1'")

FORMATS = {".jpg": "JPEG", ".jpeg": "JPEG", ".png": "PNG", ".webp": "WEBP"}
METRIC = re.compile(r"(\d+(?:\.\d+)?)(cm|mm)?", re.IGNORECASE)
ORIENTATION = {
    2: Image.Transpose.FLIP_LEFT_RIGHT, 3: Image.Transpose.ROTATE_180,
    4: Image.Transpose.FLIP_TOP_BOTTOM, 5: Image.Transpose.TRANSPOSE,
    6: Image.Transpose.ROTATE_90, 7: Image.Transpose.TRANSVERSE,
    8: Image.Transpose.ROTATE_270,
}


def sha(data):
    return sha256(data).hexdigest()


def read_json(path):
    return json.loads(path.read_text(encoding="utf-8-sig"))


def write_json(path, value):
    atomic_write(path, (json.dumps(value, ensure_ascii=False, indent=2) + "\n").encode("utf-8"))


def atomic_write(path, data, preserve=False):
    with tempfile.NamedTemporaryFile(dir=path.parent, prefix=".size-", delete=False) as handle:
        temporary = Path(handle.name)
        try:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        except BaseException:
            handle.close()
            temporary.unlink(missing_ok=True)
            raise
    try:
        if preserve:
            copymode(path, temporary)
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def scoped_file(root, raw):
    normalized = PurePosixPath(raw)
    if not normalized.parts or normalized.is_absolute() or any(
        p in (".", "..") or ":" in p or "\\" in p for p in normalized.parts
    ):
        raise ValueError(f"Expected a relative path using '/': {raw!r}")
    path = root
    for part in normalized.parts:
        path = path / part
        if path.is_symlink() or getattr(path, "is_junction", lambda: False)():
            raise ValueError(f"Linked path requires an explicit separate source: {raw}")
    resolved = path.resolve(strict=True)
    if not resolved.is_file() or not resolved.is_relative_to(root):
        raise ValueError(f"Expected a file inside {root}: {raw}")
    return resolved


def convert(edit):
    source = edit["source"]
    if "confirmed_source" in edit:
        if not edit.get("reason", "").strip():
            raise ValueError(f"Record the evidence for the correction to {source!r}")
        source = edit["confirmed_source"]
    normalized = unicodedata.normalize("NFKC", source)
    for mark, unit in (("厘米", "cm"), ("公分", "cm"), ("毫米", "mm")):
        normalized = normalized.replace(mark, unit)
    terms = [METRIC.fullmatch(re.sub(r"\s+", "", term)) for term in normalized.split("+")]
    if not all(terms) or not terms[-1][2]:
        raise ValueError(f"Unsupported measurement: {source!r}; expected cm/mm or a '+' expression")
    centimeters, inches = [], []
    with localcontext() as ctx:
        ctx.prec = 40
        for term in terms:
            unit = (term[2] or terms[-1][2]).lower()
            number = Decimal(term[1])
            cm = number if unit == "cm" else number / Decimal(10)
            centimeters.append(format(cm.normalize(), "f"))
            inches.append(str((cm / Decimal("2.54")).quantize(Decimal("0.1"), rounding=ROUND_HALF_UP)))
    layout = edit.get("layout", "inline")
    if layout not in ("inline", "stacked"):
        raise ValueError(f"Unknown label layout: {layout!r}")
    separator = " /\n" if layout == "stacked" else " / "
    return edit.get("prefix", "") + "+".join(centimeters) + " cm" + separator + "+".join(inches) + " in"


def scan(root, work):
    files = []
    for path in sorted(root.rglob("*")):
        if path.suffix.lower() not in FORMATS or not path.is_file():
            continue
        relative = path.relative_to(root).as_posix()
        row = {"path": relative}
        try:
            with Image.open(scoped_file(root, relative)) as image:
                orientation = image.getexif().get(274, 1)
                size = image.size[::-1] if orientation in (5, 6, 7, 8) else image.size
                row.update(size=size, format=image.format, frames=getattr(image, "n_frames", 1))
        except (OSError, ValueError) as error:
            row["error"] = str(error)
        files.append(row)
    for page, start in enumerate(range(0, len(files), 20), 1):
        batch = files[start:start + 20]
        sheet = Image.new("RGB", (1040, 226 * ((len(batch) + 3) // 4)), "#e6ebf0")
        draw = ImageDraw.Draw(sheet)
        for i, row in enumerate(batch):
            index = start + i + 1
            row["id"] = index
            x, y = i % 4 * 260, i // 4 * 226
            if "error" not in row:
                try:
                    with Image.open(scoped_file(root, row["path"])) as photo:
                        thumb = ImageOps.contain(ImageOps.exif_transpose(photo).convert("RGB"), (256, 204))
                        sheet.paste(thumb, (x + (260 - thumb.width) // 2, y + (204 - thumb.height) // 2))
                except (OSError, ValueError) as error:
                    row["error"] = str(error)
            draw.text((x + 6, y + 205), f"#{index}  {PurePosixPath(row['path']).stem[:28]}",
                      fill="black", font=ImageFont.load_default(size=13))
        sheet.save(work / f"scan-{page:03d}.jpg", quality=92)
    write_json(work / "inventory.json", files)
    return {"images": len(files), "unreadable": sum("error" in f for f in files)}


def check_box(image, values):
    if len(values) != 4 or any(type(v) is not int for v in values):
        raise ValueError("box requires four integer coordinates")
    x, y, right, bottom = values
    if not (0 <= x < right <= image.width and 0 <= y < bottom <= image.height):
        raise ValueError(f"Invalid box {values} for image {image.size}")
    return x, y, right, bottom


def make_mask(size, edit):
    mask = Image.new("L", size, 255)
    x, y, right, bottom = edit["box"]
    if "polygon" in edit:
        points = edit["polygon"]
        if len(points) < 3 or any(not (x <= px < right and y <= py < bottom) for px, py in points):
            raise ValueError("polygon must be inside box")
        mask = Image.new("L", size)
        ImageDraw.Draw(mask).polygon([(px - x, py - y) for px, py in points], fill=255)
    return mask


def glyph(text, width, height, edit, font_path):
    font = ImageFont.truetype(str(font_path), 160) if font_path else ImageFont.load_default(size=160)
    lines = text.splitlines()
    masks = []
    for line in lines:
        l, t, r, b = font.getbbox(line)
        line_mask = Image.new("L", (r - l, b - t))
        ImageDraw.Draw(line_mask).text((-l, -t), line, fill=255, font=font)
        masks.append(line_mask.crop(line_mask.getbbox()))
    row_height = max(row.height for row in masks)
    gap = round(row_height * 0.28)
    ink = Image.new("L", (max(row.width for row in masks), row_height * len(masks) + gap * (len(masks) - 1)))
    for i, row in enumerate(masks):
        ink.paste(row, (0, i * (row_height + gap) + row_height - row.height))
    ink = ink.crop(ink.getbbox())
    requested = edit.get("height")
    if requested is None:
        scale = min(0.78 * (height if abs(edit.get("angle", 0)) != 90 else width) / ink.height,
                    0.9 * max(width, height) / ink.width)
    else:
        if type(requested) is not int or not 3 <= requested <= max(width, height):
            raise ValueError(f"Invalid text height: {requested}")
        scale = requested / row_height
    # Rotate the clean, high-resolution coverage mask before resampling to image pixels.
    rotated = ink.rotate(-float(edit.get("angle", 0)), resample=Image.Resampling.BICUBIC, expand=True)
    rotated = rotated.crop(rotated.getbbox())
    scale = min(scale, max(1, width - 4) / rotated.width, max(1, height - 4) / rotated.height)
    return rotated.resize((max(1, round(rotated.width * scale)), max(1, round(rotated.height * scale))),
                          Image.Resampling.LANCZOS)


def solid(mode, size, color):
    return Image.new("RGB", size, ImageColor.getrgb(color)).convert(mode)


def patch_label(image, root, work, edit, text, font):
    x, y, right, bottom = check_box(image, edit["box"])
    size = (right - x, bottom - y)
    mask = make_mask(size, edit)
    if "background_patch" in edit:
        if "clean" in edit:
            raise ValueError("Choose either clean or background_patch")
        with Image.open(scoped_file(work, edit["background_patch"])) as patch:
            if patch.size != size:
                raise ValueError("background_patch must have the exact size of box")
            background = patch.convert(image.mode)
    elif "clean" in edit:
        with Image.open(scoped_file(root, edit["clean"])) as donor:
            aligned = ImageOps.exif_transpose(donor)
            if aligned.size != image.size:
                raise ValueError(f"Clean reference has a different size: {edit['clean']}")
            background = aligned.crop((x, y, right, bottom)).convert(image.mode)
    else:
        background = solid(image.mode, size, edit.get("background", "#ffffff"))
    text_mask = glyph(text, *size, edit, font)
    cx, cy = edit.get("center", ((x + right) / 2, (y + bottom) / 2))
    tx, ty = round(cx - text_mask.width / 2), round(cy - text_mask.height / 2)
    if tx < x or ty < y or tx + text_mask.width > right or ty + text_mask.height > bottom:
        raise ValueError(f"Text crosses its box: {text!r}; adjust center, height or box")
    image.paste(background, (x, y), mask)
    image.paste(solid(image.mode, text_mask.size, edit.get("ink", "#080808")), (tx, ty), text_mask)


def stage(root, plan_path, work, font_path):
    manifest_path = work / "staged.json"
    manifest_path.unlink(missing_ok=True)
    seen = set()
    results = []
    for index, item in enumerate(read_json(plan_path)["images"], 1):
        path = scoped_file(root, item["path"])
        unique = os.path.normcase(str(path))
        if unique in seen or not item["edits"]:
            raise ValueError(f"Duplicate file or empty edit list: {path.name}")
        seen.add(unique)
        original = path.read_bytes()
        preview = work / f"preview-{index:04d}.png"
        staged = work / f"staged-{index:04d}{path.suffix.lower()}"
        with Image.open(BytesIO(original)) as photo:
            fmt = FORMATS.get(path.suffix.lower())
            if photo.format != fmt or getattr(photo, "n_frames", 1) != 1:
                raise ValueError(f"Expected a single {fmt} image: {path.name}")
            if photo.mode not in ("RGB", "RGBA", "CMYK", "L", "LA", "P"):
                raise ValueError(f"Unsupported pixel mode {photo.mode}: {path.name}")
            exif = photo.getexif()
            orientation = exif.get(274, 1)
            canvas = ImageOps.exif_transpose(photo)
            if canvas.mode == "P":
                canvas = canvas.convert("RGBA")
            source_visual = canvas.convert("RGB")
            labels = []
            for edit in item["edits"]:
                text = convert(edit)
                patch_label(canvas, root, work, edit, text, font_path)
                labels.append(text)
            visual = canvas.convert("RGB")
            if ImageChops.difference(source_visual, visual).getbbox() is None:
                raise ValueError(f"No visible label changed in {path.name}")
            visual.save(preview)
            encoded = canvas.transpose(ORIENTATION[orientation]) if orientation in ORIENTATION else canvas
            save = {k: photo.info[k] for k in ("icc_profile", "dpi") if k in photo.info}
            if exif:
                save["exif"] = exif.tobytes()
            if fmt == "JPEG":
                save.update(quality=100, subsampling=0)
            if fmt == "WEBP":
                save.update(lossless=True, exact=True)
            encoded.save(staged, format=fmt, **save)
            with Image.open(staged) as check:
                check.load()
                if check.size != photo.size or check.format != fmt:
                    raise ValueError(f"Rendered image changed format or resolution: {path.name}")
        results.append({
            "path": path.relative_to(root).as_posix(), "preview": preview.name, "staged": staged.name,
            "original_sha256": sha(original), "staged_sha256": sha(staged.read_bytes()),
            "labels": labels,
        })
    if not results:
        raise ValueError("Plan contains no images")
    write_json(manifest_path, {"root": str(root), "images": results})
    return {"images": len(results), "labels": sum(len(result["labels"]) for result in results)}


def reviewed_images(root, work):
    manifest = read_json(work / "staged.json")
    if Path(manifest["root"]) != root or not manifest["images"]:
        raise ValueError("Stage belongs to another source folder or contains no images")
    prepared = {}
    for entry in manifest["images"]:
        original = scoped_file(root, entry["path"])
        rendering = scoped_file(work, entry["staged"]).read_bytes()
        current = original.read_bytes()
        if original in prepared or sha(current) != entry["original_sha256"] or sha(rendering) != entry["staged_sha256"]:
            raise ValueError(f"Source or staged image changed or was repeated: {entry['path']}")
        prepared[original] = (current, rendering)
    return prepared


def verified_zip(destination, contents):
    destination.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(destination, "x", compression=zipfile.ZIP_STORED) as archive:
        for name, data in contents.items():
            archive.writestr(name, data)
    with zipfile.ZipFile(destination) as archive:
        if set(archive.namelist()) != set(contents) or any(
            archive.read(name) != data for name, data in contents.items()
        ):
            raise OSError(f"ZIP contents did not verify: {destination}")


def export(root, work, destination):
    prepared = reviewed_images(root, work)
    verified_zip(destination, {p.relative_to(root).as_posix(): updated for p, (_, updated) in prepared.items()})
    return {"exported": len(prepared), "result": str(destination)}


def apply(root, work, backup):
    prepared = reviewed_images(root, work)
    verified_zip(backup, {p.relative_to(root).as_posix(): source for p, (source, _) in prepared.items()})
    written = []
    try:
        for path, (source, updated) in prepared.items():
            if path.read_bytes() != source:
                raise OSError(f"Source changed before replacement: {path}")
            atomic_write(path, updated, preserve=True)
            written.append(path)
        for path in written:
            if path.read_bytes() != prepared[path][1]:
                raise OSError(f"Replacement could not be verified: {path}")
    except (OSError, KeyboardInterrupt) as error:
        pending = []
        for path in reversed(written):
            try:
                if path.read_bytes() != prepared[path][1]:
                    pending.append(str(path))
                    continue
                atomic_write(path, prepared[path][0], preserve=True)
            except OSError:
                pending.append(str(path))
        note = f"Restore from verified backup {backup}: {pending}" if pending else f"Replacements rolled back. Verified backup: {backup}"
        raise OSError(f"{error}. {note}") from error
    return {"replaced": len(written), "backup": str(backup)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    for name in ("scan", "stage", "apply", "export"):
        command = commands.add_parser(name)
        command.add_argument("root", type=Path)
        if name == "stage":
            command.add_argument("plan", type=Path)
        command.add_argument("work", type=Path)
        if name == "stage":
            command.add_argument("--font", type=Path)
        if name in ("apply", "export"):
            command.add_argument("destination", type=Path, metavar="backup.zip" if name == "apply" else "result.zip")
    args = parser.parse_args()
    root, work = args.root.resolve(), args.work.resolve()
    try:
        if not root.is_dir() or work.is_relative_to(root) or root.is_relative_to(work):
            raise ValueError("Use the existing source folder and a separate scratch folder")
        work.mkdir(parents=True, exist_ok=True)
        if args.command == "scan":
            result = scan(root, work)
        elif args.command == "stage":
            result = stage(root, args.plan, work, args.font)
        else:
            destination = args.destination.resolve()
            if destination.suffix.lower() != ".zip" or destination.is_relative_to(root):
                raise ValueError("Choose a new .zip path outside the source folder")
            operation = apply if args.command == "apply" else export
            result = operation(root, work, destination)
        print(json.dumps(result, ensure_ascii=False))
    except (OSError, ValueError, KeyError, TypeError, ArithmeticError, zipfile.BadZipFile) as error:
        sys.exit(str(error))


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
    main()
