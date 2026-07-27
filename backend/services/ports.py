"""Nearest-seaport lookup.

A curated, globally-distributed list of major seaports (name, country,
coordinates). Pure local computation — no network call, no external API
dependency, so it works even when the reverse-geocoding provider is down.
"""

from __future__ import annotations

from dataclasses import dataclass
from math import asin, cos, radians, sin, sqrt
from typing import Any

EARTH_RADIUS_KM = 6371.0088


@dataclass(frozen=True)
class Port:
    name: str
    country: str
    latitude: float
    longitude: float


# name, country, latitude, longitude
_RAW_PORTS: list[tuple[str, str, float, float]] = [
    # North America — Pacific
    ("Los Angeles", "United States", 33.729, -118.262),
    ("Long Beach", "United States", 33.754, -118.216),
    ("Oakland", "United States", 37.798, -122.277),
    ("San Francisco", "United States", 37.808, -122.418),
    ("San Diego", "United States", 32.715, -117.174),
    ("Seattle", "United States", 47.603, -122.336),
    ("Portland", "United States", 45.567, -122.767),
    ("Anchorage", "United States", 61.218, -149.887),
    ("Honolulu", "United States", 21.307, -157.867),
    ("Vancouver", "Canada", 49.286, -123.111),
    ("Prince Rupert", "Canada", 54.315, -130.320),
    ("Ensenada", "Mexico", 31.858, -116.626),
    ("Manzanillo", "Mexico", 19.053, -104.315),
    ("Lazaro Cardenas", "Mexico", 17.956, -102.196),
    # North America — Atlantic / Gulf
    ("New York/New Jersey", "United States", 40.668, -74.078),
    ("Savannah", "United States", 32.084, -81.098),
    ("Charleston", "United States", 32.784, -79.925),
    ("Norfolk", "United States", 36.847, -76.334),
    ("Jacksonville", "United States", 30.395, -81.559),
    ("Miami", "United States", 25.774, -80.169),
    ("Houston", "United States", 29.749, -95.089),
    ("New Orleans", "United States", 29.943, -90.075),
    ("Tampa", "United States", 27.943, -82.453),
    ("Halifax", "Canada", 44.647, -63.573),
    ("Montreal", "Canada", 45.548, -73.539),
    ("St. John's", "Canada", 47.561, -52.712),
    ("Nuuk", "Greenland", 64.175, -51.738),
    ("Reykjavik", "Iceland", 64.146, -21.942),
    # Caribbean / Central America
    ("Nassau", "Bahamas", 25.078, -77.338),
    ("Havana", "Cuba", 23.135, -82.383),
    ("Kingston", "Jamaica", 17.977, -76.793),
    ("San Juan", "Puerto Rico", 18.466, -66.106),
    ("Santo Domingo", "Dominican Republic", 18.483, -69.887),
    ("Willemstad", "Curacao", 12.108, -68.933),
    ("Balboa", "Panama", 8.955, -79.567),
    ("Colon", "Panama", 9.359, -79.900),
    # South America — Pacific
    ("Buenaventura", "Colombia", 3.878, -77.019),
    ("Guayaquil", "Ecuador", -2.190, -79.887),
    ("Callao", "Peru", -12.056, -77.148),
    ("Arica", "Chile", -18.478, -70.323),
    ("Valparaiso", "Chile", -33.036, -71.627),
    ("San Antonio", "Chile", -33.593, -71.622),
    ("Puerto Montt", "Chile", -41.469, -72.942),
    ("Ushuaia", "Argentina", -54.807, -68.303),
    # South America — Atlantic
    ("Cartagena", "Colombia", 10.391, -75.479),
    ("Puerto Cabello", "Venezuela", 10.481, -68.017),
    ("La Guaira", "Venezuela", 10.606, -66.931),
    ("Georgetown", "Guyana", 6.804, -58.163),
    ("Paramaribo", "Suriname", 5.852, -55.203),
    ("Belem", "Brazil", -1.456, -48.504),
    ("Fortaleza", "Brazil", -3.717, -38.543),
    ("Recife", "Brazil", -8.053, -34.881),
    ("Salvador", "Brazil", -12.974, -38.512),
    ("Rio de Janeiro", "Brazil", -22.897, -43.180),
    ("Santos", "Brazil", -23.960, -46.333),
    ("Paranagua", "Brazil", -25.520, -48.509),
    ("Rio Grande", "Brazil", -32.035, -52.099),
    ("Montevideo", "Uruguay", -34.906, -56.212),
    ("Buenos Aires", "Argentina", -34.601, -58.368),
    ("Bahia Blanca", "Argentina", -38.719, -62.267),
    # Europe — Atlantic / North Sea / Baltic
    ("Rotterdam", "Netherlands", 51.925, 4.478),
    ("Antwerp", "Belgium", 51.260, 4.402),
    ("Hamburg", "Germany", 53.541, 9.994),
    ("Bremerhaven", "Germany", 53.539, 8.583),
    ("Le Havre", "France", 49.494, 0.107),
    ("Southampton", "United Kingdom", 50.909, -1.404),
    ("Felixstowe", "United Kingdom", 51.963, 1.351),
    ("London Gateway", "United Kingdom", 51.507, 0.481),
    ("Liverpool", "United Kingdom", 53.400, -2.992),
    ("Glasgow", "United Kingdom", 55.861, -4.251),
    ("Dublin", "Ireland", 53.347, -6.244),
    ("Cork", "Ireland", 51.898, -8.472),
    ("Lisbon", "Portugal", 38.708, -9.146),
    ("Sines", "Portugal", 37.956, -8.869),
    ("Bilbao", "Spain", 43.343, -3.020),
    ("Copenhagen", "Denmark", 55.676, 12.568),
    ("Aarhus", "Denmark", 56.150, 10.206),
    ("Gothenburg", "Sweden", 57.708, 11.974),
    ("Stockholm", "Sweden", 59.329, 18.068),
    ("Oslo", "Norway", 59.913, 10.752),
    ("Bergen", "Norway", 60.392, 5.324),
    ("Narvik", "Norway", 68.438, 17.427),
    ("Helsinki", "Finland", 60.167, 24.943),
    ("St. Petersburg", "Russia", 59.934, 30.335),
    ("Murmansk", "Russia", 68.970, 33.075),
    ("Riga", "Latvia", 56.949, 24.106),
    ("Klaipeda", "Lithuania", 55.706, 21.130),
    ("Tallinn", "Estonia", 59.437, 24.753),
    ("Gdansk", "Poland", 54.352, 18.646),
    # Europe — Mediterranean / Black Sea
    ("Barcelona", "Spain", 41.353, 2.163),
    ("Valencia", "Spain", 39.454, -0.328),
    ("Algeciras", "Spain", 36.133, -5.454),
    ("Marseille", "France", 43.298, 5.374),
    ("Genoa", "Italy", 44.407, 8.934),
    ("Naples", "Italy", 40.839, 14.253),
    ("Gioia Tauro", "Italy", 38.424, 15.898),
    ("Venice", "Italy", 45.440, 12.315),
    ("Piraeus", "Greece", 37.943, 23.637),
    ("Thessaloniki", "Greece", 40.633, 22.943),
    ("Istanbul", "Turkey", 41.008, 28.978),
    ("Izmir", "Turkey", 38.423, 27.143),
    ("Constanta", "Romania", 44.175, 28.638),
    ("Odessa", "Ukraine", 46.485, 30.743),
    ("Novorossiysk", "Russia", 44.723, 37.768),
    # Africa
    ("Casablanca", "Morocco", 33.607, -7.617),
    ("Tangier", "Morocco", 35.777, -5.803),
    ("Algiers", "Algeria", 36.775, 3.060),
    ("Tunis", "Tunisia", 36.806, 10.183),
    ("Alexandria", "Egypt", 31.200, 29.918),
    ("Port Said", "Egypt", 31.257, 32.284),
    ("Suez", "Egypt", 29.974, 32.553),
    ("Dakar", "Senegal", 14.693, -17.447),
    ("Freetown", "Sierra Leone", 8.484, -13.234),
    ("Monrovia", "Liberia", 6.316, -10.802),
    ("Abidjan", "Ivory Coast", 5.267, -4.017),
    ("Tema", "Ghana", 5.667, -0.017),
    ("Lagos", "Nigeria", 6.455, 3.394),
    ("Douala", "Cameroon", 4.049, 9.700),
    ("Libreville", "Gabon", 0.392, 9.454),
    ("Luanda", "Angola", -8.813, 13.234),
    ("Walvis Bay", "Namibia", -22.958, 14.505),
    ("Cape Town", "South Africa", -33.902, 18.423),
    ("Port Elizabeth", "South Africa", -33.958, 25.612),
    ("Durban", "South Africa", -29.868, 31.030),
    ("Maputo", "Mozambique", -25.966, 32.583),
    ("Toamasina", "Madagascar", -18.149, 49.404),
    ("Port Louis", "Mauritius", -20.160, 57.497),
    ("Dar es Salaam", "Tanzania", -6.816, 39.293),
    ("Mombasa", "Kenya", -4.043, 39.658),
    ("Djibouti City", "Djibouti", 11.595, 43.148),
    # Middle East / South Asia
    ("Jeddah", "Saudi Arabia", 21.485, 39.187),
    ("Dammam", "Saudi Arabia", 26.437, 50.103),
    ("Kuwait City", "Kuwait", 29.376, 47.978),
    ("Doha", "Qatar", 25.286, 51.531),
    ("Abu Dhabi", "United Arab Emirates", 24.467, 54.367),
    ("Jebel Ali", "United Arab Emirates", 25.011, 55.061),
    ("Bandar Abbas", "Iran", 27.186, 56.278),
    ("Gwadar", "Pakistan", 25.126, 62.325),
    ("Karachi", "Pakistan", 24.851, 66.990),
    ("Kandla", "India", 23.033, 70.222),
    ("Mumbai", "India", 18.949, 72.951),
    ("Cochin", "India", 9.966, 76.267),
    ("Chennai", "India", 13.100, 80.298),
    ("Visakhapatnam", "India", 17.686, 83.288),
    ("Kolkata", "India", 22.545, 88.343),
    ("Colombo", "Sri Lanka", 6.933, 79.844),
    ("Male", "Maldives", 4.175, 73.509),
    ("Chittagong", "Bangladesh", 22.335, 91.834),
    # Southeast Asia
    ("Singapore", "Singapore", 1.264, 103.822),
    ("Port Klang", "Malaysia", 3.000, 101.400),
    ("Penang", "Malaysia", 5.412, 100.362),
    ("Jakarta", "Indonesia", -6.104, 106.881),
    ("Surabaya", "Indonesia", -7.211, 112.734),
    ("Laem Chabang", "Thailand", 13.081, 100.883),
    ("Ho Chi Minh City", "Vietnam", 10.775, 106.700),
    ("Haiphong", "Vietnam", 20.865, 106.683),
    ("Manila", "Philippines", 14.583, 120.967),
    ("Cebu", "Philippines", 10.307, 123.906),
    # East Asia
    ("Hong Kong", "China", 22.285, 114.158),
    ("Shenzhen", "China", 22.573, 114.267),
    ("Guangzhou", "China", 23.098, 113.259),
    ("Xiamen", "China", 24.479, 118.082),
    ("Shanghai", "China", 31.230, 121.474),
    ("Ningbo-Zhoushan", "China", 29.868, 121.544),
    ("Qingdao", "China", 36.067, 120.383),
    ("Tianjin", "China", 39.104, 117.200),
    ("Dalian", "China", 38.914, 121.615),
    ("Kaohsiung", "Taiwan", 22.613, 120.283),
    ("Keelung", "Taiwan", 25.130, 121.740),
    ("Busan", "South Korea", 35.180, 129.075),
    ("Incheon", "South Korea", 37.456, 126.705),
    ("Tokyo", "Japan", 35.652, 139.839),
    ("Yokohama", "Japan", 35.444, 139.638),
    ("Nagoya", "Japan", 35.083, 136.883),
    ("Osaka", "Japan", 34.652, 135.430),
    ("Kobe", "Japan", 34.690, 135.196),
    ("Naha", "Japan", 26.213, 127.680),
    ("Vladivostok", "Russia", 43.117, 131.885),
    # Oceania
    ("Darwin", "Australia", -12.466, 130.842),
    ("Fremantle", "Australia", -32.056, 115.741),
    ("Adelaide", "Australia", -34.856, 138.500),
    ("Melbourne", "Australia", -37.840, 144.945),
    ("Sydney", "Australia", -33.852, 151.211),
    ("Brisbane", "Australia", -27.365, 153.171),
    ("Auckland", "New Zealand", -36.844, 174.766),
    ("Wellington", "New Zealand", -41.288, 174.777),
    ("Suva", "Fiji", -18.142, 178.442),
    ("Noumea", "New Caledonia", -22.276, 166.458),
    ("Port Moresby", "Papua New Guinea", -9.478, 147.150),
    ("Apia", "Samoa", -13.833, -171.767),
    ("Papeete", "French Polynesia", -17.535, -149.569),
]

PORTS: list[Port] = [Port(name, country, lat, lon) for name, country, lat, lon in _RAW_PORTS]


def _haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    phi1, phi2 = radians(lat1), radians(lat2)
    dphi = radians(lat2 - lat1)
    dlambda = radians(lon2 - lon1)
    a = sin(dphi / 2) ** 2 + cos(phi1) * cos(phi2) * sin(dlambda / 2) ** 2
    return 2 * EARTH_RADIUS_KM * asin(sqrt(a))


def find_nearest_port(latitude: float, longitude: float) -> dict[str, Any]:
    nearest = min(
        PORTS,
        key=lambda p: _haversine_km(latitude, longitude, p.latitude, p.longitude),
    )
    distance_km = _haversine_km(latitude, longitude, nearest.latitude, nearest.longitude)
    return {
        "name": nearest.name,
        "country": nearest.country,
        "distance_km": round(distance_km, 1),
    }
