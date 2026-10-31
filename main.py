import hashlib

from db import list_tasks
import os

from dotenv import load_dotenv
from fastapi import FastAPI, Header, HTTPException, Depends

load_dotenv()

A2A_TOKEN = os.getenv("A2A_TOKEN")
A2A_BASE_URL = os.getenv(
    "A2A_BASE_URL",
    "http://localhost:8000/a2a/"
)

if not A2A_TOKEN:
    raise RuntimeError("A2A_TOKEN is missing from .env")

app = FastAPI(
    title="Invoice Action Agent",
    description="Evidence-based invoice decision agent",
    version="1.0.0"
)

# Output modes supported by our agent
PROPOSAL_MODE = (
    "application/vnd.ga5.invoice-action-proposals+json"
)

RECEIPT_MODE = (
    "application/vnd.ga5.invoice-action-receipts+json"
)

INPUT_MODE = (
    "application/vnd.ga5.invoice-claim-batch+json"
)


# Public Agent Card: no authentication required
@app.get("/.well-known/agent-card.json")
async def agent_card():

    return {
        "name": "Invoice Action Agent",
        "description": (
            "An evidence-based invoice agent that evaluates "
            "invoice packages, proposes business actions, "
            "and executes only approved actions."
        ),
        "version": "1.0.0",

        "supportedInterfaces": [
            {
                "url": A2A_BASE_URL,
                "protocolBinding": "HTTP+JSON",
                "protocolVersion": "1.0"
            }
        ],

        "capabilities": {
            "streaming": False,
            "pushNotifications": False,
            "stateTransitionHistory": True
        },

        "defaultInputModes": [
            INPUT_MODE
        ],

        "defaultOutputModes": [
            PROPOSAL_MODE,
            RECEIPT_MODE
        ],

        "skills": [
            {
                "id": "invoice_action_agent",
                "name": "Invoice Action Agent",
                "description": (
                    "Read invoice packages, evaluate evidence, "
                    "propose safe business actions and execute "
                    "only accepted proposals."
                ),
                "tags": [
                    "invoices",
                    "payments",
                    "approval",
                    "evidence",
                    "reconciliation"
                ]
            }
        ]
    }


# Authentication dependency for protected endpoints
async def verify_token(
    authorization: str | None = Header(default=None)
):
    if not authorization:
        raise HTTPException(
            status_code=401,
            detail="Authentication required"
        )

    if not authorization.startswith("Bearer "):
        raise HTTPException(
            status_code=401,
            detail="Bearer authentication required"
        )

    token = authorization[len("Bearer "):].strip()

    if not token:
        raise HTTPException(
            status_code=401,
            detail="Authentication required"
        )

    # Each distinct Bearer token represents a separate user.
    # Store its hash, never the original token.
    return hashlib.sha256(
        token.encode("utf-8")
    ).hexdigest()


# Temporary protected test endpoint.
# We will replace this with SQLite-backed task listing.
@app.get("/a2a/tasks")
async def list_tasks_endpoint(
    principal: str = Depends(verify_token)
):
    return {
        "tasks": list_tasks(principal)
    }