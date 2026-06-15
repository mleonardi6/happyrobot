import atexit
import json
import random

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Header
from posthog import Posthog
from pydantic import BaseModel
import requests
import os

load_dotenv()

FMCSA_KEY = os.getenv("FMCSA_WEB_KEY")
API_KEY = os.getenv("API_KEY")

posthog_client = Posthog(
    os.getenv("POSTHOG_PROJECT_TOKEN", ""),
    host=os.getenv("POSTHOG_HOST", "https://us.i.posthog.com"),
    enable_exception_autocapture=True,
)
atexit.register(posthog_client.shutdown)


app = FastAPI()

FMCSA_BASE_URL = "https://mobile.fmcsa.dot.gov/qc/services"

STATE_ABBREVIATIONS = {
    "Alabama": "AL",
    "Alaska": "AK",
    "Arizona": "AZ",
    "Arkansas": "AR",
    "California": "CA",
    "Colorado": "CO",
    "Connecticut": "CT",
    "Delaware": "DE",
    "Florida": "FL",
    "Georgia": "GA",
    "Hawaii": "HI",
    "Idaho": "ID",
    "Illinois": "IL",
    "Indiana": "IN",
    "Iowa": "IA",
    "Kansas": "KS",
    "Kentucky": "KY",
    "Louisiana": "LA",
    "Maine": "ME",
    "Maryland": "MD",
    "Massachusetts": "MA",
    "Michigan": "MI",
    "Minnesota": "MN",
    "Mississippi": "MS",
    "Missouri": "MO",
    "Montana": "MT",
    "Nebraska": "NE",
    "Nevada": "NV",
    "New Hampshire": "NH",
    "New Jersey": "NJ",
    "New Mexico": "NM",
    "New York": "NY",
    "North Carolina": "NC",
    "North Dakota": "ND",
    "Ohio": "OH",
    "Oklahoma": "OK",
    "Oregon": "OR",
    "Pennsylvania": "PA",
    "Rhode Island": "RI",
    "South Carolina": "SC",
    "South Dakota": "SD",
    "Tennessee": "TN",
    "Texas": "TX",
    "Utah": "UT",
    "Vermont": "VT",
    "Virginia": "VA",
    "Washington": "WA",
    "West Virginia": "WV",
    "Wisconsin": "WI",
    "Wyoming": "WY",
    "District of Columbia": "DC"
}


class MCRequest(BaseModel):
    mc_number: str

class LoadRequest(BaseModel):
    load_id: str = ""
    state: str = ""

class AnalyticsPayload(BaseModel):
    rate: str | None = None
    load_id: str | None = None
    agreement: bool | None = None
    mc_number: str | None = None
    carrier_name: str | None = None
    call_classification: str | None = None
    sentiment_classification: str | None = None
    negotiated: bool | None = None

def get_carrier_by_docket(docket_number: str) -> dict:
    url = f"{FMCSA_BASE_URL}/carriers/docket-number/{docket_number}"

    params = {"webKey": FMCSA_KEY}
    headers = {"Accept": "application/json"}

    response = requests.get(url, params=params, headers=headers, timeout=10)

    if response.status_code != 200:
        posthog_client.capture("server", "carrier_check_failed", properties={
            "status_code": response.status_code,
        })
        posthog_client.flush()
        raise HTTPException(
            status_code=response.status_code,
            detail=f"FMCSA request failed: {response.text}"
        )


    return response.json()

def extract_carrier(data: dict) -> dict:
    try:
        return data["content"][0]["carrier"]
    except Exception:
        raise HTTPException(status_code=500, detail="Invalid FMCSA response format")

def evaluate_carrier(carrier: dict) -> dict:
    allowed = carrier.get("allowedToOperate") == "Y"
    authority = carrier.get("commonAuthorityStatus")
    power_units = carrier.get("totalPowerUnits", 0)

    issues = []

    if not allowed:
        issues.append("Not allowed to operate")

    if authority != "A":
        issues.append(f"Authority not active ({authority})")

    if power_units < 1:
        issues.append("No active trucks")

    return {
        "can_book_load": len(issues) == 0,
        "issues": issues,
        "carrier": {
            "legal_name": carrier.get("legalName"),
            "dot_number": carrier.get("dotNumber"),
            "city": carrier.get("phyCity"),
            "state": carrier.get("phyState"),
            "authority": authority,
            "power_units": power_units
        }
    }

