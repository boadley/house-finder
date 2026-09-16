# Isochrone building-footprint finder

Generates a KMZ of candidate building footprints (by real road-network
travel time and footprint size) that you can send straight to your
local contact — opens directly in Google Earth / Maps on their phone.

## One-time setup

1. Install Python 3.9+ if you don't have it: https://www.python.org/downloads/
2. Get a free OpenRouteService API key (instant, no card needed):
   https://openrouteservice.org/dev/#/signup
3. Install dependencies:
   ```
   pip install openrouteservice geopandas shapely overturemaps simplekml pyproj
   ```

## Calibrating footprint size from known buildings

If you already know ~3 buildings that are roughly the size/shape you
want, use `calibrate.py` to derive a MIN/MAX filter from them instead
of guessing:

1. Right-click each reference building's location on Google Maps and
   copy the lat/lng.
2. Paste them into `REFERENCE_POINTS` in `calibrate.py`.
3. Run `python calibrate.py`.
4. It queries the *same* Overture dataset the main script filters
   against, prints each building's footprint area, and suggests a
   MIN/MAX range (with a margin) to paste into `find_buildings.py`.

This matters because a footprint's area as measured by the dataset
can differ from what you'd estimate eyeballing satellite imagery -
calibrating against the same source you're filtering against keeps
the comparison apples-to-apples.

## Isolation filter — the actual "alone in the compound" check

`MIN_FOOTPRINT_SQM`/`MAX_FOOTPRINT_SQM` only checks size, not whether
a building is standalone — a bungalow-sized unit in a row of four
identical attached units passes the size filter just as easily as a
genuinely standalone one. `MIN_ISOLATION_METERS` filters those out by
checking the distance from each candidate to its nearest *other*
building (using the full building set in the bbox, not just size
matches) and dropping anything with a neighbor closer than that
threshold. This is the highest-leverage lever if your candidate list
is still much larger than your local contact can visit — set it to
None to disable, or tune it up/down based on how tightly-packed
buildings typically sit in your target streets.

This is a proxy, not a guarantee — it can't see an actual compound
wall, only building-to-building clearance. Pair it with a manual
satellite pass over the surviving candidates in Google Earth, where
compound walls themselves are usually visible, before dispatching a
final list to your contact.

To calibrate `MIN_ISOLATION_METERS` visually instead of guessing: it
now runs automatically as part of `calibrate.py`'s confirm phase — no
extra step needed. Once you've confirmed your reference buildings for
footprint-size calibration, the script also computes each one's real
distance to its nearest neighbor and writes `isolation_calibration.kmz`,
with each confirmed house outlined in green, nearby buildings in
yellow, and white lines labeled with the distance to each. Open it in
Google Earth and sanity-check that the suggested threshold actually
corresponds to what looks like a real compound boundary on the
imagery, not just a number.

## Route optimization (optional, separate script)

