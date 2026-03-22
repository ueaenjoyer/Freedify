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

async def refresh_link_by_filename(filename: str) -> str | None:
    """Search Premiumize cloud for a file by name and return a fresh CDN link.
    
    Used to auto-recover when a cached Premiumize CDN download URL expires (403).
    Returns the new direct download URL, or None if not found.
    """
    import logging
    logger = logging.getLogger(__name__)
    
    try:
        # Strip URL encoding and extension variants for a broader search
        from urllib.parse import unquote
        clean_name = unquote(filename)
        # Use the base name without extension for the search query
        search_term = clean_name.rsplit('.', 1)[0] if '.' in clean_name else clean_name
        
        logger.info(f"Premiumize link refresh: searching for '{search_term}'")
        results = await search_my_files(search_term)
        
        if not results:
            logger.warning(f"Premiumize link refresh: no results for '{search_term}'")
            return None
        
        # Find the best match by filename
        for item in results:
            item_name = item.get("name", "")
            if item_name.lower() == clean_name.lower() or clean_name.lower() in item_name.lower():
                fresh_link = item.get("link") or item.get("stream_link")
                if fresh_link:
                    logger.info(f"Premiumize link refresh: got fresh link for '{item_name}'")
                    return fresh_link
        
        # If no exact match, just use the first result that has a link
        for item in results:
            fresh_link = item.get("link") or item.get("stream_link")
            if fresh_link:
                logger.info(f"Premiumize link refresh: using best-match '{item.get('name')}'")
                return fresh_link
        
        logger.warning(f"Premiumize link refresh: results found but none had a download link")
        return None
        
    except Exception as e:
        logger.error(f"Premiumize link refresh error: {e}")
        return None

async def delete_item(item_id: str, is_transfer: bool = False):
    """
    Delete a transfer, folder, or file from Premiumize.
    If is_transfer is True, deletes from /transfer/delete.
    Otherwise, tries /folder/delete first, then /file/delete if it fails.
    """
    if is_transfer:
        return await _make_request("/transfer/delete", method="POST", data={"id": item_id})
    
    # Try deleting as a folder
    try:
        return await _make_request("/folder/delete", method="POST", data={"id": item_id})
    except HTTPException as e:
        # If folder delete fails, try as a file
        return await _make_request("/file/delete", method="POST", data={"id": item_id})
