"""fix_codesets_scraper.py

Scrapes FIX code-sets and standard values from fiximate.fixtrading.org and
emits a JSON file `fix_code_sets.json` containing metadata and stdValues
for each code set.

Behavior:
- Fetches the main fields page, parses the table of code-sets.
- Follows detail links (concurrently) to extract standard values found in
    the description column's nested table. Only rows where the nested row
    has three TDs and the middle TD contains '=' are accepted. The first TD
    is used as `id` and the third TD is used as `description`.
- Writes output JSON with fields: createdTime, version, author, fixData.

Usage: run `python fix_codesets_scraper.py` (requires `beautifulsoup4`, `requests`)

Author: Ajin Nair
"""

import requests
from bs4 import BeautifulSoup
import json
import os
from datetime import datetime
import time
from tqdm import tqdm
import warnings
import urllib3
from datetime import timezone
# Import SSL-related warning classes if available (older urllib3 versions may omit some)
try:
    from urllib3.exceptions import InsecureRequestWarning
except Exception:
    InsecureRequestWarning = None

try:
    from urllib3.exceptions import SNIMissingWarning

except Exception:
    SNIMissingWarning = None

# Silently ignore the warnings that exist in this environment.
if InsecureRequestWarning is not None:
    warnings.filterwarnings('ignore', category=InsecureRequestWarning)
if SNIMissingWarning is not None:
    warnings.filterwarnings('ignore', category=SNIMissingWarning)

# Also disable urllib3 warnings globally (convenient when running many requests).
urllib3.disable_warnings()


def load_env(path='.env'):
    """Simple .env loader: returns dict of key->value. Ignores comments and blank lines."""
    env = {}
    try:
        with open(path, 'r') as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith('#'):
                    continue
                if '=' not in line:
                    continue
                key, val = line.split('=', 1)
                key = key.strip()
                val = val.strip().strip('"').strip("'")
                env[key] = val
    except FileNotFoundError:
        # No .env present is fine
        pass
    return env

