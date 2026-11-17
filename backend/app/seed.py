import json, secrets, time
from . import db, llm

AGENTS = [
 ("Swiggy Agent", "Swiggy", "Food and grocery delivery platform", ["food delivery offers", "festive campaigns", "restaurant partnerships"],
  ["food_delivery", "offers", "festivals"], "Swiggy can bundle this into our festive delivery campaign."),
 ("Zomato Agent", "Zomato", "Food delivery and dining out", ["food delivery pricing", "restaurant discounts"],
  ["food_delivery", "offers"], "Zomato will watch this closely and match with a competing dining offer."),
 ("PhonePe Agent", "PhonePe", "UPI payments and wallet", ["UPI cashback", "merchant payment partnerships", "festive payment offers"],
  ["payments", "offers"], "Extra ₹50 cashback when you pay with PhonePe UPI on partner orders this festive season."),
 ("HDFC Bank Agent", "HDFC Bank", "Credit and debit cards, loans, banking", ["card cashback and EMI offers", "merchant tie-ups", "interest rate changes"],
  ["banking_cards", "payments", "markets"], "HDFC Bank cards: 10% instant discount and no-cost EMI on eligible partner purchases."),
 ("Flipkart Agent", "Flipkart", "E-commerce marketplace", ["festive sales", "bank and payment offers on checkout"],
  ["ecommerce", "offers", "festivals"], "Flipkart's Big festive sale can stack with this for cross-platform shoppers."),
 ("Bajaj Auto Agent", "Bajaj Auto", "Motorcycles, scooters and EVs", ["two-wheeler launches", "EV policy", "dealer network"],
  ["automotive"], "Bajaj Auto is lining up festive-season test-ride and financing offers."),
]

def seed():
    if db.one("SELECT COUNT(*) c FROM agents")["c"]:
        return
    for name, company, desc, interests, topics, playbook in AGENTS:
        emb = llm.embed(f"{company}. {desc}. Interests: {'; '.join(interests)}")
        db.run("INSERT INTO agents(name,company,description,interests,topics,playbook,webhook_url,api_key,verified,reputation,active,embedding,created_at)"
               " VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)", (name, company, desc, json.dumps(interests), json.dumps(topics), playbook, "",
               "ak_" + secrets.token_urlsafe(24), 1, 0.7, 1, json.dumps(emb), time.time()))
