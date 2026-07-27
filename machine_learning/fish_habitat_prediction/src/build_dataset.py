import os
import requests
import numpy as np
import pandas as pd
import xarray as xr
import copernicusmarine

# 1. CONFIGURATION: SPECIES LIST & BOUNDING BOX
SPECIES_LIST = [
    "Thunnus albacares",      # Yellowfin Tuna
    "Thunnus obesus",         # Bigeye Tuna
    "Katsuwonus pelamis",     # Skipjack Tuna
    "Xiphias gladius",        # Swordfish
    "Coryphaena hippurus",    # Mahi-mahi / Dolphinfish
    "Istiophorus platypterus" # Indo-Pacific Sailfish
]

# Indian Ocean Bounding Box
LAT_MIN, LAT_MAX = -45.0, 30.0
LON_MIN, LON_MAX = 20.0, 120.0

# Fixed: WKT polygon loop must explicitly close back at (LON_MIN, LAT_MIN)
INDIAN_OCEAN_WKT = (
    f"POLYGON(({LON_MIN} {LAT_MIN}, {LON_MAX} {LAT_MIN}, "
    f"{LON_MAX} {LAT_MAX}, {LON_MIN} {LAT_MAX}, {LON_MIN} {LAT_MIN}))"
)

MAX_RECORDS_PER_SPECIES = 2000  # Cap per species for manageable dataset size
OUTPUT_DIR = "./raw_data"
FINAL_CSV_PATH = "multi_species_habitat_dataset.csv"
os.makedirs(OUTPUT_DIR, exist_ok=True)

# 2. FETCH MULTI-SPECIES OCCURRENCES FROM OBIS
def fetch_all_species_occurrences(species_list, geometry_wkt, max_records_per_sp=2000):
    """Loops through species list and fetches presence records from OBIS API."""
    all_presence_records = []
    
    for species in species_list:
        print(f"Fetching OBIS records for: '{species}'...")
        url = "https://api.obis.org/v3/occurrence"
        params = {
            "scientificname": species,
            "geometry": geometry_wkt,
            "size": max_records_per_sp
        }
        
        try:
            response = requests.get(url, params=params, timeout=30)
            if response.status_code == 200:
                results = response.json().get("results", [])
                sp_records = []
                for row in results:
                    lat = row.get("decimalLatitude")
                    lon = row.get("decimalLongitude")
                    event_date = row.get("eventDate")
                    
                    if lat is not None and lon is not None and event_date:
                        # Extract YYYY-MM-DD from ISO strings safely
                        date_str = str(event_date).split("T")[0]
                        sp_records.append({
                            "scientific_name": species,
                            "latitude": float(lat),
                            "longitude": float(lon),
                            "observation_date": date_str,
                            "habitat_presence": 1
                        })
                print(f"  -> Fetched {len(sp_records)} records for {species}.")
                all_presence_records.extend(sp_records)
            else:
                print(f"  -> Warning: OBIS API status {response.status_code} for {species}")
        except Exception as e:
            print(f"  -> Error fetching {species}: {e}")

    if not all_presence_records:
        raise RuntimeError("No occurrence records were fetched from OBIS. Check network/WKT coordinates.")

    df = pd.DataFrame(all_presence_records)
    # Robust date conversion
    df["observation_date"] = pd.to_datetime(df["observation_date"], errors="coerce")
    df = df.dropna(subset=["observation_date"]).reset_index(drop=True)
    return df

