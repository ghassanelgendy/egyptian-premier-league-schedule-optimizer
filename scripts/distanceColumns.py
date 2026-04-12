import pandas as pd
from itertools import permutations

# 1. Define Stadiums and their "Routing Hubs"
# We map each stadium to a major City Hub to calculate road distance.
stadiums = {
    'BANI_SWEIF': {'name': 'Bani Sweif Stadium', 'hub': 'BENI_SWEIF'},
    '30_JUNE': {'name': '30 June Stadium', 'hub': 'CAIRO_EAST'}, # New Cairo
    'ARMY_SUEZ_ST': {'name': 'Egyptian Army Stadium', 'hub': 'SUEZ'},
    'FAYOUM': {'name': 'Fayoum Stadium', 'hub': 'FAYOUM'},
    'ISMAILIA_ST': {'name': 'Ismailia Stadium', 'hub': 'ISMAILIA'},
    'HARAS': {'name': 'Haras El-Hodoud Stadium', 'hub': 'ALEXANDRIA'},
    'MIL_ACAD': {'name': 'Cairo Military Academy Stadium', 'hub': 'CAIRO_EAST'},
    'PETRO_SPORT': {'name': 'Petro Sport Stadium', 'hub': 'CAIRO_EAST'},
    'AL_SALAM': {'name': 'Al-Salam Stadium', 'hub': 'CAIRO_EAST'},
    'SUEZ_CANAL': {'name': 'Suez Canal Stadium', 'hub': 'ISMAILIA'},
    'MANSOURA': {'name': 'El Mansoura Stadium', 'hub': 'MANSOURA'},
    'EL_GOUNA': {'name': 'Khaled Bichara Stadium', 'hub': 'EL_GOUNA'},
    'CAIRO_INTL': {'name': 'Cairo International Stadium', 'hub': 'CAIRO_CENTER'},
    'MISR': {'name': 'Misr Stadium', 'hub': 'NEW_CAPITAL'},
    'BORG_ARAB': {'name': 'Borg El-Arab Stadium', 'hub': 'BORG_ARAB'},
    'MAHALLA': {'name': 'Ghazl El-Mahalla Stadium', 'hub': 'MAHALLA'},
    'ASWAN': {'name': 'Aswan Stadium', 'hub': 'ASWAN'},
    'SUEZ_ST': {'name': 'Suez Stadium', 'hub': 'SUEZ'},
    'ARAB_CONT': {'name': 'Arab Contractors Stadium', 'hub': 'CAIRO_CENTER'},
    'MASRY': {'name': 'Al Masry Club Stadium', 'hub': 'PORT_SAID'},
    'ALEX_STADIUM': {'name': 'Alexandria Stadium', 'hub': 'ALEXANDRIA'},
    'GEHAZ_REYADA': {'name': 'Gehaz Elreyada Stadium', 'hub': 'CAIRO_EAST'}
}

# 2. Define Base Road Distances from CAIRO (Center) in KM
# These are approximate driving distances from Tahrir/Central Cairo.
dist_from_cairo = {
    'CAIRO_CENTER': 0,
    'CAIRO_EAST': 25,       # Nasr City/New Cairo area
    'NEW_CAPITAL': 55,
    'ALEXANDRIA': 220,
    'BORG_ARAB': 180,       # Via Desert Road (closer to Cairo than Alex city)
    'PORT_SAID': 190,
    'ISMAILIA': 120,
    'SUEZ': 135,
    'FAYOUM': 105,
    'BENI_SWEIF': 125,
    'MANSOURA': 130,
    'MAHALLA': 115,
    'ASWAN': 880,
    'EL_GOUNA': 450
}

# 3. Define Special Direct Routes (Non-Cairo transits)
# This fixes the "Cairo Detour" issue. If a direct road exists, we use it.
direct_routes = {
    # Canal Zone Line
    frozenset(['PORT_SAID', 'ISMAILIA']): 80,
    frozenset(['ISMAILIA', 'SUEZ']): 90,
    frozenset(['PORT_SAID', 'SUEZ']): 170, # Sum of above approx
    
    # Coastal / Delta
    frozenset(['ALEXANDRIA', 'BORG_ARAB']): 55,
    frozenset(['ALEXANDRIA', 'PORT_SAID']): 260, # Coastal Road
    frozenset(['ALEXANDRIA', 'MANSOURA']): 160,
    frozenset(['ALEXANDRIA', 'MAHALLA']): 130,
    frozenset(['MANSOURA', 'MAHALLA']): 25,      # Very close
    frozenset(['MANSOURA', 'PORT_SAID']): 100,   # Via Damietta approx
    
    # Upper Egypt Line (Relative to each other)
    frozenset(['BENI_SWEIF', 'FAYOUM']): 40,     # Across the bridge
    frozenset(['BENI_SWEIF', 'ASWAN']): 755,     # 880 - 125
}

def get_driving_distance(hub1, hub2):
    if hub1 == hub2:
        return 0 # Same city/area
    
    # Check explicit direct routes first
    pair = frozenset([hub1, hub2])
    if pair in direct_routes:
        return direct_routes[pair]
    
    # Check Upper Egypt Line Logic (if both are south of Cairo)
    upper_egypt = ['FAYOUM', 'BENI_SWEIF', 'ASWAN']
    if hub1 in upper_egypt and hub2 in upper_egypt:
        # Simple subtraction of distance from Cairo roughly works for the Valley road
        return abs(dist_from_cairo[hub1] - dist_from_cairo[hub2])

    # Default: Route via Cairo
    # Distance = Distance(A to Cairo) + Distance(B to Cairo)
    # We subtract a small "ring road efficiency" factor (20km) if passing through
    dist = dist_from_cairo[hub1] + dist_from_cairo[hub2]
    return max(dist - 10, 0) 

# 4. Generate Combinations
data = []
for id1, id2 in permutations(stadiums.keys(), 2):
    hub1 = stadiums[id1]['hub']
    hub2 = stadiums[id2]['hub']
    
    km = get_driving_distance(hub1, hub2)
    
    # Add small intra-city travel if hubs are same but stadiums different
    # e.g. Cairo International to 30 June is not 0km, it's about 15km
    if hub1 == hub2 and id1 != id2:
        km = 15 
        
    data.append({
        'Stadium_ID_Origin': id1,
        'Stadium_ID_Destination': id2,
        'Distance_KM_Road': km
    })

# 5. Export
df = pd.DataFrame(data)
df.to_excel('Stadium_Road_Distances.xlsx', index=False)
print("File generated successfully.")