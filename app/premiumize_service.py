import httpx
import os
from fastapi import HTTPException

PREMIUMIZE_API_KEY = os.getenv("PREMIUMIZE_API_KEY")

async def _make_request(endpoint: str, method: str = "GET", params: dict = None, data: dict = None):
    if not PREMIUMIZE_API_KEY:
        raise HTTPException(status_code=500, detail="Premiumize API key is missing. Add PREMIUMIZE_API_KEY to .env file.")
        
    url = f"https://www.premiumize.me/api{endpoint}"
    
    # Premiumize requires API key as query parameter for authentication in most cases, or Bearer auth
    query_params = {"apikey": PREMIUMIZE_API_KEY}
    if params:
        query_params.update(params)

    async with httpx.AsyncClient() as client:
        try:
            if method == "GET":
                response = await client.get(url, params=query_params)
            elif method == "POST":
                response = await client.post(url, params=query_params, data=data)
            else:
                raise ValueError(f"Unsupported HTTP method: {method}")

            response_data = response.json()
            if response_data.get("status") != "success":
                error_msg = response_data.get("message", "Unknown Premiumize error")
                raise HTTPException(status_code=400, detail=f"Premiumize Error: {error_msg}")
                
            return response_data
            
        except httpx.RequestError as e:
            raise HTTPException(status_code=500, detail=f"Request to Premiumize failed: {str(e)}")

async def create_transfer(magnet_link: str):
    """Start a new torrent transfer using a magnet link."""
    data = {
        "src": magnet_link
    }
    return await _make_request("/transfer/create", method="POST", data=data)

async def check_transfer_status(transfer_id: str = None):
    """
    Get status of transfers. 
    If transfer_id is None, returns all active. 
    """
    response = await _make_request("/transfer/list")
    transfers = response.get("transfers", [])
    
    if transfer_id:
        for t in transfers:
            if t.get("id") == transfer_id:
                return t
        
        # If not in active transfers, it might be finished and cleared.
        # We need to rely on the frontend to check if the folder exists, 
        # but for now we'll just return None to let caller know it's not active.
        return None
        
    return transfers

async def list_folder_contents(folder_id: str = None):
    """
    List contents of a Premiumize folder. 
    If folder_id is None, lists root directory.
    Filters for audio files natively.
    """
    params = {}
    if folder_id:
        params["id"] = folder_id

    response = await _make_request("/folder/list", params=params)
    items = response.get("content", [])
    
    audio_extensions = ['.mp3', '.m4b', '.m4a', '.flac', '.wav', '.ogg']
    
    audio_files = []
    # Also collect subfolders in case the audiobook is nested one level deep
    folders = []
    
    for item in items:
        if item.get("type") == "file":
            name: str = item.get("name", "").lower()
            if any(name.endswith(ext) for ext in audio_extensions):
                audio_files.append(item)
        elif item.get("type") == "folder":
            folders.append(item)
            
    # Sort files naturally (alphabetically)
    audio_files.sort(key=lambda x: x.get("name", ""))
    
    return {
        "status": "success",
        "audio_files": audio_files,
        "folders": folders,
        "name": response.get("name", "Root")
    }

async def search_my_files(query: str):
    """Search Premiumize cloud for existing downloads to skip torrenting."""
    response = await _make_request("/folder/search", params={"q": query})
    return response.get("content", [])
