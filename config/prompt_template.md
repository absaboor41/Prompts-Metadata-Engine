# Prompt template (exact output format; downstream tools depend on it)

`scripts/engine.py` reads the block between the TEMPLATE markers. Placeholders in `{braces}` are filled in a single pass:

| Placeholder | Filled with |
|---|---|
| `{ID}` | `__ID__` placeholder; `sheets.py append` replaces it with the real sheet ID |
| `{copy_space_text}` | "left third stays clean pure white so buyers can add their own title" / "right third ..." / "none (subject may use the full frame with balanced negative space)" |
| `{timeline_lines}` | one `- {time}: {action}` line per timeline beat |
| `{palette_hex_list}` | the look's colors, e.g. `#1D4ED8 royal blue (primary), ...` |
| `{lighting}` | standard lighting from looks.json + the concept's `lighting_and_fx` |
| `{build_3d_line}` | the @remotion/three line; the whole line is dropped when `build_3d` is false |
| `{keywords}` | `search_keywords` joined with ", " |

Do not edit the block unless the rendering agent is changed to match.

<!-- TEMPLATE START -->
```text
=== PROMPT {ID} ===
Title: {concept_name}
Niche: {niche} | Asset type: {asset_type_label}
Buyer use: {buyer_use_case}
Trend: {trend_hook}

CONCEPT
Central visual metaphor: {visual_metaphor}
{scene_description}
Copy space: {copy_space_text}

TIMELINE ({duration}s @ {fps}fps = {frames} frames)
{timeline_lines}

CAMERA
{camera}

COLOR & LIGHTING (on pure white #FFFFFF)
Palette ({look}): {palette_hex_list}
Color usage: {color_usage}
Lighting: {lighting}

MOTION
{motion_details}

BUILD SPECS
- Composition id "Asset{ID}", 3840x2160, {fps}fps, durationInFrames {frames}; code in src/assets/{ID}/.
- {build_3d_line}
- Seamless loop: drive animation from loopT = frame / {frames} with whole-number cycles (Math.sin(2 * Math.PI * k * loopT), integer k); frame {frames} must equal frame 0.
- Render: npx remotion render Asset{ID} output/{ID}.mp4 --codec=h264 --crf=16 --pixel-format=yuv420p --color-space=bt709

KEYWORDS: {keywords}
```
<!-- TEMPLATE END -->