# 3. GENERATE PSEUDO-ABSENCES PER SPECIES
def generate_multispecies_pseudo_absences(presence_df, ratio=1.2):
    """
    Generates background/pseudo-absence points per species.
    Uses ratio=1.2 to buffer for points landing on land that get dropped later.
    """
    print("\nGenerating pseudo-absences for each species...")
    combined_dfs = []
    
    for species, sp_df in presence_df.groupby("scientific_name"):
        num_absences = int(len(sp_df) * ratio)
        
        # Spatial sampling inside Indian Ocean bounds
        bg_lats = np.random.uniform(LAT_MIN, LAT_MAX, num_absences)
        bg_lons = np.random.uniform(LON_MIN, LON_MAX, num_absences)
        
        # Temporal sampling matching species date range
        min_date = sp_df["observation_date"].min()
        max_date = sp_df["observation_date"].max()
        date_range_days = max((max_date - min_date).days, 1)
        
        random_days = np.random.randint(0, date_range_days, num_absences)
        bg_dates = min_date + pd.to_timedelta(random_days, unit='D')
        
        bg_df = pd.DataFrame({
            "scientific_name": species,
            "latitude": bg_lats,
            "longitude": bg_lons,
            "observation_date": bg_dates,
            "habitat_presence": 0
        })
        
        combined_dfs.extend([sp_df, bg_df])
        print(f"  -> {species}: {len(sp_df)} presences + {num_absences} candidate pseudo-absences.")
        
    final_df = pd.concat(combined_dfs, ignore_index=True)
    return final_df.sample(frac=1.0, random_state=42).reset_index(drop=True)


# ==============================================================================
# 4. DOWNLOAD ENVIRONMENTAL DATA
# ==============================================================================
def download_copernicus_data(start_date, end_date):
    """Downloads physical and biogeochemical marine datasets from Copernicus."""
    print(f"\nDownloading environmental data from {start_date.strftime('%Y-%m-%d')} to {end_date.strftime('%Y-%m-%d')}...")
    
    phy_file = os.path.join(OUTPUT_DIR, "copernicus_physics.nc")
    if not os.path.exists(phy_file):
        print("  -> Subsetting Copernicus Physical Dataset...")
        copernicusmarine.subset(
            dataset_id="cmems_mod_glo_phy_my_0.083deg_P1D-m",
            variables=["thetao", "so", "uo", "vo"],
            minimum_latitude=LAT_MIN,
            maximum_latitude=LAT_MAX,
            minimum_longitude=LON_MIN,
            maximum_longitude=LON_MAX,
            start_datetime=f"{start_date.strftime('%Y-%m-%d')}T00:00:00",
            end_datetime=f"{end_date.strftime('%Y-%m-%d')}T23:59:59",
            minimum_depth=0.5,
            maximum_depth=1.0,
            output_filename=phy_file
        )

    bgc_file = os.path.join(OUTPUT_DIR, "copernicus_biogeo.nc")
    if not os.path.exists(bgc_file):
        print("  -> Subsetting Copernicus Biogeochemical Dataset...")
        copernicusmarine.subset(
            dataset_id="cmems_mod_glo_bgc_my_0.25deg_P1D-m",
            variables=["chl", "o2"],
            minimum_latitude=LAT_MIN,
            maximum_latitude=LAT_MAX,
            minimum_longitude=LON_MIN,
            maximum_longitude=LON_MAX,
            start_datetime=f"{start_date.strftime('%Y-%m-%d')}T00:00:00",
            end_datetime=f"{end_date.strftime('%Y-%m-%d')}T23:59:59",
            minimum_depth=0.5,
            maximum_depth=1.0,
            output_filename=bgc_file
        )

    return phy_file, bgc_file


def download_gebco_bathymetry():
    """Fetches GEBCO/ETOPO Bathymetry via NOAA ERDDAP."""
    bathymetry_file = os.path.join(OUTPUT_DIR, "gebco_bathymetry.nc")
    if not os.path.exists(bathymetry_file):
        print("\nDownloading Bathymetry data from NOAA ERDDAP...")
        erddap_url = (
            f"https://coastwatch.pfeg.noaa.gov/erddap/griddap/etopo180.nc?"
            f"altitude[({LAT_MIN}):1:({LAT_MAX})][({LON_MIN}):1:({LON_MAX})]"
        )
        response = requests.get(erddap_url, stream=True)
        if response.status_code == 200:
            with open(bathymetry_file, "wb") as f:
                for chunk in response.iter_content(chunk_size=1024 * 1024):
                    f.write(chunk)
            print("  -> Bathymetry download complete.")
        else:
            raise RuntimeError(f"Failed to fetch bathymetry: HTTP {response.status_code}")
            
    return bathymetry_file