def fetch_fix_code_sets():
    # Step 1: Fetch the main page with FIX code sets
    #url = "https://fiximate.fixtrading.org/en/FIX.Latest/codesets_sorted_by_name.html"
    url = "https://fiximate.fixtrading.org/en/FIX.Latest/fields_sorted_by_tagnum.html"
    response = requests.get(url)

    # Check if the request was successful
    if response.status_code != 200:
        print(f"Failed to fetch the main page: {response.status_code}")
        return

    soup = BeautifulSoup(response.content, 'html.parser')

    # Step 2: Find the table containing the code sets
    table = soup.find('table')
    if table is None:
        print("No table found on the main page.")
        return

    rows = table.find_all('tr')
    # If the table has a header row, try to skip it by checking number of header cells
    if len(rows) > 0 and rows[0].find_all(['th', 'td']):
        # assume first row is header if it contains <th> or matches expected headings
        rows = rows[1:]

    data_dict = {}

    # Step 3: Extract links and corresponding details
    # Collect code set metadata first, then fetch details concurrently
    code_sets = []
    # map detail-page link -> list of code_set_names that reference it
    link_to_names = {}
    seen_links = set()
    for row in rows:
        cols = row.find_all('td')
        if not cols:
            continue

        code_set_name = cols[1].text.strip()
        #tag_name = code_set_name.split('CodeSet')[0].strip()
        anchor = cols[0].find('a')
        # Best-effort extraction of other metadata (guard against missing cols)
        tag_id = cols[0].text.strip() if len(cols) > 1 else ''
        datatype = cols[4].text.strip() if len(cols) > 4 else ''
        description = cols[6].text.strip() if len(cols) > 6 else ''

        if anchor is None or not anchor.get('href'):
            print(f"No link found for code set '{code_set_name}', skipping.")
            continue

        code_set_link = anchor.get('href')  # Extract the link safely
        # Initialize entry with metadata; stdValues will be filled later
        data_dict[code_set_name] = {"tagName": code_set_name, "tagId": tag_id, "description": description, "tagType": datatype, "stdValues": []}

        # record mapping from link -> code set names (multiple names may share a detail page)
        link_to_names.setdefault(code_set_link, []).append(code_set_name)

        # schedule each unique detail link only once
        if code_set_link not in seen_links:
            seen_links.add(code_set_link)
            code_sets.append({
                'link': code_set_link,
            })
    print("codeset count:", len(code_sets))
    #code_sets = code_sets[0:100]  # Limit to first 100 code sets for testing

    # If there are no code sets, skip fetching details
    if code_sets:
        import concurrent.futures

        # Allow configuring a total timeout for all detail fetches via .env
        env_top = load_env('.env')
        try:
            total_timeout = int(env_top.get('TOTAL_TIMEOUT', '300'))
        except Exception:
            total_timeout = 300

        def fetch_details(item):
            """Worker: fetch detail page for a link and return (link, details_list)."""
            link = item['link']
            #print(f"Fetching details for link: {link}")
            url = f"https://fiximate.fixtrading.org/en/FIX.Latest/{link}"
            try:
                resp = requests.get(url, timeout=15)
            except Exception as e:
                print(f"Error fetching {link}: {e}")
                return link, []

            if resp.status_code != 200:
                print(f"Failed to fetch details for {link}: {resp.status_code}")
                return link, []

            soup = BeautifulSoup(resp.content, 'html.parser')
            table = soup.find('table')
            if table is None:
                print(f"No detail table found for {link}.")
                return link, []

            all_rows = table.find_all('tr')
            if not all_rows:
                return link, []

            # Detect header row and column indexes by header text
            header_cells = all_rows[0].find_all(['th', 'td'])
            has_header = bool(header_cells)
            desc_idx = None
            id_idx = None
            if has_header:
                headers = [hc.get_text(strip=True).lower() for hc in header_cells]
                for i, h in enumerate(headers):
                    if 'description' in h:
                        desc_idx = i
                    # pick a reasonable id column if present
                    if id_idx is None and any(k in h for k in ('id', 'value', 'code', 'tag')):
                        id_idx = i

            # default id col to 0 if not found
            if id_idx is None:
                id_idx = 0

            # Only use the explicitly-detected "description" column to build stdValues.
            # Within that column we expect a nested table where rows look like:
            # <tr><td>1</td><td>=</td><td>Some description</td></tr>
            # If no description column is detected, do not populate stdValues.
            if desc_idx is None:
                return link, []

            rows = all_rows[1:] if has_header else all_rows

            details = []
            for r in rows:
                cols = r.find_all('td')
                if not cols or len(cols) <= desc_idx:
                    continue

                desc_td = cols[desc_idx]
                nested_table = desc_td.find('table')
                if nested_table is None:
                    # No nested table in description cell; skip this row
                    continue

                for tr in nested_table.find_all('tr'):
                    tds = tr.find_all('td')
                    if len(tds) < 3:
                        continue
                    sep = tds[1].get_text(strip=True)
                    # require the middle cell to contain '=' to accept this row
                    if '=' not in sep:
                        continue

                    id_text = tds[0].get_text(strip=True)
                    p = tds[2].find('p')
                    desc_text = p.get_text(strip=True) if p else tds[2].get_text(strip=True)
                    if id_text:
                        details.append({'id': id_text, 'description': desc_text})

            return link, details

        # Choose a reasonable worker count; keep small to be polite to the remote server
        max_workers = min(10, max(2, (os.cpu_count() or 2)))
        with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as ex:
            futures = [ex.submit(fetch_details, item) for item in code_sets]
            # Show progress as futures complete. Respect a global timeout (total_timeout).
            start = time.time()
            try:
                for fut in tqdm(concurrent.futures.as_completed(futures, timeout=total_timeout), total=len(futures), desc="Fetching details"):
                    try:
                        link, details = fut.result()
                    except Exception as e:
                        print(f"Worker raised exception: {e}")
                        continue

                    # Attach fetched details into data_dict for all code-set names that reference this link
                    names = link_to_names.get(link, [])
                    if not names:
                        # fallback: store under link key
                        data_dict[link] = {"stdValues": details}
                    else:
                        for cs_name in names:
                            if cs_name in data_dict:
                                data_dict[cs_name]["stdValues"] = details
                            else:
                                data_dict[cs_name] = {"stdValues": details}
            except concurrent.futures.TimeoutError:
                # Some tasks didn't finish within the global timeout
                elapsed = time.time() - start
                remaining = max(0, total_timeout - int(elapsed))
                print(f"Warning: overall timeout of {total_timeout}s reached after {int(elapsed)}s; cancelling remaining tasks")
                for fut in futures:
                    if not fut.done():
                        fut.cancel()
    
    # Convert data_dict (mapping name -> metadata) into an array of objects.
    # Use only the metadata values (no `name` field) as requested.
    code_sets_array = list(data_dict.values())
    fix_data = [{"type": "FIX", "data": code_sets_array}]
    # Read version name from .env (if present) and generate a version string
    env = load_env('.env')
    PER_REQUEST_TIMEOUT = int(env.get('PER_REQUEST_TIMEOUT', '15'))
    TOTAL_TIMEOUT = int(env.get('TOTAL_TIMEOUT', '300'))
    MAX_WORKERS = int(env.get('MAX_WORKERS', '8'))
    version_name = env.get('VERSION_NAME')
    timestamp_for_version = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    if version_name:
        version = f"{version_name}+{timestamp_for_version}"
    else:
        version = timestamp_for_version

    json_output_dict = {
        "createdTime": datetime.now().replace(microsecond=0).isoformat() + "Z",
        "version": version,
        "author": env.get('AUTHOR'),
        "fixData": fix_data,
    }

    # Step 5: Save the data to a JSON file
    with open('fix_code_sets.json', 'w') as json_file:
        json.dump(json_output_dict, json_file, indent=4)

    # Print a friendly success message in green so it's easy to spot in the terminal
    GREEN = "\033[32m"
    RESET = "\033[0m"
    print(f"{GREEN}Data has been saved to fix_code_sets.json{RESET}")

if __name__ == "__main__":
    try:
        print("Starting to fetch FIX code sets...")
        fetch_fix_code_sets()
    except Exception as e:
        print(f"An error occurred: {e}")
#         Exception: If any step in the process fails
#     """
