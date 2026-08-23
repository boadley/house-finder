"""
debug_reference.py

Traces a known reference building through each stage of
find_buildings.py's pipeline (isochrone containment -> size filter)
to show exactly which step drops it.

Run this from the same folder as find_buildings.py - it imports
your live CONFIG and functions from there directly, so there's no
risk of typo'd/duplicated numbers going out of sync.

USAGE
    python debug_reference.py
"""

import time

import geopandas as gpd
import overturemaps
from shapely import wkb
from shapely.geometry import Point

import find_buildings as fb  # reuses your actual config + functions

# ============================================================
# Paste the SAME reference point(s) you used in calibrate.py
# ============================================================
REFERENCE_POINTS = [
    ("idealHouse1", 7.1316918194348, 3.385622726430695),
    ("salau", 7.132417395562675, 3.389449961356255),
]


def log(msg):
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)


def get_footprint_at_point(lat, lon, radius_deg=0.001):
    bbox = (lon - radius_deg, lat - radius_deg, lon + radius_deg, lat + radius_deg)
    reader = overturemaps.record_batch_reader("building", bbox=bbox, stac=True)
    table = reader.read_all()
    if table.num_rows == 0:
        return None
    df = table.to_pandas()
    geoms = df["geometry"].apply(wkb.loads)
    gdf = gpd.GeoDataFrame(df, geometry=geoms, crs="EPSG:4326")
    pt = Point(lon, lat)
    containing = gdf[gdf.geometry.contains(pt)]
    return None if containing.empty else containing.iloc[[0]]


def main():
    log(f"Current CONFIG in find_buildings.py:")
    log(f"  MIN_FOOTPRINT_SQM = {fb.MIN_FOOTPRINT_SQM}")
    log(f"  MAX_FOOTPRINT_SQM = {fb.MAX_FOOTPRINT_SQM}")
    log(f"  ISOCHRONE_MINUTES = {fb.ISOCHRONE_MINUTES}, PROFILE = {fb.TRAVEL_PROFILE}")
    log("")

    log("Fetching isochrone (same call find_buildings.py makes)...")
    iso = fb.get_isochrone()
    log("  done")
    log("")

    for label, lat, lon in REFERENCE_POINTS:
        log(f"--- {label} at ({lat}, {lon}) ---")

        row = get_footprint_at_point(lat, lon)
        if row is None:
            log("  STAGE 0 FAIL: no Overture footprint contains this point at all.")
            log("  -> nudge the coordinate, or this building isn't in the dataset")
            log("")
            continue

        area = row.to_crs(row.estimate_utm_crs()).geometry.area.iloc[0]
        log(f"  Footprint found: {area:.0f} sqm (Overture id: {row['id'].iloc[0]})")

        pt = Point(lon, lat)
        inside_iso = iso.geometry.iloc[0].contains(pt)
        log(f"  Inside isochrone polygon? {inside_iso}")
        if not inside_iso:
            log("  -> DROPPED HERE: this point is outside the "
                f"{fb.ISOCHRONE_MINUTES}-min {fb.TRAVEL_PROFILE} isochrone from your "
                "center point. Real road-network travel time to this building "
                "exceeds your cutoff (or ORS's road snapping put it just over "
                "the line) - increase ISOCHRONE_MINUTES or check the center point.")
            log("")
            continue

        in_range = fb.MIN_FOOTPRINT_SQM <= area <= fb.MAX_FOOTPRINT_SQM
        log(f"  Within size filter [{fb.MIN_FOOTPRINT_SQM}, {fb.MAX_FOOTPRINT_SQM}]? {in_range}")
        if not in_range:
            log("  -> DROPPED HERE: its true footprint area falls outside your "
                "configured MIN/MAX. If this doesn't match what calibrate.py "
                "suggested, the config in find_buildings.py wasn't updated to "
                "match - check for a copy-paste mismatch.")
        else:
            log("  -> Should be in the output. If it's still missing from the "
                "KMZ, check for a duplicate/near-duplicate Overture id being "
                "deduplicated, or re-run find_buildings.py fresh.")
        log("")


if __name__ == "__main__":
    main()
