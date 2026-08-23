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
calibrated MIN/MAX from those exact, visually-verified footprints,
AND exports an isolation-calibration KMZ (isolation_calibration.kmz)
showing each confirmed house plus its nearby neighbors with distance
labels, so you can visually judge in Google Earth whether that gap
matches what you'd call "standalone" before trusting a threshold.

SETUP
    pip install overturemaps geopandas shapely simplekml

USAGE
    1. Fill in REFERENCE_POINTS below (leave CONFIRMED empty first time).
    2. Run: python calibrate.py
    3. Open the generated calibration_candidates.kmz in Google Earth.
    4. For each reference point's folder, click through the numbered
       candidates against satellite imagery until you find the one
       that's actually your house. Note its index number.
    5. Fill in CONFIRMED = {"label": index, ...} below.
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

# how far to search around a confirmed building for isolation
# calibration, in meters
ISOLATION_SEARCH_RADIUS_M = 60

OUTPUT_KMZ = "calibration_candidates.kmz"
ISOLATION_KMZ = "isolation_calibration.kmz"

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


def get_nearby_buildings(geom_wgs84, radius_m):
    """All buildings within radius_m meters of a footprint (for
    isolation calibration) - a plain bbox pull around the footprint's
    centroid, generous enough to catch neighbors."""
    centroid = geom_wgs84.centroid
    deg = radius_m / 111000  # rough deg-per-meter, fine at this scale
    bbox = (centroid.x - deg, centroid.y - deg, centroid.x + deg, centroid.y + deg)
    reader = overturemaps.record_batch_reader("building", bbox=bbox, stac=True)
    table = reader.read_all()
    if table.num_rows == 0:
        return gpd.GeoDataFrame(columns=["id", "geometry"], geometry="geometry", crs="EPSG:4326")
    df = table.to_pandas()
    geoms = df["geometry"].apply(wkb.loads)
    return gpd.GeoDataFrame(df, geometry=geoms, crs="EPSG:4326")


def compute_isolation(row, radius_m=ISOLATION_SEARCH_RADIUS_M):
    """Distance from this confirmed building to its nearest OTHER
    building, plus the full nearby set (for visual export)."""
    nearby = get_nearby_buildings(row.geometry, radius_m)
    if nearby.empty:
        return None, nearby

    nearby_m = nearby.to_crs(nearby.estimate_utm_crs())
    this_m = gpd.GeoSeries([row.geometry], crs="EPSG:4326").to_crs(nearby_m.crs).iloc[0]

    dists = nearby_m.geometry.apply(lambda g: this_m.distance(g))
    others = dists[dists > 0.01]  # exclude itself (distance ~0)
    if others.empty:
        return None, nearby

    return others.min(), nearby


def export_isolation_kmz(confirmed_rows, path):
    kml = simplekml.Kml()
    for label, row, nearest_dist, nearby in confirmed_rows:
        folder = kml.newfolder(name=f"{label} (nearest neighbor: {nearest_dist:.0f}m)")

        exterior = list(row.geometry.exterior.coords)
        pol = folder.newpolygon(name=f"{label} (confirmed)", outerboundaryis=exterior)
        pol.style.linestyle.color = simplekml.Color.green
        pol.style.linestyle.width = 3
        pol.style.polystyle.color = simplekml.Color.changealphaint(100, simplekml.Color.green)

        centroid = row.geometry.centroid
        for _, other in nearby.iterrows():
            other_centroid = other.geometry.centroid
            if other_centroid.distance(centroid) < 1e-9:
                continue
            other_exterior = list(other.geometry.exterior.coords)
            opol = folder.newpolygon(name="neighbor", outerboundaryis=other_exterior)
            opol.style.linestyle.color = simplekml.Color.yellow
            opol.style.linestyle.width = 1
            opol.style.polystyle.color = simplekml.Color.changealphaint(40, simplekml.Color.yellow)

            line = folder.newlinestring(
                name=f"{centroid.distance(other_centroid) * 111000:.0f}m (centroid-to-centroid, approx)",
                coords=[(centroid.x, centroid.y), (other_centroid.x, other_centroid.y)],
            )
            line.style.linestyle.color = simplekml.Color.white
            line.style.linestyle.width = 1

    kml.savekmz(path)


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
    isolation_rows = []
    for label, idx in CONFIRMED.items():
        gdf = all_candidates.get(label)
        if gdf is None or idx not in gdf.index:
            log(f"  '{label}' index {idx}: NOT FOUND - check the index is valid")
            continue
        row = gdf.loc[idx]
        area = row["area_sqm"]
        log(f"  '{label}' [{idx}]: {area:.0f} sqm (confirmed)")
        areas.append(area)

        log(f"    computing isolation distance for '{label}'...")
        nearest_dist, nearby = compute_isolation(row)
        if nearest_dist is None:
            log(f"    no other buildings found within {ISOLATION_SEARCH_RADIUS_M}m - "
                f"very isolated, or search radius too small")
        else:
            log(f"    nearest neighbor: {nearest_dist:.1f}m away "
                f"({len(nearby)} buildings in search radius)")
            isolation_rows.append((label, row, nearest_dist, nearby))

    if not areas:
        log("No confirmed footprints resolved - nothing to calibrate.")
        return

    obs_min, obs_max = min(areas), max(areas)
    sug_min = obs_min * (1 - MARGIN)
    sug_max = obs_max * (1 + MARGIN)

    log("")
    log(f"Observed footprint range: {obs_min:.0f}-{obs_max:.0f} sqm")
    log(f"Suggested filter (with {MARGIN*100:.0f}% margin):")
    log(f"  MIN_FOOTPRINT_SQM = {sug_min:.0f}")
    log(f"  MAX_FOOTPRINT_SQM = {sug_max:.0f}")

    if isolation_rows:
        export_isolation_kmz(isolation_rows, ISOLATION_KMZ)
        dists = [d for _, _, d, _ in isolation_rows]
        obs_min_iso = min(dists)
        sug_iso = obs_min_iso * (1 - MARGIN)
        log("")
        log(f"Observed isolation distances: {', '.join(f'{d:.0f}m' for d in dists)}")
        log(f"Suggested MIN_ISOLATION_METERS = {sug_iso:.0f} "
            f"(smallest confirmed gap, minus {MARGIN*100:.0f}% margin so "
            f"your own reference houses still pass)")
        log(f"Wrote {ISOLATION_KMZ} - open in Google Earth: each confirmed "
            f"house is outlined in green, its nearby buildings in yellow, "
            f"with white lines labeled by distance. Check the suggested "
            f"threshold visually - if a labeled gap doesn't look like a real "
            f"compound boundary to you, adjust MIN_ISOLATION_METERS by hand.")


if __name__ == "__main__":
    main()
