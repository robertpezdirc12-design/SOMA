# Changelog

All notable changes to SOMA. The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), version numbers
are major.minor.bugfix. New entries collect under "Unreleased" and move into their own section with date and Git tag when
the version is bumped.

## [Unreleased]

### Added

- `soma inspect`: what the model is, measured instead of looked at. It reports volume, surface area, bounding box, centre of mass, the number of solids, shells, faces, edges and vertices, and whether each part is a valid, closed body — for the whole model and per part, as one JSON document with a fixed schema (`soma.inspect/1`, described in `docs/INSPECT-SCHEMA.md`). The same command measures a finished STEP or BREP file (`--step`), so an export can be checked against the model it came from: same number of bodies, same volume, same box. `--density 1.24` adds a mass estimate, `--strict` makes a geometric error an exit code for CI. The document contains no timestamp and no absolute path, so two runs on the same geometry are identical and can be diffed.
- `docs/FASTENERS-INVENTORY.md`: what the standard-parts library covers today, which of the 48 bd_warehouse tables are used (20), and what is missing — bearings, a bill of materials, low-profile and shoulder screws, retaining rings, shaft keys, O-rings, and the partially threaded shank of ISO 4014. It also records why `cq_warehouse` should not be added as a dependency: the tables are already here and the geometry is SOMA's own code.
- `soma mcp`: SOMA as an MCP server over stdio, for coding agents outside the app (Codex, Claude Code, Gemini CLI, Cursor). Four tools: build the model, measure it, list what it needs, export it. None of them takes code, a command or a path — the project folder is fixed when the server starts and export always writes to `exports/` inside it, so an agent cannot run anything the user did not already run by opening the model. `--read-only` leaves only the measuring tools in the list. Whatever a model prints while a tool runs goes to stderr, so the protocol on stdout stays clean.
- `soma bom`: the parts list, read from the model instead of typed by hand. Purchased parts are grouped by designation with a count — four screws called "Screw 1".."Screw 4" are one line with count 4 — and heat-set inserts carry the manufacturer's part number from the table. Own parts are listed with volume, and with `--density` a mass. `--csv` writes a table for a spreadsheet (UTF-8 with BOM, so Excel shows umlauts), `--merge-identical` puts own parts that repeat on one line. Until now a purchased part existed in the model and then disappeared from every output, because `soma export --all` skips them on purpose. Schema `soma.bom/1`, described in `docs/BOM.md`.
- Bearings: `Bearing("608", at=(x, y, z))` from the standard-parts library. Deep-groove ball bearings from 3 to 10 mm bore, open and capped (`623-2Z`, `E2.608-2Z`, `630/8-2RS1`), 56 catalogue numbers. Bore, outside diameter and width are the catalogue values, so the part sits in a housing and on a shaft like a washer; the rings and balls in between follow a rule rather than a catalogue drawing, and the weight is the catalogue mass (`mass_g`) and not volume x density. Each bearing is one body, so `soma inspect` does not warn about several bodies, and two 608s in a model become one line with count 2 in `soma bom`. It started with the two deep-groove tables only; the three roller and angular-contact tables followed later in the same release, below.
- Angular-contact and roller bearings, in the same class: `Bearing("7200 BECBP")`, `Bearing("NJ 202 ECP")`, `Bearing("30302 J2")`. The three tables the inventory had deliberately left out (G1a) are now read, so the library covers 100 catalogue numbers in five families and bores from 3 to 15 mm. `kind` says what rolls (`"ball"` or `"roller"`) and `family_key` which table the number came from. Two things the data decided: a tapered roller bearing's width is `T` and not `B` — `B` is only the inner ring, so a bearing built on it would be 1.25 mm too thin at 30302 and would not enter its housing — and the tapered table weighs in `kg` where the others weigh in `mass`. The cone angle is **not** guessed: the table gives `a`, the distance from the face to the cone apex, which is not an angle, so the rollers are cylinders exactly as in the cylindrical family and the docstring says so. What is exact is the envelope, which is what decides whether the part fits.
- Shoulder screws: `Screw("ISO 7379", "M6x25")`. The length is the shoulder length, as the standard defines it, so `shank_length` is longer by the threaded end and `shoulder_hole()` cuts the pivot hole at the shoulder diameter instead of the thread clearance — an M6 shoulder screw needs 6.5 mm, not 6.6. Built as one revolve (head, shoulder, undercut, threaded end) because the undercut is narrower than the thread: fusing cylinders would leave a bore where the drawing has a groove. Sizes M5 to M10.
- Low profile socket head screws: `Screw("OpenBuilds", "M5x10")`. Named after the series the table really is, not DIN 7984 — the head is lower (1.5 instead of 2.0 mm at M3) and wider. Asking for "DIN 7984" now answers with that sentence instead of handing out dimensions that are not DIN 7984.
- Retaining rings: `RetainingRing("DIN 471", 20, at=(x, y, z))` for a shaft, `"DIN 472"` for a bore, 86 and 88 sizes from 3 to 300 mm. The ring body, its width, the thickness and the gap are the table values; the lugs are rectangles with a plier hole, which is a drawing rather than a measurement. `ring.groove()` cuts the matching groove — floor at `d2`, width `m`, centred on the ring — so the ring and its groove cannot disagree.
- Shaft keys: `ShaftKey("DIN 6885", 20, 40)` or `ShaftKey(20, 40)`, form A with rounded ends, shafts from 6 to 50 mm. The key straddles the shaft surface: `at` is a point on the shaft, it reaches `shaft_depth` in and `height - shaft_depth` out. `keyway("shaft")` cuts the milled groove with rounded ends, `keyway("hub")` the broached one with square ends, each at the depth of the table. The two depth columns were the open question and were settled against all 31 rows: `t4` is the shaft, `t2` the hub, and `t2 + t4` is always the key height plus 0.2 to 0.3 mm of clearance.
- Pan head and cheese head screws: `Screw("ISO 1580", "M3x10")` and `Screw("ISO 1207", "M3x10")`, from M1.6 to M10. Both are one flat cylinder with a chamfered rim, which is what both heads are; the slot is not modelled, as no thread is, so `Screw.key` returns `None` for them instead of inventing a width across flats. The head dimensions come from the table, so the pan head is visibly the flat one — 1.8 mm high at M3 against 3.0 mm for a socket head.
- Heads with a collar: `Screw("DIN 967", "M5x20")` (pan head with collar), `Screw("ISO 7380-2", "M5x20")` (button head with collar) and `Screw("DIN 1662", "M6x30")` (hexagon bolt with flange). All three widen the bearing surface with a disc of `dc` and height `c`, and in all three `k` is the height **over all**, so the collar is the lower part of the head and not an addition to it — adding it would make every one of them too tall by `c`. The collar is drawn as a cylinder; the 25° underside and the c/2 rim rounding change neither the envelope nor the bearing face, and the docstring says so. `head_diameter` now prefers `dc`, because for these three the widest point is the collar and not the head: DIN 1662 M6 is 13.6 mm at the flange against 6.93 mm across the hexagon corners.
- `Screw("ISO 7045", "M5x20")`: the cross-recess pan head, geometrically the same head as ISO 1580. `Washer("ISO 7092", "M3")`: the small plain washer, down to M1.
- `Screw("DIN 1665")` now answers that DIN 1665 is the nut and DIN 1662 the bolt, instead of leaving the reader with a list of standards — the flange table carries both column sets, so the confusion is easy to walk into.
- Unchamfered hex nut: `Nut("ISO 4036", "M6")`. A table of its own, not ISO 4032 with the chamfer filed off — it is a lower nut in the same width across flats (M6: 3.2 against 5.2 mm), and `nut.chamfer` says which one you have. Without the chamfer the bearing face is the full width across corners, which is what a washer or a plate bears on.
- Flange and domed cap nuts: `Nut("DIN 1665", "M6")` and `Nut("DIN 1587", "M6")`. The flange nut is the hexagon plus a disc at its seat (M5 to M20), the cap nut a hemisphere on top of the hexagon with the bore stopping at the dome (M4 to M24) — so the cap nut is genuinely closed, and a probe above the hexagon finds material instead of air.
- Chamfered and internal-tooth lock washers: `Washer("ISO 7090", "M5")` and `Washer("DIN 6797", "M3")`. The lock washer gets `n` radial teeth reaching 30 % of the radial width into the bore, with the tooth count taken from the table's `n` column. ISO 7090 starts at M5 — M3 and M4 are not in that standard.
- O-rings: `ORing("025", at=(x, y, z))` with `gland()` for the groove, 349 sizes from 001 to 475 and eight cord thicknesses. The size is the ISO 3601 dash number, not a diameter — 025 is 29.87 mm inside, 020 is 21.95 — so `for_inner_diameter(30, 1.78)` answers the question a designer actually asks, and a size that does not exist is rejected with that sentence instead of quietly becoming another ring. `gland(kind="shaft"|"bore"|"face")` cuts the groove from the same numbers that place the ring: the floor is the ring's inner diameter, the bore its outer diameter, the face groove floor its underside, so ring and groove cannot disagree. Width, depth and the corner radius at the groove floor come from the gland table by cord thickness, and `gland_spec()` returns them with the squeeze in mm and percent for a drawing. The gland dimensions are the Apple Rubber design guide, not ISO 3601-2 — bd_warehouse says so itself — and `backing_rings=1|2` is refused for cords under 1.78 mm, where the table has no width for them.
- `Screw.thread_length`: how much of the shank is actually threaded. ISO 4014 and DIN 931 are partially threaded, and the standard fixes the thread at 2d + 6 up to 125 mm, 2d + 12 up to 200 mm and 2d + 25 above that; every other standard here is fully threaded. The shape is a plain cylinder either way, because SOMA models no threads, so this is the number for a drawing note, a FEM bolt or a parts list — and the one to use instead of `shank_length`.
- `tap_hole(material="hard")` and `tap_drill_for("hard")`: tapping steel needs a different drill from aluminium (M6: 5.4 against 5.0 mm). The default stays `"soft"`, so nothing that already worked changed.
- `Washer.trap()`: the round recess for a washer that sits below the surface, the counterpart of `Nut.trap()`.
- `docs/EXTERNAL-BRIDGES.md`: the decision and the POC procedure for PartCAD, FreeCAD and KiCad, with acceptance numbers and kill criteria, so no bridge is built on a hunch. It also records the rejections: `cq_warehouse` as a dependency, and the official CadQuery MCP server, which runs a Python string and would add a second way to execute code with the user's rights.
- `docs/DRAFTWRIGHT-HANDOFF.md`: how a Draftwright result (photo, sketch, measurements, product rules) becomes a SOMA model through `inputs/` and `param()` alone — one JSON file with numbers, sources and open questions, no client, no API key, no new dependency.
- `npm run test:tables`: every row of every standard-parts table is built, not only the rows some other test happens to use — 1279 parts from eight classes, each checked for exactly one valid solid and for the dimensions the table itself claims. It is the test for the class of bug the `68` typo belonged to: a row the geometry cannot build, or whose numbers contradict each other, is invisible until someone happens to ask for that size. It also checks the lists nobody tests while nobody uses them — `standards()` against the registries, every `HINTS` entry against the names that really exist (a hint for a name that resolves can never fire), every `ALIASES` target. About 90 s, so it is a suite of its own rather than part of `test:fasteners`. It found the three heat-set insert bugs below on its first run.
- The worked example of the Draftwright handoff, `docs/examples/draftwright-bracket/`: the VESA 100 wall bracket from `docs/DRAFTWRIGHT-HANDOFF.md` as `inputs/draftwright.json`, `NOTES.md` and `model.py`. It shows the whole loop the contract describes — what Draftwright measured, which of those numbers became a `param()` and which stayed a constant with a reason, the three rules turned into geometry and one decision not to add any, and both open questions answered in `NOTES.md` instead of in a chat. `npm run test:handoff` builds it in a temporary folder and holds the result against the JSON: every dimension as a parameter with the same value, `bounds.size` as the plate, the volume against the block minus fillets and holes so the features are proven built and not merely declared, and one answer bullet per open question. Then it builds the same model with 4 mm instead of 6 mm and requires the comparison to report it — a verification that has never failed is not a verification.
- `soma inspect --overlaps`: which parts cut into each other, as a list of pairs with the volume of the common body, its thickness (`2 V / A`, so a flat sliver along a contact face and a real penetration are told apart) and the centre of that body, so the report points at the place to look at. Until now `soma inspect` measured every part on its own and could report `ok: true` for an assembly whose parts occupy the same space. Each pair also becomes an `error` in `checks.issues`, so `--overlaps --strict` is a gate in CI. It is opt-in because it costs one boolean intersection per candidate pair — the one check whose cost grows with the square of the part count. Reference parts are left out, and the default output is byte-identical to before, so nothing that reads the document had to change. The MCP tool `soma_inspect` takes the same thing as `overlaps: true`, so an agent working through the server sees a part in the wrong place instead of only parts that are individually valid.
- The assembly example `docs/examples/bearing-block/`: a housing with a stepped through-bore, two 6200 deep groove ball bearings, two DIN 471 circlips holding the inner rings, one shaft and a DIN 6885 key. Every suite before this one measured a single part, and a standard part is only right or wrong against the part it goes into. `npm run test:assembly` builds it, measures the pairs (no pair overlaps), proves the features from the shaft volume — a full Ø10 × 79 cylinder is 6205.3 mm³, the measured 6090.9 is that minus two ring grooves and one 20 mm keyway — checks each ring against its bearing and that the ring lugs stay inside the 26 mm middle bore, and checks that the parts list counts 2 + 2 + 1. Then it builds two deliberately wrong copies, free-state rings and an unturned key, and requires the measurement to catch both.
- `view.dim(..., text_at=(x, y), leader=True)`: a dimension whose text does not fit between its arrows now puts the text outside and joins it to the dimension line with a leader. A Ø10 shaft carries 13 mm of text, so on an assembly drawing it can never stand in the middle; `text_at` alone moved the text and left it hanging beside the dimension, because ezdxf writes `DIMTMOVE=2` ("text moves freely"). `leader=True` writes `DIMTMOVE=1` and draws the line. Also on `diameter()` and `radius()`. For a circle no leader is needed: with `text_at` along the `angle` ray the text sits at the end of the dimension line as it is.
- The assembly drawing of the worked example, `docs/examples/bearing-block/drawings/assembly.py`: A3, a full section A-A along the shaft axis, a plan, six dimensions, five item numbers and a parts list, built at 1:1 from the same model the tests measure. `npm run test:assembly` requires it to build without a warning and reads the parts list out of the DXF, comparing it row for row against `soma bom`, so a table that goes stale fails the test. It is also where the dimensioning rules were measured rather than assumed: the shaft runs through the middle of the section, so width, depth and overhang are pushed outside it; a diameter text has to sit at the end of its line and not beside it; and 10 mm of shaft cannot hold 13 mm of text.
- The check compares a parts list with the item numbers on the sheet: every number in the `Pos` column needs a leader that points at its part, every leader carrying a bare number needs a row in the list, and a number may not be used twice. A parts list is typed by hand while the model it describes is not, so it goes wrong in the two ways that are invisible: a part is added and nobody draws its balloon, or a balloon is numbered 6 while the table stops at 5. Both now come back as a warning naming the item and its part — "The parts list has item 2 "Key", but no leader points at that part". A table whose header says neither `Pos` nor `Item` is not a parts list and is left alone, so a hole or flag table stays quiet. The row the check found on its first run was in `test/drawing.mjs`: a sheet that had been building without a complaint had a numbered row with no leader.
- `RetainingRing(..., mounted=True)`: the ring as it sits in its groove instead of as it comes out of the box. The tables always have `d3 < d2` — a 10 mm ring is 9.3 mm free and its groove 9.6 mm — so a free-state ring overlaps the shaft by `(d2 - d3) / 2` all the way round. That is how a circlip is made, but it is a collision to any interference measurement. The default is unchanged, so nothing modelled before moves.
- The part sheet of the worked example, `docs/examples/bearing-block/drawings/shaft.py`: A4 at 2:1, a section C-C along the axis and a section B-B across the keyway at 5:1, eight dimensions. It is the second half of the lesson the assembly sheet started, and it is where the *view* was decided by the drawing rules rather than by taste: the keyway lies on +Y and the front view looks from -Y, so a plain view would show it as a hidden edge and a dimension belongs on a visible one — a section along the axis at x = 0 cuts it lengthwise and leaves the outline unchanged. Its numbers are computed, not typed: 23.95 is `OVERHANG + SEAT - 0.05`, the axial play a circlip needs because its groove is 0.1 wider than the ring. `npm run test:assembly` requires it to build without a warning, counts two sections and eight dimensions, holds each value against the model, and reads the notes out of the DXF to check that the keyway depth there is `key.shaft_depth` and not a number typed next to it.
- The housing's part sheet, `docs/examples/bearing-block/drawings/housing.py`: A4 at 1:1, a section A-A along the bore and a plan below it, seven dimensions — the block's three outside dimensions, the two shoulders as a chain from the front face, Ø30 in the plan and Ø26 in the section between the two lines that are its walls (DIN 406 allows the Ø in front of a linear dimension where the circle is not in the view). The seats stand outside the block on the right: they are 30 mm inside it and a line drawn between them would run through the hatching. This is the sheet that found the bug below.

