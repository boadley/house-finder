# House Finder 🏠

House Finder is a geospatial analysis pipeline that identifies candidate building footprints based on real road-network travel time, footprint size, and spatial isolation. It automatically generates ready-to-use KMZ files that can be opened directly in Google Earth or mobile navigation apps (like OsmAnd), streamlining the process of on-the-ground scouting and field research.

## Value Proposition

For organizations conducting field research, real estate scouting, or canvassing, manually finding suitable buildings in a target area is time-consuming and error-prone. This tool automates the process by filtering buildings from the Overture Maps dataset based on your specific criteria:

- **Travel Time:** Generates isochrones to ensure all candidates are within a specified driving or walking time from a central point.
- **Size Calibration:** Filters buildings by footprint area (square meters), which can be precisely calibrated against known reference buildings.
- **Spatial Isolation:** Identifies standalone structures (e.g., individual compounds) by checking the distance from each candidate to its nearest neighbor.
- **Route Optimization:** Automatically orders the resulting candidate buildings into an efficient visiting sequence for field teams.

## Key Features

- **Overture Maps Integration:** Queries high-quality, up-to-date footprint data by merging sources like Google Open Buildings, Microsoft, OSM, and more.
- **OpenRouteService (ORS) Powered:** Calculates real-world travel times and optimizes field routes.
- **Custom Calibration Tool:** Includes a script (`calibrate.py`) to automatically determine the ideal footprint size and isolation parameters based on a few known reference buildings.
- **Chunking for Field Work:** Outputs manageable subsets of buildings geographically grouped together, making it easy to distribute work across different days or team members.
- **Mobile-Ready Outputs:** Generates KMZ files with detailed polygons for visual inspection in Google Earth, and points for turn-by-turn navigation in offline apps like OsmAnd.

## Installation

1. Install Python 3.9+
2. Obtain a free [OpenRouteService API key](https://openrouteservice.org/dev/#/signup)
3. Install dependencies:
   ```bash
   pip install openrouteservice geopandas shapely overturemaps simplekml pyproj
   ```

## Usage Guide

### 1. Find and Filter Buildings
Edit the configuration variables at the top of `find_buildings.py` (e.g., `ORS_API_KEY`, `CENTER_LAT`, `CENTER_LON`, `ISOCHRONE_MINUTES`).

```bash
python find_buildings.py
```
This generates chunked KMZ files containing the filtered buildings, ready for visual inspection.

### 2. Calibrate Parameters (Optional)
If you already have a few reference buildings that match your target criteria, use `calibrate.py` to automatically determine the ideal `MIN_FOOTPRINT_SQM`, `MAX_FOOTPRINT_SQM`, and `MIN_ISOLATION_METERS`.

```bash
python calibrate.py
```

### 3. Optimize Routes (Optional)
Reorder the buildings in a generated chunk into an efficient visiting sequence for your field team. 

```bash
python optimize_route.py chunks/candidate_buildings_001.kmz routes/candidate_buildings_001_route.kmz --start-lat <LAT> --start-lon <LON> --ors-api-key <YOUR_ORS_API_KEY>
```