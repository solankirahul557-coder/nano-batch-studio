#!/usr/bin/env python3
"""
Nano Batch Studio — batch product-image generator.

Supports both providers:
  • Google  — Nano Banana Pro / 2 / 2 Lite / original
  • OpenAI  — GPT Image 2 / 1.5 / 1 / 1 mini

Three modes:
  text     one image per product name in a CSV
  edit     one scene per photo in the input folder (filenames kept)
  compose  blends several photos into one scene, N variations

Run: double-click run_batch.bat, or  python nano_batch.py
"""

import base64
import csv
import hashlib
import json
import os
import queue
import random
import re
import sys
import threading
import time
from io import BytesIO
from pathlib import Path
from urllib.parse import urljoin, urlparse

import tkinter as tk
from tkinter import ttk, filedialog, messagebox, scrolledtext, font as tkfont

# ---- optional deps -------------------------------------------------------
_MISSING = []
try:
    from PIL import Image
except ImportError:
    _MISSING.append("Pillow")
try:
    from google import genai
    from google.genai import types
    HAS_GOOGLE = True
except ImportError:
    HAS_GOOGLE = False
try:
    from openai import OpenAI
    HAS_OPENAI = True
except ImportError:
    HAS_OPENAI = False
try:
    from dotenv import load_dotenv
except ImportError:
    load_dotenv = None
try:
    import requests
    from bs4 import BeautifulSoup
    HAS_WEB = True
except ImportError:
    HAS_WEB = False

ROOT = Path(__file__).resolve().parent
ENV_PATH = ROOT / ".env"
SETTINGS_PATH = ROOT / "settings.json"

# ---- model registry ------------------------------------------------------
# label -> (provider, api model id)
MODELS = {
    "Nano Banana Pro  (Google)":      ("google", "gemini-3-pro-image-preview"),
    "Nano Banana 2  (Google)":        ("google", "gemini-3.1-flash-image"),
    "Nano Banana 2 Lite  (Google)":   ("google", "gemini-3.1-flash-lite-image"),
    "Nano Banana  (Google)":          ("google", "gemini-2.5-flash-image"),
    "GPT Image 2.5 Sunburst  (ChatGPT)": ("openai", "gpt-image-2.5-sunburst"),
    "GPT Image 2.5 Flare  (ChatGPT)":    ("openai", "gpt-image-2.5-flare"),
    "GPT Image 2  (ChatGPT)":         ("openai", "gpt-image-2"),
    "GPT Image 1.5  (ChatGPT)":       ("openai", "gpt-image-1.5"),
    "GPT Image 1  (ChatGPT)":         ("openai", "gpt-image-1"),
    "GPT Image 1 mini  (ChatGPT)":    ("openai", "gpt-image-1-mini"),
}
MODEL_LABELS = list(MODELS.keys())

RATIOS = ["1:1", "2:3", "3:2", "3:4", "4:3", "4:5", "5:4", "9:16", "16:9", "21:9", "auto"]
GOOGLE_SIZES = ["1K", "2K", "4K"]
OPENAI_QUALITY = ["low", "medium", "high"]
# GPT Image 2.5 adds higher tiers
OPENAI_QUALITY_25 = ["low", "medium", "high", "xhigh", "max", "auto"]
ALL_QUALITY = set(OPENAI_QUALITY_25)


def quality_choices(model_id):
    return OPENAI_QUALITY_25 if str(model_id).startswith("gpt-image-2.5") else OPENAI_QUALITY
FORMATS = ["png", "jpg", "jpeg", "webp"]
IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".webp"}

DEFAULT_PROMPT = (
    "Create a wonderful Minimalist Scandinavian interior scene using this "
    "furniture piece as a hero product of the scene. Use these items from the "
    "image and make it realistic. Don't alter the products proportion."
)

# Appended automatically when "Furnish with my own products only" is on.
# Edit the wording here if you want to change how strict it is.
LIBRARY_INSTRUCTION = (
    "\n\nIMPORTANT — furniture rules for this scene:\n"
    "The FIRST image is the hero product. It must appear exactly as shown, with its "
    "shape, proportions, colour and materials unchanged.\n"
    "The REMAINING images are the only other furniture and decor items you are allowed "
    "to place in the scene. Choose whichever of them suit the composition and leave the "
    "rest out — you do not have to use them all. Reproduce any item you use faithfully, "
    "without changing its design or proportions.\n"
    "Do NOT invent, add or substitute any other furniture, lighting or decor that is not "
    "shown in these images. Plain walls, floors, windows, natural light and simple soft "
    "furnishings are fine, and empty space is better than an invented object."
)

MAX_REFS = 14  # the models blend up to 14 reference images per request


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------
def provider_of(label):
    return MODELS.get(label, ("google", label))[0]


def model_id_of(label):
    return MODELS.get(label, ("google", label))[1]


def slugify(text):
    text = re.sub(r"[^\w\s-]", "", str(text)).strip().lower()
    return re.sub(r"\s+", "-", text)[:60] or "image"


def list_images(folder):
    folder = Path(folder)
    if not folder.is_dir():
        return []
    return sorted(p for p in folder.iterdir() if p.suffix.lower() in IMAGE_EXTS)


def ext_for(fmt):
    return "jpg" if fmt.lower() in {"jpeg", "jpg"} else fmt.lower()


def save_image(img, out_dir, stem, fmt):
    ext = ext_for(fmt)
    out = Path(out_dir) / f"{stem}.{ext}"
    n = 2
    while out.exists():
        out = Path(out_dir) / f"{stem}-v{n}.{ext}"
        n += 1
    kw = {}
    if ext == "jpg":
        img = img.convert("RGB")
        kw = {"quality": 95}
    img.save(out, **kw)
    return out


def read_products(csv_path):
    csv_path = Path(csv_path)
    if not csv_path.exists():
        raise FileNotFoundError(f"Products file not found:\n{csv_path}")
    rows = []
    with open(csv_path, "r", encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        headers = [h.strip().lower() for h in (reader.fieldnames or [])]
        if "product" not in headers:
            raise ValueError("The products file needs a column headed 'product'.")
        name_key = next(h for h in reader.fieldnames if h.strip().lower() == "product")
        extra_key = next((h for h in reader.fieldnames if h.strip().lower() == "extra"), None)
        for r in reader:
            name = (r.get(name_key) or "").strip()
            if name:
                rows.append({"name": name,
                             "extra": (r.get(extra_key) or "").strip() if extra_key else ""})
    if not rows:
        raise ValueError("No products listed in that file.")
    return rows


# ---- website library ------------------------------------------------------
WEB_HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; NanoBatchStudio/1.0)"}
SKIP_WORDS = ("logo", "icon", "sprite", "placeholder", "banner", "avatar",
              "favicon", "badge", "flag", "payment", "spinner", "loader")
WEB_EXTS = (".jpg", ".jpeg", ".png", ".webp")
CACHE_DIRNAME = "library_cache"


