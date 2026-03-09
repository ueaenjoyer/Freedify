import asyncio
import logging
import sys

from app.tidal_service import search_albums, get_album

logging.basicConfig(level=logging.INFO, stream=sys.stdout)

async def test():
    print("Searching for 'The Beatles' albums on Tidal...")
    from app.tidal_service import _fetch_from_proxy
    data = await _fetch_from_proxy("/search/?al=The%20Beatles")
    import json
    with open("test_albums.json", "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)
        
    results = await search_albums("The Beatles", limit=2)
    
    if not results:
        print("No albums returned.")
        return
        
    for album in results:
        print(f"\nFound Album: {album['title']} (ID: {album['id']}) - Cover: {album['cover']}")
        
    first_album_id = results[0]['id']
    print(f"\nFetching tracks for {first_album_id}...")
    
    from app.tidal_service import _fetch_from_proxy
    raw_album = await _fetch_from_proxy(f"/album/?id={first_album_id.replace('td_', '')}")
    import json
    with open("test_album_details.json", "w", encoding="utf-8") as f:
        json.dump(raw_album, f, indent=2)
        
    album_details = await get_album(first_album_id)
    if not album_details:
        print("Failed to get album details!")
        return
        
    print(f"Loaded {album_details['title']} by {album_details['artist']}")
    print(f"Track count: {len(album_details['tracks'])}")
    for i, t in enumerate(album_details['tracks'][:3]):
        print(f"  [{i+1}] {t['title']} (HiRes: {t['is_hires']})")

if __name__ == "__main__":
    asyncio.run(test())
