"""
Geographic engine for LawNexa Advocate discovery.
"""
import math

def calculate_distance(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    if not all(math.isfinite(float(v)) for v in (lat1, lon1, lat2, lon2)):
        raise ValueError("Coordinates must be valid finite numbers")
    if not (-90 <= lat1 <= 90 and -90 <= lat2 <= 90 and -180 <= lon1 <= 180 and -180 <= lon2 <= 180):
        raise ValueError("Coordinates fall outside valid boundaries")
    
    radius_km = 6371.0
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    
    a = (math.sin(dlat / 2) ** 2 + 
         math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(dlon / 2) ** 2)
    a = min(1.0, max(0.0, a))
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(max(0.0, 1.0 - a)))
    
    return round(radius_km * c, 2)
