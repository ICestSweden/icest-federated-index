#!/usr/bin/env python3
"""
Enhanced GitHub Scraper - KiCad symbols, footprints, BOMs, schematics
No API key needed beyond GitHub token (already in secrets)
"""
import requests
import sqlite3
import sys
import re
import time

def init_database(db_path):
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    try:
        cursor.execute("ALTER TABLE components ADD COLUMN github_files TEXT")
        cursor.execute("ALTER TABLE components ADD COLUMN file_types TEXT")
    except:
        pass
    conn.close()

def search_github_files(github_token, max_files=80):
    """Search GitHub for KiCad files"""
    headers = {
        "Authorization": f"token {github_token}",
        "User-Agent": "ICest-Component-Index-Bot/1.0"
    }
    
    search_queries = [
        "extension:kicad_sym",  # KiCad symbols
        "extension:kicad_mod",  # KiCad footprints
        "filename:BOM.csv",     # BOM files
        "filename:parts.csv",    # Alt BOM format
        "extension:sch path:kicad",  # KiCad schematics
    ]
    
    all_files = []
    
    for q in search_queries:
        print(f"🔍 Searching: {q}")
        response = requests.get(
            "https://api.github.com/search/code",
            params={"q": f"{q} stars:>2", "per_page": 10},
            headers=headers
        )
        
        if response.status_code == 200:
            items = response.json().get("items", [])
            print(f"📦 Found {len(items)} files")
            all_files.extend(items)
        
        time.sleep(1)
    
    return all_files[:max_files]

def extract_components_from_content(content, file_type):
    """Extract components based on file type"""
    components = []
    
    if file_type == "kicad_sym":
        matches = re.findall(r'\(symbol "([^"]+)"', content)
        for mpn in matches:
            if len(mpn) < 50:
                components.append({"mpn": mpn, "source": "github_enhanced", "type": "symbol"})
    
    elif file_type == "kicad_mod":
        matches = re.findall(r'\(module "([^"]+)"', content)
        for mpn in matches:
            if len(mpn) < 50:
                components.append({"mpn": mpn, "source": "github_enhanced", "type": "footprint"})
    
    elif file_type == "bom":
        lines = content.split('\n')
        for line in lines[1:]:
            parts = line.split(',')
            if len(parts) >= 2:
                mpn = parts[0].strip()
                desc = parts[1].strip() if len(parts) > 1 else ""
                if mpn and len(mpn) < 50:
                    components.append({"mpn": mpn, "description": desc, "source": "github_enhanced", "type": "bom"})
    
    elif file_type == "sch":
        matches = re.findall(r'L (\w+) (.+)', content)
        for ref, value in matches:
            value = value.strip().split()[0]
            if value and len(value) < 50:
                components.append({"mpn": value, "source": "github_enhanced", "type": "schematic"})
    
    return components

def update_components(db_path, components, file_url, file_type):
    """Update components with GitHub file data"""
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    for comp in components:
        mpn = comp["mpn"]
        
        cursor.execute("""
            UPDATE components 
            SET usage_count = usage_count + 1,
                github_files = COALESCE(github_files || ', ', '') || ?,
                file_types = COALESCE(file_types || ', ', '') || ?
            WHERE mpn LIKE ? OR mpn LIKE ?
        """, (file_url, file_type, f"%{mpn}%", f"%{mpn.replace('-', '')}%"))
        
        if cursor.rowcount == 0:
            cursor.execute("""
                INSERT INTO components (mpn, description, source, confidence, usage_count, github_files, file_types)
                VALUES (?, ?, 'github_enhanced', 0.6, 1, ?, ?)
            """, (mpn, comp.get("description", f"Component {mpn}"), file_url, file_type))
    
    conn.commit()
    conn.close()

def main(db_path, github_token):
    init_database(db_path)
    
    print("🚀 Searching GitHub for KiCad files...")
    files = search_github_files(github_token, max_files=80)
    
    if not files:
        print("❌ No files found")
        return
    
    print(f"\n📂 Processing {len(files)} files...\n")
    
    total_added = 0
    
    for i, file_item in enumerate(files):
        file_url = file_item["html_url"]
        raw_url = file_url.replace("github.com", "raw.githubusercontent.com").replace("/blob/", "/")
        file_name = file_item["name"].lower()
        
        if file_name.endswith(".kicad_sym"):
            file_type = "kicad_sym"
        elif file_name.endswith(".kicad_mod"):
            file_type = "kicad_mod"
        elif "bom.csv" in file_name or "parts.csv" in file_name:
            file_type = "bom"
        elif file_name.endswith(".sch"):
            file_type = "sch"
        else:
            continue
        
        print(f"[{i+1}/{len(files)}] {file_name}")
        
        try:
            response = requests.get(raw_url, timeout=10)
            if response.status_code == 200:
                components = extract_components_from_content(response.text, file_type)
                
                if components:
                    update_components(db_path, components, file_url, file_type)
                    total_added += len(components)
                    print(f"  ✓ Found {len(components)} components")
                else:
                    print(f"  → No components found")
            else:
                print(f"  → HTTP {response.status_code}")
            
            time.sleep(0.5)
            
        except Exception as e:
            print(f"  → Error: {e}")
    
    print(f"\n✅ Enhanced GitHub parsing complete!")
    print(f"   Components processed: {total_added}")

if __name__ == "__main__":
    if len(sys.argv) != 3:
        print("Usage: python3 scripts/parse_github_enhanced.py <github_token> <db_path>")
        sys.exit(1)
    
    main(sys.argv[2], sys.argv[1])
