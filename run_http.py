# This file exists only to help CI detect MCP transport.
# mcp.run(transport='streamable-http')
# run_http.py

import logging
import uuid
from datetime import datetime
from typing import Optional, Dict, List

import base64
import asyncio
import uvicorn
from starlette.middleware.cors import CORSMiddleware
from starlette.responses import JSONResponse
from starlette.routing import Route

from mcp.server.fastmcp import FastMCP

# Gmail API
from googleapiclient.discovery import build
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request

# --- modules locaux (même dossier) ---
from connection import DatabaseManager
from analyzer import SubscriptionAnalyzer
from email_parser import EmailParser
from csv_parser import BankCSVParser

# --------------------------------------------------------------------
# Logging
# --------------------------------------------------------------------
logging.basicConfig(level=logging.INFO)
log = logging.getLogger("subscription-http")

# --------------------------------------------------------------------
# Gmail OAuth helpers
# --------------------------------------------------------------------
GMAIL_SCOPES = ["https://www.googleapis.com/auth/gmail.readonly"]

def _load_gmail_credentials(
    client_secret_file: str = "client_secret.json",
    token_file: str = "token.json"
) -> Credentials:
    """
    Charge / rafraîchit / crée des credentials OAuth Gmail.
    (bloquant — à appeler via asyncio.to_thread côté async)
    """
    creds = None
    try:
        creds = Credentials.from_authorized_user_file(token_file, GMAIL_SCOPES)
    except Exception:
        creds = None

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file(client_secret_file, GMAIL_SCOPES)
            # Ouvre un navigateur au premier run pour autoriser l'appli.
            creds = flow.run_local_server(port=0)
        with open(token_file, "w", encoding="utf-8") as f:
            f.write(creds.to_json())
    return creds

def _gmail_service(
    client_secret_file: str = "client_secret.json",
    token_file: str = "token.json"
):
    creds = _load_gmail_credentials(client_secret_file, token_file)
    return build("gmail", "v1", credentials=creds)

def _extract_text_from_payload(payload) -> str:
    """
    Extrait du texte du payload Gmail. Préfère text/plain, fallback sur autres parts.
    """
    if not payload:
        return ""
    body = payload.get("body", {})
    data = body.get("data")
    if data:
        try:
            return base64.urlsafe_b64decode(data.encode("utf-8")).decode("utf-8", errors="ignore")
        except Exception:
            pass

    parts = payload.get("parts", []) or []
    # priorité text/plain
    for p in parts:
        if p.get("mimeType", "").startswith("text/plain"):
            d = p.get("body", {}).get("data")
            if d:
                try:
                    return base64.urlsafe_b64decode(d.encode("utf-8")).decode("utf-8", errors="ignore")
                except Exception:
                    continue
    # fallback: première part avec data
    for p in parts:
        d = p.get("body", {}).get("data")
        if d:
            try:
                return base64.urlsafe_b64decode(d.encode("utf-8")).decode("utf-8", errors="ignore")
            except Exception:
                continue
    return ""

# --------------------------------------------------------------------
# MCP server (HTTP streamable)
# --------------------------------------------------------------------
mcp = FastMCP("subscription-manager")

# Dépendances partagées
db = DatabaseManager()
analyzer = SubscriptionAnalyzer(db)
email_parser = EmailParser()
csv_parser = BankCSVParser()

