# Nano Batch Studio

A desktop app for making product images in batches — turn a folder of product
photos into styled scenes, or generate images from a product list. Built for
e-commerce and interior work where you need the same treatment applied across
many products.

Runs locally on Windows, macOS and Linux. Bring your own API key.

![Python](https://img.shields.io/badge/python-3.10%2B-blue)
![License](https://img.shields.io/badge/license-MIT-green)

---

## What it does

**Three ways to work**

| Mode | What it does |
|---|---|
| **Photo scenes** | Builds a new scene around each photo in a folder — one image in, one out, original filenames kept. |
| **Product list** | Generates images from product names in a CSV, no photos needed. |
| **Combine** | Blends several product photos into one scene, with variations. |

**Furnish with your own products.** In Photo scenes mode you can hand the model
a library of your own product photos and tell it to use *only* those to dress
the scene, instead of inventing furniture. The library can be a local folder or
images fetched automatically from a website.

**Ten models, two providers.** Google's Nano Banana family (Pro, 2, 2 Lite) and
OpenAI's GPT Image family — including **GPT Image 2.5 Sunburst**, the strongest at
reproducing your product faithfully, and **GPT Image 2.5 Flare** for faster batches.
Switch between them from one dropdown; each provider's key is stored separately.

**Batch-friendly.** Live progress and log, a Stop button that responds
immediately, automatic retries on genuine network hiccups, no wasted retries on
errors that can never succeed, and files that never overwrite each other.

---

## Install

You need [Python 3.10+](https://www.python.org/downloads/) with Tkinter
(included in the standard installer — on Windows, tick *Add Python to PATH*).

```bash
git clone https://github.com/YOUR-USERNAME/nano-batch-studio.git
cd nano-batch-studio
pip install -r requirements.txt
```

Then start it:

```bash
python nano_batch.py
```

On Windows you can double-click **run_batch.bat** instead.

### API keys

Get a key from [Google AI Studio](https://aistudio.google.com/apikey) or the
[OpenAI platform](https://platform.openai.com/api-keys), then paste it into the
**API key** box in the app — it is saved to a local `.env` file for next time.

Both providers' image models are paid, so billing must be enabled. OpenAI's GPT
Image models additionally require organisation verification.

> `.env` and `settings.json` are git-ignored. Never commit real keys.

---

## Using it

1. Put your product photos in the `inputs` folder.
2. Open the app and pick a mode under **Choose your source**.
3. Write your prompt — what the scene should look like.
4. Pick a model, aspect ratio, resolution and file format.
5. Press **Generate images**. Results land in `outputs`.

Optional: on the **Product library** page, switch on *Use only my own products*
and point it at a folder, or fetch from a website.

### Output sizes

Google models take a free aspect ratio at 1K / 2K / 4K. OpenAI's GPT Image 2.5
and GPT Image 2 accept custom resolutions, and the app works out the largest
valid size for your aspect ratio within OpenAI's limits. Older GPT Image models
support only three fixed sizes; the app tells you when that applies.

---

## Project layout

```
nano_batch.py      generation engine, models, providers, settings
studio_ui.py       the interface
requirements.txt   dependencies
products.csv       example product list for Product list mode
```

The `inputs`, `outputs`, `library` and `library_cache` folders are created
automatically the first time you run the app.

`studio_ui.py` subclasses the app in `nano_batch.py` and replaces only the
presentation layer, so the engine and interface can be worked on separately.

---

## Notes

- Images from Google's models carry an invisible SynthID watermark.
- The website library reads a page's HTML; sites that load images purely with
  JavaScript return nothing, in which case save the images to a folder instead.
- Only fetch images you have the rights to use.

## License

MIT — see [LICENSE](LICENSE).
