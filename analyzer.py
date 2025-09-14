from datetime import datetime, timedelta
from typing import List, Dict

class SubscriptionAnalyzer:
    def __init__(self, db):
        self.db = db

    def calculate_next_billing(self, cycle: str) -> str:
        now = datetime.now()
        if cycle == "yearly":
            return (now.replace(microsecond=0) + timedelta(days=365)).isoformat()
        return (now.replace(microsecond=0) + timedelta(days=30)).isoformat()

    def normalize_to_monthly(self, cost: float, cycle: str) -> float:
        if cycle == "yearly":
            return round(cost / 12.0, 2)
        return float(cost)

    def calculate_monthly_spending(self, subs: List[Dict]) -> float:
        total = 0.0
        for s in subs:
            total += self.normalize_to_monthly(s.get('cost', 0.0), s.get('billing_cycle','monthly'))
        return round(total, 2)

    def find_unused_subscriptions(self, subs: List[Dict]) -> List[Dict]:
        # MVP: renvoie vide (ou une détection bidon)
        return []

    def find_duplicates(self, subs: List[Dict]) -> List[Dict]:
        # MVP: group by name lower; si doublons => saving = cost d'un
        seen = {}
        dups = []
        for s in subs:
            k = s.get('name','').strip().lower()
            seen.setdefault(k, []).append(s)
        for k, lst in seen.items():
            if len(lst) > 1:
                saving = min([x.get('cost',0) for x in lst])
                dups.append({"services":[x.get('name') for x in lst], "potential_saving": saving})
        return dups

    def find_alternatives(self, name: str):
        # MVP statique
        mapping = {
            "Adobe Creative Cloud": ["Canva Pro", "Affinity Suite"],
            "Dropbox Plus": ["Google One", "iCloud+"]
        }
        return mapping.get(name, [])
