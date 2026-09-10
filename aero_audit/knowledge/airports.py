"""North American airports (major and busy regionals) with coordinates and field elevation.

Coordinates are airport reference points to ~0.01 degree; good enough for 'nearest airport
within 40 nm' logic, not for surveying. `major` marks the airports whose METARs are fetched by
default in nationwide live mode.
"""

from __future__ import annotations

import math
from dataclasses import dataclass


@dataclass(frozen=True)
class Airport:
    icao: str
    iata: str
    name: str
    city: str
    country: str
    lat: float
    lon: float
    elev_ft: int
    major: bool = False


_ROWS = [
    # icao, iata, name, city, country, lat, lon, elev, major
    ("KATL", "ATL", "Hartsfield-Jackson Atlanta", "Atlanta", "US", 33.6407, -84.4277, 1026, True),
    ("KLAX", "LAX", "Los Angeles", "Los Angeles", "US", 33.9416, -118.4085, 125, True),
    ("KORD", "ORD", "Chicago O'Hare", "Chicago", "US", 41.9742, -87.9073, 672, True),
    ("KDFW", "DFW", "Dallas/Fort Worth", "Dallas", "US", 32.8998, -97.0403, 607, True),
    ("KDEN", "DEN", "Denver", "Denver", "US", 39.8561, -104.6737, 5434, True),
    ("KJFK", "JFK", "New York JFK", "New York", "US", 40.6413, -73.7781, 13, True),
    ("KSFO", "SFO", "San Francisco", "San Francisco", "US", 37.6213, -122.3790, 13, True),
    ("KSEA", "SEA", "Seattle-Tacoma", "Seattle", "US", 47.4502, -122.3088, 433, True),
    ("KLAS", "LAS", "Las Vegas Harry Reid", "Las Vegas", "US", 36.0840, -115.1537, 2181, True),
    ("KMCO", "MCO", "Orlando", "Orlando", "US", 28.4312, -81.3081, 96, True),
    ("KEWR", "EWR", "Newark Liberty", "Newark", "US", 40.6895, -74.1745, 18, True),
    ("KCLT", "CLT", "Charlotte Douglas", "Charlotte", "US", 35.2140, -80.9431, 748, True),
    ("KPHX", "PHX", "Phoenix Sky Harbor", "Phoenix", "US", 33.4373, -112.0078, 1135, True),
    ("KIAH", "IAH", "Houston Bush", "Houston", "US", 29.9902, -95.3368, 97, True),
    ("KMIA", "MIA", "Miami", "Miami", "US", 25.7959, -80.2870, 8, True),
    ("KBOS", "BOS", "Boston Logan", "Boston", "US", 42.3656, -71.0096, 20, True),
    ("KMSP", "MSP", "Minneapolis-St Paul", "Minneapolis", "US", 44.8848, -93.2223, 841, True),
    ("KFLL", "FLL", "Fort Lauderdale", "Fort Lauderdale", "US", 26.0742, -80.1506, 9, True),
    ("KDTW", "DTW", "Detroit Metro", "Detroit", "US", 42.2124, -83.3534, 645, True),
    ("KPHL", "PHL", "Philadelphia", "Philadelphia", "US", 39.8729, -75.2437, 36, True),
    ("KLGA", "LGA", "New York LaGuardia", "New York", "US", 40.7769, -73.8740, 21, True),
    ("KBWI", "BWI", "Baltimore/Washington", "Baltimore", "US", 39.1774, -76.6684, 146, True),
    ("KSLC", "SLC", "Salt Lake City", "Salt Lake City", "US", 40.7899, -111.9791, 4227, True),
    ("KDCA", "DCA", "Washington Reagan", "Washington", "US", 38.8512, -77.0402, 15, True),
    ("KIAD", "IAD", "Washington Dulles", "Washington", "US", 38.9531, -77.4565, 313, True),
    ("KSAN", "SAN", "San Diego", "San Diego", "US", 32.7338, -117.1933, 17, True),
    ("KTPA", "TPA", "Tampa", "Tampa", "US", 27.9755, -82.5332, 26, True),
    ("KAUS", "AUS", "Austin-Bergstrom", "Austin", "US", 30.1975, -97.6664, 542, True),
    ("KBNA", "BNA", "Nashville", "Nashville", "US", 36.1263, -86.6774, 599, True),
    ("KMDW", "MDW", "Chicago Midway", "Chicago", "US", 41.7868, -87.7522, 620, False),
    ("KDAL", "DAL", "Dallas Love Field", "Dallas", "US", 32.8471, -96.8518, 487, False),
    ("KPDX", "PDX", "Portland", "Portland", "US", 45.5898, -122.5951, 31, False),
    ("KSTL", "STL", "St. Louis Lambert", "St. Louis", "US", 38.7487, -90.3700, 618, False),
    ("KHOU", "HOU", "Houston Hobby", "Houston", "US", 29.6454, -95.2789, 46, False),
    ("KRDU", "RDU", "Raleigh-Durham", "Raleigh", "US", 35.8776, -78.7875, 435, False),
    ("KOAK", "OAK", "Oakland", "Oakland", "US", 37.7213, -122.2208, 9, False),
    ("KSMF", "SMF", "Sacramento", "Sacramento", "US", 38.6954, -121.5908, 27, False),
    ("KSJC", "SJC", "San Jose", "San Jose", "US", 37.3639, -121.9289, 62, False),
    ("KMCI", "MCI", "Kansas City", "Kansas City", "US", 39.2976, -94.7139, 1026, False),
    ("KSNA", "SNA", "John Wayne Orange County", "Santa Ana", "US", 33.6757, -117.8682, 56, False),
    ("KMSY", "MSY", "New Orleans", "New Orleans", "US", 29.9934, -90.2580, 4, False),
    ("KSAT", "SAT", "San Antonio", "San Antonio", "US", 29.5337, -98.4698, 809, False),
    ("KRSW", "RSW", "Southwest Florida", "Fort Myers", "US", 26.5362, -81.7552, 30, False),
    ("KIND", "IND", "Indianapolis", "Indianapolis", "US", 39.7173, -86.2944, 797, False),
    ("KPIT", "PIT", "Pittsburgh", "Pittsburgh", "US", 40.4915, -80.2329, 1203, False),
    ("KCLE", "CLE", "Cleveland Hopkins", "Cleveland", "US", 41.4117, -81.8498, 791, False),
    ("KCMH", "CMH", "Columbus", "Columbus", "US", 39.9980, -82.8919, 815, False),
    ("KCVG", "CVG", "Cincinnati/Northern Kentucky", "Cincinnati", "US", 39.0488, -84.6678, 896, False),
    ("KMKE", "MKE", "Milwaukee Mitchell", "Milwaukee", "US", 42.9472, -87.8966, 723, False),
    ("KJAX", "JAX", "Jacksonville", "Jacksonville", "US", 30.4941, -81.6879, 30, False),
    ("KPBI", "PBI", "Palm Beach", "West Palm Beach", "US", 26.6832, -80.0956, 19, False),
    ("KBUF", "BUF", "Buffalo Niagara", "Buffalo", "US", 42.9405, -78.7322, 728, False),
    ("KABQ", "ABQ", "Albuquerque Sunport", "Albuquerque", "US", 35.0402, -106.6090, 5355, False),
    ("KOMA", "OMA", "Omaha Eppley", "Omaha", "US", 41.3032, -95.8941, 984, False),
    ("KOKC", "OKC", "Oklahoma City Will Rogers", "Oklahoma City", "US", 35.3931, -97.6007, 1395, False),
    ("KTUL", "TUL", "Tulsa", "Tulsa", "US", 36.1984, -95.8881, 677, False),
    ("KMEM", "MEM", "Memphis", "Memphis", "US", 35.0424, -89.9767, 341, True),
    ("KSDF", "SDF", "Louisville Muhammad Ali", "Louisville", "US", 38.1744, -85.7360, 501, True),
    ("KANC", "ANC", "Anchorage Ted Stevens", "Anchorage", "US", 61.1743, -149.9962, 152, False),
    ("KHNL", "HNL", "Honolulu", "Honolulu", "US", 21.3187, -157.9225, 13, False),
    ("KBDL", "BDL", "Bradley", "Hartford", "US", 41.9389, -72.6832, 173, False),
    ("KPVD", "PVD", "Providence", "Providence", "US", 41.7240, -71.4283, 55, False),
    ("KRIC", "RIC", "Richmond", "Richmond", "US", 37.5052, -77.3197, 167, False),
    ("KORF", "ORF", "Norfolk", "Norfolk", "US", 36.8946, -76.2012, 27, False),
    ("KBHM", "BHM", "Birmingham", "Birmingham", "US", 33.5629, -86.7535, 650, False),
    ("KELP", "ELP", "El Paso", "El Paso", "US", 31.8072, -106.3776, 3959, False),
    ("KTUS", "TUS", "Tucson", "Tucson", "US", 32.1161, -110.9410, 2643, False),
    ("KRNO", "RNO", "Reno-Tahoe", "Reno", "US", 39.4991, -119.7681, 4415, False),
    ("KBOI", "BOI", "Boise", "Boise", "US", 43.5644, -116.2228, 2871, False),
    ("KGEG", "GEG", "Spokane", "Spokane", "US", 47.6199, -117.5339, 2385, False),
    ("KDSM", "DSM", "Des Moines", "Des Moines", "US", 41.5340, -93.6631, 958, False),
    ("KLIT", "LIT", "Little Rock", "Little Rock", "US", 34.7294, -92.2243, 262, False),
    ("KGSO", "GSO", "Piedmont Triad", "Greensboro", "US", 36.0978, -79.9373, 926, False),
    ("KSAV", "SAV", "Savannah/Hilton Head", "Savannah", "US", 32.1276, -81.2021, 51, False),
    ("KCHS", "CHS", "Charleston", "Charleston", "US", 32.8986, -80.0405, 46, False),
    ("KMYR", "MYR", "Myrtle Beach", "Myrtle Beach", "US", 33.6797, -78.9283, 25, False),
    ("KGRR", "GRR", "Gerald R. Ford", "Grand Rapids", "US", 42.8808, -85.5228, 794, False),
    ("KMSN", "MSN", "Dane County", "Madison", "US", 43.1399, -89.3375, 887, False),
    ("KSYR", "SYR", "Syracuse Hancock", "Syracuse", "US", 43.1112, -76.1063, 421, False),
    ("KALB", "ALB", "Albany", "Albany", "US", 42.7483, -73.8017, 285, False),
    ("KTEB", "TEB", "Teterboro", "Teterboro", "US", 40.8501, -74.0608, 9, False),
    ("KHPN", "HPN", "Westchester County", "White Plains", "US", 41.0670, -73.7076, 439, False),
    ("KVNY", "VNY", "Van Nuys", "Los Angeles", "US", 34.2098, -118.4900, 802, False),
    ("KAPA", "APA", "Centennial", "Denver", "US", 39.5701, -104.8493, 5885, False),
    ("KSDL", "SDL", "Scottsdale", "Scottsdale", "US", 33.6229, -111.9105, 1510, False),
    ("KPWK", "PWK", "Chicago Executive", "Wheeling", "US", 42.1142, -87.9015, 647, False),
    ("KBUR", "BUR", "Hollywood Burbank", "Burbank", "US", 34.2007, -118.3587, 778, False),
    ("KONT", "ONT", "Ontario", "Ontario", "US", 34.0560, -117.6012, 944, False),
    ("KLGB", "LGB", "Long Beach", "Long Beach", "US", 33.8177, -118.1516, 60, False),
    ("KSFB", "SFB", "Orlando Sanford", "Sanford", "US", 28.7776, -81.2375, 55, False),
    ("KPIE", "PIE", "St. Pete-Clearwater", "St. Petersburg", "US", 27.9102, -82.6874, 11, False),
    ("KBZN", "BZN", "Bozeman Yellowstone", "Bozeman", "US", 45.7772, -111.1530, 4473, False),
    ("KFAT", "FAT", "Fresno Yosemite", "Fresno", "US", 36.7762, -119.7181, 336, False),
    ("KCOS", "COS", "Colorado Springs", "Colorado Springs", "US", 38.8058, -104.7008, 6187, False),
    ("KICT", "ICT", "Wichita Eisenhower", "Wichita", "US", 37.6499, -97.4331, 1333, False),
    ("KMHT", "MHT", "Manchester-Boston", "Manchester", "US", 42.9326, -71.4357, 266, False),
    ("KPWM", "PWM", "Portland Jetport", "Portland", "US", 43.6462, -70.3093, 76, False),
    ("KBTV", "BTV", "Burlington", "Burlington", "US", 44.4720, -73.1533, 335, False),
    ("KFAR", "FAR", "Hector", "Fargo", "US", 46.9207, -96.8158, 902, False),
    ("KSUX", "SUX", "Sioux Gateway", "Sioux City", "US", 42.4026, -96.3844, 1098, False),
    ("KBIL", "BIL", "Billings Logan", "Billings", "US", 45.8077, -108.5429, 3652, False),
    ("CYYZ", "YYZ", "Toronto Pearson", "Toronto", "CA", 43.6777, -79.6248, 569, True),
    ("CYVR", "YVR", "Vancouver", "Vancouver", "CA", 49.1947, -123.1792, 14, True),
    ("CYUL", "YUL", "Montreal-Trudeau", "Montreal", "CA", 45.4706, -73.7408, 118, True),
    ("CYYC", "YYC", "Calgary", "Calgary", "CA", 51.1215, -114.0076, 3557, True),
    ("CYEG", "YEG", "Edmonton", "Edmonton", "CA", 53.3097, -113.5797, 2373, False),
    ("CYOW", "YOW", "Ottawa Macdonald-Cartier", "Ottawa", "CA", 45.3225, -75.6692, 374, False),
    ("CYWG", "YWG", "Winnipeg Richardson", "Winnipeg", "CA", 49.9100, -97.2399, 783, False),
    ("CYHZ", "YHZ", "Halifax Stanfield", "Halifax", "CA", 44.8808, -63.5086, 477, False),
    ("CYQB", "YQB", "Quebec City Jean Lesage", "Quebec", "CA", 46.7911, -71.3933, 244, False),
    ("CYYJ", "YYJ", "Victoria", "Victoria", "CA", 48.6469, -123.4259, 63, False),
    ("CYTZ", "YTZ", "Billy Bishop Toronto City", "Toronto", "CA", 43.6275, -79.3962, 252, False),
    ("MMMX", "MEX", "Mexico City Benito Juarez", "Mexico City", "MX", 19.4363, -99.0721, 7316, True),
    ("MMUN", "CUN", "Cancun", "Cancun", "MX", 21.0365, -86.8771, 22, True),
    ("MMGL", "GDL", "Guadalajara", "Guadalajara", "MX", 20.5218, -103.3111, 5016, False),
    ("MMMY", "MTY", "Monterrey", "Monterrey", "MX", 25.7785, -100.1069, 1278, False),
    ("MMTJ", "TIJ", "Tijuana", "Tijuana", "MX", 32.5411, -116.9702, 489, False),
    ("MMSD", "SJD", "Los Cabos", "San Jose del Cabo", "MX", 23.1518, -109.7211, 374, False),
    ("MMPR", "PVR", "Puerto Vallarta", "Puerto Vallarta", "MX", 20.6801, -105.2544, 23, False),
    ("MMHO", "HMO", "Hermosillo", "Hermosillo", "MX", 29.0959, -111.0480, 627, False),
    ("NMMX", "NLU", "Felipe Angeles", "Mexico City", "MX", 19.7369, -99.0148, 7369, False),
    ("TJSJ", "SJU", "San Juan Luis Munoz Marin", "San Juan", "PR", 18.4394, -66.0018, 9, False),
    ("MYNN", "NAS", "Lynden Pindling", "Nassau", "BS", 25.0390, -77.4662, 16, False),
    ("MKJP", "KIN", "Norman Manley", "Kingston", "JM", 17.9357, -76.7875, 10, False),
    ("MKJS", "MBJ", "Sangster", "Montego Bay", "JM", 18.5037, -77.9134, 4, False),
    ("MPTO", "PTY", "Tocumen", "Panama City", "PA", 9.0714, -79.3835, 135, False),
    ("MUHA", "HAV", "Jose Marti", "Havana", "CU", 22.9892, -82.4091, 210, False),
    ("TNCM", "SXM", "Princess Juliana", "St Maarten", "SX", 18.0410, -63.1089, 14, False),
    ("MDSD", "SDQ", "Las Americas", "Santo Domingo", "DO", 18.4297, -69.6689, 59, False),
    ("MDPC", "PUJ", "Punta Cana", "Punta Cana", "DO", 18.5674, -68.3634, 47, False),
    ("MGGT", "GUA", "La Aurora", "Guatemala City", "GT", 14.5833, -90.5275, 4952, False),
    ("MROC", "SJO", "Juan Santamaria", "San Jose", "CR", 9.9981, -84.2041, 3021, False),
]