### Changed

- Six skills gained rules that came out of measurements, not taste. **Tolerances and fits**: `soma inspect` as the way to check a fit numerically, and a mesh tolerance that follows the size of the part (a fixed 0.01 mm is pointless on a 300 mm part). **Assemblies**: why names in a STEP file are ASCII and unique, that groups become sub-assemblies, and how to verify an export against the model. **3D printing**: mass and filament length before a print, `--strict` so an open shell cannot reach a slicer, and a tolerance of about half the layer height. **CNC**: STEP and never STL to a shop, and the same verification before the file goes out. **FEM**: check that the part is one valid closed solid before waiting for a solve, and that thread length is not in the geometry. **Standard parts**: what the library covers and what it does not, that fine pitches are not supported, and that the parts list comes from `soma bom` instead of from memory.
- The "Standard parts" skill no longer lists bearing sizes the library does not have (6001, 6002, 6201, 688) and no longer tells the agent to model bearings by hand: it names `Bearing(...)`, says which numbers exist, and that the volume from `soma inspect` is smaller than the real part so a parts list has to use `mass_g`.
- Fine pitches are now rejected with a message that says what happened. `Screw("ISO 4762", "M10x1.25")` used to be read as M10 with a 1.25 mm length and rejected as a non-standard length, which sent the reader looking for a length that was never meant; a second number below `min(3, d/2)` is now treated as a pitch, and `"M10x1.25x40"` is recognised as pitch plus length. Both name the coarse designation to use instead.
- **A wrong number in a copied table was corrected**, the only place SOMA does not take the bd_warehouse data unchanged: the ISO 1580 length series read `2,2.5,3,4,5,68,10,…` instead of `…,5,6,8,10,…`, so `Screw("ISO 1580", "M3x6")` and `M3x8` — two of the most common pan head screws there are — were rejected as non-standard lengths. Fixed in `nominal_screw_lengths.csv`, recorded in `QUELLE.md` and in the inventory, and covered by a test so it cannot come back.
- The "Standard parts" skill documents the three new families with the mistake each one prevents: a clearance hole on a shoulder screw gives a pin that rattles, a retaining ring belongs against a shoulder and not mid-shaft, and the shaft and hub keyways are cut to different depths on purpose. It also states the two things the assembly example got wrong: a key lies in the plane of `at` and has to be turned onto a shaft that does not run along X, and a circlip needs `mounted=True` in an assembly that measures interference.
- `Nut.trap()` follows the shape of the nut instead of always cutting a hexagon: a flange nut gets a round pocket for its flange with the hexagon above it, a domed cap nut a round pocket up over the dome. A side slot is refused for both with a sentence rather than a slot a flange cannot pass through.
- `npm run test:assembly` is 19 checks and now covers the drawing as well. It also copies the example without `.soma/`, `output/`, `exports/` and `__pycache__/`, so the suite no longer depends on what a previous run happened to leave in the folder.
- The agent's `AGENTS.md` lists `soma inspect`, so a model is checked by measurement after a change instead of by looking at the picture.

