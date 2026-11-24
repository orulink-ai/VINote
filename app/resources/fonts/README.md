# Fixed desktop graphic font

NotoSansSC-Regular.ttf is the unmodified, static weight-400 Noto Sans SC asset
already included in VINote-app. This desktop copy is independent of the App
submodule at runtime. It is distributed with its SIL Open Font License in OFL.txt.

SHA-256: `028a6826552d2ab32eede9d4243381351382a154f974d96cac543fc571570407`

Upstream provenance recorded with the original asset: Google Fonts Noto Sans SC,
retrieved 2026-10-11 and instantiated at wght=400 with fontTools. No download or
font modification is part of the desktop renderer/build. The renderer verifies
this exact hash and never substitutes a system font or fetches missing glyphs.

## Visual slides bold weight

`NotoSansSC-Bold.ttf` is the companion static weight-700 Noto Sans SC asset used
by VINote's offline HTML visual slide renderer (`visual_slide_renderer.py`) to
provide crisp heading and KPI typographic contrast alongside `NotoSansSC-Regular.ttf`.
Distributed under the same SIL Open Font License in `OFL.txt`.

SHA-256: `8c3394530d07b75cada0128a643801db834efd045d94bae5106612c68cc290b4`

Upstream provenance: Google Fonts `NotoSansSC[wght].ttf`, instantiated at
`wght=700` with `fontTools.varLib.instancer`. Verified strictly by SHA-256
before in-memory CDP fulfillment.
