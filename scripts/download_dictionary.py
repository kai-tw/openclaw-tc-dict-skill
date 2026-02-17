#!/usr/bin/env python3
"""
Download and manage Traditional Chinese dictionary data from MOE.

Requirements:
    Install dependencies: uv pip install -r requirements.txt
    (or: pip install pandas openpyxl)

Usage:
    python download_dictionary.py [--dict-name DICT_NAME] [--storage-path PATH] [--force]

Args:
    --dict-name: Dictionary name (default: 'concised')
    --storage-path: Directory to store dictionaries (default: ~/.openclaw/dictionaries)
    --force: Force download even if latest version is already cached

Returns:
    JSON with status, version info, and file path
"""

import argparse
import json
import logging
import os
import re
import shutil
import ssl
import sys
import tempfile
import urllib.error
import urllib.request
import zipfile
from datetime import datetime
from pathlib import Path

# Create SSL context that doesn't verify certificates
# (MOE website may have certificate issues)
ssl_context = ssl.create_default_context()
ssl_context.check_hostname = False
ssl_context.verify_mode = ssl.CERT_NONE

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s'
)
logger = logging.getLogger(__name__)


class DictionaryDownloader:
    """Manages downloading and versioning MOE dictionaries."""
    
    # MOE dictionary sources
    SOURCES = {
        'concised': {
            'name': '國語辭典簡編本',
            'url_pattern': 'https://language.moe.gov.tw/001/Upload/Files/site_content/M0001/respub/download/dict_concised_2014_{version}.zip',
            'extract_folder_pattern': 'dict_concised_2014_{version}',
            'xlsx_filename': 'dict_concised_2014.xlsx',
        },
        # Placeholder for future dictionaries
        'revised': {
            'name': '重編國語辭典修訂本',
            'url_pattern': 'https://language.moe.gov.tw/001/Upload/Files/site_content/M0001/respub/download/dict_revised_2014_{version}.zip',
            'extract_folder_pattern': 'dict_revised_2014_{version}',
            'xlsx_filename': 'dict_revised_2014.xlsx',
        },
    }
    
    def __init__(self, storage_path: str = None):
        """
        Initialize downloader.
        
        Args:
            storage_path: Directory to store dictionaries. Defaults to ~/.openclaw/dictionaries
        """
        if storage_path:
            self.storage_path = Path(storage_path).expanduser()
        else:
            self.storage_path = Path.home() / '.openclaw' / 'dictionaries'
        
        self.metadata_file = self.storage_path / 'metadata.json'
        self.storage_path.mkdir(parents=True, exist_ok=True)
    
    def load_metadata(self) -> dict:
        """Load version metadata."""
        if self.metadata_file.exists():
            try:
                with open(self.metadata_file) as f:
                    return json.load(f)
            except Exception as e:
                logger.warning(f"Failed to load metadata: {e}")
                return {}
        return {}
    
    def save_metadata(self, metadata: dict):
        """Save version metadata."""
        try:
            with open(self.metadata_file, 'w', encoding='utf-8') as f:
                json.dump(metadata, f, indent=2, ensure_ascii=False)
        except Exception as e:
            logger.error(f"Failed to save metadata: {e}")
            raise
    
    def get_latest_version(self, dict_name: str) -> str:
        """
        Fetch latest version from MOE website.
        
        Queries the MOE download page and extracts the latest version number
        from the filename (YYYYMMDD format).
        
        Args:
            dict_name: Dictionary identifier (e.g., 'concised')
        
        Returns:
            Version string (YYYYMMDD) or None if unable to determine
        """
        if dict_name not in self.SOURCES:
            raise ValueError(f"Unknown dictionary: {dict_name}")
        
        try:
            # For now, return hardcoded latest; in production, parse MOE webpage
            # This would require scraping or API call to MOE site
            page_url = 'https://language.moe.gov.tw/001/Upload/Files/site_content/M0001/respub/dict_concised_download.html'
            
            with urllib.request.urlopen(page_url, timeout=10, context=ssl_context) as response:
                html = response.read().decode('utf-8')
                
                # Extract version from filename pattern: dict_concised_2014_YYYYMMDD
                pattern = r'dict_concised_2014_(\d{8})'
                matches = re.findall(pattern, html)
                
                if matches:
                    # Return the latest (highest) version
                    latest = sorted(matches, reverse=True)[0]
                    logger.info(f"Latest version from MOE: {latest}")
                    return latest
                else:
                    logger.warning("Could not extract version from MOE page")
                    return None
        
        except Exception as e:
            logger.error(f"Failed to fetch latest version: {e}")
            return None
    
    def download_and_extract(self, dict_name: str, version: str) -> dict:
        """
        Download dictionary zip and extract.
        
        Args:
            dict_name: Dictionary identifier
            version: Version string (YYYYMMDD)
        
        Returns:
            dict with status, path, and version info
        """
        if dict_name not in self.SOURCES:
            raise ValueError(f"Unknown dictionary: {dict_name}")
        
        source = self.SOURCES[dict_name]
        download_url = source['url_pattern'].format(version=version)
        extract_folder = source['extract_folder_pattern'].format(version=version)
        
        logger.info(f"Downloading {dict_name} v{version}...")
        
        try:
            # Download to temporary file
            with tempfile.NamedTemporaryFile(suffix='.zip', delete=False) as tmp:
                tmp_path = tmp.name
            
            # Download zip
            with urllib.request.urlopen(download_url, timeout=30, context=ssl_context) as response:
                with open(tmp_path, 'wb') as f:
                    shutil.copyfileobj(response, f)
            
            logger.info(f"Downloaded {os.path.getsize(tmp_path)} bytes")
            
            # Extract to storage (create version-specific folder)
            extract_path = self.storage_path / extract_folder
            extract_path.mkdir(parents=True, exist_ok=True)
            
            with zipfile.ZipFile(tmp_path, 'r') as zip_ref:
                # List all files in zip
                file_list = zip_ref.namelist()
                logger.info(f"Zip contains: {file_list}")
                
                # Extract directly to version folder
                zip_ref.extractall(extract_path)
            
            logger.info(f"Extracted to {extract_path}")
            
            # Clean up temp file
            os.unlink(tmp_path)
            
            # Find xlsx file (could be versioned filename or standard filename)
            # Try versioned filename first: dict_concised_2014_20251229.xlsx
            versioned_filename = f"dict_concised_2014_{version}.xlsx"
            xlsx_candidates = [
                extract_path / versioned_filename,
                extract_path / source['xlsx_filename'],
            ]
            
            # Also check for any .xlsx files in the folder
            xlsx_files = list(extract_path.glob('*.xlsx'))
            
            xlsx_path = None
            for candidate in xlsx_candidates:
                if candidate.exists():
                    xlsx_path = candidate
                    break
            
            if not xlsx_path and xlsx_files:
                xlsx_path = xlsx_files[0]
            
            if not xlsx_path or not xlsx_path.exists():
                raise FileNotFoundError(f"xlsx not found in {extract_path}. Files: {list(extract_path.glob('*'))}")
            
            logger.info(f"Dictionary file: {xlsx_path}")
            
            return {
                'success': True,
                'dict_name': dict_name,
                'version': version,
                'xlsx_path': str(xlsx_path),
                'xlsx_filename': xlsx_path.name,  # Store actual filename
                'extract_path': str(extract_path),
                'timestamp': datetime.utcnow().isoformat() + 'Z',
            }
        
        except Exception as e:
            logger.error(f"Download/extract failed: {e}")
            if 'tmp_path' in locals():
                try:
                    os.unlink(tmp_path)
                except:
                    pass
            raise
    
    def update_dictionary(self, dict_name: str, force: bool = False) -> dict:
        """
        Check for updates and download if needed.
        
        Args:
            dict_name: Dictionary identifier
            force: Force download even if version matches
        
        Returns:
            dict with status and result info
        """
        logger.info(f"Checking for updates to {dict_name}...")
        
        # Get latest version
        latest_version = self.get_latest_version(dict_name)
        if not latest_version:
            return {
                'success': False,
                'error': 'Could not determine latest version from MOE',
            }
        
        # Load local metadata
        metadata = self.load_metadata()
        local_version = metadata.get(dict_name, {}).get('version')
        
        logger.info(f"Local version: {local_version}, Latest: {latest_version}")
        
        if local_version == latest_version and not force:
            logger.info("Already at latest version")
            return {
                'success': True,
                'status': 'up_to_date',
                'version': latest_version,
            }
        
        # Download and extract
        result = self.download_and_extract(dict_name, latest_version)
        
        if result['success']:
            # Update metadata
            metadata[dict_name] = {
                'version': latest_version,
                'downloaded_at': result['timestamp'],
                'path': result['extract_path'],
                'filename': result['xlsx_filename'],  # Use actual filename from result
            }
            self.save_metadata(metadata)
            logger.info(f"Updated {dict_name} to v{latest_version}")
        
        return result


def main():
    """CLI entry point."""
    parser = argparse.ArgumentParser(description='Download MOE dictionary data')
    parser.add_argument('--dict-name', default='concised', help='Dictionary name')
    parser.add_argument('--storage-path', help='Storage directory path')
    parser.add_argument('--force', action='store_true', help='Force download')
    parser.add_argument('--check-only', action='store_true', help='Check version only')
    
    args = parser.parse_args()
    
    try:
        downloader = DictionaryDownloader(args.storage_path)
        
        if args.check_only:
            latest = downloader.get_latest_version(args.dict_name)
            print(json.dumps({
                'success': latest is not None,
                'latest_version': latest,
            }))
        else:
            result = downloader.update_dictionary(args.dict_name, force=args.force)
            print(json.dumps(result))
            sys.exit(0 if result['success'] else 1)
    
    except Exception as e:
        print(json.dumps({
            'success': False,
            'error': str(e),
        }), file=sys.stderr)
        sys.exit(1)


if __name__ == '__main__':
    main()
