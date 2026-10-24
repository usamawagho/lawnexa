import math

def calculate_distance(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """
    Haversine Formula: Earth ke curvature ke mutabiq 2 GPS Coordinates 
    ke darmiyan Distance in KM calculate karta hai.
    """
    R = 6371.0  # Earth radius in KM

    # Degrees ko Radians mein convert kar rahe hain
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)

    a = (math.sin(dlat / 2) ** 2 + 
         math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(dlon / 2) ** 2)
    
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
    return round(R * c, 2)


# Sample Lawyers Database (Dummy Coordinates)
lawyers_database = [
    {"id": 1, "name": "Advocate Ali Khan", "specialty": "Tax", "lat": 31.5204, "lng": 74.3587},       # Location A (Center)
    {"id": 2, "name": "Advocate Usman", "specialty": "Criminal", "lat": 31.5500, "lng": 74.3600},     # ~3.3 KM away
    {"id": 3, "name": "Advocate Sara Ahmed", "specialty": "Family", "lat": 31.7000, "lng": 74.4000},    # ~20 KM away
]

def get_nearby_lawyers(client_lat: float, client_lng: float, radius_km: float = 10.0):
    nearby = []
    for lawyer in lawyers_database:
        dist = calculate_distance(client_lat, client_lng, lawyer["lat"], lawyer["lng"])
        if dist <= radius_km:
            lawyer_data = lawyer.copy()
            lawyer_data["distance_km"] = dist
            nearby.append(lawyer_data)
    return nearby

# Run Test
if __name__ == "__main__":
    # Client Coordinates (Lahore Center Example)
    client_lat = 31.5204
    client_lng = 74.3587
    
    print("=== Searching Lawyers within 10 KM Radius ===")
    results = get_nearby_lawyers(client_lat, client_lng, radius_km=10.0)
    
    for lawyer in results:
        print(f"Name: {lawyer['name']} | Specialty: {lawyer['specialty']} | Distance: {lawyer['distance_km']} KM")