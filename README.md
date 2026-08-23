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
