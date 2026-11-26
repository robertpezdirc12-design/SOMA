# Herkunft der Maßtabellen

Die CSV-Dateien in diesem Ordner stammen unverändert aus **bd_warehouse** von Gumyr
(https://github.com/gumyr/bd_warehouse, Ordner `src/bd_warehouse/data/`, Stand Commit
`eed2da118da99007ad2d3904466ac0b24964f84d` vom 21.09.2026, Version 0.3.0).

Lizenz: Apache License 2.0, Text in `LICENSE-bd_warehouse.txt`. Copyright 2024 Gumyr.

Verwendet von `soma/fasteners.py`. Der Code dort ist eigener Code und übernimmt nichts aus bd_warehouse.

| Datei | Inhalt |
|---|---|
| `socket_head_cap_parameters.csv` | ISO 4762 |
| `button_head_parameters.csv` | ISO 7380-1 |
| `countersunk_head_parameters.csv` | ISO 10642 (weitere Senkschrauben ungenutzt) |
| `hex_head_parameters.csv` | ISO 4017, ISO 4014, DIN 931 |
| `setscrew_parameters.csv` | ISO 4026 |
| `hex_nut_parameters.csv` | ISO 4032, ISO 4033, ISO 4035 |
| `square_nut_parameters.csv` | DIN 557 |
| `plain_washer_parameters.csv` | ISO 7089, ISO 7091, ISO 7093 |
| `clearance_hole_sizes.csv` | Durchgangslöcher (Close, Normal, Loose = ISO 273 fein, mittel, grob) |
| `tap_hole_sizes.csv` | Kernlöcher (genutzt: Spalte Soft) |
| `nominal_screw_lengths.csv` | Normlängen je Schraubennorm |
| `heatset_nut_parameters.csv` | Gewindeeinsätze von ruthex, CNC Kitchen, McMaster-Carr, Hilitchi, AE-SamZhihui |
| `drill_sizes.csv` | Zollbohrer (Nummern und Buchstaben) für die Bohrungen der Gewindeeinsätze |
| `single_row_deep_groove_ball_bearing_parameters.csv` | Rillenkugellager, offen (623, 604, 608, 6000, 6200, 6300 …) |
| `single_row_capped_deep_groove_ball_bearing_parameters.csv` | Rillenkugellager, gedeckelt oder gedichtet (-2Z, -2RS1, -2RZ) |
| `shoulder_screw.csv` | ISO 7379 (Schulterschraube) |
| `low_profile_parameters.csv` | Flachkopf-Innensechskant nach OpenBuilds (nicht DIN 7984, siehe unten) |
| `din471.csv` | Sprengringe für Wellen |
| `din472.csv` | Sprengringe für Bohrungen |
| `shaft_key_parameters.csv` | Passfedern DIN 6885 |

Nicht kopiert, obwohl vorhanden: `single_row_angular_contact_ball_bearing_parameters.csv`,
`single_row_cylindrical_roller_bearing_parameters.csv`, `single_row_tapered_roller_bearing_parameters.csv`. Kein Code
liest sie, und eine Tabelle im Ordner, die niemand liest, ist genau der Fehler, vor dem die Inventur warnt.

Bekannte Eigenheiten der Daten:

- Die Werte sind teils Nennmaße, teils Größtmaße (ISO 4762 M3: Kopf 5,68 mm, also das Größtmaß mit Rändelung).
- Die Bohrungen der Gewindeeinsätze sind Zollbohrer und weichen etwas von den metrischen Richtwerten im Skill
  „3D-Druck“ ab (ruthex M3: 4,04 statt 4,0 mm, M5: 6,53 statt 6,4 mm). Gegen Herstellerblätter geprüft ist das nicht.
- Für die M10-Einsätze von ruthex und CNC Kitchen steht als Bohrer „M14“, mehr als der Einsatz dick ist. `soma`
  lehnt diese Einsätze mit einer Meldung ab.
- Bei ISO 4035 M3 steht die Zeile unter der Steigung 0,45 statt 0,5. `soma` nimmt dann die vorhandene Zeile, denn ohne
  Gewinde zählt nur der Durchmesser.

Eigenheiten der Lagertabellen, die den Code bestimmen:

- `d1` und `D1` bedeuten in den beiden Tabellen nicht dasselbe. Bei den offenen Lagern ist `D1 - d1` immer kleiner als
  die Breite (brauchbar als Schulterabstand), bei den gedeckelten in 16 von 26 Zeilen größer — dort sind es die
  Dichtsitze. Aus diesen Spalten lässt sich der Kugeldurchmesser also nicht ableiten; `_bearing_local` rechnet die
  Ringe deshalb aus dem radialen Platz und die Kugeln aus der Breite. Gezeichnet ist damit die Hülle, nicht das Innere.
- Eine Zeile der gedeckelten Tabelle hat keine Bezeichnung (Zeile 8). `_bearing_index` überspringt sie.
- Mehrere gedeckelte Lager heißen anders, als man sie bestellt: die Tabelle führt `E2.608-2Z` (SKF Energy Efficient),
  nicht `608-2Z`. `Bearing` rät nicht, sondern schlägt die ähnlichste Bezeichnung vor.
- Die Tabelle führt die Masse in kg; `Bearing.mass_g` gibt sie in Gramm. Das ist der einzige Wert am Lager, der das
  gezeichnete Volumen nicht braucht — und deshalb der, den eine Kosovnica zeigen sollte.

Eigenheiten der neuen Tabellen:

- `shoulder_screw.csv` führt die Länge in `b` als **Gewindelänge** (M6: 11 mm) und in `g2` den Freistich davor
  (2,5 mm). Die Schulterlänge ist die Länge, die man bestellt; `Screw` zählt sie deshalb als `length` und
  `shank_length` kommt obendrauf. Der Freistich ist mit `dg2` enger als das Gewinde — deshalb ein Rotationsprofil und
  keine Vereinigung von Zylindern, sonst entstünde dort eine Bohrung statt einer Nut.
- `low_profile_parameters.csv` ist die Reihe von OpenBuilds, nicht DIN 7984: der Kopf ist niedriger (M3: 1,5 statt
  2,0 mm) und breiter (5,68 statt 5,5 mm). `soma` nennt sie deshalb „OpenBuilds" und meldet bei „DIN 7984", was
  stattdessen da ist, statt die Maße still umzudeuten.
- `din471.csv` und `din472.csv` sind nach Wellen- bzw. Bohrungsdurchmesser `d1` sortiert, nicht nach einer
  Gewindegröße; die erste Spalte ist eine nackte Zahl. `d5` ist die Spaltweite und dient auch als Loch der Zange,
  `b` die Bandbreite, `a` die Nasenlänge, `d2`/`m` sind Durchmesser und Breite der Nut. `d4` wird nicht verwendet —
  die Spalte bedeutet in den beiden Tabellen nicht dasselbe (bei DIN 471 wächst sie mit der Größe, bei DIN 472
  nicht), und ohne sichere Bedeutung wird sie nicht geraten.
- `shaft_key_parameters.csv` nennt die Nuttiefen `t2` und `t4`; `t4` ist die Nut in der **Welle**, `t2` die in der
  **Nabe**. Geprüft an allen 31 Zeilen: `t2 + t4` ist immer `h` plus 0,2 bis 0,3 mm Spiel, und für 2x2, 3x3 und 8x7
  stimmt die Zuordnung mit DIN 6885 überein. Eine Länge führt die Tabelle nicht — die ist eine Entwurfsentscheidung.
