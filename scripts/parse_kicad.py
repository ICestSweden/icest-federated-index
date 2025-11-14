#!/usr/bin/env python3
"""
KiCad Component Library Parser
Clones KiCad libraries and extracts component information from .dcm files into SQLite database.
"""

import argparse
import sqlite3
import subprocess
import sys
import os
import re
from pathlib import Path
from typing import Dict, List, Optional, Tuple
import tempfile
import shutil

try:
    from tqdm import tqdm
except ImportError:
    print("Error: tqdm is required. Install with: pip install tqdm")
    sys.exit(1)


class ComponentParser:
    """Parser for KiCad .dcm component description files."""
    
    def __init__(self):
        self.components = []
        
    def parse_dcm_file(self, file_path: Path) -> List[Dict[str, str]]:
        """
        Parse a single .dcm file and extract component information.
        
        Args:
            file_path: Path to the .dcm file
            
        Returns:
            List of component dictionaries
        """
        components = []
        
        try:
            with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
                content = f.read()
        except Exception as e:
            print(f"Warning: Could not read file {file_path}: {e}")
            return components
        
        # Find all component blocks ($CMP ... $ENDCMP)
        component_pattern = r'\$CMP\s+(.+?)\n(.*?)\$ENDCMP'
        matches = re.findall(component_pattern, content, re.DOTALL)
        
        for match in matches:
            mpn = match[0].strip()
            block_content = match[1]
            
            component = {
                'mpn': mpn,
                'description': '',
                'keywords': '',
                'datasheet_url': '',
                'source': str(file_path.name)
            }
            
            # Extract description (line after 'D ')
            desc_match = re.search(r'^D\s+(.+?)$', block_content, re.MULTILINE)
            if desc_match:
                component['description'] = desc_match.group(1).strip()
            
            # Extract keywords (line after 'K ')
            keywords_match = re.search(r'^K\s+(.+?)$', block_content, re.MULTILINE)
            if keywords_match:
                component['keywords'] = keywords_match.group(1).strip()
            
            # Extract datasheet URL (line after 'F ')
            datasheet_match = re.search(r'^F\s+(.+?)$', block_content, re.MULTILINE)
            if datasheet_match:
                component['datasheet_url'] = datasheet_match.group(1).strip()
            
            components.append(component)
        
        return components


