# local-tts

Local text-to-speech generation with Resemble AI Chatterbox voice cloning.

First-time setup installs Python dependencies and downloads the Chatterbox model
into `models/huggingface`. Later runs reuse the downloaded model and generate
MP3 files into `output/`.

## First-Time Setup

Create and activate a virtual environment if you do not already have one:

```bash
python -m venv .venv
source .venv/bin/activate
```

Install Python dependencies:

```bash
pip install -r requirements.txt
```

Install `ffmpeg` for MP3 conversion:

```bash
sudo apt install ffmpeg
# or
brew install ffmpeg
```

Chatterbox downloads model files from Hugging Face on first use.

Default model cache:

```text
models/huggingface
```

Model:
https://huggingface.co/ResembleAI/chatterbox/tree/main

Source:
https://github.com/resemble-ai/chatterbox

## Input Files

Default files:

```text
data/reference.mp3
data/segments.json
```

Use a clean reference recording: one speaker, minimal background noise, no
music, and audio you have permission to use.

`data/segments.json` must be a JSON object with a `segments` array. Each segment
requires `text` and `audio_filename`.

```json
{
  "segments": [
    {
      "id": "seg_001",
      "audio_filename": "001_intro.mp3",
      "text": "Text to speak."
    }
  ]
}
```

Examples:

- [data/segments.example.json](data/segments.example.json)
- [data/reference.example.txt](data/reference.example.txt)

For a new project, copy the JSON example and edit it:

```bash
cp data/segments.example.json data/segments.json
```

Then add your real reference audio as `data/reference.mp3` or
`data/reference.wav`.

## Settings

Edit [.env](.env) for normal runs:

```dotenv
LOCAL_TTS_SEGMENTS=data/segments.json
LOCAL_TTS_REFERENCE=data/reference.mp3
LOCAL_TTS_OUTPUT_DIR=output
LOCAL_TTS_MODEL_CACHE=models/huggingface
LOCAL_TTS_DEVICE=auto
LOCAL_TTS_MULTILINGUAL=false
LOCAL_TTS_LANGUAGE_ID=en
LOCAL_TTS_EXAGGERATION=0.35
LOCAL_TTS_CFG_WEIGHT=0.3
LOCAL_TTS_BITRATE=192k
LOCAL_TTS_FORCE=false
LOCAL_TTS_DRY_RUN=false
```

`.env` is intentionally non-secret. Do not put API keys, passwords, or other
credentials in it.

Useful settings:

- `LOCAL_TTS_MODEL_CACHE`: where downloaded Chatterbox model files are stored.
- `LOCAL_TTS_DEVICE`: `auto`, `cuda`, `mps`, or `cpu`.
- `LOCAL_TTS_FORCE`: regenerate files that already exist.
- `LOCAL_TTS_MULTILINGUAL`: use the multilingual model.
- `LOCAL_TTS_LANGUAGE_ID`: language code for multilingual mode.

CLI flags can override `.env` for one run.

## First Model Download

Download the model once:

```bash
python generate_local_chatterbox_segments.py --download-model
```

This stores model files under:

```text
models/huggingface
```

The download can take time and disk space. If the model is already present, the
same command reuses it and exits.

Then run a dry run. This validates input paths and output filenames without
loading the model:

```bash
python generate_local_chatterbox_segments.py --dry-run
```

Then run generation:

```bash
python generate_local_chatterbox_segments.py
```

Generated MP3 files are written to `output/`. The run manifest is written to
`output/generation_manifest.json`.

## Later Runs

Activate the environment, edit `data/segments.json` or `.env` if needed, then
run:

```bash
source .venv/bin/activate
python generate_local_chatterbox_segments.py --dry-run
python generate_local_chatterbox_segments.py
```

Set `LOCAL_TTS_FORCE=true` in `.env` or pass `--force` to regenerate MP3 files
that already exist.

Use a different settings file:

```bash
python generate_local_chatterbox_segments.py --env-file my-settings.env
```

## Project Structure

```text
generate_local_chatterbox_segments.py  CLI entrypoint
local_tts/                             implementation modules
data/                                  input templates and local input files
output/                                generated MP3 files
```
