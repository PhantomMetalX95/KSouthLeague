# Gameweek video maker

Turns one gameweek into a vertical (1080x1920) round-up video with a voice-over:
intro, one scene per match (score, scorers, assists, cards, clean sheets), results and week totals, the table with
movement arrows, and a "next up" outro. Works for Instagram Reels, TikTok, WhatsApp Status and Facebook Stories.

The data comes straight from your site (the same data as the Gameweeks and Stats pages), so enter the results and
the Match stats in Admin first.

## One-time setup (Windows)
1. Install Python 3.10, 3.11 or 3.12 from python.org. Tick "Add python.exe to PATH" in the installer.
2. Open PowerShell in this folder and run:
   ```
   pip install -r requirements.txt
   ```
3. Open `api-address.txt` and replace the line with your site's data address, for example `https://your-site.com/api/data`.

## Make a video
- Easiest: double-click `make-video.bat`, type the gameweek number (or press Enter for the latest) and wait.
- Or in PowerShell:
  ```
  python make_video.py --api https://your-site.com/api/data --week 3
  ```
  Output: `gameweek-3.mp4`, plus `gameweek-3.txt` containing the exact voice-over script.
- Try it without your site: `python make_video.py --data sample-data.json --week 2`

A video takes a few minutes to render on an ordinary PC.

## Voice-over
`--voice auto` (default) tries these in order and tells you which one it used:

| Voice | Needs | Notes |
|---|---|---|
| `edge` | internet, `pip install edge-tts` (in requirements) | Natural voices. Default voice is Kenyan English (`en-KE-ChilembaNeural`); falls back to `en-GB-RyanNeural`. List voices with `edge-tts --list-voices`. |
| `kokoro` | `pip install kokoro-onnx soundfile` | Works offline. Downloads a ~120 MB voice model into `tts/` the first time. Voices such as `bm_george`, `bm_lewis`, `am_michael`. |
| `sapi` | `pip install pyttsx3` | Windows built-in voices, offline, more robotic. |
| `none` | nothing | Silent video. |

Pick one with `--voice kokoro --voice-name bm_lewis`. Speed for the edge voice: `--rate +12%`.

## Useful options
- `--cta "FOLLOW @YOURPAGE"` text on the last screen.
- `--music song.mp3` mixes music quietly under the voice (use music you have the rights to).
- `--stills folder` saves a PNG of every scene (handy for a thumbnail or a single image post).
- `--no-video` only writes the script text and stills.

## Fixing how names are spoken
Open `make_video.py` and edit `PRONOUNCE` near the top. The left side is how the name appears on screen,
the right side is how the voice should say it, for example `"Civo": "Cheevo"`.
Read the generated `.txt` file to check the script before posting.

## Notes
- A match with no stats entered still gets a scene, with the score only ("Match details not recorded").
- Only finished matches in the chosen gameweek are included.
- Team crests are read from `assets/badges/` (matched by file name). Add new crests there with the same file name you used on the site.
- Fonts (Big Shoulders Display, Archivo) are open-licence and bundled in `assets/fonts/`.
