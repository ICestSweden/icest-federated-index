#!/usr/bin/env python3
"""
Wikidata Component Parser
Queries Wikidata for electronic components
"""

import requests
import sqlite3

def parse_wikidata(output_db):
    # Connect to database (creates it if doesn't exist)
    conn = sqlite3.connect(output_db)
    cursor = conn.cursor()
    
    # Create table if it doesn't exist
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS components (
            mpn TEXT PRIMARY KEY,
            description TEXT,
            keywords TEXT,
            datasheet_url TEXT,
            source TEXT,
            confidence REAL
        )
    """)
    
    # SPARQL query to find electronic components
    query = """
    SELECT DISTINCT ?item ?mpn ?label ?description ?manufacturer ?datasheet WHERE {
      ?item wdt:P31 wd:Q1259759.
      OPTIONAL { ?item wdt:P1874 ?mpn. }
      OPTIONAL { ?item rdfs:label ?label. FILTER(LANG(?label) = "en") }
      OPTIONAL { ?item schema:description ?description. FILTER(LANG(?description) = "en") }
      OPTIONAL { ?item wdt:P176 ?manufacturer. }
      OPTIONAL { ?item wdt:P8566 ?datasheet. }
      SERVICE wikibase:label { bd:serviceParam wikibase:language "en". }
    }
    LIMIT 5000
    """
    
    url = "https://query.wikidata.org/sparql"
    response = requests.get(url, params={'query': query, 'format': 'json'})
    
    if response.status_code == 200:
        data = response.json()
        added = 0
        for item in data['results']['bindings']:
            mpn = item.get('mpn', {}).get('value', 'N/A')
            label = item.get('label', {}).get('value', '')
            description = item.get('description', {}).get('value', '')
            
            # Skip entries without MPN
            if mpn == 'N/A':
                continue
                
            # Insert into database
            cursor.execute("""
                INSERT OR IGNORE INTO components (mpn, description, source, confidence)
                VALUES (?, ?, 'wikidata', 0.9)
            """, (mpn, f"{label} - {description}"[:200]))
            added += 1
        
        conn.commit()
        print(f"Added {added} components from Wikidata")
    
    conn.close()

if __name__ == "__main__":
    parse_wikidata("index.db")
