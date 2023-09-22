from __future__ import annotations
from typing import Optional, List
import logging
import requests

# TODO: placeholder for if no model is loaded


def post_request(payload: dict, url: str):
    headers = {"Content-Type": "application/json"}
    response = requests.post(url, headers=headers, json=payload)
    return response.json()


def get_request(payload: dict, url: str):
    headers = {"Content-Type": "application/json"}
    response = requests.get(url, headers=headers, json=payload)
    return response.json()


async def generate_text(
    prompt: str,
    generate_params: Optional[dict] = {},
):
    try:
        payload = {"prompt": prompt, **generate_params}
        response = post_request(payload, "http://127.0.0.1:5000/api/v1/generate")
    except Exception as e:
        logging.error(f"Error in request, have you loaded a model? {e}")
    return response.get("results")[0].get("text")


def count_tokens(text: str):
    try:
        payload = {"prompt": text}
        response = post_request(payload, "http://127.0.0.1:5000/api/v1/token-count")
    except Exception as e:
        logging.error(f"Error in request, have you loaded a model? {e}")
    return response.get("results")[0].get("tokens")
