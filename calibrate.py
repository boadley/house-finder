"""
calibrate.py

Two-phase visual calibration, because trusting whichever footprint a
point happens to land in is fragile - a few meters of GPS/click
imprecision can land you on a neighboring shed instead of the house.

PHASE 1 (export): for each reference point, pulls every building
footprint within SEARCH_RADIUS_DEG and writes them all to a KMZ,
each labeled with an index and its footprint area. Open that KMZ in
Google Earth (satellite view on) and visually confirm which labeled
polygon is actually your reference house.

PHASE 2 (confirm): paste the confirmed index (or Overture id) for
each reference point into CONFIRMED below, rerun - it computes the
calibrated MIN/MAX from those exact, visually-verified footprints.

SETUP
    pip install overturemaps geopandas shapely simplekml

USAGE
    1. Fill in REFERENCE_POINTS below (leave CONFIRMED empty first time).
    2. Run: python calibrate.py
    3. Open the generated calibration_candidates.kmz in Google Earth.
    4. For each reference point's folder, click through the numbered
       candidates against satellite imagery until you find the one
       that's actually your house. Note its index number.
    5. Fill in CONFIRMED = {"label": index, ...} below. i.e CONFIRMED = {"idealHouse1": 2, "salau": 0}
    6. Run again - now it prints the calibrated MIN/MAX range.
"""

import time

import geopandas as gpd
import overturemaps
import simplekml
from shapely import wkb
from shapely.geometry import Point

# ============================================================
# CONFIG
# ============================================================

REFERENCE_POINTS = [
    # (label, lat, lon) - approximate is fine, this is just a search center
    ("idealHouse1", 7.1316918194348, 3.385622726430695),
    ("salau", 7.132417395562675, 3.389449961356255),
]

# how far around each point to search for candidates, in degrees
# (0.0006 =~ 65m at this latitude - widen if your point was very
# imprecise, e.g. if it was a street address rather than a map click)
SEARCH_RADIUS_DEG = 0.0006

# PHASE 2: after visually checking the KMZ, fill this in with the
# confirmed candidate index per label, e.g. {"idealHouse1": 2, "salau": 0}
# Leave empty ({}) to just export candidates for phase 1.
CONFIRMED = {"idealHouse1": 10, "salau": 3}

MARGIN = 0.2  # +/- margin around observed min/max, as a fraction

OUTPUT_KMZ = "calibration_candidates.kmz"

# ============================================================


def log(msg):
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)


def get_candidates(lat, lon, radius_deg):
    bbox = (lon - radius_deg, lat - radius_deg, lon + radius_deg, lat + radius_deg)
    reader = overturemaps.record_batch_reader("building", bbox=bbox, stac=True)
    table = reader.read_all()
    if table.num_rows == 0:
        return gpd.GeoDataFrame(columns=["id", "geometry"], geometry="geometry", crs="EPSG:4326")

    df = table.to_pandas()
    geoms = df["geometry"].apply(wkb.loads)
    gdf = gpd.GeoDataFrame(df, geometry=geoms, crs="EPSG:4326")

    pt = Point(lon, lat)
    gdf_m = gdf.to_crs(gdf.estimate_utm_crs())
    pt_m = gpd.GeoSeries([pt], crs="EPSG:4326").to_crs(gdf_m.crs).iloc[0]
    gdf["area_sqm"] = gdf_m.geometry.area.values
    gdf["dist_m"] = gdf_m.geometry.distance(pt_m).values

    return gdf.sort_values("dist_m").reset_index(drop=True)


def export_candidates_kmz(all_candidates, path):
    kml = simplekml.Kml()
    for label, gdf in all_candidates.items():
        folder = kml.newfolder(name=label)
        for i, row in gdf.iterrows():
            geom = row.geometry
            exterior = list(geom.exterior.coords) if geom.geom_type == "Polygon" \
                else list(geom.geoms[0].exterior.coords)
            pol = folder.newpolygon(
                name=f"[{i}] {row['area_sqm']:.0f} sqm, {row['dist_m']:.0f}m away",
                outerboundaryis=exterior,
            )
            pol.description = f"Overture id: {row['id']}"
            pol.style.linestyle.color = simplekml.Color.yellow
            pol.style.linestyle.width = 2
            pol.style.polystyle.color = simplekml.Color.changealphaint(
                80, simplekml.Color.yellow
            )
    kml.savekmz(path)


def main():
    log(f"Searching {len(REFERENCE_POINTS)} reference point(s), "
        f"radius {SEARCH_RADIUS_DEG} deg (~{SEARCH_RADIUS_DEG * 111000:.0f}m)")

    all_candidates = {}
    for label, lat, lon in REFERENCE_POINTS:
        log(f"Querying '{label}'...")
        gdf = get_candidates(lat, lon, SEARCH_RADIUS_DEG)
        log(f"  {len(gdf)} candidate(s) found")
        for i, row in gdf.iterrows():
            log(f"    [{i}] {row['area_sqm']:.0f} sqm, {row['dist_m']:.0f}m away "
                f"(id: {row['id']})")
        all_candidates[label] = gdf

    if not CONFIRMED:
        log("")
        log("CONFIRMED is empty - exporting candidates only.")
        export_candidates_kmz(all_candidates, OUTPUT_KMZ)
        log(f"Wrote {OUTPUT_KMZ}")
        log("Open it in Google Earth (satellite on), find the correct "
            "candidate per label by its index number, then fill in "
            "CONFIRMED = {\"label\": index, ...} and rerun.")
        return

    log("")
    log("CONFIRMED provided - computing calibration from confirmed footprints:")
    areas = []
    for label, idx in CONFIRMED.items():
        gdf = all_candidates.get(label)
        if gdf is None or idx not in gdf.index:
            log(f"  '{label}' index {idx}: NOT FOUND - check the index is valid")
            continue
        area = gdf.loc[idx, "area_sqm"]
        log(f"  '{label}' [{idx}]: {area:.0f} sqm (confirmed)")
        areas.append(area)

    if not areas:
        log("No confirmed footprints resolved - nothing to calibrate.")
        return

    obs_min, obs_max = min(areas), max(areas)
    sug_min = obs_min * (1 - MARGIN)
    sug_max = obs_max * (1 + MARGIN)

    log("")
    log(f"Observed range: {obs_min:.0f}-{obs_max:.0f} sqm")
    log(f"Suggested filter (with {MARGIN*100:.0f}% margin):")
    log(f"  MIN_FOOTPRINT_SQM = {sug_min:.0f}")
    log(f"  MAX_FOOTPRINT_SQM = {sug_max:.0f}")


if __name__ == "__main__":
    main()