"""
find_buildings.py

Finds building footprints within a real road-network isochrone
(drive/walk time, not a circular buffer) around a center point,
filtered by footprint size, and exports them to KMZ for field use -
split into manageable chunks, grouped geographically so each chunk
is a walkable/driveable cluster rather than a scattered sample.

WORKFLOW
1. Query OpenRouteService for an isochrone polygon (real road network).
2. Query Overture Maps' buildings dataset for footprints inside that
   polygon's bounding box.
3. Clip to the exact isochrone shape, compute footprint area (sqm),
   filter to your target size range.
4. Sort survivors along a space-filling (Z-order) curve so nearby
   buildings end up adjacent in the list, then slice into chunks of
   CHUNK_SIZE and export each chunk to its own KMZ.

SETUP (one-time)
    pip install openrouteservice geopandas shapely overturemaps simplekml pyproj

    Get a free ORS API key: https://openrouteservice.org/dev/#/signup
    (free tier: 2,000 isochrone requests/day - way more than you need)

USAGE
    Edit the CONFIG block below, then run:
        python find_buildings.py

    Re-run any time you change AOI, isochrone minutes, footprint size,
    or chunk size - every one of those is just a variable below.
"""

import time

import geopandas as gpd
import openrouteservice
import overturemaps
import simplekml
from shapely import wkb
from shapely.geometry import shape


def log(msg):
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)

# ============================================================
# CONFIG - edit these, then just re-run the script
# ============================================================

ORS_API_KEY = "eyJvcmciOiI1YjNjZTM1OTc4NTExMTAwMDFjZjYyNDgiLCJpZCI6IjdkN2VhMzc0NmExNjRhNTNhOTliOWU4N2FkMTQwOTgwIiwiaCI6Im11cm11cjY0In0="

# Center point of your AOI. Get exact coords by right-clicking the
# spot on Google Maps -> the lat/lng shown at the top is what you want.
# (Placeholder below is central Abeokuta - replace with your exact
# Panseke point.)
CENTER_LAT = 7.136823441977621 # dominos pizza panseke
CENTER_LON = 3.332508859664971

# Real road-network isochrone settings
ISOCHRONE_MINUTES = 15
TRAVEL_PROFILE = "driving-car"   # also: "foot-walking", "cycling-regular"

# Footprint size filter (sqm) - fill in from calibrate.py's output
MIN_FOOTPRINT_SQM = 90
MAX_FOOTPRINT_SQM = 106

# How many buildings per output KMZ. Buildings are sorted along a
# space-filling curve first, so each chunk is a geographically
# contiguous cluster, not a random scatter across the whole AOI.
CHUNK_SIZE = 200

OUTPUT_PREFIX = "candidate_buildings"  # files: candidate_buildings_001.kmz, ...

# ============================================================
# STEP 1 - real road-network isochrone via OpenRouteService
# ============================================================

def get_isochrone():
    client = openrouteservice.Client(key=ORS_API_KEY)
    result = client.isochrones(
        locations=[[CENTER_LON, CENTER_LAT]],
        profile=TRAVEL_PROFILE,
        range=[ISOCHRONE_MINUTES * 60],   # ORS wants seconds
        attributes=["area"],
    )
    iso_geom = shape(result["features"][0]["geometry"])
    return gpd.GeoDataFrame({"geometry": [iso_geom]}, crs="EPSG:4326")


# ============================================================
# STEP 2 - building footprints from Overture Maps (bbox query)
# ============================================================
#
# Uses the official `overturemaps` client rather than a hand-rolled
# S3 parquet glob: it resolves the current release automatically via
# Overture's STAC catalog, so there's no release-date string to keep
# updated (and no risk of a guessed/stale date silently hanging).
# Typical runtime for a city-sized bbox is well under a minute.

def get_buildings_in_bbox(iso_gdf):
    minx, miny, maxx, maxy = iso_gdf.total_bounds
    bbox = (minx, miny, maxx, maxy)  # (west, south, east, north)

    log(f"  bbox: {bbox}")
    t0 = time.time()
    reader = overturemaps.record_batch_reader("building", bbox=bbox, stac=True)
    table = reader.read_all()
    log(f"  fetched {table.num_rows} rows in {time.time() - t0:.1f}s")

    if table.num_rows == 0:
        return gpd.GeoDataFrame(columns=["id", "geometry"], geometry="geometry", crs="EPSG:4326")

    df = table.to_pandas()
    geoms = df["geometry"].apply(wkb.loads)
    buildings = gpd.GeoDataFrame(df, geometry=geoms, crs="EPSG:4326")
    return buildings


# ============================================================
# STEP 3 - clip to isochrone + filter by footprint size
# ============================================================

def filter_buildings(buildings, iso_gdf):
    clipped = gpd.clip(buildings, iso_gdf)

    # project to a local metric CRS for accurate area in sqm
    # (UTM zone 31N covers this part of Nigeria)
    clipped_m = clipped.to_crs("EPSG:32631")
    clipped["area_sqm"] = clipped_m.geometry.area

    matches = clipped[
        (clipped["area_sqm"] >= MIN_FOOTPRINT_SQM)
        & (clipped["area_sqm"] <= MAX_FOOTPRINT_SQM)
    ].copy()
    return matches


