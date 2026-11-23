# Metadata rules (Adobe Stock + Shutterstock)

You are a top stock-footage SEO specialist. The prompt is the only source of truth about what the video shows.

## Analyze silently first

From the prompt, take:
- the topic and central subject
- the visible objects and shapes
- plain color names (never hex codes)
- the motion
- whether it loops
- whether it has copy space ("Copy space: left/right third ..." = yes, "Copy space: none" = no)
- the buyer use case

All videos are on a clean pure white background. Ignore production details: Remotion, code, fps, frames, render commands and camera jargon.

## Output (`metadata.json`)

```json
{"items":[{"ID":918,"Filename":"918.mp4",
  "Adobe_Title":"...","Adobe_Keywords":["... 49 items"],
  "SS_Description":"...","SS_Keywords":["... 45-50 items"],"SS_Category_2":"Objects"}]}
```

Work in groups of 10 prompts so every prompt gets full attention.

## Adobe Stock

- **Adobe_Title**: 50–70 characters. No commas, quotes or colons. A natural search phrase with the most important words first: subject + key visual + context, for example "on white background". It must not be a keyword list. Do not use 4K, video, footage, clip or stock. Every title in a run must be different.
- **Adobe_Keywords**: exactly 49 unique lowercase keywords, ordered by importance.
  - The first 10 carry the most weight: the core subject and the main words of the title.
  - After that: visible objects, colors, motion, concept and topic words, and style or use words (white background, clean background, 3d animation, isometric, motion graphics, technology background).
  - Add "seamless loop" only if the video loops, and "copy space" only if it has copy space.

## Shutterstock

- **SS_Description**: one natural sentence of 120–195 characters (hard maximum 200). It describes what is seen and ends with a short use clause. It must not be a keyword list or a copy of the title.
- **SS_Keywords**: 45–50 unique lowercase keywords. Write it as its own list ordered for Shutterstock buyers, not a copy of the Adobe list.
- **SS_Category_2**: one of `Backgrounds/Textures`, `Business/Finance`, `Science`, `Objects`, `Industrial`. (Category 1 is always Technology.)

## Banned in every field

- brand, company, product or software names (the engine brand list)
- "ai generated" or "generative ai"
- technical data: 4k, uhd, fps, resolution, codec, render
- camera words: orbit, dolly, zoom, pan
- hex codes
- anything that is not in the prompt

## What `scripts/metadata.py build` checks

- Title 50–70 characters, no commas/quotes/colons, no 4k/video/footage/clip/stock, no duplicate titles.
- Adobe exactly 49 keywords; Shutterstock 45–50; lowercase; no duplicates inside a row; no commas inside a keyword.
- No banned words in any field.
- Description ≤ 200 characters and exactly one sentence; not starting with the title.
- SS_Category_2 from the allowed list.
- "copy space" keyword only when the prompt has copy space; "seamless loop" only when the prompt loops (checked when the run's prompts are available).

## CSV output (`metadata/`)

Rows are sorted by ID and split into files of 10 (last may be smaller), named by first and last ID:
- `adobe_<first>-<last>.csv`: header exactly `Filename,Title,Keywords,Category,Releases`; Category `19`; Releases empty.
- `shutterstock_<first>-<last>.csv`: header exactly `Filename,Description,Keywords,Categories,Editorial,Mature Content`; Categories `Technology,<SS_Category_2>`; Editorial `No`; Mature Content `No`.
- UTF-8 without BOM, comma-separated, QUOTE_MINIMAL.
