"""
optimize_route.py

Takes a candidate-buildings KMZ (as produced by find_buildings.py) and
writes a new KMZ with the buildings reordered into an efficient
visiting sequence, plus a route line connecting them in that order and
numbered pins so your contact knows what order to visit.

This is entirely separate from the main pipeline and only runs when
you explicitly call it - it never runs automatically.

SETUP
    pip install openrouteservice simplekml

USAGE
    python optimize_route.py INPUT.kmz OUTPUT.kmz [options]

    --profile {driving-car,foot-walking,cycling-regular}
        default: driving-car

    --start-lat LAT --start-lon LON
        fixed starting point (e.g. your contact's home, or the AOI
        center). If omitted, the route starts from whichever building
        gives the shortest total route.

    --no-matrix
        skip the real-road-distance ORS matrix call and use
        straight-line (haversine) distance instead. Faster, uses no
        ORS quota, less accurate on winding road networks. Use this
        automatically kicks in anyway if the matrix call fails or the
        chunk is too large for a single request.

EXAMPLE
    python optimize_route.py candidate_buildings_001.kmz candidate_buildings_001_routed.kmz --start-lat 7.1508 --start-lon 3.3467

NOTES ON SCALE
    ORS's free-tier matrix endpoint has a location-count limit that
    varies by plan/instance. A ~200-building chunk is normally fine
    in one call; if it errors, this script automatically falls back
    to straight-line distance for that run rather than failing.
"""

import argparse
import math
import time
import zipfile
from xml.etree import ElementTree as ET

import simplekml

KML_NS = "{http://www.opengis.net/kml/2.2}"


def log(msg):
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)


# ============================================================
# STEP 1 - parse buildings (pins) out of the input KMZ
# ============================================================

def parse_kmz_pins(path):
    """
    Extracts every Point placemark from the KMZ - this is deliberately
    format-agnostic about which folder they're in, so it works whether
    you point it at a raw find_buildings.py output or something
    hand-edited afterward.
    """
    with zipfile.ZipFile(path) as z:
        kml_name = next(n for n in z.namelist() if n.endswith(".kml"))
        kml_bytes = z.read(kml_name)

    root = ET.fromstring(kml_bytes)
    buildings = []
    for placemark in root.iter(f"{KML_NS}Placemark"):
        point = placemark.find(f"{KML_NS}Point")
        if point is None:
            continue  # skip polygons/lines, we only want the pins
        coords_el = point.find(f"{KML_NS}coordinates")
        if coords_el is None or not coords_el.text:
            continue
        lon, lat, *_ = [float(v) for v in coords_el.text.strip().split(",")]

        name_el = placemark.find(f"{KML_NS}name")
        desc_el = placemark.find(f"{KML_NS}description")
        buildings.append({
            "name": name_el.text if name_el is not None else "",
            "description": desc_el.text if desc_el is not None else "",
            "lat": lat,
            "lon": lon,
        })

    return buildings


# ============================================================
# STEP 2 - distance matrix (real road distance, or straight-line)
# ============================================================

def haversine_m(lat1, lon1, lat2, lon2):
    R = 6371000
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dlambda / 2) ** 2
    return 2 * R * math.asin(math.sqrt(a))


def straight_line_matrix(buildings):
    n = len(buildings)
    matrix = [[0.0] * n for _ in range(n)]
    for i in range(n):
        for j in range(n):
            if i != j:
                matrix[i][j] = haversine_m(
                    buildings[i]["lat"], buildings[i]["lon"],
                    buildings[j]["lat"], buildings[j]["lon"],
                )
    return matrix


def ors_matrix(buildings, profile, api_key):
    import openrouteservice
    client = openrouteservice.Client(key=api_key)
    locations = [[b["lon"], b["lat"]] for b in buildings]
    result = client.distance_matrix(
        locations=locations,
        profile=profile,
        metrics=["duration"],
    )
    return result["durations"]


def build_matrix(buildings, profile, api_key, use_matrix):
    n = len(buildings)
    if not use_matrix:
        log(f"  using straight-line distance ({n} buildings)")
        return straight_line_matrix(buildings)

    if not api_key or api_key == "PASTE_YOUR_FREE_ORS_KEY_HERE":
        log("  no ORS_API_KEY provided - falling back to straight-line distance")
        return straight_line_matrix(buildings)

    log(f"  requesting {n}x{n} real-road matrix from ORS...")
    try:
        matrix = ors_matrix(buildings, profile, api_key)
        log("  matrix received")
        return matrix
    except Exception as e:
        log(f"  ORS matrix request failed ({e}) - falling back to straight-line distance")
        return straight_line_matrix(buildings)


# ============================================================
# STEP 3 - route: nearest-neighbor construction + 2-opt improvement
# ============================================================

def nearest_neighbor_route(matrix, start_idx):
    n = len(matrix)
    unvisited = set(range(n))
    route = [start_idx]
    unvisited.remove(start_idx)
    current = start_idx
    while unvisited:
        nxt = min(unvisited, key=lambda j: matrix[current][j])
        route.append(nxt)
        unvisited.remove(nxt)
        current = nxt
    return route