def _best_from_srcset(srcset):
    """Pick the largest candidate out of a srcset attribute."""
    best, best_w = None, -1
    for part in srcset.split(","):
        bits = part.strip().split()
        if not bits:
            continue
        url, w = bits[0], -1
        if len(bits) > 1 and bits[1].endswith("w"):
            try:
                w = int(bits[1][:-1])
            except ValueError:
                w = -1
        if w > best_w:
            best, best_w = url, w
    return best


def extract_image_urls(html, base_url):
    """Return candidate product-image URLs found in a page, in order."""
    soup = BeautifulSoup(html, "html.parser")
    found, seen = [], set()

    def add(u):
        if not u:
            return
        u = u.strip()
        if u.startswith("data:"):
            return
        full = urljoin(base_url, u)
        if not full.split("?")[0].lower().endswith(WEB_EXTS):
            return
        if any(w in full.lower() for w in SKIP_WORDS):
            return
        if full not in seen:
            seen.add(full)
            found.append(full)

    for tag in soup.find_all("img"):
        if tag.get("srcset"):
            add(_best_from_srcset(tag["srcset"]))
        for attr in ("src", "data-src", "data-original", "data-lazy-src", "data-image"):
            add(tag.get(attr))
    for tag in soup.find_all("source"):
        if tag.get("srcset"):
            add(_best_from_srcset(tag["srcset"]))
    for tag in soup.find_all("meta", property="og:image"):
        add(tag.get("content"))
    return found


def extract_links(html, base_url):
    """Same-domain page links, for optionally following product pages."""
    soup = BeautifulSoup(html, "html.parser")
    host = urlparse(base_url).netloc
    out, seen = [], set()
    for a in soup.find_all("a", href=True):
        full = urljoin(base_url, a["href"]).split("#")[0]
        if urlparse(full).netloc != host or full in seen:
            continue
        if full.lower().endswith((".pdf", ".zip", ".jpg", ".png")):
            continue
        seen.add(full)
        out.append(full)
    return out


def fetch_site_images(url, dest, max_images=40, min_px=400, max_pages=1,
                      log=print, stop_flag=None):
    """Download product images from a website into `dest`. Returns how many were saved."""
    if not HAS_WEB:
        raise RuntimeError("Install the web libraries first:  pip install requests beautifulsoup4")
    dest = Path(dest)
    dest.mkdir(parents=True, exist_ok=True)

    session = requests.Session()
    session.headers.update(WEB_HEADERS)

    pages = [url]
    if max_pages > 1:
        try:
            r = session.get(url, timeout=20)
            r.raise_for_status()
            pages += extract_links(r.text, url)[:max_pages - 1]
        except Exception as e:
            log(f"   couldn't read links ({str(e)[:60]})")

    hashes = set()
    manifest_path = dest / ".fetched.json"
    if manifest_path.exists():                # what we've already downloaded before
        try:
            hashes = set(json.loads(manifest_path.read_text(encoding="utf-8")))
        except Exception:
            hashes = set()

    saved = 0
    for pi, page in enumerate(pages, 1):
        if (stop_flag is not None and stop_flag.is_set()) or saved >= max_images:
            break
        log(f"   reading page {pi}/{len(pages)}")
        try:
            r = session.get(page, timeout=20)
            r.raise_for_status()
            urls = extract_image_urls(r.text, page)
        except Exception as e:
            log(f"   page failed ({str(e)[:70]})")
            continue
        log(f"   found {len(urls)} candidate image(s)")

        for u in urls:
            if (stop_flag is not None and stop_flag.is_set()) or saved >= max_images:
                break
            try:
                ir = session.get(u, timeout=20)
                ir.raise_for_status()
                data = ir.content
                h = hashlib.md5(data).hexdigest()
                if h in hashes:
                    continue
                img = Image.open(BytesIO(data))
                img.load()
                if min(img.size) < min_px:      # too small = icon or thumbnail
                    continue
                name = re.sub(r"[^\w\-]+", "-", Path(urlparse(u).path).stem[:60]).strip("-") or "product"
                out = dest / f"{name}.png"
                n = 2
                while out.exists():
                    out = dest / f"{name}-{n}.png"
                    n += 1
                img.convert("RGB").save(out)
                hashes.add(h)
                saved += 1
                log(f"   saved {out.name}  ({img.size[0]}x{img.size[1]})")
            except Exception:
                continue
        interruptible_sleep(0.4, stop_flag)  # be polite to the server

    try:
        manifest_path.write_text(json.dumps(sorted(hashes)), encoding="utf-8")
    except Exception:
        pass
    return saved


# Errors that will never succeed on a retry — no point burning three attempts.
PERMANENT_ERROR_MARKERS = (
    "must be verified", "organization must be", "invalid_api_key", "incorrect api key",
    "401", "403", "404", "billing", "quota", "insufficient_quota",
    "content_policy", "moderation_blocked", "safety", "invalid_request_error",
    "unsupported", "not supported", "does not exist", "permission",
)
TRANSIENT_ERROR_MARKERS = (
    "429", "500", "502", "503", "504", "rate limit", "timeout", "timed out",
    "overloaded", "unavailable", "connection", "temporarily",
)


def is_permanent_error(exc):
    """True when retrying is pointless (bad key, unverified org, blocked prompt...)."""
    text = str(exc).lower()
    if any(m in text for m in TRANSIENT_ERROR_MARKERS):
        return False
    return any(m in text for m in PERMANENT_ERROR_MARKERS)


def error_hint(exc):
    """A short plain-English pointer for the errors people actually hit."""
    text = str(exc).lower()
    if "must be verified" in text or "organization must be" in text:
        return ("Your OpenAI organisation isn't verified for this model. Verify at "
                "platform.openai.com → Settings → Organization → General, then make sure "
                "your API key belongs to that same organisation.")
    if "invalid_api_key" in text or "incorrect api key" in text or "401" in text:
        return "That API key was rejected. Check it was copied in full and belongs to the right provider."
    if "insufficient_quota" in text or "billing" in text:
        return "The account has no credit or billing set up for this model."
    if "429" in text or "rate limit" in text:
        return "Rate limited by the provider. It will retry; lowering the batch size also helps."
    if "content_policy" in text or "moderation" in text or "safety" in text:
        return "The prompt or a reference image was blocked by the provider's safety filter."
    if "connection" in text or "timeout" in text or "timed out" in text:
        return "Network problem reaching the provider."
    return ""


def interruptible_sleep(seconds, stop_flag, step=0.25):
    """Sleep, but notice a Stop press quickly."""
    waited = 0.0
    while waited < seconds:
        if stop_flag is not None and stop_flag.is_set():
            return
        time.sleep(min(step, seconds - waited))
        waited += step


def pick_library(lib_dir, count, exclude=None):
    """Pick supporting product photos to offer alongside the hero.
    `count` is a number or 'all'. The hero file is never included twice."""
    files = list_images(lib_dir)
    if exclude is not None:
        ex = Path(exclude).resolve()
        files = [p for p in files if p.resolve() != ex]
    if not files:
        return []
    cap = MAX_REFS - 1  # leave room for the hero image
    if str(count).strip().lower() == "all":
        k = min(len(files), cap)
        return random.sample(files, k)
    try:
        k = int(str(count).strip())
    except ValueError:
        k = 6
    k = max(0, min(k, len(files), cap))
    return random.sample(files, k) if k else []