AIRPORTS: dict[str, Airport] = {r[0]: Airport(*r) for r in _ROWS}
BY_IATA: dict[str, Airport] = {a.iata: a for a in AIRPORTS.values()}
MAJOR: list[Airport] = [a for a in AIRPORTS.values() if a.major]

_CELL = 1.0  # degrees; a 40 nm search never needs more than the 3x3 neighbourhood
_GRID: dict[tuple[int, int], list[Airport]] = {}
for _a in AIRPORTS.values():
    _GRID.setdefault((int(_a.lat // _CELL), int(_a.lon // _CELL)), []).append(_a)


def _nm(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    p1, p2 = math.radians(lat1), math.radians(lat2)
    a = math.sin((p2 - p1) / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(math.radians(lon2 - lon1) / 2) ** 2
    return 2 * 3440.065 * math.asin(math.sqrt(a))


def nearest_airport(lat: float, lon: float, max_nm: float = 40.0) -> tuple[Airport, float] | None:
    cx, cy = int(lat // _CELL), int(lon // _CELL)
    best: tuple[Airport, float] | None = None
    for dx in (-1, 0, 1):
        for dy in (-1, 0, 1):
            for a in _GRID.get((cx + dx, cy + dy), ()):
                d = _nm(lat, lon, a.lat, a.lon)
                if d <= max_nm and (best is None or d < best[1]):
                    best = (a, d)
    return best
