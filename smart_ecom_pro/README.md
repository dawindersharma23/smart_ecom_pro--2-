# SmartCart AI: Smart E-Commerce Platform with AI Price Predictor & Review Analyzer
MCA Final Year Project · Flask · scikit-learn · SQLite

## Overview
A full-stack e-commerce web app with built-in AI: dynamic pricing for sellers, NLP review intelligence for buyers and admins, product recommendations, order tracking and real payments (Razorpay).

## Features
**Store:** register/login (hashed passwords, sessions), customer/admin roles, search + filter + sort, cart, checkout with stock validation, order history with a status timeline, dark/light theme.
**Admin:** dashboard charts (revenue, category sales, top sellers, sentiment), order management (Placed -> Packed -> Shipped -> Delivered / Cancelled with restock + refund status), CSV exports (products, orders, reviews, price history, prediction log).
**AI modules**
- *Price Predictor:* Gradient Boosting fair price + profit-optimal price from a demand curve, feature importance, 4 charts, CSV download.
- *AI Pricing Optimizer:* per-product suggested price from cost, competitor price, 14-day sales speed, rating and stock; +-15% guardrail; one-click apply; competitor prices editable or uploaded by CSV.
- *Price forecast:* 7-day linear-trend forecast on each product page.
- *Review AI:* TF-IDF + Logistic Regression sentiment with negation handling, model confidence, aspect-wise scores (quality, delivery, price, service), fake-review checks, highlighted key words. Paste many reviews for a full dashboard.
- *Reviews by product name or link:* sentiment, aspects, rating distribution, praise/complaint words, buyer and seller suggestions, CSV/JSON download.
- *Recommender:* "Similar products" (TF-IDF + cosine) and "Customers also bought" (item-item collaborative filtering).
- *Model Lab:* accuracy, F1, confusion matrix, model comparison and actual-vs-predicted plot for models trained on real data.

## Quick start
```
pip install -r requirements.txt
python app.py            # http://127.0.0.1:5000
python -m pytest -q      # automated tests (or run tests/test_app.py)
```
Demo logins: admin `admin@shop.com` / `admin123`; customers `demo1@shop.com` ... `demo25@shop.com` / `demo123`. Change the admin password and `SECRET_KEY` before any real deployment.
Demo data: 40 products, 25 customers, ~180 orders, ~320 analysed reviews, 45-day price history.

## Train on real data
```
python train.py sentiment data/Reviews.csv      # review text + rating/label columns
python train.py price data/products.csv         # selling price, MRP, rating, ratings count, category
```
80/20 split, models compared (LogReg vs Naive Bayes; Linear vs Random Forest vs Gradient Boosting), best model saved to `models/` and loaded automatically on restart. See `data/README.txt`. Until you do this, the models run on synthetic demo data (the 99% scores are not real-world accuracy).

## Payments
- **Razorpay (real gateway):** set `RAZORPAY_KEY_ID` and `RAZORPAY_KEY_SECRET` (Razorpay Dashboard -> API Keys; test-mode keys are free). Checkout switches to Razorpay automatically (UPI, cards, netbanking, wallets). The server decides the amount, creates the Razorpay order and verifies the HMAC signature before marking an order paid (forged, replayed and other-user payments are rejected). For production add the `payment.captured` webhook; live mode needs Razorpay KYC.
- **Demo gateway (no keys):** UPI / Card / COD in test mode. Test card `4242 4242 4242 4242`; declined card `4000 0000 0000 0002`; UPI `test@upi` or `fail@upi`.

## Amazon / Flipkart reviews (browser import)
Amazon and Flipkart block server-side fetching, so the app imports reviews from **your own browser**: open Link Reviews, drag the "Import reviews" bookmarklet to your bookmarks bar, open a product's reviews page and click it. The reviews (with star ratings) open in this app for analysis (charts, suggestions, CSV). Amazon is supported through its `data-hook` markup; Flipkart is a best-effort heuristic because its layout changes often. Tested against mock pages that imitate both layouts (not the live sites). Use for personal research and follow each site's terms of service.

## Train models inside the app (Admin -> Model Lab)
1. Import real rated reviews with the bookmarklet and click "Add rated reviews to the model training set" (4-5 stars = positive, 1-2 = negative).
2. Once you have 200+ (positive and negative), click "Train the sentiment model on the collected reviews". Or upload any Kaggle CSV (reviews or products) in the same card.
3. The model trains in the background, is saved to `models/`, and the Model Lab report (accuracy, F1, confusion matrix) appears.

## Reviews by product name
Set `BRAVE_API_KEY` (free tier) for official search; without it a fragile DuckDuckGo fallback is used. Reviews can only be extracted from pages that publish structured review data; big marketplaces block bots, so paste or upload reviews (TXT/CSV) there. Respect each site's terms of service.

## Docker
`docker compose up --build` then open http://localhost:8000 (gunicorn). Put keys in a `.env` file (see `.env.example`).

## Project structure
`app.py` routes + DB · `ml.py` models · `train.py` real-data training · `reviewtools.py` link/name review extraction + suggestions · `payments.py` demo gateway · `razorpay_gateway.py` real gateway · `templates/index.html` + `static/` UI · `tests/` automated tests.

## Known limitations
Competitor prices are simulated unless you enter real ones. Models use synthetic data until trained on real CSVs. Name search and Razorpay need internet access and keys. Not load-tested.

## Future scope
Transformer (BERT) sentiment, payment webhooks, multi-vendor sellers, Prophet/LSTM forecasting, PostgreSQL + cloud deployment.