# Models that accept arbitrary WIDTHxHEIGHT (rather than the three fixed presets)
ARBITRARY_SIZE_MODELS = ("gpt-image-2.5", "gpt-image-2")
# OpenAI resolution limits
OA_MAX_EDGE = 3840
OA_MIN_PIXELS = 655_360
OA_MAX_PIXELS = 8_294_400
OA_STEP = 16
# long-edge target for each size tier
TIER_LONG_EDGE = {"1K": 1536, "2K": 2560, "4K": 3840}


def supports_arbitrary_size(model_id):
    return str(model_id).startswith(ARBITRARY_SIZE_MODELS)


def _round16(v):
    return max(OA_STEP, int(round(v / OA_STEP)) * OA_STEP)


def openai_custom_size(aspect, tier):
    """Build a WIDTHxHEIGHT string honouring OpenAI's limits:
    edges <= 3840 and multiples of 16, total pixels 655,360-8,294,400."""
    try:
        a, b = str(aspect).split(":")
        r = float(a) / float(b)
    except Exception:
        r = 1.0
    r = min(max(r, 1 / 3), 3.0)           # ratio must sit within 1:3 .. 3:1

    long_edge = TIER_LONG_EDGE.get(str(tier).upper(), 2560)
    if r >= 1:
        w, h = float(long_edge), long_edge / r
    else:
        h, w = float(long_edge), long_edge * r

    # shrink if over the pixel budget or the edge cap
    scale = min(1.0, OA_MAX_EDGE / max(w, h))
    if w * h * scale * scale > OA_MAX_PIXELS:
        scale = min(scale, (OA_MAX_PIXELS / (w * h)) ** 0.5)
    w, h = w * scale, h * scale

    # grow if under the pixel floor
    if w * h < OA_MIN_PIXELS:
        up = (OA_MIN_PIXELS / (w * h)) ** 0.5
        if max(w, h) * up <= OA_MAX_EDGE:
            w, h = w * up, h * up

    w, h = _round16(w), _round16(h)

    # rounding can nudge past a limit - walk back down / up in 16px steps
    guard = 0
    while (w * h > OA_MAX_PIXELS or max(w, h) > OA_MAX_EDGE) and guard < 200:
        w, h = max(OA_STEP, w - OA_STEP), max(OA_STEP, _round16(h - OA_STEP * h / w))
        guard += 1
    guard = 0
    while w * h < OA_MIN_PIXELS and max(w, h) + OA_STEP <= OA_MAX_EDGE and guard < 200:
        w, h = w + OA_STEP, _round16(h + OA_STEP * h / w)
        guard += 1
    return f"{int(w)}x{int(h)}"


def openai_size_for(aspect, tier="2K", model_id=""):
    """Pick the size string for a request."""
    if str(aspect).lower() == "auto":
        return "auto"
    if supports_arbitrary_size(model_id):
        return openai_custom_size(aspect, tier)
    # older models: only the three fixed presets
    try:
        a, b = str(aspect).split(":")
        r = float(a) / float(b)
    except Exception:
        return "auto"
    if r >= 1.2:
        return "1536x1024"
    if r <= 0.83:
        return "1024x1536"
    return "1024x1024"


# ---------------------------------------------------------------------------
# provider calls -> list of PIL images
# ---------------------------------------------------------------------------
def call_google(key, model_id, prompt, ref_paths, aspect, size):
    client = genai.Client(api_key=key)
    contents = [prompt]
    for p in (ref_paths or []):
        contents.append(Image.open(p))
    # Gemini has no "auto" aspect ratio — leave it unset and let the model decide
    img_kw = {"image_size": size}
    if str(aspect).lower() != "auto":
        img_kw["aspect_ratio"] = aspect
    resp = client.models.generate_content(
        model=model_id,
        contents=contents,
        config=types.GenerateContentConfig(
            response_modalities=["TEXT", "IMAGE"],
            image_config=types.ImageConfig(**img_kw),
        ),
    )
    imgs, notes = [], []
    cands = getattr(resp, "candidates", None) or []
    if not cands:
        return imgs, ["blocked or empty response"]
    for part in cands[0].content.parts:
        if getattr(part, "inline_data", None) is not None and part.inline_data.data:
            imgs.append(Image.open(BytesIO(part.inline_data.data)))
        elif getattr(part, "text", None):
            notes.append(part.text.strip())
    return imgs, notes


def call_openai(key, model_id, prompt, ref_paths, aspect, quality, tier="2K", n=1):
    client = OpenAI(api_key=key)
    size = openai_size_for(aspect, tier, model_id)
    kw = {"model": model_id, "prompt": prompt, "size": size, "n": n}
    if quality in ALL_QUALITY:
        kw["quality"] = quality

    handles = []
    try:
        if ref_paths:
            for p in ref_paths:
                handles.append(open(p, "rb"))
            resp = client.images.edit(image=handles if len(handles) > 1 else handles[0], **kw)
        else:
            resp = client.images.generate(**kw)
    finally:
        for h in handles:
            try:
                h.close()
            except Exception:
                pass

    imgs = []
    for item in (resp.data or []):
        b64 = getattr(item, "b64_json", None)
        if b64:
            imgs.append(Image.open(BytesIO(base64.b64decode(b64))))
    return imgs, ([] if imgs else ["no image returned"])


def generate_once(s, prompt, ref_paths):
    if s["provider"] == "google":
        if not HAS_GOOGLE:
            raise RuntimeError("google-genai isn't installed. Run: pip install -r requirements.txt")
        return call_google(s["google_key"], s["model_id"], prompt, ref_paths,
                           s["aspect"], s["size_tier"])
    if not HAS_OPENAI:
        raise RuntimeError("openai isn't installed. Run: pip install -r requirements.txt")
    return call_openai(s["openai_key"], s["model_id"], prompt, ref_paths,
                       s["aspect"], s["oq"], s["size_tier"])


