import math

def calculate_distance(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """
    Haversine Formula: Earth ke curvature ke mutabiq 2 GPS Coordinates 
    ke darmiyan Distance in KM calculate karta hai. Domain errors se 
    bachne ke liye clamping added hai.
    """
    R = 6371.0  # Earth radius in KM

    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)

    a = (math.sin(dlat / 2) ** 2 + 
         math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(dlon / 2) ** 2)
    
    # Floating point precision overflow protect karein
    a = max(0.0, min(1.0, a))
    
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
    return round(R * c, 2)