@app.post("/check-carrier")
def check_carrier(
    payload: MCRequest,
    x_api_key: str = Header(None)  # API key passed in header
):

    if not API_KEY:
        raise HTTPException(status_code=500, detail="Server missing API key config")

    if x_api_key != API_KEY:
        raise HTTPException(status_code=401, detail="Invalid API key")

    mc_number = payload.mc_number

    # 1. Fetch FMCSA data
    raw = get_carrier_by_docket(mc_number)

    print(f"FMCSA raw response: {json.dumps(raw)}")  # Debug log

    # 2. Extract carrier object
    carrier = extract_carrier(raw)

    print(f"Extracted carrier: {json.dumps(carrier)}")  # Debug log

    # 3. Evaluate validity
    result = evaluate_carrier(carrier)

    posthog_client.capture("server", "carrier_checked", properties={
        "can_book_load": result["can_book_load"],
        "has_issues": len(result["issues"]) > 0,
        "issue_count": len(result["issues"]),
        "authority_status": result["carrier"]["authority"],
        "power_units": result["carrier"]["power_units"],
        "carrier_state": result["carrier"]["state"],
    })
    posthog_client.flush()

    return result

@app.post("/load")
def get_load(payload: LoadRequest, x_api_key: str = Header(None)):

    if not API_KEY:
        raise HTTPException(status_code=500, detail="Server missing API key config")
    if x_api_key != API_KEY:
        raise HTTPException(status_code=401, detail="Invalid API key")

    with open("loads.json", "r") as f:
        loads = json.load(f)

    # load_id takes precedence
    if payload.load_id != "":
        selection_method = "by_id"
        load_id = payload.load_id
    elif payload.state != "":
        selection_method = "by_state"
        # Search for a load in the provided state
        state_input = payload.state.casefold()
        state_abbr = None

        # Find the state abbreviation
        for full_name, abbr in STATE_ABBREVIATIONS.items():
            if full_name.casefold() == state_input:
                state_abbr = abbr
                break

        if not state_abbr:
            posthog_client.capture("server", "load_not_found", properties={
                "selection_method": selection_method,
                "reason": "invalid_state",
            })
            posthog_client.flush()
            raise HTTPException(status_code=400, detail=f"Invalid state: {payload.state}")

        # Filter loads by state (origin ends with ", STATE")
        matching_loads = {
            load_id: load for load_id, load in loads.items()
            if load["origin"].endswith(f", {state_abbr}")
        }

        if not matching_loads:
            posthog_client.capture("server", "load_not_found", properties={
                "selection_method": selection_method,
                "reason": "no_matching_loads",
            })
            posthog_client.flush()
            raise HTTPException(status_code=404, detail=f"No loads found for state: {payload.state}")

        load_id = random.choice(list(matching_loads.keys()))
    else:
        selection_method = "random"
        # No load_id or state provided, pick random
        load_id = random.choice(list(loads.keys()))

    load = loads.get(load_id)

    if not load:
        posthog_client.capture("server", "load_not_found", properties={
            "selection_method": selection_method,
            "reason": "load_id_not_found",
        })
        posthog_client.flush()
        raise HTTPException(status_code=404, detail="Load not found")


    posthog_client.capture("server", "load_retrieved", properties={
        "selection_method": selection_method,
    })
    posthog_client.flush()

    return {
        "status": "success",
        "data": load
    }

@app.post("/analytics")
async def analytics(
    payload: AnalyticsPayload,
    x_api_key: str = Header(...)
):
    if x_api_key != API_KEY:
        raise HTTPException(status_code=401)

    if payload.mc_number and payload.carrier_name:
        posthog_client.set(
            distinct_id=payload.mc_number,
            properties={"carrier_name": payload.carrier_name},
        )
        posthog_client.flush()

    # Query load data if load_id provided
    load_data = {}
    if payload.load_id:
        with open("loads.json", "r") as f:
            loads = json.load(f)
        load = loads.get(payload.load_id)
        if load:
            origin_state = load["origin"].split(", ")[1] if ", " in load["origin"] else None
            destination_state = load["destination"].split(", ")[1] if ", " in load["destination"] else None
            
            load_data = {
                "equipment_type": load.get("equipment_type"),
                "commodity_type": load.get("commodity_type"),
                "miles": load.get("miles"),
                "origin_state": origin_state,
                "destination_state": destination_state,
            }

    posthog_client.capture(
        distinct_id=payload.mc_number or "unknown",
        event="call_completed",
        properties={
            "rate": payload.rate or None,
            "agreement": payload.agreement,
            "call_classification": payload.call_classification,
            "sentiment_classification": payload.sentiment_classification,
            "negotiated": payload.negotiated,
            **load_data,
        },
    )
    posthog_client.flush()

    return {
        "success": True
    }