# ==============================================================================
# 5. VECTORIZED MATCHING (ALL SPECIES AT ONCE)
# ==============================================================================
def enrich_dataset(df, phy_path, bgc_path, bathy_path):
    """Matches all species observations with environmental features using xarray indexing."""
    print("\nEnriching combined multi-species observations with environmental variables...")
    
    lat_arr = xr.DataArray(df["latitude"].values, dims="points")
    lon_arr = xr.DataArray(df["longitude"].values, dims="points")
    time_arr = xr.DataArray(df["observation_date"].values.astype("datetime64[ns]"), dims="points")

    # Physical oceanography
    with xr.open_dataset(phy_path) as ds_phy:
        phy_sub = ds_phy.sel(latitude=lat_arr, longitude=lon_arr, time=time_arr, method="nearest")
        df["sea_surface_temperature"] = np.squeeze(phy_sub["thetao"].values)
        df["salinity"] = np.squeeze(phy_sub["so"].values)
        df["current_u"] = np.squeeze(phy_sub["uo"].values)
        df["current_v"] = np.squeeze(phy_sub["vo"].values)

    # Biogeochemistry
    with xr.open_dataset(bgc_path) as ds_bgc:
        bgc_sub = ds_bgc.sel(latitude=lat_arr, longitude=lon_arr, time=time_arr, method="nearest")
        df["chlorophyll"] = np.squeeze(bgc_sub["chl"].values)
        df["dissolved_oxygen"] = np.squeeze(bgc_sub["o2"].values)

    # Bathymetry (2D spatial)
    with xr.open_dataset(bathy_path) as ds_bathy:
        bathy_sub = ds_bathy.sel(latitude=lat_arr, longitude=lon_arr, method="nearest")
        df["bathymetry"] = np.squeeze(bathy_sub["altitude"].values)

    return df

# 6. PIPELINE EXECUTION
def main():
    # 1. Fetch multi-species presence records
    presence_df = fetch_all_species_occurrences(SPECIES_LIST, INDIAN_OCEAN_WKT, MAX_RECORDS_PER_SPECIES)
    
    # 2. Add species-wise pseudo-absences
    df = generate_multispecies_pseudo_absences(presence_df, ratio=1.2)
    


    4589
    # 3. Fetch environmental NetCDF datasets across total date range
    start_date = df["observation_date"].min()
    end_date = df["observation_date"].max()
    
    phy_nc, bgc_nc = download_copernicus_data(start_date, end_date)
    bathy_nc = download_gebco_bathymetry()
    
    # 4. Enrich dataset with ocean variables
    df = enrich_dataset(df, phy_nc, bgc_nc, bathy_nc)
    
    # 5. Clean missing values (land points / missing satellite data) and export
    df = df.dropna().reset_index(drop=True)
    
    column_order = [
        "scientific_name",
        "latitude",
        "longitude",
        "observation_date",
        "habitat_presence",
        "sea_surface_temperature",
        "salinity",
        "current_u",
        "current_v",
        "chlorophyll",
        "dissolved_oxygen",
        "bathymetry"
    ]
    df = df[column_order]
    
    df.to_csv(FINAL_CSV_PATH, index=False)
    
    print("\n==================================================")
    print(f"Pipeline Complete! Saved multi-species dataset to '{FINAL_CSV_PATH}'")
    print(f"Total Cleaned Rows: {len(df)}")
    print("\nSpecies distribution in final dataset:")
    print(df.groupby(["scientific_name", "habitat_presence"]).size())
    print("==================================================")

if __name__ == "__main__":
    main()