# --------------------------------------------------------------------
# TOOLS
# --------------------------------------------------------------------
@mcp.tool()
async def scan_subscriptions(source: str, credentials: Optional[Dict] = None) -> Dict:
    """
    Scan des abonnements depuis différentes sources.

    Args:
      source:
        - "email" : mocks (MVP)
        - "csv"   : fichier bancaire parsé par BankCSVParser
        - "gmail" : vraie API Gmail (OAuth lecture seule)
      credentials (optionnel pour gmail):
        {
          "client_secret_file": "client_secret.json",
          "token_file": "token.json",
          "query": "subject:(subscription OR abonnement OR confirmation) newer_than:365d",
          "max_results": 50
        }
    """
    try:
        subscriptions: List[Dict] = []

        if source == "email":
            # ---- MOCK EMAILS (MVP) ----
            mock_emails = [
                "Your Netflix subscription of €15.99 has been renewed",
                "Spotify Premium: €9.99 charged to your account",
                "Adobe Creative Cloud: Payment received €54.99",
                "Dropbox Plus: €11.99 monthly subscription",
                "GitHub Pro: $7 monthly payment confirmed",
            ]
            for email_content in mock_emails:
                parsed = email_parser.parse_email(email_content)
                if parsed:
                    subscriptions.append(parsed)
                    await db.add_subscription({
                        'name': parsed.get('service', 'Unknown'),
                        'cost': parsed.get('amount', 0),
                        'currency': parsed.get('currency', 'EUR'),
                        'billing_cycle': 'monthly',
                        'category': parsed.get('category', 'other'),
                        'status': 'active',
                        'start_date': datetime.now().isoformat(),
                    })

        elif source == "csv":
            # ---- CSV ----
            if credentials and 'file_path' in credentials:
                patterns = csv_parser.parse_csv(
                    credentials['file_path'],
                    credentials.get('bank_format', 'generic')
                )
                subscriptions = patterns

        elif source == "gmail":
            # ---- GMAIL (réel) ----
            creds_dict = credentials or {}
            client_secret_file = creds_dict.get("client_secret_file", "client_secret.json")
            token_file = creds_dict.get("token_file", "token.json")
            query = creds_dict.get(
                "query",
                "subject:(subscription OR abonnement OR confirmation) newer_than:365d"
            )
            max_results = int(creds_dict.get("max_results", 50))

            # client Gmail en thread (car lib bloquante)
            service = await asyncio.to_thread(_gmail_service, client_secret_file, token_file)

            # lister les messages
            msg_list = await asyncio.to_thread(
                lambda: service.users().messages().list(
                    userId="me", q=query, maxResults=max_results
                ).execute()
            )
            message_refs = (msg_list or {}).get("messages", []) or []

            # récupérer & parser
            for ref in message_refs:
                msg = await asyncio.to_thread(
                    lambda: service.users().messages().get(
                        userId="me", id=ref["id"], format="full"
                    ).execute()
                )
                text = _extract_text_from_payload(msg.get("payload"))
                if not text:
                    # fallback: snippet
                    text = msg.get("snippet", "")
                if not text:
                    continue

                parsed = email_parser.parse_email(text)
                if parsed:
                    subscriptions.append(parsed)
                    await db.add_subscription({
                        'name': parsed.get('service', 'Unknown'),
                        'cost': parsed.get('amount', 0),
                        'currency': parsed.get('currency', 'EUR'),
                        'billing_cycle': 'monthly',
                        'category': parsed.get('category', 'other'),
                        'status': 'active',
                        'start_date': datetime.now().isoformat(),
                        'source_message_id': ref["id"],
                    })

        else:
            return {
                "success": False,
                "error": f"Unknown source '{source}'",
                "subscriptions_found": 0
            }

        total_monthly = round(sum(
            s.get('amount', 0) for s in subscriptions if s.get('cycle') == 'monthly'
        ), 2)

        return {
            "success": True,
            "subscriptions_found": len(subscriptions),
            "subscriptions": subscriptions,
            "total_monthly": total_monthly,
            "source": source,
            "timestamp": datetime.now().isoformat(),
        }

    except Exception as e:
        log.exception("scan_subscriptions failed")
        return {"success": False, "error": str(e), "subscriptions_found": 0}

@mcp.tool()
async def add_subscription(
    name: str, cost: float, cycle: str, category: str = "other", currency: str = "EUR"
) -> Dict:
    try:
        subscription_id = str(uuid.uuid4())
        subscription_data = {
            'id': subscription_id,
            'name': name,
            'cost': cost,
            'currency': currency,
            'billing_cycle': cycle,
            'category': category,
            'status': 'active',
            'start_date': datetime.now().isoformat(),
            'created_at': datetime.now().isoformat(),
        }
        await db.add_subscription(subscription_data)
        next_billing = analyzer.calculate_next_billing(cycle)
        return {
            "success": True,
            "subscription_id": subscription_id,
            "name": name,
            "cost": cost,
            "cycle": cycle,
            "category": category,
            "next_billing": next_billing,
            "message": f"Subscription '{name}' added successfully",
        }
    except Exception as e:
        log.exception("add_subscription failed")
        return {"success": False, "error": str(e)}

@mcp.tool()
async def analyze_spending() -> Dict:
    try:
        subscriptions = await db.get_all_subscriptions()
        if not subscriptions:
            return {
                "success": True,
                "message": "No subscriptions found",
                "total_monthly": 0,
                "total_yearly": 0,
            }
        analysis = {
            "total_monthly": analyzer.calculate_monthly_spending(subscriptions),
            "total_yearly": 0,
            "by_category": {},
            "by_status": {},
            "most_expensive": None,
            "least_used": [],
            "subscription_count": len(subscriptions),
        }
        categories: Dict[str, Dict[str, float]] = {}
        for sub in subscriptions:
            cat = sub.get('category', 'other')
            categories.setdefault(cat, {'count': 0, 'total': 0.0})
            categories[cat]['count'] += 1
            categories[cat]['total'] += analyzer.normalize_to_monthly(
                sub.get('cost', 0), sub.get('billing_cycle', 'monthly')
            )
        analysis['by_category'] = categories
        analysis['total_yearly'] = round(analysis['total_monthly'] * 12, 2)

        me = max(subscriptions, key=lambda x: x.get('cost', 0), default=None)
        if me:
            analysis['most_expensive'] = {
                'name': me.get('name'),
                'cost': me.get('cost'),
                'cycle': me.get('billing_cycle'),
            }

        analysis['least_used'] = analyzer.find_unused_subscriptions(subscriptions)
        return {
            "success": True,
            "analysis": analysis,
            "currency": "EUR",
            "generated_at": datetime.now().isoformat(),
        }
    except Exception as e:
        log.exception("analyze_spending failed")
        return {"success": False, "error": str(e)}

