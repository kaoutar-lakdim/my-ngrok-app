# csv_parser.py
import csv
from typing import List, Dict

class BankCSVParser:
    def parse_csv(self, file_path: str, bank_format: str = "generic") -> List[Dict]:
        patterns = []
        with open(file_path, newline='', encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                desc = (row.get("description") or row.get("libelle") or "").lower()
                try:
                    amt = float(row.get("amount") or row.get("montant") or 0)
                except ValueError:
                    continue
                for svc in ["netflix","spotify","adobe creative cloud","dropbox","github pro"]:
                    if svc in desc:
                        name = "GitHub Pro" if "github" in svc else svc.title()
                        patterns.append({
                            "service": name,
                            "amount": abs(amt),
                            "currency": "EUR",
                            "cycle": "monthly",
                            "category": "streaming" if name in ("Netflix","Spotify") else "other"
                        })
                        break
        return patterns
