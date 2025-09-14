import re
class EmailParser:
    def parse_email(self, text: str):
        text = text.lower()

        # Cherche un montant
        amount_match = re.search(r'(\d+[.,]?\d*)\s?(€|\$)', text)
        amount = float(amount_match.group(1).replace(',', '.')) if amount_match else 0
        currency = amount_match.group(2) if amount_match else "EUR"

        # Cherche un service (ex: BasicFit, Spotify, etc.)
        services = ["basicfit", "powerprot", "watch watch", "radiojazz", "google cloud"]
        service = next((s for s in services if s in text), "Unknown")

        # Catégorisation simple
        category = "fitness" if "fit" in service else "entertainment"

        return {
            "service": service.title(),
            "amount": amount,
            "currency": currency,
            "cycle": "monthly",
            "category": category,
        }
