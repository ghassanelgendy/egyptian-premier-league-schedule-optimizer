import pandas as pd
from itertools import permutations

# --- 1. CONFIGURATION (Same accurate logic as before) ---
stadiums = {
    'BANI_SWEIF': {'name': 'Bani Sweif Stadium', 'hub': 'BENI_SWEIF'},
    '30_JUNE': {'name': '30 June Stadium', 'hub': 'CAIRO_EAST'},
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

dist_from_cairo = {
    'CAIRO_CENTER': 0, 'CAIRO_EAST': 25, 'NEW_CAPITAL': 55,
    'ALEXANDRIA': 220, 'BORG_ARAB': 180, 'PORT_SAID': 190,
    'ISMAILIA': 120, 'SUEZ': 135, 'FAYOUM': 105,
    'BENI_SWEIF': 125, 'MANSOURA': 130, 'MAHALLA': 115,
    'ASWAN': 880, 'EL_GOUNA': 450
}

direct_routes = {
    frozenset(['PORT_SAID', 'ISMAILIA']): 80,
    frozenset(['ISMAILIA', 'SUEZ']): 90,
    frozenset(['PORT_SAID', 'SUEZ']): 170,
    frozenset(['ALEXANDRIA', 'BORG_ARAB']): 55,
    frozenset(['ALEXANDRIA', 'PORT_SAID']): 260,
    frozenset(['ALEXANDRIA', 'MANSOURA']): 160,
    frozenset(['ALEXANDRIA', 'MAHALLA']): 130,
    frozenset(['MANSOURA', 'MAHALLA']): 25,
    frozenset(['MANSOURA', 'PORT_SAID']): 100,
    frozenset(['BENI_SWEIF', 'FAYOUM']): 40,
    frozenset(['BENI_SWEIF', 'ASWAN']): 755,
}

def get_driving_distance(hub1, hub2):
    if hub1 == hub2: return 0
    pair = frozenset([hub1, hub2])
    if pair in direct_routes: return direct_routes[pair]
    upper_egypt = ['FAYOUM', 'BENI_SWEIF', 'ASWAN']
    if hub1 in upper_egypt and hub2 in upper_egypt:
        return abs(dist_from_cairo[hub1] - dist_from_cairo[hub2])
    dist = dist_from_cairo[hub1] + dist_from_cairo[hub2]
    return max(dist - 10, 0)

# --- 2. CALCULATE ---
data = []
# Use keys() twice to ensure we get a full square matrix (A->A, A->B, B->A)
for origin in stadiums.keys():
    for destination in stadiums.keys():
        hub1 = stadiums[origin]['hub']
        hub2 = stadiums[destination]['hub']
        
        km = get_driving_distance(hub1, hub2)
        
        # Intra-city buffer
        if hub1 == hub2 and origin != destination:
            km = 15
        elif origin == destination:
            km = 0
            
        data.append({
            'Origin': origin,
            'Destination': destination,
            'Distance': km
        })

# --- 3. PIVOT TO MATRIX ---
df = pd.DataFrame(data)

# This creates the matrix: Index=Origin, Columns=Destination, Values=Distance
matrix_df = df.pivot(index='Origin', columns='Destination', values='Distance')

# --- 4. EXPORT ---
matrix_df.to_excel('Stadium_Distance_Matrix.xlsx')
print("Matrix file generated successfully.")