### Fixed

- `Nut.trap()` for a domed cap nut cut a round pocket as wide as the **dome**, but the hexagon below it is wider across its corners (M6: 9.5 mm dome, 11.55 mm across corners). The nut could not enter its own pocket: reinserting it left 47.04 mm³ of interference at M6, 25.08 at M5 and 99.41 at M8. The pocket now clears `max(dk, s/COS30)` and still reaches over the dome. The old check asserted the undersized width; it now cuts a real boss and requires zero interference, for non-sunk and sunk nuts.
- `Nut("DIN 1587", ..., sunk=True)` — a sunk domed cap nut — was placed by the height of its hexagon, not by its outer face. The dome then stood 4.75 mm proud of the surface on an M6 (the seat was at the hexagon's top, not the dome's), and `trap()` pocketed only part of the nut. Sinking now uses `overall_height` (`m + dk/2` for a cap nut), which is identical to `height` for every other nut. The new check measures the top face of a sunk cap nut, a half-sunk one and a sunk hex nut, and the pocket depth.
- `soma inspect --step ... --parts <name>` and `--entry <file>` silently ignored both options and returned the whole file with exit 0, while the same options on a model were validated. A CI job that gated on a filtered export could therefore pass on an unfiltered file. Both combinations are now rejected with a clear message (`--json` gets an `ok: false` document), and the test covers the JSON and text paths.
- `soma drawing build <name>` built a renamed sheet successfully and then reported `No drawing '<old name>' found` with exit 1. A second lookup after the build, against the just-rewritten index, was redundant: `_drawing_target()` already rejects typos before anything is built. That check is gone; a regression test renames a sheet, builds it by its old name and requires exit 0, while a genuine typo still fails.
- `ShaftKey.keyway("hub")` cut the hub groove **into the shaft, not the hub**. The tool was built from local `-hub_depth` to `0`, i.e. below the seat, where the shaft is; the hub lies above the seat in local `+Z`. `hub.cut(key.keyway("hub"))` — the documented use — removed no material at all (0 mm³), while the key protruded 2.5 mm into a hub with a 2.8 mm groove. The tool now runs from `0` to `+hub_depth`. The existing test only checked the tool's height, not which side of `at` it was on; it now cuts a real hub and measures the removed volume, and fails with the old code.
- The housing of the assembly example had **no shoulder**, although its own docstring describes one ("the step at each end is the shoulder that stops an outer ring from moving outwards"). It cut a Ø30 through-bore and then cut Ø26 between the seats — a cut inside a larger hole, which removes nothing. The bore was therefore 30 mm from face to face, the two bearings had nothing to bear against, and every test still passed, because each of them measured the parts and not the feature: `inspect --overlaps` sees no overlap either way, and the shaft volume, the ring positions and the parts list are all unaffected. Found by drawing the housing's part sheet: the section showed a straight bore where the model's docstring promised a step. The bore is now cut from the inside out (26 through, then 30 at each end), and `npm run test:assembly` holds the housing volume against the block minus the stepped bore, so the shoulder is a number and not a claim — 131781.7 mm³ with it, 128966.8 without.
- A diameter dimension in a *section* was always reported as "view has no circle with radius … around …", even when the circle was right there: the check compared the dimension's point against `View.circles()`, which reports the depth of the edge a circle came from, while the circle of a cut face sits on the cutting plane — a groove rim at z = 25.05 against a section at z = 46. Only the position *in the view* decides whether a sheet is right, so the comparison now happens in view coordinates. Found by dimensioning the Ø10 h6 on the shaft's cross-section, which is the one place a diameter belongs.
- `soma drawing build assembly` — the file name — built the sheet and then said `No drawing 'assembly' found` and returned 1, because only the sheet's own name ("Bearing block") and its outputs were valid handles. `drawrun.find()` now also matches the file stem, so the short name a reader types works.
- Both worked examples listed the `.soma/` build outputs one by one in their `.gitignore`, so `soma analyze` (`.soma/results/`) and `soma export` (`exports/`) left untracked files behind the moment a reader tried them. They now ignore `.soma/`, `output/` and `exports/` as a whole: everything in there comes back from `soma build`.
- A build that could not open the build lock said nothing and built anyway. A lock that does not lock is worse than no lock, because the user believes the model is protected from two builds writing the same files at once. It now retries the open a few times (a virus scanner can hold the file for a moment) and then says on stderr that it is building without the lock. Found while chasing a flaky check in `test:buildlock`.
- The `test:buildlock` check for the "waiting for another build" message depended on the second process starting within the first build's 10 s sleep. Under load the spawn can take longer than the whole build, the lock is then free, and the message is correctly absent — the test called that a failure. The message is now asserted in the case where the wait is forced (the other build sleeps 60 s), and the concurrent case only has to prove that both builds succeed and run in order.
- The documented `ShaftKey` example was only right for a shaft that lies along X with its keyway facing up. A key lies in the plane of `at` with its length along local X, so a shaft along Z — the usual case — needs `direction` and `angle` to turn it onto the shaft; without them the key lies *across* the shaft, looks plausible in the viewer and is half buried in it (8.87 mm³, found by `soma inspect --overlaps`). Fixed in the class docstring, in `app/resources/skills/standard-parts.md` and in `docs/FASTENERS-INVENTORY.md`, each with the reason.
- The handoff document's own sample could not be built, in two ways: the `model.py` used `cq` without `import cadquery as cq`, and the plate was 120 × 80 with a VESA 100 hole pattern — 100 mm spacing needs 100 mm of plate plus edge distance in *both* directions, so all four holes would have hung over the edge. Both corrected, and the document now says why: a handoff that is internally consistent is not the same as one that can be built.
- `.gitignore` carried `examples/` without a leading slash, which matches at every depth — the first worked example, `docs/examples/draftwright-bracket/`, was silently invisible to git. Anchored to `/examples/`, which is what the line was for.
- `HeatSetInsert(..., variant=...)` matched the table's variant by substring, so naming `"H2-D3"` also matched `"H2-D3.2"` and the choice stayed ambiguous — the error message told the reader to pass `variant=` and passing it did not help. Nine AE-SamZhihui sizes could not be built at all. An exact match is tried first now and the substring is only the fallback.
- One row of `heatset_nut_parameters.csv` appears twice with identical numbers (AE-SamZhihui M2.5x8 H8-D4), which made that insert unreachable: two rows with the same dimensions are the same part, so they now count as one.
- Heat-set insert holes: the drill was read from the inch table only, so a metric drill written in the table (`"M14"`) counted as unknown. And a drill outside thread-to-outer-diameter was reported as "the table gives no usable hole" without saying which of the two things was wrong. Three rows contradict themselves — CNCKitchen M1.6x1.6 names `#39` (2.53 mm) for a 2.5 mm insert, and both M10x12.7 rows name `M14` for a 12.6 mm one — so they are still refused, now with a sentence that says the row contradicts itself rather than leaving the reader to guess.