class KiCadLibraryExtractor:
    """Main class for extracting KiCad component data."""
    
    def __init__(self, input_dir: Optional[Path] = None, output_db: Path = Path('components.db')):
        """
        Initialize the extractor.
        
        Args:
            input_dir: Directory containing KiCad libraries (if None, will clone)
            output_db: Path to output SQLite database
        """
        self.input_dir = input_dir
        self.output_db = output_db
        self.parser = ComponentParser()
        self.temp_dir = None
        
    def clone_repository(self, repo_url: str = "https://gitlab.com/kicad/libraries/kicad-symbols.git") -> Path:
        """
        Clone the KiCad libraries repository.
        
        Args:
            repo_url: URL of the Git repository
            
        Returns:
            Path to the cloned repository
        """
        print("Cloning KiCad libraries repository...")
        print(f"Repository URL: {repo_url}")
        
        # Create temporary directory for cloning
        self.temp_dir = tempfile.mkdtemp(prefix="kicad_libs_")
        clone_path = Path(self.temp_dir) / "kicad-symbols"
        
        try:
            # Try shallow clone first (faster)
            result = subprocess.run(
                ["git", "clone", "--depth", "1", repo_url, str(clone_path)],
                capture_output=True,
                text=True,
                check=False
            )
            
            if result.returncode != 0:
                print("Shallow clone failed, trying full clone...")
                # Fall back to full clone
                result = subprocess.run(
                    ["git", "clone", repo_url, str(clone_path)],
                    capture_output=True,
                    text=True,
                    check=True
                )
            
            print(f"Repository cloned successfully to: {clone_path}")
            return clone_path
            
        except subprocess.CalledProcessError as e:
            print(f"Error cloning repository: {e}")
            print(f"stderr: {e.stderr}")
            self.cleanup()
            sys.exit(1)
        except FileNotFoundError:
            print("Error: git is not installed or not in PATH")
            self.cleanup()
            sys.exit(1)
    
    def find_dcm_files(self, base_dir: Path) -> List[Path]:
        """
        Recursively find all .dcm files in the symbols directory.
        
        Args:
            base_dir: Base directory to search
            
        Returns:
            List of paths to .dcm files
        """
        symbols_dir = base_dir
        
        # Check if we need to look for a symbols subdirectory
        if (base_dir / "symbols").exists():
            symbols_dir = base_dir / "symbols"
        elif not any(base_dir.glob("*.dcm")):
            # If no .dcm files in root and no symbols dir, check common locations
            for possible_dir in ["", "kicad-symbols", "libraries"]:
                test_path = base_dir / possible_dir
                if test_path.exists() and (test_path / "symbols").exists():
                    symbols_dir = test_path / "symbols"
                    break
                elif test_path.exists() and any(test_path.glob("*.dcm")):
                    symbols_dir = test_path
                    break
        
        print(f"Searching for .dcm files in: {symbols_dir}")
        
        # Find all .dcm files recursively
        dcm_files = list(symbols_dir.rglob("*.dcm"))
        
        if not dcm_files:
            # Try searching in the entire base directory as fallback
            print(f"No .dcm files found in symbols directory, searching entire directory...")
            dcm_files = list(base_dir.rglob("*.dcm"))
        
        print(f"Found {len(dcm_files)} .dcm files")
        return dcm_files
    
    def create_database(self):
        """Create the SQLite database and components table."""
        conn = sqlite3.connect(self.output_db)
        cursor = conn.cursor()
        
        # Create components table
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS components (
                mpn TEXT PRIMARY KEY,
                description TEXT,
                keywords TEXT,
                datasheet_url TEXT,
                source TEXT,
                confidence REAL DEFAULT 1.0
            )
        ''')
        
        conn.commit()
        conn.close()
        print(f"Database created/verified: {self.output_db}")
    
    def insert_components(self, components: List[Dict[str, str]]):
        """
        Insert components into the database.
        
        Args:
            components: List of component dictionaries
        """
        if not components:
            return
            
        conn = sqlite3.connect(self.output_db)
        cursor = conn.cursor()
        
        # Use INSERT OR REPLACE to handle duplicates
        for component in components:
            cursor.execute('''
                INSERT OR REPLACE INTO components 
                (mpn, description, keywords, datasheet_url, source, confidence)
                VALUES (?, ?, ?, ?, ?, ?)
            ''', (
                component['mpn'],
                component['description'],
                component['keywords'],
                component['datasheet_url'],
                component['source'],
                1.0  # Default confidence value
            ))
        
        conn.commit()
        conn.close()
    
    def process_files(self, dcm_files: List[Path]):
        """
        Process all .dcm files and extract components.
        
        Args:
            dcm_files: List of paths to .dcm files
        """
        all_components = []
        failed_files = []
        
        print("\nParsing .dcm files...")
        
        # Process files with progress bar
        for file_path in tqdm(dcm_files, desc="Processing files", unit="file"):
            try:
                components = self.parser.parse_dcm_file(file_path)
                all_components.extend(components)
            except Exception as e:
                failed_files.append((file_path, str(e)))
                continue
        
        # Report any failures
        if failed_files:
            print(f"\nWarning: Failed to process {len(failed_files)} files:")
            for file_path, error in failed_files[:5]:  # Show first 5 errors
                print(f"  - {file_path.name}: {error}")
            if len(failed_files) > 5:
                print(f"  ... and {len(failed_files) - 5} more")
        
        # Insert components into database
        print(f"\nInserting {len(all_components)} components into database...")
        self.insert_components(all_components)
        
        # Print statistics
        self.print_statistics(all_components)
    
    def print_statistics(self, components: List[Dict[str, str]]):
        """
        Print statistics about the extracted components.
        
        Args:
            components: List of component dictionaries
        """
        # Get unique MPNs
        unique_mpns = set(comp['mpn'] for comp in components)
        
        # Count components with various fields
        with_description = sum(1 for comp in components if comp['description'])
        with_keywords = sum(1 for comp in components if comp['keywords'])
        with_datasheet = sum(1 for comp in components if comp['datasheet_url'])
        
        print("\n" + "="*60)
        print("EXTRACTION COMPLETE")
        print("="*60)
        print(f"Total components processed: {len(components)}")
        print(f"Unique MPNs: {len(unique_mpns)}")
        print(f"Components with description: {with_description}")
        print(f"Components with keywords: {with_keywords}")
        print(f"Components with datasheet URL: {with_datasheet}")
        print(f"Database saved to: {self.output_db}")
        print("="*60)
    
    def cleanup(self):
        """Clean up temporary directories."""
        if self.temp_dir and Path(self.temp_dir).exists():
            try:
                shutil.rmtree(self.temp_dir)
                print(f"Cleaned up temporary directory: {self.temp_dir}")
            except Exception as e:
                print(f"Warning: Could not remove temporary directory: {e}")
    
    def run(self):
        """Run the complete extraction process."""
        try:
            # Determine input directory
            if self.input_dir is None:
                # Clone repository
                input_path = self.clone_repository()
            else:
                input_path = self.input_dir
                if not input_path.exists():
                    print(f"Error: Input directory does not exist: {input_path}")
                    sys.exit(1)
                print(f"Using existing directory: {input_path}")
            
            # Create database
            self.create_database()
            
            # Find .dcm files
            dcm_files = self.find_dcm_files(input_path)
            
            if not dcm_files:
                print("Error: No .dcm files found!")
                self.cleanup()
                sys.exit(1)
            
            # Process files
            self.process_files(dcm_files)
            
        finally:
            # Clean up if we cloned the repository
            if self.input_dir is None:
                self.cleanup()


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="Extract KiCad component information from .dcm files into SQLite database",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Clone repository and extract components
  python %(prog)s
  
  # Use existing directory
  python %(prog)s --input-dir /path/to/kicad-symbols
  
  # Specify output database
  python %(prog)s --output-db my_components.db
        """
    )
    
    parser.add_argument(
        '--input-dir',
        type=Path,
        default=None,
        help='Path to existing KiCad libraries directory (if not specified, will clone from GitLab)'
    )
    
    parser.add_argument(
        '--output-db',
        type=Path,
        default=Path('components.db'),
        help='Path to output SQLite database (default: components.db)'
    )
    
    args = parser.parse_args()
    
    # Create and run extractor
    extractor = KiCadLibraryExtractor(
        input_dir=args.input_dir,
        output_db=args.output_db
    )
    
    try:
        extractor.run()
    except KeyboardInterrupt:
        print("\n\nInterrupted by user")
        extractor.cleanup()
        sys.exit(1)
    except Exception as e:
        print(f"\nUnexpected error: {e}")
        extractor.cleanup()
        sys.exit(1)


if __name__ == "__main__":
    main()