# ---------------------------------------------------------------------------
# worker
# ---------------------------------------------------------------------------
def run_batch(s, q, stop_flag):
    log = lambda m: q.put(("log", m))
    out_dir = Path(s["out_dir"])
    out_dir.mkdir(parents=True, exist_ok=True)
    mode = s["mode"]
    per = max(1, int(s["per"]))

    if mode == "text":
        products = read_products(s["products_csv"])
        units = [(p["name"], p["extra"], None, slugify(p["name"])) for p in products]
    elif mode == "edit":
        refs = list_images(s["input_dir"])
        if not refs:
            raise ValueError("No images found in the input folder.")
        units = []
        for p in refs:
            paths = [p]
            if s.get("lib_on") and s.get("lib_dir"):
                paths += pick_library(s["lib_dir"], s.get("lib_count", 6), exclude=p)
            units.append((p.stem, "", paths, p.stem))
    else:
        refs = list_images(s["input_dir"])
        if not refs:
            raise ValueError("No images found in the input folder.")
        subset = str(s["per_room"]).strip()
        units = []
        for v in range(1, max(1, int(s["variations"])) + 1):
            if subset.lower() == "all":
                pick = refs[:14]
            else:
                k = min(int(subset or 1), len(refs), 14)
                pick = random.sample(refs, k)
            units.append((f"room-{v:02d}", "", pick, f"room-{v:02d}"))
        per = 1

    q.put(("max", len(units)))
    log(f"{s['model_label']}  |  {mode}  |  size: {s['size_tier']}  |  {len(units)} item(s)")
    if s["provider"] == "openai":
        log(f"(output {openai_size_for(s['aspect'], s['size_tier'], s['model_id'])}, "
            f"quality {s['oq']})")
    log("")

    ok = fail = 0
    failures = []
    hints_shown = set()
    t0 = time.time()
    for i, (label, extra, ref_paths, out_base) in enumerate(units, 1):
        if stop_flag.is_set():
            log("\nStopped by user.")
            break
        log(f"[{i}/{len(units)}] {label} ...")
        prompt = s["prompt"].replace("{product}", label)
        if extra:
            prompt += f"\nAdditional details: {extra}"
        if s.get("lib_on") and ref_paths and len(ref_paths) > 1:
            prompt += LIBRARY_INSTRUCTION
            log(f"      with: {', '.join(p.stem for p in ref_paths[1:])}")

        made = 0
        last_error = None
        # each pass produces one image, so "images per item" really gives that many
        for copy_no in range(1, per + 1):
            if stop_flag.is_set():
                break
            for attempt in range(1, 4):
                if stop_flag.is_set():
                    break
                try:
                    imgs, notes = generate_once(s, prompt, ref_paths)
                    if imgs:
                        made += 1
                        stem = out_base if copy_no == 1 else f"{out_base}_{copy_no}"
                        out = save_image(imgs[0], out_dir, stem, s["fmt"])
                        log(f"      saved  ->  {out.name}")
                    else:
                        reason = (notes[0] if notes else "empty response")
                        log(f"      no image ({reason[:70]})")
                        last_error = reason
                    break
                except Exception as e:
                    last_error = str(e)
                    if is_permanent_error(e):
                        log(f"      FAILED ({str(e)[:90]})")
                        hint = error_hint(e)
                        if hint and hint not in hints_shown:
                            log(f"      → {hint}")
                            hints_shown.add(hint)
                        break                      # retrying would change nothing
                    if attempt < 3:
                        log(f"      retry ({str(e)[:70]})")
                        interruptible_sleep(2 ** attempt, stop_flag)
                    else:
                        log(f"      FAILED ({str(e)[:90]})")
                        hint = error_hint(e)
                        if hint and hint not in hints_shown:
                            log(f"      → {hint}")
                            hints_shown.add(hint)

        if made:
            ok += 1
        else:
            fail += 1
            failures.append(label)
        q.put(("progress", i))

    summary = f"Finished in {time.time()-t0:.0f}s  —  {ok} created, {fail} failed."
    if failures:
        shown = ", ".join(failures[:5]) + (" …" if len(failures) > 5 else "")
        log(f"\nDidn't finish: {shown}")
    q.put(("done", summary))