## [1.0.0] - 2026-11-22

SOMA 1.0. It brings its own agent, SOMA AI, so you no longer need a coding agent to design with SOMA. Models made with 1.0 keep working in later versions, changes that break them only come with a new major version.

### Added

- Voice input for SOMA AI: the microphone next to the chat input turns what you say into text, on this computer. Nothing you say leaves it. The first click asks for your language and downloads the speech model once (Parakeet TDT 0.6B v3 by NVIDIA, 487 MB, 25 European languages, license CC BY 4.0). Click to speak, click again for the text: it lands in the input where the cursor is and is not sent, so you can read it first. Esc drops a recording. Settings > SOMA AI shows the model and removes it. Before the download SOMA checks that the speech engine runs on the computer (on macOS it needs macOS 14 or newer). Behind it is sherpa-onnx (Apache 2.0), which comes with SOMA.
- SOMA AI: an agent built into SOMA, for everyone without a coding agent of their own. It is a chat instead of a terminal, the first tab of the agent area. Sign in with ChatGPT or with an API key (Anthropic, OpenAI, Google Gemini, OpenRouter, OpenCode Zen or Go), describe the part or add a photo of a sketch, and follow what it does in plain words, with the time it has been working. When it needs to know something, it asks all its questions at once, with answers to click or in your own words. Earlier conversations of a model can be continued. The model menu has a search. Settings > SOMA AI shows the sign-ins, the model, what a conversation used and what SOMA AI may do. The tutorial introduces SOMA AI, shows in the + menu how to use your own agent instead, and says that you never have to touch the code. It stays in the model's folder: looking at or changing files outside it, downloading and installing software ask you first, dangerous commands are stopped. A note before the first message names the risks. "Send to agent" in the viewer puts the part, measurement or markup into its input. For the best results we recommend Opus 5.5 or GPT-6.2 Astra. The model list also brings models that came out after your version of SOMA, such as GPT-6.2 Sol: it loads the newest list from pi.dev for your sign-ins. Behind it is pi (pi.dev, MIT), which comes with SOMA. Agents in a terminal such as Claude Code work as before.
- Play or pause static FEM deformation in Analysis. Solved colors and values stay fixed during the shape cycle. On narrow canvases, compact controls flow into rows while the close button stays visible. Thanks to Ryan Hailey (fork RyanHailey21/SOMA, issue #12).
- "As one STEP file" in the Export menu: the whole model in a single STEP file with its groups as sub-assemblies, part names and colors, for other CAD programs. Purchased parts such as screws are included, reference parts too, in a group "Reference". On the command line: `soma export --assembly --format step` (issue #11).
- Video tutorial on YouTube (7 min, from installing to export): "Watch video" on the start page card and at the top of Help opens it in your browser.
- Settings > General > Build time limit: how long a build may take before SOMA stops it, from 5 minutes to 2 hours or no limit. The default stays 10 minutes. The message of a stopped build says where to raise it (issue #13).
- A loading screen while a new model is created ("New model", the tutorial, a CadQuery script): it shows at once, names the step (first build, version history, opening) and stays until the viewer, the files and the agent panel have loaded the model. Before, the old model stayed on screen for several seconds without a sign that anything happened. The tutorial's tour starts once the model is loaded.

- A layout for narrow windows such as phones: below a width of about 760 pixels SOMA shows one view at a time, chosen in a tab bar at the bottom (Model, Agent, Parameters, More), instead of the columns side by side. "More" holds the files, the code, analyses, animations, drawings, skills, help and settings. The start page, Settings and Help fit the width too. Widening the window brings back the columns as they were. Mainly for the web version (issue #14).
- SOMA AI: an effort setting, how long SOMA AI thinks before it acts (Low to Max, the levels the model offers). The button next to the model below the chat input and Settings > SOMA AI change it, for the open conversation and new ones. More effort gives better models, so the recommendation now says High effort or more.
- Settings > General > Tabs when a model opens: up to three tabs of the agent area that open with every model, the first one in front. Each is SOMA AI, an empty terminal, one of the agents (Claude Code, OpenCode, Codex, Gemini CLI) or a command of your own, for example a tool that runs in a terminal. A command is typed into a terminal in the model folder with the model's Python, and the terminal stays open when it ends. It is stored only on this computer, never in a model (issue #18).

### Changed

- A model opens with only SOMA AI in the agent area. The empty terminal that opened next to it is one click away under +, or set it under Settings > General.
- Settings sorted anew: a new tab General comes first, with the tabs when a model opens, the start page (the check for new versions moved there from About, and the tutorial card can be switched on again) and the build time limit (moved from Viewer). Shortcuts moved behind Skills.
- Electron 44.11.5 (security fixes in Chromium and Node.js), and the patched versions of the libraries undici and fast-uri.
- Large models build much faster. The meshes for the viewer are made on several processor cores while the STEP file is written, parts larger than about half a meter are meshed relative to their own size (a 19 m mast took 96 seconds alone before, now under one), and faces with freeform surfaces get their area for the viewer from the mesh (the measuring tool still measures exactly). On the sailboat from issue #13 (1024 parts) the time after the model's own code went from about 3 minutes to under 1, and the viewer file is a third smaller. Small models look and build as before. `SOMA_BUILD_WORKERS=0` turns the worker processes off (issue #16).
- The CadQuery skill has a new section "Fast builds" for the agent: cut and join many bodies in one call, place copies of identical parts instead of rebuilding them, keep chain links and planks as separate bodies instead of fusing them, check each part only once. On the sailboat from issue #13 fusing two chains alone took 30 seconds, as separate links a fraction of a second.

### Fixed

- History: clicking an older version of a large model seemed to do nothing. Its preview stopped after 2 minutes, while reading the STEP file of a large model takes longer. Now it has no time limit, the viewer shows that it is loading, and Cancel or Esc stops it. Versions the agent commits keep their build as a ready preview even when it goes on working right away, so they open at once. In a folder opened with "Open folder" that has no Git repository of its own, the empty history now says why (issue #17).
- SOMA AI: the chat sometimes stopped following new steps and answers and stayed a little above the end, although nobody had scrolled. Now only scrolling up stops it.
- SOMA AI: after "Load file" for an older `.soma` file, the chat continued the later conversation, which talks about a state the folder no longer has. Now a new conversation starts, the earlier one is still under "Earlier conversations".
- SOMA AI: a reopened conversation shows "Worked for …" for its earlier tasks again.
- SOMA AI: the field for your own answer to its questions was a single line, so a longer answer ran out of sight. It now wraps and grows with the text. Enter still goes on or sends, Shift+Enter starts a new line.
- Animations were missing after opening a `.soma` file on another computer (the file holds their code, not the built animations): they are built again after opening.
- Analyses were gone after opening a `.soma` file on another computer, because their results are too large to go along. Now the file keeps a list of them: the Analysis tab shows each with its values as saved and "Compute" to calculate it again, and `soma analyze list` names them for the agent.
- Exporting a single part as STEP or BREP could write only a shell instead of a solid, when the part was a CadQuery compound holding one solid. Thanks to SukbeomH (fork SukbeomH/SOMA) for spotting this.
- "Open folder" is more careful with the folder: a `model.py` that appears while the confirmation is open is kept instead of replaced, `.soma/project.json` is backed up before it changes (an unreadable one is listed as a change first), and a folder where `.soma` is a file is refused with a message before anything is written. Thanks to vasilipuchko (fork zihotki/SOMA).
- The viewer fits the model again when a rebuild takes it out of the picture, for example when the agent replaces the starter box with a table. A small change keeps the camera where you put it. "Fit" in a viewer narrower than high no longer cuts off the sides.
- Drawings were missing after saving and opening a `.soma` file: the "Drawings" view said "No drawings yet", although the PDFs were there. The file now keeps the list of sheets. For files saved before, the view names the drawing files that are not built yet, with a button to build them. Opening a `.soma` file also keeps the files' modification times, so sheets no longer show "older than the code" right after opening.
- SOMA AI: a model chosen below the chat input is now also the one Settings > SOMA AI shows and new conversations start with.
- SOMA AI: the chat follows new steps and answers while you are at its end, also while an answer is still being written. Scrolled up, it stays where you read.
- SOMA AI no longer works unseen: when it starts working or asks something, the agent area opens if it was collapsed, and a question brings its chat to the front.
- SOMA AI: when the ChatGPT sign-in has expired, the chat says so and offers "Sign in again", instead of "Something went wrong at the AI service. Try again", which could never help.
- SOMA AI asks fewer rounds of questions: at most once before a task and only what really matters, otherwise it picks sensible defaults and names them.
- `soma drawing build <file>` without a list of sheets (for example in a cloned folder) builds all drawings, so `output/drawings.pdf` keeps every sheet instead of only that file's.

## [0.11.0] - 2026-11-03

### Added

- Skill "Plasma cutting" for parts cut from metal plate on a CNC plasma table: kerf and accuracy, smallest holes, islands that fall out of text and cutouts, webs, heat distortion, tab and slot for welding, one DXF per plate. Settings for material, plate thickness, kerf and the smallest hole that is cut.
- Click an STL, 3MF, AMF or OBJ file in the file tree to look at it in the viewer, like STEP files, for example to check an export. Units in 3MF and AMF are converted to millimeters, sharp edges and open borders are drawn as lines. Section and Explode work, measuring does not, since a mesh has no CAD geometry.
- Mesh settings in the Export menu for STL, 3MF, AMF, OBJ, GLB and GLTF: units (mm or m), the axis pointing up (Z or Y) and the mesh density (coarse, normal, fine), for example for game engines. `soma export` takes them as `--units`, `--up`, `--detail` and `--tolerance`.
- Warnings from a mesh export (a mesh that is not closed) now show up in the app's message after the export, not only on the command line.

### Changed

- GLB and GLTF exports are now in meters with Y up, as the glTF format defines it. Before, a part of 100 mm arrived 100 m tall in Blender or a game engine. Each part is one mesh instead of one per CAD face, and the mesh density follows the part size like the other mesh formats instead of a fixed, very fine one.
- The Windows installer is about twice as fast: it unpacks straight into the installation folder instead of extracting to a temporary folder first and copying from there. The installer download is larger in exchange (about 620 instead of 470 MB).
- When a mesh export (3MF, AMF, STL, OBJ) warns that faces could not be meshed, it now names each face with its type, area and location, and marks tiny ones as a probable sliver, for example where two rounds meet.

### Fixed

- The macOS app no longer changes its own files while it runs: Python wrote cached bytecode into the app bundle, which breaks the code signature. The bundled Python now comes precompiled and writes no cache, so model folders no longer get a `__pycache__` folder either. Thanks to Mike O'Connor (fork mjoconr/SOMA) for spotting this.
- Some STEP files could not be shown in the viewer ("Step file does not contain an assembly"), for example a single body like a logo from another CAD program. They now open with one part per body, keeping names and colors where the file has them. `import_assembly()` reads such files too, and `import_step()` no longer drops all bodies but the first when a file has several side by side.
- Saving could crash with "A JavaScript error occurred in the main process: file data stream has unexpected number of bytes" when a file of the model changed while it was being packed, for example by a build or the agent. No build starts while the model is being saved or exported, a file that changes anyway is packed a second time, and if it keeps changing, saving reports it instead of crashing.

## [0.10.2] - 2026-10-24

### Added

- Search field above the file tree: it shows only files whose name contains the text, with their folders opened.
- Videos in the Animation tab are sorted by folder, and each folder can be collapsed (remembered per model), so the agent's many short clips no longer hide the main videos.
- Right-click a video in the Animation tab, or click "…" in the video player, to show it in the file tree or in Explorer, rename or delete it.
- The video player has a mute button (M) and a volume slider. Both are remembered.

### Changed

- Folders in the file tree start collapsed. The folder of a file you open in the editor opens by itself.

### Fixed

- Exports as 3MF, AMF, STL and OBJ are now one closed, manifold mesh per body with shared vertices. Before, every CAD face was its own patch, and slicers reported open edges and repaired the mesh, sometimes leaving a crack in the wall along a fillet. Degenerate triangles at the corners of fillets are gone too. Curves are meshed a bit finer (at most 0.05 mm deviation). If a mesh still cannot be closed, for example for an open surface, `soma export` prints a warning.

## [0.10.1] - 2026-10-22

### Added

- The guide (F1) and the README explain how to work with an agent app such as the Codex app or Claude Desktop instead of an agent in SOMA's terminal.

### Changed

- "Send to agent" also copies its note to the clipboard, so you can paste it into an agent app outside SOMA. Without an open terminal it no longer shows an error, the note is in the clipboard.

### Security

- The bundled Python environment uses Pillow 13.0.0 and aiohttp 3.14.4, which fix several reported vulnerabilities (crafted image files, HTTP server limits).

## [0.10.0] - 2026-10-22

### Added

- "Open folder" uses SOMA in a folder of yours, for example a Git repository: viewer, skills, agent instructions and `soma`, without a .soma file. Before anything changes, SOMA lists the files it creates and changes, with Cancel. It adds a section to `AGENTS.md` and a line to `CLAUDE.md` (backed up first), leaves your Git history and `requirements.txt` alone, and never moves or deletes the folder.
- "Copy path for agent app" in the menu for new tabs copies the model folder, so an agent app such as Claude Desktop or the Codex app can work on the model. SOMA shows its changes, and `soma render` works from there too.
- `soma anim build`, `info` and `check` warn about motion that plays back differently than written: jumps within one frame, turns so fast that they wobble between frames, and parts that are still hidden at the end.
- `add_part(..., alpha=)` sets the opacity of a part. A reference with `alpha=1` is opaque, for scenery in animations such as a floor or a logo, and still stays out of `soma export --all`.

### Changed

- Free parts moved with `to()` in an animation follow a rigid-body screw path: a turn runs on the arc about its axis instead of wobbling around the model origin. Animations that combine a large turn with a large shift in one `to()` take a different path than before.

### Fixed

- Long animations with many steps build much faster (a two-minute animation in seconds instead of many minutes), so the app shows them again.
- `soma analyze fem` no longer stops with a raw mesher error when several parts cannot be meshed together (for example parts that overlap slightly). It explains the likely cause and suggests mesh sizes. If only the check with the coarser mesh fails, the result is kept with a note.
- `soma` writes its output as UTF-8, so ° and ² show correctly in agent apps outside the SOMA terminal.
- `soma analyze fem` run from an agent app (through `.soma\env`) finds the bundled CalculiX. Before, it fell back to the built-in solver, without contact and bolt preload.

## [0.9.0] - 2026-10-16

### Added

- The start page shows a small label next to the version number when a newer version is available on GitHub, it opens the release page. Turn it off under Settings > About.
- Click a STEP file in Files to view it in the 3D viewer, with measuring, section, explode and the structure tree. "Back to model" returns to your model, builds wait until then.
- "New from CadQuery script" in the model menu: make a model from an existing CadQuery script, with a loading screen while it builds for the first time. Scripts with `show_object()` (CQ-editor), `ocp_vscode` or `result` build as they are.
- "As CadQuery script" in the Export menu: the model as plain CadQuery that runs in CQ-editor, VS Code and other tools without SOMA, with parameters and standard parts. Importing it again gives back the original code.
- A portable ZIP for Windows on the releases page, to run SOMA without installing it.
- Origin and main axes in the 3D viewer (red X, green Y, blue Z): the new button next to the view cube or the display menu turns them on. Settings > Viewer shows them for every model.
- A log file for bug reports (`logs/soma.log` in the app data): errors, builds, which agent was started and its version. "Copy system info" under Settings > About now adds the end of the log, the folder is listed there and under Storage. Nothing is sent anywhere.

### Changed

- A tidier start page: Recent models come first, with a filter by name. New model and Open sit next to the title, "From CadQuery script" in the arrow menu of New model. The agents take less space, and any other CLI agent works too. "Back to …" names the open model, Esc goes back as well.

### Fixed

- The cards of Measure, Section and Explode no longer hide behind the banner of a version preview.

## [0.8.0] - 2026-10-13

### Added

- "Import" button next to Export: choose files in a file dialog to add them to `inputs/`, the same as dragging them into the window.
- "Drawings" on the left: all technical drawings in one view next to the 3D viewer, with size, scale, warnings and "older than the code" above each sheet, and buttons to open the code or DXF, rebuild or send a sheet to the agent.
- Click a view on a drawing to look at the model from that direction (a section sets the section tool to the same plane, a detail zooms in), click a dimension to see its points and value on the model.
- PDF viewer: single page or all pages, page previews on the left, fit the whole page.
- Text in drawing PDFs can be selected and quoted to the agent (it was drawn as outlines only). Rebuild older drawings to get it.
- Export drawings from the "Drawings" view: all sheets as one PDF, each sheet as PDF, DXF or both into a folder, or a single sheet.

### Changed

- PDF viewer: no floating "Quote to agent" button next to selected text any more; the button in the bar turns orange instead.
- `soma drawing build` writes more to `.soma/drawings/index.json` (parts, axes and section planes of the views, model points and positions of the dimensions, positions of warnings), so the app can link sheet and model.

## [0.7.2] - 2026-10-13

### Fixed

- Agents that run their commands outside the app's terminal (seen with Codex on Windows, which uses a background service with the environment of another program) can use `soma render` again: it now finds the running app without the terminal's environment variables.

### Added

- `soma build` notes when the shell lacks the environment of the app's terminals and says how to call `soma` and `pip` instead.
- New skill "Shell environment" (on demand for new models): what the agent does when `soma` or `pip` is not found, or umlauts in files look garbled in Windows PowerShell.

## [0.7.1] - 2026-10-12

### Fixed

- Measuring no longer gets stuck at "The model has been rebuilt in the meantime" after the agent ran `soma build` in the terminal. The viewer now picks up builds made outside the app, and the measuring tool reloads the model itself if it still finds an older one.
- Two builds of the same model (the app's automatic build and `soma build` in the terminal) no longer write into the same files at once. The second one waits and says so in the terminal. Viewer files are replaced in one step, so the viewer and the measuring service never read a half-written file.

### Changed

- Time limits in the app: builds, animations and exports may take 10 minutes (was 5), analyses run again from the app 60 minutes (was 5).

## [0.7.0] - 2026-10-12

### Added

- The packages include `THIRD_PARTY_NOTICES.md` and the license texts of all bundled npm packages.
- `SECURITY.md` explains how to report vulnerabilities privately, and issue templates ask for the system info from Settings > About.
- Tutorial for new users: the start page shows "New to SOMA?" with "Start tutorial" and "Got it". The tutorial opens an example model and walks through the window in ten steps (agent, code, selecting, measuring, mark up, parameters, history, saving and export, help), with the right button highlighted. Help can start it again at any time.

### Changed

- This changelog is now in English, also for older versions.
- Questions such as "Save the model before closing?" appear as a dark window inside the app instead of a white system dialog. Enter picks the highlighted button, Escape cancels.
- Windows: the title bar of the window is dark instead of white.

### Fixed

- New models: the box of the template failed to build with a wall of exactly 3 mm, although the Parameters panel allows 1.2 to 4 mm. The corner radius now grows with the wall.

## [0.6.2] - 2026-10-11

### Fixed

- Linux: On machines with a graphics card the app wrongly switched to software rendering at startup and then no longer started. Now it only switches when the 3D view really gets no WebGL, remembers that and restarts once.

## [0.6.1] - 2026-10-11

### Added

- Installation packages for download under the GitHub releases, for Windows, Linux and macOS (Apple Silicon).
- Linux without a usable graphics driver (virtual machine, remote desktop): the app restarts once with software rendering instead of staying without a 3D view. If that fails too, it says that WebGL is missing.

### Changed

- At startup the app shows a short loading screen until the start page is ready. Before, the empty interface flashed up briefly.

### Fixed

- macOS: The terminal did not open in the installation package. If a shell does not start, the app now names the reason on all systems.
- Linux: The package brings the libraries gmsh needs for FEM (libGLU and a few X11 libraries). Without them the import failed on many systems.

## [0.6.0] - 2026-10-10

### Added

- Installation packages: installer for Windows, AppImage and tar.gz for Linux, dmg for macOS with Apple Silicon, with Python, CadQuery, `soma`, CalculiX and Git included. So far only tested on Windows, the packages are not signed yet.
- FEM with bolts: `study.bolt("Bolt 1")` preloads a bolt from `soma.fasteners`, then the loads act. The result lists preload, tension and shear force at the end and the utilization of the yield strength for each bolt, the contact of the joint shows whether it opens or slips. Without a value 70 % of the yield strength, for plastic parts limited to what the area under the head can carry. Nut, washer and clamped parts are included automatically.

### Changed

- The bundled skills have English file names, for example `3d-printing.md` instead of `3d-druck.md`. Older models keep their copies under the old name, the app still recognizes them as the same skill. Your own versions of bundled skills in the settings move along at startup.

### Fixed

- Overhang in the viewer: the worst spot is labeled "Max" instead of "Min".
- A click on Analysis or Animation in the left bar shows the list instead of opening a result right away.
- FEM: The force carried by a contact is now correct even when the part is also supported elsewhere or the contact presses on the edge of a support. Before, contact force and the balance of the reaction forces could be clearly off there.
- FEM: Meshes with single inverted elements in narrow gaps (for example between washer and nut) are smoothed instead of failing with "distorted elements".
- FEM: No more "-0.0" in forces in the result.
- FEM with contact: A plate held only by the contact (for example a holder with an arm) failed with "a part moves without limit" or "The contact does not settle". SOMA took the search for the contact area for oscillation too early, and the soft fallback law pushed the parts apart. Now the contact is softer (stiffness equal to the Young's modulus instead of ten times, displacements differ by 0.4 %), may search longer, and the fallback law follows the load.
- Skill "Strength with FEM": friction between bolted parts only holds with `bolt()`, the skill now says so.

## [0.5.0] - 2026-10-10

FEM runs on CalculiX and knows contact between parts: lifting off, sliding, with and without friction.

### Added

- FEM with contact: `study.contact("Lid", "Housing")` turns the touching area of two parts into a contact that can lift off and slide, with `friction=` also with friction. The result lists the force carried, the highest pressure, where it is open and where it slides for each contact. The image has the quantity "Contact pressure", the report one line per contact.
- FEM lists all parts that touch each other, with area and whether they are bonded, and points to `contact()`.
- FEM runs on CalculiX instead of the built-in solver, two to three times faster at usual model sizes with the same numbers. CalculiX comes with SOMA (Windows: 53 MB). Without CalculiX the built-in solver still works, only without contact.
- Settings, "About" tab: lists gmsh and CalculiX with version.

### Changed

- FEM: The note that the peak stress depends on the mesh is left out for barely loaded parts (below 2 % of the strength).

## [0.4.1] - 2026-10-10

Help with numbered screenshots that the agent knows as a skill, plus improvements from an agent's review: `soma render` with free direction and hiding, reading PDFs, drawings with text measurement.

### Added

- Help: The "Help" button in the bar (also on the start page, key F1) opens a short guide to all areas of the app, with screenshots on which the elements are numbered. The agent gets the same guide as the skill "Using the app" (by default "On demand") with images, so it can answer questions about using the app.
- Settings, "About" tab: names Kai Jungsthöfel as author.
- `soma render`: free view direction (`--view=1,-2,1`), hide parts or groups (`--hide`) or show only them (`--only`), fit to parts (`--fit`) and `--zoom`. The agent can look inside a model this way without writing an animation.
- The agent can read PDFs from `inputs/`: pdfplumber (MIT) is in the base environment, with text, lines and coordinates.
- Technical drawings: `sh.text_width()` measures text before building, `leader(..., side="left"/"right")` sets the side of the note, `sh.table()` without `widths` fits the columns to the text.
- Animations also address parts by their group (`"Housing/Lid"`).

### Changed

- `AGENTS.md`: The front of a model faces −Y (front view from −Y, X to the right), so agents orient models correctly from the start.

### Fixed

- Technical drawings: The docstring of `Sheet` named the image `.soma/drawings/<name>.png`, the file is named after the ASCII identifier (`Washer_small.png`).
- Markup: The drawing area adapts to the viewer. When it grows, for example because the PDF next to it is closed, the area grows with it instead of staying small in the corner. The mouse wheel zooms around the pointer (up to 8x), dragging with the right or middle mouse button pans, Ctrl+0 fits again. The image for the agent keeps its full resolution.

## [0.4.0] - 2026-10-09

Structure tree in the viewer, Analysis and Animation tabs with a calm report, multi-selection and keys, settings for Viewer, Shortcuts, Storage and About.

### Added

- Structure tree in the viewer: the parts sit at the top left of the view like in CATIA, without background. Collapsed it shows only the model name (with "· 2 hidden" when something is hidden), expanded one level of groups (the next opens on demand) with tree lines, eye and half circle right before each name, references as a group at the end, search, "Show all" at the bottom. F3 opens and closes it. A click in the model highlights the part in the tree, in a collapsed group the group. The same tree applies to the model, the analysis (only the computed bodies) and the animation.
- Multi-selection in the viewer and the tree: Ctrl+click and Shift+click, ranges with Shift in the tree, box selection with Alt + drag in the viewer (left to right fully inside, right to left touching). Dragging across the eyes in the tree hides several parts at once. Keys H (hide), Shift+H (show all), I (isolate), T (transparent), Esc (clear selection). Right-click now also works in the view, for one part or the whole selection. A new "Shortcuts" tab in the settings lists all keys.
- "Analysis" and "Animation" tabs in the left bar, a dot signals something new from the agent. Analysis shows the list of results and a calm report: one big number, whether it holds, the critical parts with a jump to the spot, the assumptions one line each to expand (supports, forces, material, mesh), the parts as a table, computation and notes. Animation shows animations and videos, the steps from the subtitles (a click jumps there) and the videos of the animation.
- Analysis in the view: narrow legend at the bottom right, the scale is set with the "Auto ▾" button in it, display options in a bar at the bottom (safety factor, stress and now displacement, exaggeration, load case), force and minimum value as labels at their place. Animation: playback bar at the bottom with markers for the steps. The × in the bar returns to the model.
- Settings, "Viewer" tab: mouse bindings like SolidWorks, Fusion 360 and Inventor, Onshape, Creo, NX and Blender or Rhino, with legend. Reversible zoom direction. Orthographic view without vanishing points, the image stays put when switching. Display when a model opens (edges, wireframe, transparent). Decimal places for measuring (0 to 4), the text for the agent keeps three. Everything applies immediately.
- Settings, "Storage" tab: how much space SOMA uses on the computer, split into models, backups, preview cache, start page images and your own skills, with a button to open the folder. The preview cache can be cleared.
- Settings, "About" tab: versions of SOMA, soma, Python, CadQuery, OCP, Electron and Git, detected agents, folders and all components with license. "Copy system info" puts the details for a bug report on the clipboard.

### Changed

- The "Parts" tab and the switch at the top left of the viewer are gone: parts are in the structure tree, analyses and animations in their tabs. The sidebar is closed on first start.
- `soma analyze fem` also writes Poisson's ratio and density per material into the result, and whether the mesh size was chosen automatically, for the report.
- In the viewer only a left click selects, no longer also the right or middle button. So briefly rotating or panning with these buttons selects nothing.

## [0.3.0] - 2026-10-09

Technical drawings, your own skills, the `.soma` file format and the DXF view.

### Added

- DXF view: DXF files open in the code panel with a click in the file tree, drawn like the technical drawings (line types, hatches, dimensions, text). Zoom with the mouse wheel, pan by dragging, show and hide layers, size and coordinates under the pointer. "Mark up view" gives the visible area with its coordinates to the agent. When the agent changes the file, the view redraws and keeps the area. What cannot be drawn (for example 3D solids) is named in a note.
- Your own skills: "Settings" at the bottom of the left bar (grayed out before) and on the start page opens the settings. There you can change bundled skills and create, duplicate, import from Markdown files and delete your own. The editor with preview checks header, settings and placeholders as you type. Your own skills apply to all models on this computer and are switched on and off in the "Skills" panel like the bundled ones. Changed bundled skills can be reset at any time, deleted and replaced files go to the backup.
- Technical drawings: the agent describes a drawing in `drawings/*.py` (`soma.drawing`) with views, sections, details, dimensions, text and parts list, `soma drawing build` writes PDF and DXF to `output/drawings/`, all sheets together to `output/drawings.pdf`, and an image the agent uses to check its result. Long parts can be drawn broken, sections also with a stepped section line. Dimensions are always measured on the model, a check reports text overlapping edges, dimensions and parts list, entries too long for the title block, dimensions next to edges and typed numbers. Plus the skill "Technical drawings" with the rules according to ISO.
- Skill "Parametric models", always on for new models: the agent first decides what determines the size and what stays fixed when changing it, exposes a few independent values as parameters, derives the rest from them and test-builds the model at the limits of each range. The maximum number of parameters and the extent of this check are configurable.

### Changed

- Models are saved as a `.soma` file instead of `.zip`. The app still opens ZIP files. A model from a ZIP is saved as `.soma` next to it on the next save, the ZIP stays. If you need the whole model as a ZIP, you find "Everything as ZIP" in the export menu.
- The file tree shows the copies of the skills from `.soma/skills/` as their own group "Skills", collapsed and read-only. They are still switched on and off in the "Skills" panel.
- Every row in the "Parameters" panel shows the range the agent set without expanding ("30–200 mm", "3 options"), red when the value is outside.
- Smaller ZIP on save: images and videos from `renders/` are no longer included, and the version history is packed first, so similar versions of the model take hardly any extra space. For the engine model the history shrinks from 81 to 35 MB.

### Fixed

- In the editor the header of a skill (between two `---`) appeared bold like a heading. It now shows dimmed as its own block.
- Bold text in the terminal (for example the agent's headings) looked shaky, round letters sat one pixel lower than straight ones. The app now brings the real bold face of the terminal font instead of having bold synthesized.
- Skills and other Markdown files with a header between two `---` (front matter) showed this header as a huge heading in the document view. It now shows small as source text at the top.
- After changing a parameter, `soma anim` and `soma render --result` still considered animations and results up to date. Now `parameters.json` counts as part of the model, as in the app.

## [0.2.0] - 2026-10-08

Parameters for the user, the app in English, start on the start page and the license.

### Added

- The app starts on the start page. A new model that still matches the template and was never saved disappears when you leave it. Other models can be removed on the start page, the working folder goes to the recycle bin.
- README in English with images for the start page of the repository, plus this changelog.
- License: GPL-3.0 or later, text in `LICENSE`. Users' models are exempt from it (`MODEL-EXCEPTION.md`).
- Parameters: with `param()` the agent exposes single values, for example dimensions, counts, options or an angle. In the new "Parameters" panel you change them yourself, the model rebuilds. Your values are stored in `parameters.json`, the agent's value stays in the code, and every field can be reset to it. Values outside the range are reported and built anyway. The template for new models has four parameters.

### Changed

- The app is now in English: interface, messages, output and error messages of `soma`, skills and the notes to the agent. Numbers use a decimal point. Older models open as before.

## [0.1.0] - 2026-10-08

First numbered version. It sums up the state of the prototype.

### Added

- Desktop app with a terminal next to the 3D viewer. The agent is your choice (Claude Code, OpenCode, Codex, Gemini CLI …), the app detects common agents and starts them.
- Models as Python code with CadQuery (`model.py`, `parts/`), helper library `soma` with `add_part`, groups and roles, STEP import of single parts and whole assemblies.
- Build on every change (can be turned off), errors with file and line, a prewarmed Python process, opening without rebuilding.
- Viewer with selection and jump to the code, view cube, pivot point, part tree with groups, transparency and isolation.
- Measuring on the exact geometry: faces, edges, distances, hole spacing.
- Section and exploded view with disassembly analysis, step-by-step playback.
- Handing over to the agent: selection, measurements, section and markup (drawing on the view) as text or image into the terminal.
- Editor for code and Markdown, PDF view with quoting to the agent.
- Model as a ZIP file with Git history, timeline with preview and restore, saving only explicitly.
- Skills: 15 bundled rule sets (3D printing, CNC, sheet metal, tolerances, strength with FEM …), per model off, on demand or always, with settings.
- Standard parts according to ISO and DIN with matching holes, countersinks and nut traps (`soma.fasteners`).
- Animations in Python, analyses (overhang, wall thickness, clearance, strength with FEM), images and videos via `soma render`.
- Export to STEP, STL, 3MF, glTF, DXF, SVG and other formats.
- Extra packages: `pip install` in the terminal goes into a small environment per model, `requirements.txt` travels with the model, on another computer the app reinstalls the packages.
- Version number on the start page, on the logo and in `project.json`.

[Unreleased]: https://github.com/Kai-Jungsthoefel/SOMA/compare/v1.0.0...HEAD
[1.0.0]: https://github.com/Kai-Jungsthoefel/SOMA/compare/v0.11.0...v1.0.0
[0.11.0]: https://github.com/Kai-Jungsthoefel/SOMA/compare/v0.10.2...v0.11.0
[0.10.2]: https://github.com/Kai-Jungsthoefel/SOMA/compare/v0.10.1...v0.10.2
[0.10.1]: https://github.com/Kai-Jungsthoefel/SOMA/compare/v0.10.0...v0.10.1
[0.10.0]: https://github.com/Kai-Jungsthoefel/SOMA/compare/v0.9.0...v0.10.0
[0.9.0]: https://github.com/Kai-Jungsthoefel/SOMA/compare/v0.8.0...v0.9.0
[0.8.0]: https://github.com/Kai-Jungsthoefel/SOMA/compare/v0.7.2...v0.8.0
[0.7.2]: https://github.com/Kai-Jungsthoefel/SOMA/compare/v0.7.1...v0.7.2
[0.7.1]: https://github.com/Kai-Jungsthoefel/SOMA/compare/v0.7.0...v0.7.1
[0.7.0]: https://github.com/Kai-Jungsthoefel/SOMA/compare/v0.6.2...v0.7.0
[0.6.2]: https://github.com/Kai-Jungsthoefel/SOMA/compare/v0.6.1...v0.6.2
[0.6.1]: https://github.com/Kai-Jungsthoefel/SOMA/compare/v0.6.0...v0.6.1
[0.6.0]: https://github.com/Kai-Jungsthoefel/SOMA/compare/v0.5.0...v0.6.0
[0.5.0]: https://github.com/Kai-Jungsthoefel/SOMA/compare/v0.4.1...v0.5.0
[0.4.1]: https://github.com/Kai-Jungsthoefel/SOMA/compare/v0.4.0...v0.4.1
[0.4.0]: https://github.com/Kai-Jungsthoefel/SOMA/compare/v0.3.0...v0.4.0
[0.3.0]: https://github.com/Kai-Jungsthoefel/SOMA/compare/v0.2.0...v0.3.0
[0.2.0]: https://github.com/Kai-Jungsthoefel/SOMA/compare/v0.1.0...v0.2.0
[0.1.0]: https://github.com/Kai-Jungsthoefel/SOMA/releases/tag/v0.1.0