`optimize_route.py` is completely separate from the main pipeline —
it never runs automatically, only when you call it. Point it at a
KMZ (typically one of `find_buildings.py`'s chunked output files) and
it reorders the buildings into an efficient visiting sequence,
drawing a route line and numbering the stops:

```
pip install openrouteservice simplekml
python optimize_route.py candidate_buildings_001.kmz candidate_buildings_001_routed.kmz
```

Useful flags:
- `--start-lat LAT --start-lon LON` — fix a starting point (e.g. your
  contact's home, or wherever they'll actually start the day from).
  Without this, it tries to find whichever starting building gives
  the shortest overall route (only for chunks ≤30 buildings — larger
  chunks start from whichever building is nearest the group's
  centroid, since trying every possible start gets slow above that).
- `--profile foot-walking` — if your contact is walking, not driving.
- `--no-matrix` — skip the real-road-distance ORS API call and use
  straight-line distance instead. Faster, no API quota used, but less
  accurate where roads wind. This also kicks in automatically if the
  ORS matrix call fails (e.g. `--ors-api-key` not provided, or the
  chunk is too large for one request), so a real key isn't strictly
  required to get a route — just a straight-line-optimized one.
- `--ors-api-key YOUR_KEY` — reuses the same key from `find_buildings.py`.

The output KMZ has a blue route line (survives OsmAnd's KML import,
since lines aren't dropped like polygons are) plus numbered pins in
visiting order.

## Every time you want a new/adjusted map

Open `find_buildings.py` and edit the CONFIG block at the top:

| Variable | What it controls |
|---|---|
| `ORS_API_KEY` | your key from step 2 above |
| `CENTER_LAT` / `CENTER_LON` | your AOI center — get exact coords by right-clicking the spot on Google Maps |
| `ISOCHRONE_MINUTES` | travel-time radius (real roads, not a circle) |
| `TRAVEL_PROFILE` | `driving-car`, `foot-walking`, or `cycling-regular` |
| `MIN_FOOTPRINT_SQM` / `MAX_FOOTPRINT_SQM` | building footprint size range to match your target dimensions |
| `CHUNK_SIZE` | buildings per output KMZ file (default 200) |
| `OUTPUT_PREFIX` | base filename - outputs `{prefix}_001.kmz`, `{prefix}_002.kmz`, etc |

Then run:
```
python find_buildings.py
```

You'll get `candidate_buildings_001.kmz`, `candidate_buildings_002.kmz`,
etc. — each capped at `CHUNK_SIZE` buildings, and each one a
geographically contiguous cluster (buildings are sorted along a
space-filling curve before chunking, so consecutive files roughly
correspond to consecutive neighborhoods, not a random scatter). Open
one in Google Earth to sanity-check clusters before sending them out,
or send each file to a different person/day for canvassing.

## What's in the output KMZ

Two folders:
- **Footprints (polygons)** — the actual building outline as a shape,
  colored fill. Renders fully in **Google Earth**, including over the
  satellite basemap. This is what you (or your contact, if they have
  Google Earth) should use to visually check compound layout.
- **Pins (for navigation)** — a centroid point per matching building,
  labeled with its footprint area. This is what survives import into
  **OsmAnd** — OsmAnd converts KML/KMZ to GPX on import and does not
  support polygons, so only these pins will show there. That's fine
  for navigation purposes; you just lose the shape preview.

OsmAnd also doesn't show satellite imagery by default (it's an
offline vector map app) — satellite requires enabling an online raster
map plugin separately. Google Earth has satellite built in and is the
better tool for visual QA; use OsmAnd for turn-by-turn to the pins
once you've picked candidates.

## Notes / limitations

- Footprint size filtering catches shape, not room count or occupancy —
  it tells you "a building this size exists here," not that it's a
  standalone-compound bungalow specifically. Use it to shortlist
  clusters of streets, then have your contact confirm on the ground
  (compound wall, single structure, vacancy) — same caveat as the
  satellite-imagery approach in general.
- Overture conflates Google Open Buildings, Microsoft Building
  Footprints, OSM, and Esri Community Maps, so you get the benefit of
  Google's stronger African coverage and Microsoft's detections in one
  query — no need to pick a single source. Still, expect some real
  buildings to be missing rather than false positives (it under-counts
  more than it over-counts).
- The Overture release path in the script (`2025-08-20.0`) may age out;
  check https://docs.overturemaps.org for the current release if the
  query returns nothing.

## Full command

`python optimize_route.py chunks/15min_driving_candidate_buildings_28.kmz routes/15min_driving_candidate_buildings_28_route.kmz --start-lat 7.136823441977621 --start-lon 3.332508859664971 --ors-api-key eyJvcmciOiI1YjNjZTM1OTc4NTExMTAwMDFjZjYyNDgiLCJpZCI6IjdkN2VhMzc0NmExNjRhNTNhOTliOWU4N2FkMTQwOTgwIiwiaCI6Im11cm11cjY0In0=`