# ---------------------------------------------------------------------------
# UI
# ---------------------------------------------------------------------------
class App:
    PADX = 12

    def __init__(self, root):
        self.root = root
        self.q = queue.Queue()
        self.stop_flag = threading.Event()
        root.title("Nano Batch Studio")
        root.geometry("780x760")
        root.minsize(660, 520)

        self._init_style()
        self._build()
        self._load_settings()
        self._sync_provider()
        self._sync_mode()
        root.protocol("WM_DELETE_WINDOW", self._on_close)
        self._poll()

    # ---------- look ----------
    def _init_style(self):
        st = ttk.Style()
        if "vista" in st.theme_names():
            st.theme_use("vista")
        elif "clam" in st.theme_names():
            st.theme_use("clam")
        base = tkfont.nametofont("TkDefaultFont")
        base.configure(size=10)
        self.f_title = tkfont.Font(family=base.cget("family"), size=17, weight="bold")
        self.f_sub = tkfont.Font(family=base.cget("family"), size=9)
        self.f_sec = tkfont.Font(family=base.cget("family"), size=10, weight="bold")
        self.f_mono = tkfont.Font(family="Consolas", size=9)
        st.configure("Section.TLabelframe.Label", font=self.f_sec)
        st.configure("Hint.TLabel", foreground="#666666", font=self.f_sub)
        st.configure("Go.TButton", font=(base.cget("family"), 11, "bold"), padding=(22, 9))

    def _section(self, parent, title):
        lf = ttk.Labelframe(parent, text="  " + title + "  ", style="Section.TLabelframe",
                            padding=(12, 8))
        lf.pack(fill="x", pady=(0, 10))
        lf.columnconfigure(1, weight=1)
        return lf

    # ---------- layout ----------
    def _build(self):
        # --- bottom bar: packed first so it is ALWAYS visible ---
        bottom = ttk.Frame(self.root, padding=(16, 8))
        bottom.pack(side="bottom", fill="both")

        bar = ttk.Frame(bottom)
        bar.pack(fill="x", pady=(0, 6))
        self.btn_start = ttk.Button(bar, text="Generate", style="Go.TButton", command=self._start)
        self.btn_start.pack(side="left")
        self.btn_stop = ttk.Button(bar, text="Stop", width=8,
                                   command=self._stop, state="disabled")
        self.btn_stop.pack(side="left", padx=6)
        ttk.Button(bar, text="Open output folder",
                   command=self._open_out).pack(side="left", padx=6)
        ttk.Button(bar, text="Reset", width=8, command=self._reset).pack(side="right")

        self.progress = ttk.Progressbar(bottom, mode="determinate")
        self.progress.pack(fill="x", pady=(0, 6))

        self.log = scrolledtext.ScrolledText(bottom, height=9, state="disabled",
                                             wrap="word", font=self.f_mono,
                                             relief="solid", borderwidth=1)
        self.log.pack(fill="both", expand=True)

        self.status = ttk.Label(bottom, text="Ready", style="Hint.TLabel", anchor="w")
        self.status.pack(fill="x", pady=(6, 0))

        # --- scrollable settings area above it ---
        area = ttk.Frame(self.root)
        area.pack(side="top", fill="both", expand=True)
        canvas = tk.Canvas(area, highlightthickness=0, borderwidth=0)
        vbar = ttk.Scrollbar(area, orient="vertical", command=canvas.yview)
        canvas.configure(yscrollcommand=vbar.set)
        vbar.pack(side="right", fill="y")
        canvas.pack(side="left", fill="both", expand=True)

        wrap = ttk.Frame(canvas, padding=(16, 12))
        win = canvas.create_window((0, 0), window=wrap, anchor="nw")
        wrap.bind("<Configure>", lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.bind("<Configure>", lambda e: canvas.itemconfigure(win, width=e.width))

        def _wheel(event):
            delta = -1 * (event.delta // 120) if event.delta else (1 if event.num == 5 else -1)
            canvas.yview_scroll(delta, "units")
        canvas.bind_all("<MouseWheel>", _wheel)
        canvas.bind_all("<Button-4>", _wheel)
        canvas.bind_all("<Button-5>", _wheel)

        head = ttk.Frame(wrap)
        head.pack(fill="x", pady=(0, 12))
        ttk.Label(head, text="Nano Batch Studio", font=self.f_title).pack(anchor="w")
        ttk.Label(head, text="Batch product images from Google Nano Banana or ChatGPT GPT Image",
                  style="Hint.TLabel").pack(anchor="w")

        # ---- model & key ----
        sec = self._section(wrap, "Model")
        ttk.Label(sec, text="Model").grid(row=0, column=0, sticky="w", pady=3)
        self.v_model = tk.StringVar(value=MODEL_LABELS[0])
        cb = ttk.Combobox(sec, textvariable=self.v_model, values=MODEL_LABELS,
                          state="readonly", width=34)
        cb.grid(row=0, column=1, sticky="w", padx=8, pady=3)
        cb.bind("<<ComboboxSelected>>", lambda e: self._sync_provider())

        self.lbl_key = ttk.Label(sec, text="Google API key")
        self.lbl_key.grid(row=1, column=0, sticky="w", pady=3)
        self.v_gkey = tk.StringVar()
        self.v_okey = tk.StringVar()
        self.e_key = ttk.Entry(sec, textvariable=self.v_gkey, show="•")
        self.e_key.grid(row=1, column=1, columnspan=2, sticky="ew", padx=8, pady=3)
        self.lbl_prov = ttk.Label(sec, text="", style="Hint.TLabel")
        self.lbl_prov.grid(row=2, column=1, sticky="w", padx=8)

        # ---- mode & sources ----
        sec = self._section(wrap, "What to make")
        ttk.Label(sec, text="Mode").grid(row=0, column=0, sticky="w", pady=3)
        modes = ttk.Frame(sec)
        modes.grid(row=0, column=1, columnspan=2, sticky="w", padx=8)
        self.v_mode = tk.StringVar(value="edit")
        for val, txt in [("text", "From a product list"),
                         ("edit", "One scene per photo"),
                         ("compose", "Combine photos into scenes")]:
            ttk.Radiobutton(modes, text=txt, value=val, variable=self.v_mode,
                            command=self._sync_mode).pack(side="left", padx=(0, 14))

        self.lbl_in = ttk.Label(sec, text="Input folder")
        self.lbl_in.grid(row=1, column=0, sticky="w", pady=3)
        self.v_in = tk.StringVar(value=str(ROOT / "inputs"))
        self.e_in = ttk.Entry(sec, textvariable=self.v_in)
        self.e_in.grid(row=1, column=1, sticky="ew", padx=8, pady=3)
        self.b_in = ttk.Button(sec, text="Browse", width=9,
                               command=lambda: self._pick_dir(self.v_in))
        self.b_in.grid(row=1, column=2, pady=3)

        self.lbl_csv = ttk.Label(sec, text="Product list (CSV)")
        self.lbl_csv.grid(row=2, column=0, sticky="w", pady=3)
        self.v_csv = tk.StringVar(value=str(ROOT / "products.csv"))
        self.e_csv = ttk.Entry(sec, textvariable=self.v_csv)
        self.e_csv.grid(row=2, column=1, sticky="ew", padx=8, pady=3)
        self.b_csv = ttk.Button(sec, text="Browse", width=9,
                                command=lambda: self._pick_file(self.v_csv))
        self.b_csv.grid(row=2, column=2, pady=3)

        ttk.Label(sec, text="Output folder").grid(row=3, column=0, sticky="w", pady=3)
        self.v_out = tk.StringVar(value=str(ROOT / "outputs"))
        ttk.Entry(sec, textvariable=self.v_out).grid(row=3, column=1, sticky="ew", padx=8, pady=3)
        ttk.Button(sec, text="Browse", width=9,
                   command=lambda: self._pick_dir(self.v_out)).grid(row=3, column=2, pady=3)

        self.lbl_count = ttk.Label(sec, text="", style="Hint.TLabel")
        self.lbl_count.grid(row=4, column=1, sticky="w", padx=8, pady=(2, 0))

        # ---- my-products-only library ----
        sec = self._section(wrap, "Furnish the scene")
        self.v_lib_on = tk.BooleanVar(value=False)
        self.chk_lib = ttk.Checkbutton(
            sec, text="Use only my own products to furnish the scene",
            variable=self.v_lib_on, command=self._sync_lib)
        self.chk_lib.grid(row=0, column=0, columnspan=3, sticky="w")
        ttk.Label(sec, text="Otherwise the model invents its own furniture around the hero product.",
                  style="Hint.TLabel").grid(row=1, column=0, columnspan=3, sticky="w", pady=(0, 6))

        # where the library comes from
        srow = ttk.Frame(sec)
        srow.grid(row=2, column=0, columnspan=3, sticky="w", pady=(0, 2))
        self.lbl_src = ttk.Label(srow, text="Library source")
        self.lbl_src.pack(side="left", padx=(0, 12))
        self.v_src = tk.StringVar(value="folder")
        ttk.Radiobutton(srow, text="A folder on my computer", value="folder",
                        variable=self.v_src, command=self._sync_lib).pack(side="left", padx=(0, 14))
        ttk.Radiobutton(srow, text="A website", value="web",
                        variable=self.v_src, command=self._sync_lib).pack(side="left")

        self.lbl_url = ttk.Label(sec, text="Website address")
        self.lbl_url.grid(row=3, column=0, sticky="w", pady=3)
        self.v_url = tk.StringVar(value="")
        self.e_url = ttk.Entry(sec, textvariable=self.v_url)
        self.e_url.grid(row=3, column=1, sticky="ew", padx=8, pady=3)
        self.b_fetch = ttk.Button(sec, text="Fetch", width=9, command=self._fetch_site)
        self.b_fetch.grid(row=3, column=2, pady=3)

        wrow = ttk.Frame(sec)
        wrow.grid(row=4, column=0, columnspan=3, sticky="w", pady=(0, 4))
        self.lbl_wmax = ttk.Label(wrow, text="Download up to")
        self.lbl_wmax.pack(side="left")
        self.v_wmax = tk.IntVar(value=40)
        self.sp_wmax = ttk.Spinbox(wrow, from_=1, to=300, textvariable=self.v_wmax, width=5)
        self.sp_wmax.pack(side="left", padx=(6, 16))
        self.lbl_wpages = ttk.Label(wrow, text="Pages to read")
        self.lbl_wpages.pack(side="left")
        self.v_wpages = tk.IntVar(value=1)
        self.sp_wpages = ttk.Spinbox(wrow, from_=1, to=30, textvariable=self.v_wpages, width=5)
        self.sp_wpages.pack(side="left", padx=(6, 16))
        self.lbl_wmin = ttk.Label(wrow, text="Ignore images under (px)")
        self.lbl_wmin.pack(side="left")
        self.v_wmin = tk.IntVar(value=400)
        self.sp_wmin = ttk.Spinbox(wrow, from_=50, to=2000, increment=50,
                                   textvariable=self.v_wmin, width=6)
        self.sp_wmin.pack(side="left", padx=6)

        self.lbl_lib = ttk.Label(sec, text="Product library folder")
        self.lbl_lib.grid(row=5, column=0, sticky="w", pady=3)
        self.v_lib = tk.StringVar(value=str(ROOT / "library"))
        self.e_lib = ttk.Entry(sec, textvariable=self.v_lib)
        self.e_lib.grid(row=5, column=1, sticky="ew", padx=8, pady=3)
        self.b_lib = ttk.Button(sec, text="Browse", width=9,
                                command=lambda: self._pick_dir(self.v_lib))
        self.b_lib.grid(row=5, column=2, pady=3)

        row = ttk.Frame(sec)
        row.grid(row=6, column=0, columnspan=3, sticky="w", pady=(2, 0))
        self.lbl_libn = ttk.Label(row, text="Offer the model this many items")
        self.lbl_libn.pack(side="left")
        self.v_libn = tk.StringVar(value="6")
        self.e_libn = ttk.Entry(row, textvariable=self.v_libn, width=7)
        self.e_libn.pack(side="left", padx=8)
        self.lbl_libhint = ttk.Label(row, text="(a number, or 'all' — max 13)", style="Hint.TLabel")
        self.lbl_libhint.pack(side="left")
        self.lbl_libcount = ttk.Label(sec, text="", style="Hint.TLabel")
        self.lbl_libcount.grid(row=7, column=1, sticky="w", padx=8, pady=(2, 0))

        # ---- amounts ----
        sec = self._section(wrap, "How many")
        row = ttk.Frame(sec)
        row.grid(row=0, column=0, columnspan=3, sticky="w")
        self.lbl_per = ttk.Label(row, text="Images per item")
        self.lbl_per.pack(side="left")
        self.v_per = tk.IntVar(value=1)
        self.sp_per = ttk.Spinbox(row, from_=1, to=8, textvariable=self.v_per, width=5)
        self.sp_per.pack(side="left", padx=(8, 22))
        self.lbl_var = ttk.Label(row, text="Scene variations")
        self.lbl_var.pack(side="left")
        self.v_var = tk.IntVar(value=1)
        self.sp_var = ttk.Spinbox(row, from_=1, to=50, textvariable=self.v_var, width=5)
        self.sp_var.pack(side="left", padx=(8, 22))
        self.lbl_room = ttk.Label(row, text="Photos per scene")
        self.lbl_room.pack(side="left")
        self.v_room = tk.StringVar(value="1")
        self.e_room = ttk.Entry(row, textvariable=self.v_room, width=7)
        self.e_room.pack(side="left", padx=8)

        # ---- output look ----
        sec = self._section(wrap, "Output")
        row = ttk.Frame(sec)
        row.grid(row=0, column=0, columnspan=3, sticky="w")
        ttk.Label(row, text="Aspect").pack(side="left")
        self.v_aspect = tk.StringVar(value="3:2")
        cb_asp = ttk.Combobox(row, textvariable=self.v_aspect, values=RATIOS,
                              state="readonly", width=7)
        cb_asp.pack(side="left", padx=(8, 22))
        cb_asp.bind("<<ComboboxSelected>>", lambda e: self._sync_provider())
        self.lbl_q = ttk.Label(row, text="Size")
        self.lbl_q.pack(side="left")
        self.v_quality = tk.StringVar(value="2K")
        self.cb_quality = ttk.Combobox(row, textvariable=self.v_quality,
                                       values=GOOGLE_SIZES, state="readonly", width=6)
        self.cb_quality.pack(side="left", padx=(8, 22))
        self.cb_quality.bind("<<ComboboxSelected>>", lambda e: self._sync_provider())
        self.lbl_oq = ttk.Label(row, text="Quality")
        self.lbl_oq.pack(side="left")
        self.v_oq = tk.StringVar(value="high")
        self.cb_oq = ttk.Combobox(row, textvariable=self.v_oq, values=OPENAI_QUALITY,
                                  state="readonly", width=8)
        self.cb_oq.pack(side="left", padx=(8, 22))
        ttk.Label(row, text="Format").pack(side="left")
        self.v_fmt = tk.StringVar(value="jpg")
        ttk.Combobox(row, textvariable=self.v_fmt, values=FORMATS,
                     state="readonly", width=7).pack(side="left", padx=8)
        self.lbl_asphint = ttk.Label(sec, text="", style="Hint.TLabel")
        self.lbl_asphint.grid(row=1, column=0, columnspan=3, sticky="w", pady=(4, 0))

        # ---- prompt ----
        sec = self._section(wrap, "Prompt")
        self.t_prompt = tk.Text(sec, height=5, wrap="word", relief="solid", borderwidth=1)
        self.t_prompt.insert("1.0", DEFAULT_PROMPT)
        self.t_prompt.grid(row=0, column=0, columnspan=3, sticky="ew")
        ttk.Label(sec, text="Tip: in product-list mode, {product} is replaced by each name.",
                  style="Hint.TLabel").grid(row=1, column=0, sticky="w", pady=(4, 0))

        for var in (self.v_in, self.v_csv):
            var.trace_add("write", lambda *a: self._refresh_count())
        self.v_lib.trace_add("write", lambda *a: self._sync_lib())

    # ---------- dynamic behaviour ----------
    def _sync_provider(self):
        prov = provider_of(self.v_model.get())
        mid = model_id_of(self.v_model.get())
        # Size (1K/2K/4K) applies to every model
        self.cb_quality.configure(values=GOOGLE_SIZES)
        if self.v_quality.get() not in GOOGLE_SIZES:
            self.v_quality.set("2K")

        if prov == "openai":
            choices = quality_choices(mid)
            self.lbl_key.configure(text="OpenAI API key")
            self.e_key.configure(textvariable=self.v_okey)
            self.cb_oq.configure(values=choices, state="readonly")
            if self.v_oq.get() not in choices:
                self.v_oq.set("high")
            self.lbl_oq.configure(foreground="")
            self.lbl_prov.configure(
                text="ChatGPT image models need an OpenAI key from a verified organisation.")
            actual = openai_size_for(self.v_aspect.get(), self.v_quality.get(), mid)
            if supports_arbitrary_size(mid):
                self.lbl_asphint.configure(text=f"Output resolution: {actual} pixels.")
            else:
                self.lbl_asphint.configure(
                    text=f"This model only supports fixed sizes — output will be {actual}. "
                         f"Use a GPT Image 2.5 model for 2K/4K.")
        else:
            self.lbl_key.configure(text="Google API key")
            self.e_key.configure(textvariable=self.v_gkey)
            self.cb_oq.configure(state="disabled")
            self.lbl_oq.configure(foreground="#999999")
            self.lbl_prov.configure(text="")
            self.lbl_asphint.configure(text="")
        missing = (prov == "openai" and not HAS_OPENAI) or (prov == "google" and not HAS_GOOGLE)
        if missing:
            pkg = "openai" if prov == "openai" else "google-genai"
            self.lbl_prov.configure(text=f"'{pkg}' isn't installed yet — run: pip install {pkg}")

    def _sync_mode(self):
        m = self.v_mode.get()
        def state(widgets, on):
            for w in widgets:
                try:
                    w.configure(state=("normal" if on else "disabled"))
                except tk.TclError:
                    pass
        state([self.e_in, self.b_in], m in {"edit", "compose"})
        state([self.e_csv, self.b_csv], m == "text")
        state([self.sp_per], m in {"text", "edit"})
        state([self.sp_var, self.e_room], m == "compose")
        for lbl, on in [(self.lbl_in, m in {"edit", "compose"}), (self.lbl_csv, m == "text"),
                        (self.lbl_per, m in {"text", "edit"}),
                        (self.lbl_var, m == "compose"), (self.lbl_room, m == "compose")]:
            lbl.configure(foreground=("" if on else "#999999"))
        self._sync_lib()
        self._refresh_count()

    def _cache_dir_for(self, url):
        host = (urlparse(url).netloc or "site").replace(":", "_")
        return ROOT / CACHE_DIRNAME / re.sub(r"[^\w.\-]+", "-", host)

    def _sync_lib(self):
        """The library only applies to 'One scene per photo' mode."""
        allowed = self.v_mode.get() == "edit"
        try:
            self.chk_lib.configure(state=("normal" if allowed else "disabled"))
        except tk.TclError:
            pass
        on = allowed and self.v_lib_on.get()
        web = on and self.v_src.get() == "web"

        for w in (self.e_lib, self.b_lib):
            try:
                w.configure(state=("normal" if (on and not web) else "disabled"))
            except tk.TclError:
                pass
        for w in (self.e_url, self.b_fetch, self.sp_wmax, self.sp_wpages, self.sp_wmin):
            try:
                w.configure(state=("normal" if web else "disabled"))
            except tk.TclError:
                pass
        try:
            self.e_libn.configure(state=("normal" if on else "disabled"))
        except tk.TclError:
            pass
        for lbl, active in [(self.lbl_src, on), (self.lbl_lib, on and not web),
                            (self.lbl_url, web), (self.lbl_wmax, web),
                            (self.lbl_wpages, web), (self.lbl_wmin, web),
                            (self.lbl_libn, on), (self.lbl_libhint, on)]:
            lbl.configure(foreground=("" if active else "#999999"))

        # when using a website, the library folder IS the download cache
        if web and self.v_url.get().strip():
            self.v_lib.set(str(self._cache_dir_for(self.v_url.get().strip())))

        if on:
            n = len(list_images(self.v_lib.get()))
            if web and n == 0:
                self.lbl_libcount.configure(text="Nothing downloaded yet — press Fetch.")
            else:
                self.lbl_libcount.configure(
                    text=f"{n} product photo(s) available" if n else "No images found in that folder yet")
        else:
            self.lbl_libcount.configure(text="")

    def _fetch_site(self):
        if not HAS_WEB:
            messagebox.showerror(
                "Missing components",
                "Fetching from a website needs two extra packages.\n\n"
                "Run in this folder:\n  pip install requests beautifulsoup4")
            return
        url = self.v_url.get().strip()
        if not url:
            messagebox.showerror("No address", "Please enter a website address.")
            return
        if not url.lower().startswith(("http://", "https://")):
            url = "https://" + url
            self.v_url.set(url)

        dest = self._cache_dir_for(url)
        self.v_lib.set(str(dest))
        self.b_fetch.configure(state="disabled")
        self.status.configure(text="Fetching product images…")
        self._logmsg(f"\nFetching products from {url}")
        self._logmsg(f"   into {dest}")

        maxi, pages, minpx = int(self.v_wmax.get()), int(self.v_wpages.get()), int(self.v_wmin.get())

        def work():
            try:
                n = fetch_site_images(url, dest, max_images=maxi, min_px=minpx,
                                      max_pages=pages, log=lambda m: self.q.put(("log", m)),
                                      stop_flag=self.stop_flag)
                self.q.put(("fetched", n))
            except Exception as e:
                self.q.put(("fetch_error", str(e)))

        threading.Thread(target=work, daemon=True).start()

    def _refresh_count(self):
        m = self.v_mode.get()
        try:
            if m == "text":
                n = len(read_products(self.v_csv.get()))
                self.lbl_count.configure(text=f"{n} product(s) in the list")
            else:
                n = len(list_images(self.v_in.get()))
                self.lbl_count.configure(text=f"{n} image(s) in the input folder")
        except Exception:
            self.lbl_count.configure(text="")

    # ---------- small helpers ----------
    def _pick_dir(self, var):
        d = filedialog.askdirectory(initialdir=var.get() or str(ROOT))
        if d:
            var.set(d)

    def _pick_file(self, var):
        d = filedialog.askopenfilename(initialdir=str(ROOT),
                                       filetypes=[("CSV", "*.csv"), ("All files", "*.*")])
        if d:
            var.set(d)

    def _open_out(self):
        d = self.v_out.get()
        Path(d).mkdir(parents=True, exist_ok=True)
        try:
            if sys.platform.startswith("win"):
                os.startfile(d)
            elif sys.platform == "darwin":
                os.system(f'open "{d}"')
            else:
                os.system(f'xdg-open "{d}"')
        except Exception:
            pass

    def _logmsg(self, msg):
        self.log.configure(state="normal")
        self.log.insert("end", msg + "\n")
        self.log.see("end")
        self.log.configure(state="disabled")

    def _reset(self):
        if not messagebox.askyesno("Reset", "Put all settings back to defaults?"):
            return
        self.v_model.set(MODEL_LABELS[0]); self.v_mode.set("edit")
        self.v_in.set(str(ROOT / "inputs")); self.v_csv.set(str(ROOT / "products.csv"))
        self.v_out.set(str(ROOT / "outputs"))
        self.v_per.set(1); self.v_var.set(1); self.v_room.set("1")
        self.v_aspect.set("3:2"); self.v_quality.set("2K"); self.v_fmt.set("jpg")
        self.v_oq.set("high")
        self.v_lib_on.set(False); self.v_lib.set(str(ROOT / "library")); self.v_libn.set("6")
        self.v_src.set("folder"); self.v_url.set("")
        self.v_wmax.set(40); self.v_wpages.set(1); self.v_wmin.set(400)
        self.t_prompt.delete("1.0", "end"); self.t_prompt.insert("1.0", DEFAULT_PROMPT)
        self._sync_provider(); self._sync_mode()

    # ---------- settings ----------
    def _load_keys(self):
        if load_dotenv and ENV_PATH.exists():
            load_dotenv(ENV_PATH)
        g = os.getenv("GEMINI_API_KEY", "")
        o = os.getenv("OPENAI_API_KEY", "")
        self.v_gkey.set("" if g.strip() in {"", "PASTE_YOUR_KEY_HERE"} else g)
        self.v_okey.set("" if o.strip() in {"", "PASTE_YOUR_KEY_HERE"} else o)

    def _save_keys(self):
        try:
            ENV_PATH.write_text(
                f"GEMINI_API_KEY={self.v_gkey.get().strip()}\n"
                f"OPENAI_API_KEY={self.v_okey.get().strip()}\n", encoding="utf-8")
        except Exception:
            pass

    def _save_settings(self):
        data = {
            "model": self.v_model.get(), "mode": self.v_mode.get(),
            "in": self.v_in.get(), "csv": self.v_csv.get(), "out": self.v_out.get(),
            "per": int(self.v_per.get()), "var": int(self.v_var.get()), "room": self.v_room.get(),
            "aspect": self.v_aspect.get(), "quality": self.v_quality.get(), "fmt": self.v_fmt.get(),
            "oq": self.v_oq.get(),
            "prompt": self.t_prompt.get("1.0", "end").strip(),
            "lib_on": self.v_lib_on.get(), "lib": self.v_lib.get(), "libn": self.v_libn.get(),
            "src": self.v_src.get(), "url": self.v_url.get(),
            "wmax": int(self.v_wmax.get()), "wpages": int(self.v_wpages.get()),
            "wmin": int(self.v_wmin.get()),
        }
        try:
            SETTINGS_PATH.write_text(json.dumps(data, indent=2), encoding="utf-8")
        except Exception:
            pass

    def _load_settings(self):
        self._load_keys()
        if not SETTINGS_PATH.exists():
            return
        try:
            d = json.loads(SETTINGS_PATH.read_text(encoding="utf-8"))
        except Exception:
            return

        def setv(var, val):
            if val is not None:
                try:
                    var.set(val)
                except Exception:
                    pass
        if d.get("model") in MODELS:
            setv(self.v_model, d["model"])
        setv(self.v_mode, d.get("mode"))
        setv(self.v_in, d.get("in")); setv(self.v_csv, d.get("csv")); setv(self.v_out, d.get("out"))
        setv(self.v_per, d.get("per")); setv(self.v_var, d.get("var")); setv(self.v_room, d.get("room"))
        setv(self.v_aspect, d.get("aspect")); setv(self.v_quality, d.get("quality"))
        setv(self.v_fmt, d.get("fmt")); setv(self.v_oq, d.get("oq"))
        setv(self.v_lib_on, d.get("lib_on")); setv(self.v_lib, d.get("lib"))
        setv(self.v_libn, d.get("libn"))
        setv(self.v_src, d.get("src")); setv(self.v_url, d.get("url"))
        setv(self.v_wmax, d.get("wmax")); setv(self.v_wpages, d.get("wpages"))
        setv(self.v_wmin, d.get("wmin"))
        if d.get("prompt"):
            self.t_prompt.delete("1.0", "end")
            self.t_prompt.insert("1.0", d["prompt"])

    def _on_close(self):
        self._save_settings()
        self._save_keys()
        self.root.destroy()

    # ---------- run ----------
    def _poll(self):
        try:
            while True:
                kind, payload = self.q.get_nowait()
                if kind == "log":
                    self._logmsg(payload)
                elif kind == "max":
                    self.progress["maximum"] = payload
                    self.progress["value"] = 0
                elif kind == "progress":
                    self.progress["value"] = payload
                    self.status.configure(text=f"Working… {payload}/{int(self.progress['maximum'])}")
                elif kind == "fetched":
                    self.b_fetch.configure(state="normal")
                    self._sync_lib()
                    msg = (f"Downloaded {payload} product image(s)." if payload
                           else "No suitable images found on that page.")
                    self._logmsg(msg)
                    self.status.configure(text=msg)
                    if not payload:
                        messagebox.showinfo(
                            "Nothing downloaded",
                            "No suitable product images were found.\n\n"
                            "Try a product listing page, lower the minimum size, "
                            "or increase 'Pages to read'. Some shops load images with "
                            "JavaScript, which this can't see — saving them manually to a "
                            "folder works in that case.")
                elif kind == "fetch_error":
                    self.b_fetch.configure(state="normal")
                    self.status.configure(text="Fetch failed")
                    self._logmsg(f"Fetch failed: {payload}")
                    messagebox.showerror("Fetch failed", payload)
                elif kind in ("done", "error"):
                    self._logmsg(payload)
                    self.status.configure(text=payload)
                    self.btn_start.configure(state="normal")
                    self.btn_stop.configure(state="disabled")
                    (messagebox.showerror if kind == "error" else messagebox.showinfo)(
                        "Nano Batch Studio", payload)
        except queue.Empty:
            pass
        self.root.after(120, self._poll)

    def _stop(self):
        self.stop_flag.set()
        self.status.configure(text="Stopping after the current image…")

    def _start(self):
        if "Pillow" in _MISSING:
            messagebox.showerror("Missing component",
                                 "Pillow isn't installed.\n\nRun:  pip install -r requirements.txt")
            return
        label = self.v_model.get()
        prov = provider_of(label)
        key = (self.v_okey if prov == "openai" else self.v_gkey).get().strip()
        if not key:
            messagebox.showerror("No API key",
                                 f"Please paste your {'OpenAI' if prov=='openai' else 'Google'} API key.")
            return
        prompt = self.t_prompt.get("1.0", "end").strip()
        if not prompt:
            messagebox.showerror("No prompt", "Please write a prompt.")
            return

        self._save_keys()
        self._save_settings()
        self.stop_flag.clear()
        self.btn_start.configure(state="disabled")
        self.btn_stop.configure(state="normal")
        self.status.configure(text="Starting…")

        s = {
            "provider": prov, "model_label": label, "model_id": model_id_of(label),
            "google_key": self.v_gkey.get().strip(), "openai_key": self.v_okey.get().strip(),
            "mode": self.v_mode.get(), "input_dir": self.v_in.get(),
            "products_csv": self.v_csv.get(), "out_dir": self.v_out.get(),
            "per": self.v_per.get(), "variations": self.v_var.get(), "per_room": self.v_room.get(),
            "aspect": self.v_aspect.get(), "size_tier": self.v_quality.get(),
            "oq": self.v_oq.get(),
            "fmt": self.v_fmt.get(), "prompt": prompt,
            "lib_on": self.v_lib_on.get(), "lib_dir": self.v_lib.get(),
            "lib_count": self.v_libn.get(),
        }

        def work():
            try:
                run_batch(s, self.q, self.stop_flag)
            except Exception as e:
                self.q.put(("error", f"Stopped: {e}"))

        threading.Thread(target=work, daemon=True).start()


def ensure_folders():
    """Create the working folders if they're missing, so a fresh clone just runs."""
    for name in ("inputs", "outputs", "library", CACHE_DIRNAME):
        try:
            (ROOT / name).mkdir(parents=True, exist_ok=True)
        except Exception:
            pass


def main():
    from studio_ui import StudioApp
    if sys.platform.startswith("win"):
        try:
            import ctypes
            ctypes.windll.shcore.SetProcessDpiAwareness(1)
        except (AttributeError, OSError):
            pass
    ensure_folders()
    root = tk.Tk()
    StudioApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
