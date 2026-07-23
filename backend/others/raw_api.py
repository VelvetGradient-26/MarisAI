from fastapi import FastAPI
import requests

from copernicusmarine import subset

app = FastAPI()

@app.get("/")
def landing_page(): 
    return "This is the landing page"

@app.get("/weather")
async def fetch_weather(): 
    # New York
    lat = 40.7128
    lon = -74.0060

    url = f"https://api.weather.gov/points/{lat},{lon}"

    response = requests.get(url)
    return response.json()

@app.get("/marine_data_open_meteo")
async def fetch_marine_data_from_open_meteo(): 
    url = (
        "https://marine-api.open-meteo.com/v1/marine"
        "?latitude=13.08"
        "&longitude=80.27"
        "&hourly=wave_height,sea_surface_temperature"
    )

    response = requests.get(url)
    return response.json()

@app.get("/NOAA_buoy_data")
async def fetch_marine_data_from_noaa_buoy(): 
    url = "https://www.ndbc.noaa.gov/data/realtime2/46042.txt"

    response = requests.get(url)
    return response.text

@app.get("/NASA_Earth_Data")
async def fetch_data_from_nasa(): 
    headers = {
        "Authorization": "Bearer YOUR_TOKEN"
    }

    url = "YOUR_DATASET_URL"

    response = requests.get(url, headers=headers)
    return "Authorization/Login Needed; Work in Progress"

@app.get("/GBIF")
async def fetch_data_from_gbif(): 
    url = (
        "https://api.gbif.org/v1/occurrence/search"
        "?marine=true"
        "&limit=10"
    )
    response = requests.get(url)
    return response.json()

@app.get("/OBIS")
async def fetch_marine_data_from_obis(): 
    url = (
        "https://api.obis.org/v3/occurrence"
        "?size=10"
    )    
    response = requests.get(url)
    return response.json()

@app.get("/fishing_data")
async def fetch_fishing_data_from_global_fishing_watch(): 
    return "Endpoints require registration/API access"

@app.get("/bird_migration")
async def fetch_bird_migration_data(): 
    headers = {
            "X-eBirdApiToken": "YOUR_KEY"
    }

    url = "https://api.ebird.org/v2/data/obs/IN/recent"
    response = requests.get(url, headers=headers)
    return "API key needed"

@app.get("/earthquake_data")
async def fetch_earthquake_data_from_usgs(): 
    url = (
        "https://earthquake.usgs.gov/fdsnws/event/1/query"
        "?format=geojson"
    )

    response = requests.get(url)
    return response.json()
