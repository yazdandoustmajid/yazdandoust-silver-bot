# Yazdandoust Silver Store

Store + Telegram Mini App starter for Yazdandoust Silver.

## Categories
- Silver shot 995
- Silver bullion
- 925 silver products
  - Service
  - Half-set
  - Earrings
  - Rings

## Pricing
925 products: weight (grams) × global 925 product price-per-gram.
Silver shot 995 uses the configurable base price plus the weight markup rules.

## Run locally
1. Python 3.11+
2. `python -m venv .venv`
3. Activate the environment
4. `pip install -r requirements.txt`
5. `python app.py`
6. Open http://127.0.0.1:8000

Admin:
- http://127.0.0.1:8000/admin

This is intentionally separate from the existing GitHub Actions bot. The current bot can later publish its live 995 price to this API without changing its core logic.
