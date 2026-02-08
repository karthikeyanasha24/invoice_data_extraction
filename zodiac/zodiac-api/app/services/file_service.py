import logging
from ..config.config import USE_BLOB_STORAGE, MUST_USE_BLOB_STORAGE, UPLOAD_DIR, EDI_DIR
from fastapi import HTTPException, status
import vercel_blob
import os
import traceback
from typing import Union

logger=logging.getLogger("zodiac.file_service")

async def save_file_to_storage(file_content: bytes, filename: str, subdirectory: str = "uploads", allow_overwrite: bool = False) -> str:
    """Save file content to appropriate storage (local or Vercel Blob)
    
    Args:
        file_content: File content as bytes
        filename: Name of the file
        subdirectory: Subdirectory to save in (default: "uploads")
        allow_overwrite: Whether to overwrite existing files (default: False)
    """
    logger.info("=" * 50)
    logger.info("💾 FILE SAVE OPERATION")
    logger.info("=" * 50)
    logger.info(f"📁 Filename: {filename}")
    logger.info(f"📂 Subdirectory: {subdirectory}")
    logger.info(f"📊 File size: {len(file_content)} bytes")
    logger.info(f"🔄 Allow overwrite: {allow_overwrite}")
    logger.info(
        f"🎯 Storage mode: {'Vercel Blob' if USE_BLOB_STORAGE else 'Local'}")
    logger.info(f"🚨 Mandatory blob storage: {MUST_USE_BLOB_STORAGE}")

    # Validate mandatory blob storage requirement
    if MUST_USE_BLOB_STORAGE and not USE_BLOB_STORAGE:
        logger.error(
            "💥 CRITICAL ERROR: Blob storage is mandatory but not available!")
        logger.error(
            "🚨 Cannot save file - blob storage is required for PROD deployment")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Blob storage is mandatory but not available"
        )

    if USE_BLOB_STORAGE:
        try:
            # Use Vercel Blob storage
            blob_path = f"{subdirectory}/{filename}"
            logger.info(f"📦 Saving to Vercel Blob: {blob_path}")
            logger.info(
                f"🔧 Using vercel_blob module: {vercel_blob is not None}")

            # Prepare options for blob storage
            blob_options = {
                "access": "public",
                "addRandomSuffix": False
            }
            
            # Add overwrite option if requested
            if allow_overwrite:
                blob_options["allowOverwrite"] = True  # Allow overwriting existing blobs
                logger.info(f"⚠️ Overwrite mode enabled - will replace existing blob if present")
            
            # Use vercel_blob.put to upload file
            logger.info(f"🔧 Blob options: {blob_options}")
            blob_response = vercel_blob.put(blob_path, file_content, options=blob_options)
            logger.info(f"✅ File saved to Vercel Blob successfully!")
            logger.info(f"🌐 Blob Response: {blob_response}")
            logger.info(f"📊 Uploaded {len(file_content)} bytes")

            # Return the full blob response for URL extraction
            if isinstance(blob_response, dict):
                logger.info(f"✅ File saved successfully!")
                logger.info(f"📁 Saved as: {filename}")
                logger.info(f"📍 Storage path: {blob_response}")
                return blob_response
            else:
                logger.info(f"✅ File saved successfully!")
                logger.info(f"📁 Saved as: {filename}")
                logger.info(f"📍 Storage path: {str(blob_response)}")
                return str(blob_response)
        except Exception as e:
            logger.error(f"❌ Failed to save to Vercel Blob: {e}")
            logger.error(f"🔍 Error type: {type(e).__name__}")
            logger.error(f"📝 Error details: {str(e)}")

            # Provide more specific error messages
            if "token" in str(e).lower():
                error_detail = "Blob storage authentication failed: Invalid or missing token"
            elif "network" in str(e).lower() or "connection" in str(e).lower():
                error_detail = "Blob storage network error: Unable to connect to cloud storage"
            elif "permission" in str(e).lower() or "access" in str(e).lower():
                error_detail = "Blob storage permission error: Insufficient access rights"
            else:
                error_detail = f"Failed to save file to blob storage: {str(e)}"

            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=error_detail
            )
    else:
        # Use local file storage
        try:
            target_dir = UPLOAD_DIR if subdirectory == "uploads" else EDI_DIR
            UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
            EDI_DIR.mkdir(parents=True, exist_ok=True)
            file_path = target_dir / filename
            # logger.info(f"👤 Running as user: {os.getlogin()}")
            logger.info(f"📂 Attempting to write to: {file_path}")
            logger.info(f"🔒 Write access? {os.access(target_dir, os.W_OK)}")
            logger.info(f"📁 Saving to local storage: {file_path}")
            logger.info(f"📂 Target directory: {target_dir}")
            logger.info(f"📄 Full path: {file_path}")
            logger.info(f"Current path : {os.getcwd()}")

            try:
                with open(file_path, "wb") as buffer:
                    buffer.write(file_content)
            except:
                with open(os.path.join(os.getcwd(), 'uploads', filename), 'wb') as buffer:
                    buffer.write(file_content)
            logger.info(f"✅ File saved locally successfully!")
            logger.info(f"📊 Written {len(file_content)} bytes")
            logger.info(f"📍 Local path: {file_path}")
            return str(file_path)
        except Exception as e:
            traceback.print_exc()
            logger.error(f"❌ Failed to save locally: {e}")
            logger.error(f"🔍 Error type: {type(e).__name__}")
            logger.error(f"📝 Error details: {str(e)}")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Failed to save file locally: {str(e)}"
            )