def route_length(route, matrix):
    return sum(matrix[route[i]][route[i + 1]] for i in range(len(route) - 1))


def two_opt(route, matrix, max_iterations=1000):
    improved = True
    iterations = 0
    n = len(route)
    while improved and iterations < max_iterations:
        improved = False
        iterations += 1
        for i in range(1, n - 2):
            for j in range(i + 1, n - 1):
                a, b, c, d = route[i - 1], route[i], route[j], route[j + 1]
                current_cost = matrix[a][b] + matrix[c][d]
                new_cost = matrix[a][c] + matrix[b][d]
                if new_cost < current_cost - 1e-6:
                    route[i:j + 1] = route[i:j + 1][::-1]
                    improved = True
    return route


def best_start_route(matrix, fixed_start_idx=None, exhaustive_start_limit=30):
    n = len(matrix)
    if fixed_start_idx is not None:
        route = nearest_neighbor_route(matrix, fixed_start_idx)
        return two_opt(route, matrix)

    if n > exhaustive_start_limit:
        # trying every possible start is O(n^3)-ish with 2-opt - fine
        # for small chunks, too slow for ~200 buildings. The caller
        # handles this case via centroid_start_route instead.
        return None

    # try every building as a start, keep whichever gives the shortest
    # total route - only worth it for small chunks
    best_route, best_len = None, math.inf
    for start in range(n):
        route = nearest_neighbor_route(matrix, start)
        route = two_opt(route, matrix, max_iterations=50)
        length = route_length(route, matrix)
        if length < best_len:
            best_route, best_len = route, length
    return two_opt(best_route, matrix)


def centroid_start_route(buildings, matrix):
    n = len(buildings)
    avg_lat = sum(b["lat"] for b in buildings) / n
    avg_lon = sum(b["lon"] for b in buildings) / n
    start_idx = min(
        range(n),
        key=lambda i: haversine_m(avg_lat, avg_lon, buildings[i]["lat"], buildings[i]["lon"]),
    )
    route = nearest_neighbor_route(matrix, start_idx)
    return two_opt(route, matrix)


# ============================================================
# STEP 4 - export routed KMZ
# ============================================================

def export_routed_kmz(buildings, route, path):
    kml = simplekml.Kml()

    line_folder = kml.newfolder(name="Route")
    coords = [(buildings[i]["lon"], buildings[i]["lat"]) for i in route]
    line = line_folder.newlinestring(name="Visiting route", coords=coords)
    line.style.linestyle.color = simplekml.Color.blue
    line.style.linestyle.width = 4

    pin_folder = kml.newfolder(name="Stops (in visiting order)")
    for order, idx in enumerate(route, start=1):
        b = buildings[idx]
        pin = pin_folder.newpoint(
            name=f"{order}. {b['name']}",
            coords=[(b["lon"], b["lat"])],
        )
        pin.description = b["description"] or ""

    kml.savekmz(path)


# ============================================================
# MAIN
# ============================================================

def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("input_kmz", help="Path to candidate-buildings KMZ")
    parser.add_argument("output_kmz", help="Path to write the routed KMZ")
    parser.add_argument("--profile", default="driving-car",
                         choices=["driving-car", "foot-walking", "cycling-regular"])
    parser.add_argument("--start-lat", type=float, default=None)
    parser.add_argument("--start-lon", type=float, default=None)
    parser.add_argument("--no-matrix", action="store_true",
                         help="skip ORS matrix call, use straight-line distance")
    parser.add_argument("--ors-api-key", default="PASTE_YOUR_FREE_ORS_KEY_HERE",
                         help="required unless --no-matrix is set")
    args = parser.parse_args()

    log(f"Reading pins from {args.input_kmz}...")
    buildings = parse_kmz_pins(args.input_kmz)
    log(f"  {len(buildings)} buildings found")

    if len(buildings) < 2:
        log("Fewer than 2 buildings - nothing to route.")
        return

    log("Building distance matrix...")
    matrix = build_matrix(buildings, args.profile, args.ors_api_key, use_matrix=not args.no_matrix)

    fixed_start_idx = None
    if args.start_lat is not None and args.start_lon is not None:
        fixed_start_idx = min(
            range(len(buildings)),
            key=lambda i: haversine_m(args.start_lat, args.start_lon,
                                       buildings[i]["lat"], buildings[i]["lon"]),
        )
        log(f"  fixed start: nearest building is index {fixed_start_idx} "
            f"({buildings[fixed_start_idx]['name']})")

    log("Solving route (nearest-neighbor + 2-opt)...")
    t0 = time.time()
    route = best_start_route(matrix, fixed_start_idx)
    if route is None:
        log(f"  >30 buildings with no fixed start - using centroid-nearest start")
        route = centroid_start_route(buildings, matrix)
    log(f"  done in {time.time() - t0:.1f}s, total route cost: {route_length(route, matrix):.0f}")

    log(f"Writing {args.output_kmz}...")
    export_routed_kmz(buildings, route, args.output_kmz)
    log("Done.")


if __name__ == "__main__":
    main()