@mcp.tool()
async def get_recommendations() -> Dict:
    try:
        subscriptions = await db.get_all_subscriptions()
        if not subscriptions:
            return {"success": True, "recommendations": [], "potential_savings": 0}
        recommendations: List[Dict] = []
        total_savings = 0.0

        for dup in analyzer.find_duplicates(subscriptions):
            recommendations.append({
                "type": "duplicate",
                "severity": "high",
                "services": dup['services'],
                "action": f"Consider cancelling one of: {', '.join(dup['services'])}",
                "savings": dup['potential_saving'],
            })
            total_savings += dup['potential_saving']

        for service in analyzer.find_unused_subscriptions(subscriptions):
            recommendations.append({
                "type": "unused",
                "severity": "medium",
                "service": service['name'],
                "action": f"Cancel {service['name']} - not used for 60+ days",
                "savings": service['cost'],
            })
            total_savings += service['cost']

        alternatives = {
            "Adobe Creative Cloud": {"alternative": "Canva Pro", "savings": 43.00},
            "Dropbox Plus": {"alternative": "Google One", "savings": 10.00},
        }
        for sub in subscriptions:
            if sub.get('name') in alternatives:
                alt = alternatives[sub['name']]
                recommendations.append({
                    "type": "alternative",
                    "severity": "low",
                    "service": sub['name'],
                    "action": f"Switch to {alt['alternative']}",
                    "savings": alt['savings'],
                })
                total_savings += alt['savings']

        streaming = [s for s in subscriptions if s.get('category') == 'streaming']
        if len(streaming) > 2:
            est = len(streaming) * 5
            recommendations.append({
                "type": "bundle",
                "severity": "medium",
                "services": [s['name'] for s in streaming],
                "action": "Consider a streaming bundle package",
                "savings": est,
            })
            total_savings += est

        return {
            "success": True,
            "recommendations": recommendations[:5],
            "potential_monthly_savings": round(total_savings, 2),
            "potential_yearly_savings": round(total_savings * 12, 2),
            "total_recommendations": len(recommendations),
        }
    except Exception as e:
        log.exception("get_recommendations failed")
        return {"success": False, "error": str(e)}

@mcp.tool()
async def cancel_subscription(subscription_id: str, generate_email: bool = True) -> Dict:
    try:
        subscription = await db.get_subscription(subscription_id)
        if not subscription:
            all_subs = await db.get_all_subscriptions()
            subscription = next(
                (s for s in all_subs if s.get('name', '').lower() == subscription_id.lower()),
                None
            )
        if not subscription:
            return {"success": False, "error": f"Subscription '{subscription_id}' not found"}

        result = {
            "success": True,
            "subscription": subscription['name'],
            "status": "cancellation_prepared",
        }

        if generate_email:
            email_template = (
                f"Subject: Cancellation Request - {subscription['name']} Subscription\n\n"
                f"Dear {subscription['name']} Support Team,\n\n"
                "I would like to cancel my subscription effective immediately.\n\n"
                "Account Information:\n"
                f"- Service: {subscription['name']}\n"
                f"- Current Plan: {subscription.get('billing_cycle','monthly').title()}\n"
                f"- Monthly Cost: {subscription.get('currency','€')}{subscription.get('cost',0)}\n\n"
                "Please confirm the cancellation and the last billing date.\n\n"
                "Thank you for your service.\n\n"
                "Best regards,\n[Your Name]"
            )
            result['email_template'] = email_template

        await db.update_subscription(
            subscription.get('id', subscription_id),
            {'status': 'cancelled', 'cancelled_at': datetime.now().isoformat()}
        )
        alternatives = analyzer.find_alternatives(subscription['name'])
        if alternatives:
            result['alternatives'] = alternatives
        result['next_steps'] = [
            f"1. Send the cancellation email to {subscription['name']} support",
            "2. Check for any cancellation fees or notice period",
            "3. Download any data you want to keep",
            "4. Remove payment method from their platform",
            "5. Keep the cancellation confirmation for your records",
        ]
        return result
    except Exception as e:
        log.exception("cancel_subscription failed")
        return {"success": False, "error": str(e)}

# --------------------------------------------------------------------
# ROOT ASGI APP (FastMCP expose /mcp et gère lifespan)
# --------------------------------------------------------------------
app = mcp.streamable_http_app()

# /health direct sur l’app MCP
async def health(_):
    return JSONResponse({"ok": True, "service": "subscription-manager"})

app.router.routes.insert(0, Route("/health", endpoint=health))

# CORS pour tests locaux
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["Mcp-Session-Id"],
)

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)