async def read_file_from_storage(file_path: Union[str, dict], blob_xml_path: str = None, blob_edi_path: str = None) -> bytes:
    """Read file content from appropriate storage (local or Vercel Blob)

    Args:
        file_path: Path to the file (local path or blob pathname)
        blob_xml_path: Blob URL for XML file from database (if available)
        blob_edi_path: Blob URL for EDI file from database (if available)
    """
    logger.info("=" * 50)
    logger.info("📖 FILE READ OPERATION")
    logger.info("=" * 50)
    logger.info(f"📁 File path: {file_path}")
    logger.info(f"🌐 Blob XML path: {blob_xml_path}")
    logger.info(f"🌐 Blob EDI path: {blob_edi_path}")
    logger.info(
        f"🎯 Storage mode: {'Vercel Blob' if USE_BLOB_STORAGE else 'Local'}")
    logger.info(f"🚨 Mandatory blob storage: {MUST_USE_BLOB_STORAGE}")

    # Validate mandatory blob storage requirement
    if MUST_USE_BLOB_STORAGE and not USE_BLOB_STORAGE:
        logger.error(
            "💥 CRITICAL ERROR: Blob storage is mandatory but not available!")
        logger.error(
            "🚨 Cannot read file - blob storage is required for PROD deployment")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Blob storage is mandatory but not available"
        )

    if USE_BLOB_STORAGE:
        try:
            # Read from Vercel Blob storage
            logger.info(f"📦 Reading from Vercel Blob")
            logger.info(
                f"🔧 Using vercel_blob module: {vercel_blob is not None}")

            # Determine which blob path to use based on file type
            download_url = None

            # First priority: Use provided blob paths from database
            if blob_xml_path and blob_xml_path.strip():
                download_url = blob_xml_path
                logger.info(
                    f"🌐 Using blob XML path from database: {download_url}")
            elif blob_edi_path and blob_edi_path.strip():
                download_url = blob_edi_path
                logger.info(
                    f"🌐 Using blob EDI path from database: {download_url}")
            # Second priority: Extract URL from file_path if it's a blob response
            elif isinstance(file_path, dict) and 'url' in file_path:
                download_url = file_path['url']
                logger.info(f"🌐 Using blob URL from file_path: {download_url}")
            # Third priority: Construct URL from pathname
            elif isinstance(file_path, dict) and 'pathname' in file_path:
                blob_path = file_path['pathname']
                download_url = f"https://jdwai1wj6716hbub.public.blob.vercel-storage.com/{blob_path}"
                logger.info(
                    f"🌐 Constructed blob URL from pathname: {download_url}")
            # Fourth priority: Try to determine from string patterns (for backward compatibility)
            elif file_path and isinstance(file_path, str):
                if "xml" in file_path.lower() or "uploads" in file_path:
                    download_url = blob_xml_path
                    logger.info(
                        f"🌐 Using blob XML path based on file path: {download_url}")
                elif "edi" in file_path.lower() or "x12" in file_path.lower() or "converted" in file_path:
                    download_url = blob_edi_path
                    logger.info(
                        f"🌐 Using blob EDI path based on file path: {download_url}")
                else:
                    # Try to construct URL from string path
                    download_url = f"https://jdwai1wj6716hbub.public.blob.vercel-storage.com/{file_path}"
                    logger.info(
                        f"🌐 Constructed blob URL from string path: {download_url}")
            else:
                logger.warning(
                    f"⚠️ Could not determine blob URL from file_path: {file_path}")

            # Ensure we have a valid download URL
            if not download_url:
                logger.error(f"❌ No valid blob URL found for file access")
                logger.error(f"🔍 file_path: {file_path}")
                logger.error(f"🔍 blob_xml_path: {blob_xml_path}")
                logger.error(f"🔍 blob_edi_path: {blob_edi_path}")
                raise HTTPException(
                    status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                    detail="No valid blob URL found for file access"
                )

            # Use requests to download the file from the blob URL
            import requests
            logger.info(f"🌐 Downloading from URL: {download_url}")
            response = requests.get(download_url)
            response.raise_for_status()

            file_content = response.content
            logger.info(f"✅ File read from Vercel Blob successfully!")
            logger.info(f"📊 Retrieved {len(file_content)} bytes")
            return file_content
        except Exception as e:
            logger.error(f"❌ Failed to read from Vercel Blob: {e}")
            logger.error(f"🔍 Error type: {type(e).__name__}")
            logger.error(f"📝 Error details: {str(e)}")

            # Provide more specific error messages
            if "404" in str(e) or "not found" in str(e).lower():
                error_detail = "File not found in blob storage: File may have been deleted or moved"
            elif "network" in str(e).lower() or "connection" in str(e).lower():
                error_detail = "Blob storage network error: Unable to connect to cloud storage"
            elif "permission" in str(e).lower() or "access" in str(e).lower():
                error_detail = "Blob storage permission error: Insufficient access rights to read file"
            else:
                error_detail = f"Failed to read file from blob storage: {str(e)}"

            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=error_detail
            )
    else:
        # Read from local file storage
        try:
            # Handle blob response in local storage mode
            if isinstance(file_path, dict):
                logger.warning(
                    f"⚠️ Received blob response in local storage mode - this shouldn't happen")
                logger.warning(f"⚠️ Blob response: {file_path}")
                # Extract the pathname for local file access
                local_path = file_path.get('pathname', str(file_path))
                logger.info(f"📁 Using extracted pathname: {local_path}")
            else:
                local_path = file_path

            logger.info(f"📁 Reading from local storage: {local_path}")
            logger.info(f"🔍 File exists: {os.path.exists(local_path)}")

            with open(local_path, "rb") as buffer:
                file_content = buffer.read()

            logger.info(f"✅ File read locally successfully!")
            logger.info(f"📊 Retrieved {len(file_content)} bytes")
            return file_content
        except Exception as e:
            logger.error(f"❌ Failed to read locally: {e}")
            logger.error(f"🔍 Error type: {type(e).__name__}")
            logger.error(f"📝 Error details: {str(e)}")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Failed to read file locally: {str(e)}"
            )
