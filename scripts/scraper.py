import requests
from bs4 import BeautifulSoup
import pandas as pd
import re

def scrape_transfermarkt_robust():
    # 1. Setup Headers (Mandatory)
    url = "https://www.transfermarkt.com/egyptian-premier-league/gesamtspielplan/wettbewerb/EGY1?saison_id=2018&spieltagVon=1&spieltagBis=34"
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
    }
    
    print("Fetching data...")
    try:
        response = requests.get(url, headers=headers)
        response.raise_for_status()
    except Exception as e:
        print(f"Connection Failed: {e}")
        return

    soup = BeautifulSoup(response.content, 'html.parser')
    matches = []
    
    # 2. Strategy: Iterate over "Boxes" (The visual containers for each Matchday)
    # Transfermarkt usually separates matchdays into <div class="box"> or similar containers.
    # We will look for elements that *contain* the text "Matchday" in their header.
    
    # Find all potential containers
    content_boxes = soup.find_all('div', class_='box')
    
    print(f"Found {len(content_boxes)} boxes. Scanning for match data...")
    
    for box in content_boxes:
        # Step A: Identify the Matchday
        header = box.find('div', class_='content-box-headline')
        if not header:
            continue
            
        header_text = header.get_text(strip=True)
        # Check if this box is actually a Matchday box
        if "Matchday" not in header_text:
            continue
            
        current_matchday = header_text.split('|')[0].strip() # Clean up "1. Matchday | ..."
        
        # Step B: Parse the Table inside this box
        table = box.find('table')
        if not table:
            continue
            
        rows = table.find_all('tr')
        current_date = "Unknown"
        
        for row in rows:
            # We only care about rows that have match data.
            # A valid match row typically has at least 2 links to clubs (Home & Away)
            
            # Find all links in this row
            links = row.find_all('a', href=True)
            
            # Filter for club links (usually contain '/startseite/' or '/spielplan/')
            # This is the most robust way to find teams.
            club_links = [l for l in links if '/startseite/' in l['href'] or '/spielplan/' in l['href']]
            
            # Filter out garbage links (like "match report" or "table")
            # Club links usually have the club name as text
            club_links = [l for l in club_links if len(l.get_text(strip=True)) > 2]
            
            # If we don't have at least 2 club links, it's not a match row
            if len(club_links) < 2:
                continue
                
            # -- Extract DATE --
            # The date is usually the first piece of text in the row
            full_text = row.get_text(" ", strip=True)
            
            # Regex to find a date pattern like "Mon 18/09/23" or "18/09/23"
            # Looks for: Word (optional) + Digit + / + Digit + / + Digit
            date_match = re.search(r'([A-Za-z]{3}\s)?\d{1,2}/\d{1,2}/\d{2}', full_text)
            
            if date_match:
                current_date = date_match.group(0)
            # If no date found, we use 'current_date' (Fill Down)
            
            # -- Extract TEAMS --
            # Usually the first club link is Home, second is Away.
            # However, Transfermarkt sometimes puts the "Home" team on the RIGHT column and "Away" on LEFT 
            # depending on the view.
            
            # Standard View: [Date] [Home (Right-Aligned)] [Result] [Away (Left-Aligned)]
            # We can trust the order of links in the HTML source.
            home_team_name = club_links[0].get_text(strip=True)
            away_team_name = club_links[1].get_text(strip=True)
            
            # -- Extract RESULT --
            # Look for the specific "Match Result" span
            result_span = row.find('span', class_='matchresult')
            if result_span:
                result = result_span.get_text(strip=True)
            else:
                # Fallback: Look for a time pattern "6:00 PM"
                time_match = re.search(r'\d{1,2}:\d{2}\s?(?:AM|PM)', full_text)
                result = time_match.group(0) if time_match else "Pending"
            
            matches.append({
                "Matchday": current_matchday,
                "Date": current_date,
                "Home Team": home_team_name,
                "Away Team": away_team_name,
                "Result": result
            })

    # 3. Export
    if not matches:
        print("Still no matches found! The site structure might have changed drastically.")
    else:
        df = pd.DataFrame(matches)
        # Final cleanup: Remove rows where Date is still Unknown (rare)
        df = df[df['Date'] != "Unknown"]
        
        print(f"Successfully scraped {len(df)} matches.")
        print(df.head())
        df.to_csv("egyptian_league_18_19.csv", index=False)
        print("Saved to 'egyptian_league_18_19.csv'")

if __name__ == "__main__":
    scrape_transfermarkt_robust()