# ============================================================
# STEP 4 - sort for spatial locality, chunk, export to KMZ
# ============================================================

def _morton_key(x, y, bits=16):
    """
    Z-order (Morton) curve key: interleaves the bits of x and y so
    that sorting by this key groups spatially nearby points together.
    x, y must be normalized to integers in [0, 2**bits).
    """
    def spread_bits(v):
        v &= (1 << bits) - 1
        result = 0
        for i in range(bits):
            result |= (v & (1 << i)) << i
        return result

    return spread_bits(x) | (spread_bits(y) << 1)


def sort_by_locality(matches):
    centroids = matches.geometry.centroid
    xs, ys = centroids.x.values, centroids.y.values
    xmin, xmax = xs.min(), xs.max()
    ymin, ymax = ys.min(), ys.max()

    def norm(v, vmin, vmax, bits=16):
        span = vmax - vmin
        if span == 0:
            return [0] * len(v)
        return ((v - vmin) / span * ((1 << bits) - 1)).astype(int)

    xs_norm = norm(xs, xmin, xmax)
    ys_norm = norm(ys, ymin, ymax)

    keys = [_morton_key(int(x), int(y)) for x, y in zip(xs_norm, ys_norm)]
    matches = matches.copy()
    matches["_morton"] = keys
    return matches.sort_values("_morton").drop(columns="_morton").reset_index(drop=True)


def export_chunk_kmz(chunk, iso_gdf, path, chunk_label):
    kml = simplekml.Kml()

    # isochrone boundary, for context (included in every chunk so each
    # file is self-contained/orientable on its own)
    iso_folder = kml.newfolder(name=f"{ISOCHRONE_MINUTES}-min isochrone")
    for geom in iso_gdf.geometry:
        coords = list(geom.exterior.coords) if geom.geom_type == "Polygon" \
            else list(geom.geoms[0].exterior.coords)
        pol = iso_folder.newpolygon(name="AOI boundary", outerboundaryis=coords)
        pol.style.linestyle.color = simplekml.Color.red
        pol.style.linestyle.width = 3
        pol.style.polystyle.fill = 0

    # actual footprint polygons - renders fully in Google Earth incl.
    # satellite underneath; dropped on KML->GPX conversion in OsmAnd
    footprint_folder = kml.newfolder(name=f"{chunk_label} - Footprints")
    for _, row in chunk.iterrows():
        geom = row.geometry
        exterior = list(geom.exterior.coords) if geom.geom_type == "Polygon" \
            else list(geom.geoms[0].exterior.coords)
        pol = footprint_folder.newpolygon(
            name=f"{row['area_sqm']:.0f} sqm",
            outerboundaryis=exterior,
        )
        pol.description = f"Footprint area: {row['area_sqm']:.0f} sqm\nOverture ID: {row['id']}"
        pol.style.linestyle.color = simplekml.Color.yellow
        pol.style.linestyle.width = 2
        pol.style.polystyle.color = simplekml.Color.changealphaint(80, simplekml.Color.yellow)

    # centroid pins - what survives OsmAnd's KML->GPX import, use for navigation
    pin_folder = kml.newfolder(name=f"{chunk_label} - Pins (for navigation)")
    for _, row in chunk.iterrows():
        centroid = row.geometry.centroid
        pin = pin_folder.newpoint(
            name=f"{row['area_sqm']:.0f} sqm",
            coords=[(centroid.x, centroid.y)],
        )
        pin.description = f"Footprint area: {row['area_sqm']:.0f} sqm\nOverture ID: {row['id']}"

    kml.savekmz(path)


def export_chunked_kmz(matches, iso_gdf, prefix, chunk_size):
    if len(matches) == 0:
        log("  no matches to export")
        return

    ordered = sort_by_locality(matches)
    n_chunks = -(-len(ordered) // chunk_size)  # ceil division
    pad = len(str(n_chunks))

    for i in range(n_chunks):
        chunk = ordered.iloc[i * chunk_size : (i + 1) * chunk_size]
        chunk_label = f"Chunk {i+1} of {n_chunks}"
        filename = f"{prefix}_{str(i+1).zfill(pad)}.kmz"
        export_chunk_kmz(chunk, iso_gdf, filename, chunk_label)
        log(f"  {filename}: {len(chunk)} buildings")

    log(f"Wrote {n_chunks} file(s), ~{chunk_size} buildings each "
        f"({len(ordered)} total)")


# ============================================================
# MAIN
# ============================================================

if __name__ == "__main__":
    log("Fetching isochrone...")
    t0 = time.time()
    iso = get_isochrone()
    log(f"  isochrone ready in {time.time() - t0:.1f}s")

    log("Querying building footprints...")
    buildings = get_buildings_in_bbox(iso)

    log("Clipping to isochrone and filtering by size...")
    t0 = time.time()
    matches = filter_buildings(buildings, iso)
    log(f"  {len(matches)} buildings match {MIN_FOOTPRINT_SQM}-{MAX_FOOTPRINT_SQM} sqm "
        f"(clipped/filtered in {time.time() - t0:.1f}s)")

    log("Writing chunked KMZ files...")
    export_chunked_kmz(matches, iso, OUTPUT_PREFIX, CHUNK_SIZE)
    log("Done.")
