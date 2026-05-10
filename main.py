from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware
import requests
import hmac
import hashlib
import base64
import json
import os
import anthropic
from dotenv import load_dotenv

load_dotenv()

app = FastAPI(title="BargainAI Shopify App")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

SHOPIFY_CLIENT_ID = os.getenv("SHOPIFY_CLIENT_ID")
SHOPIFY_CLIENT_SECRET = os.getenv("SHOPIFY_CLIENT_SECRET")
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY")
APP_URL = os.getenv("APP_URL")
SECRET_KEY = os.getenv("SECRET_KEY")

# Store tokens in memory for now
# In production use a database
store_tokens = {}

claude_client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)


# ===== HEALTH CHECK =====
@app.get("/health")
def health():
    return {"status": "BargainAI Shopify App running!"}


# ===== STEP 1 — INSTALL (OAuth start) =====
@app.get("/")
async def install(request: Request):
    shop = request.query_params.get("shop")
    return HTMLResponse("""
        <html><body style="font-family:sans-serif;padding:2rem;text-align:center">
        <h1>BargainAI</h1>
        <p>India's first AI dukandaar for Shopify stores</p>
        <p>Install this app from the Shopify App Store</p>
        </body></html>
        """)

    scopes = "read_products,read_orders,read_customers,write_script_tags"
    redirect_uri = f"{APP_URL}/auth/callback"
    install_url = (
        f"https://{shop}/admin/oauth/authorize"
        f"?client_id={SHOPIFY_CLIENT_ID}"
        f"&scope={scopes}"
        f"&redirect_uri={redirect_uri}"
        f"&state={SECRET_KEY}"
    )
    return RedirectResponse(install_url)


# ===== STEP 2 — AUTH CALLBACK =====
@app.get("/auth/callback")
async def auth_callback(
    shop: str,
    code: str,
    state: str,
    hmac_param: str = None,
    request: Request = None
):
    # Exchange code for access token
    token_url = f"https://{shop}/admin/oauth/access_token"
    response = requests.post(token_url, json={
        "client_id": SHOPIFY_CLIENT_ID,
        "client_secret": SHOPIFY_CLIENT_SECRET,
        "code": code
    })

    if response.status_code != 200:
        raise HTTPException(
            status_code=400, detail="Failed to get access token")

    data = response.json()
    access_token = data.get("access_token")

    # Store token
    store_tokens[shop] = access_token
    print(f"Store installed: {shop}")
    print(f"Access token: {access_token[:10]}...")

    # Redirect to success page
    return RedirectResponse(f"{APP_URL}/installed?shop={shop}")


# ===== STEP 3 — INSTALLED SUCCESS PAGE =====
@app.get("/installed")
def installed(shop: str):
    return HTMLResponse(f"""
    <html>
    <head>
        <style>
            body{{font-family:sans-serif;padding:2rem;text-align:center;background:#f5f0eb}}
            .card{{background:#fff;border-radius:16px;padding:2rem;max-width:500px;margin:2rem auto;box-shadow:0 4px 20px rgba(0,0,0,0.1)}}
            h1{{color:#8B4513}}
            .code{{background:#1a1a2e;color:#f5c842;padding:1rem;border-radius:8px;font-family:monospace;font-size:13px;text-align:left;margin:1rem 0}}
            .btn{{background:#8B4513;color:#fff;padding:10px 20px;border-radius:8px;text-decoration:none;display:inline-block;margin-top:1rem}}
        </style>
    </head>
    <body>
        <div class="card">
            <h1>🏪 BargainAI Installed!</h1>
            <p>Store: <strong>{shop}</strong></p>
            <p>Add this script to your Shopify theme to activate the dukandaar widget:</p>
            <div class="code">
&lt;script src="{APP_URL}/widget.js?shop={shop}"&gt;&lt;/script&gt;
            </div>
            <p>Go to your Shopify theme editor and paste this before &lt;/body&gt;</p>
            <a href="https://{shop}/admin" class="btn">Go to Shopify Admin</a>
        </div>
    </body>
    </html>
    """)


# ===== STEP 4 — GET PRODUCTS FROM SHOPIFY =====
@app.get("/products/{shop}")
def get_products(shop: str):
    token = store_tokens.get(shop)
    if not token:
        raise HTTPException(status_code=401, detail="Store not authenticated")

    response = requests.get(
        f"https://{shop}/admin/api/2024-04/products.json?limit=20",
        headers={"X-Shopify-Access-Token": token}
    )

    if response.status_code != 200:
        raise HTTPException(status_code=400, detail="Failed to fetch products")

    products = response.json().get("products", [])

    # Format products for BargainAI
    formatted = []
    for p in products:
        variant = p["variants"][0] if p["variants"] else {}
        price = float(variant.get("price", 0))
        formatted.append({
            "id": p["id"],
            "name": p["title"],
            "description": p.get("body_html", "").replace("<p>", "").replace("</p>", ""),
            "price": price,
            "floor_price": round(price * 0.85),
            "image": p["images"][0]["src"] if p.get("images") else None,
            "emoji": "🛍"
        })

    return {"products": formatted}


# ===== STEP 5 — AI BARGAIN ENDPOINT =====
@app.post("/bargain")
async def bargain(request: Request):
    body = await request.json()

    shop = body.get("shop")
    product_name = body.get("product_name")
    product_desc = body.get("product_desc", "")
    current_offer = body.get("current_offer")
    floor_price = body.get("floor_price")
    mrp = body.get("mrp")
    customer_message = body.get("message")
    history = body.get("history", [])
    language = body.get("language", "hinglish")
    gender = body.get("gender", "Unknown")

    if gender == "Female":
        address = "Didi"
    elif gender == "Male":
        address = "Bhaiya"
    else:
        address = "Aap"

    if language == "hinglish":
        system_prompt = f"""Tu ek experienced Indian dukandaar hai jo {product_name} bech raha hai online chat pe.

Product: {product_name}
Description: {product_desc[:200] if product_desc else 'Premium quality product'}
MRP: Rs.{mrp}
Current offer: Rs.{current_offer}
Floor price (minimum — kabhi nahi jaana): Rs.{floor_price}
Customer ko {address} bolkar address karo

Rules:
- Natural Hinglish mein baat karo
- Warm, friendly aur thoda playful tone
- Agar price drop karo — Rs.10-25 drop kar sakte ho but floor se neeche nahi
- New price clearly batao response mein
- 2-3 sentences max
- 1-2 emojis only
- Customer ko special feel karao"""
    else:
        system_prompt = f"""You are a warm friendly Indian shopkeeper selling {product_name} online.

Product: {product_name}
Description: {product_desc[:200] if product_desc else 'Premium quality product'}
MRP: Rs.{mrp}
Current offer: Rs.{current_offer}
Floor price (never go below): Rs.{floor_price}

Rules:
- Natural conversational English
- Warm, friendly, slightly playful
- Can drop price Rs.10-25 but never below floor
- Mention new price clearly in response
- 2-3 sentences max
- 1-2 emojis"""

    messages = history[-6:] + [{"role": "user", "content": customer_message}]

    response = claude_client.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=150,
        system=system_prompt,
        messages=messages
    )

    reply = response.content[0].text.strip()

    # Extract new price if dropped
    import re
    price_match = re.search(r'Rs\.(\d+)', reply)
    new_offer = current_offer
    if price_match:
        extracted = int(price_match.group(1))
        if floor_price <= extracted < current_offer:
            new_offer = extracted

    return {
        "reply": reply,
        "new_offer": new_offer,
        "offer_dropped": new_offer < current_offer
    }


# ===== STEP 6 — WIDGET JAVASCRIPT =====
@app.get("/widget.js")
async def widget_js(shop: str, request: Request):
    products_url = f"{APP_URL}/products/{shop}"
    bargain_url = f"{APP_URL}/bargain"

    js_code = f"""
(function() {{
  // BargainAI Widget v1.0
  const SHOP = '{shop}';
  const API_URL = '{APP_URL}';
  let currentOffer = 0;
  let floorPrice = 0;
  let currentProduct = {{}};
  let chatHistory = [];
  let isTyping = false;
  let lang = 'hinglish';
  let isOpen = false;

  // Inject styles
  const style = document.createElement('style');
  style.textContent = `
    #bai-bubble{{position:fixed;bottom:24px;right:24px;width:60px;height:60px;border-radius:50%;background:linear-gradient(135deg,#8B4513,#D2691E);border:none;cursor:pointer;box-shadow:0 4px 20px rgba(139,69,19,0.4);font-size:26px;z-index:9999;animation:baiPulse 2.5s ease-in-out infinite;display:flex;align-items:center;justify-content:center}}
    @keyframes baiPulse{{0%,100%{{box-shadow:0 4px 20px rgba(139,69,19,0.4)}}50%{{box-shadow:0 6px 32px rgba(139,69,19,0.65)}}}}
    #bai-widget{{position:fixed;bottom:96px;right:24px;width:360px;height:560px;background:#fff;border-radius:20px;box-shadow:0 20px 60px rgba(0,0,0,0.2);display:none;flex-direction:column;overflow:hidden;z-index:9998;font-family:sans-serif}}
    #bai-widget.bai-open{{display:flex;animation:baiOpen 0.35s cubic-bezier(0.34,1.56,0.64,1) both}}
    @keyframes baiOpen{{from{{opacity:0;transform:scale(0.85) translateY(20px)}}to{{opacity:1;transform:scale(1) translateY(0)}}}}
    .bai-header{{background:linear-gradient(135deg,#8B4513,#D2691E);padding:14px 16px;display:flex;align-items:center;gap:10px}}
    .bai-avatar{{width:40px;height:40px;border-radius:50%;background:rgba(255,255,255,0.2);display:flex;align-items:center;justify-content:center;font-size:20px}}
    .bai-name{{font-size:15px;font-weight:600;color:#fff;flex:1}}
    .bai-close{{background:rgba(255,255,255,0.15);border:none;color:#fff;width:28px;height:28px;border-radius:50%;cursor:pointer;font-size:14px}}
    .bai-tabs{{display:flex;background:#fdf8f4;border-bottom:1px solid #f0ebe4}}
    .bai-tab{{flex:1;padding:8px;font-size:11px;font-weight:500;color:#999;border:none;background:none;cursor:pointer;border-bottom:2px solid transparent}}
    .bai-tab.bai-active{{color:#8B4513;border-bottom-color:#D2691E}}
    .bai-products{{flex:1;overflow-y:auto;padding:10px;display:flex;flex-direction:column;gap:8px;background:#fdf8f4}}
    .bai-prow{{background:#fff;border-radius:12px;border:1px solid #f0ebe4;padding:10px;display:flex;gap:10px;align-items:center;cursor:pointer}}
    .bai-pemoji{{font-size:24px;width:40px;height:40px;background:#fdf0e0;border-radius:10px;display:flex;align-items:center;justify-content:center}}
    .bai-pname{{font-size:13px;font-weight:500;color:#1a1a1a}}
    .bai-pprice{{font-size:14px;font-weight:600;color:#8B4513}}
    .bai-bargainbtn{{padding:5px 10px;border-radius:8px;background:linear-gradient(135deg,#8B4513,#D2691E);border:none;color:#fff;font-size:11px;font-weight:600;cursor:pointer;white-space:nowrap}}
    .bai-pricebar{{background:linear-gradient(135deg,#8B4513,#D2691E);padding:6px 14px;display:flex;justify-content:space-between;align-items:center}}
    .bai-prlabel{{font-size:10px;color:rgba(255,255,255,0.6)}}
    .bai-prval{{font-size:14px;font-weight:600;color:#fff}}
    .bai-chat{{flex:1;display:flex;flex-direction:column;overflow:hidden}}
    .bai-msgs{{flex:1;overflow-y:auto;padding:12px;display:flex;flex-direction:column;gap:8px;background:#fdf8f4}}
    .bai-msg{{max-width:84%;padding:8px 12px;border-radius:12px;font-size:12.5px;line-height:1.5;animation:baiMsg 0.3s ease both}}
    @keyframes baiMsg{{from{{opacity:0;transform:translateY(6px)}}to{{opacity:1;transform:translateY(0)}}}}
    .bai-bot{{background:#fff;color:#333;align-self:flex-start;border-radius:12px 12px 12px 2px;border:1px solid #f0ebe4}}
    .bai-user{{background:linear-gradient(135deg,#8B4513,#D2691E);color:#fff;align-self:flex-end;border-radius:12px 12px 2px 12px}}
    .bai-typing{{display:flex;gap:4px;padding:10px 14px;background:#fff;border-radius:12px;align-self:flex-start;border:1px solid #f0ebe4;width:54px}}
    .bai-typing span{{width:6px;height:6px;border-radius:50%;background:#ddd;animation:baiDot 1.2s ease-in-out infinite}}
    .bai-typing span:nth-child(2){{animation-delay:0.2s}}
    .bai-typing span:nth-child(3){{animation-delay:0.4s}}
    @keyframes baiDot{{0%,60%,100%{{transform:translateY(0);background:#ddd}}30%{{transform:translateY(-5px);background:#D2691E}}}}
    .bai-qr{{padding:8px;display:flex;flex-wrap:wrap;gap:5px;background:#fff;border-top:1px solid #f0ebe4}}
    .bai-qrbtn{{padding:5px 9px;border-radius:14px;border:1px solid #e8e0d8;background:#fff;font-size:11px;color:#8B4513;cursor:pointer;font-weight:500}}
    .bai-inputrow{{padding:8px 10px;background:#fff;border-top:1px solid #f0ebe4;display:flex;gap:8px;align-items:center}}
    .bai-input{{flex:1;padding:8px 12px;border-radius:20px;border:1px solid #e8e0d8;font-size:12px;outline:none}}
    .bai-send{{width:34px;height:34px;border-radius:50%;background:linear-gradient(135deg,#8B4513,#D2691E);border:none;cursor:pointer;color:#fff;font-size:16px}}
    .bai-footer{{padding:5px;background:#fff;text-align:center;border-top:1px solid #f5f0eb;font-size:10px;color:#ccc}}
  `;
  document.head.appendChild(style);

  // Create bubble
  const bubble = document.createElement('button');
  bubble.id = 'bai-bubble';
  bubble.innerHTML = '🏪';
  bubble.onclick = toggleWidget;
  document.body.appendChild(bubble);

  // Create widget
  const widget = document.createElement('div');
  widget.id = 'bai-widget';
  widget.innerHTML = `
    <div class="bai-header">
      <div class="bai-avatar">🏪</div>
      <div class="bai-name">BargainAI Dukandaar</div>
      <button class="bai-close" onclick="document.getElementById('bai-widget').classList.remove('bai-open')">✕</button>
    </div>
    <div class="bai-tabs">
      <button class="bai-tab bai-active" id="bai-tab-p" onclick="baiSwitchTab('products')">🛍 Products</button>
      <button class="bai-tab" id="bai-tab-c" onclick="baiSwitchTab('chat')">💬 Bargain</button>
    </div>
    <div id="bai-products" class="bai-products"><div style="text-align:center;padding:2rem;color:#999">Loading products...</div></div>
    <div id="bai-chat" class="bai-chat" style="display:none">
      <div class="bai-pricebar">
        <div class="bai-prlabel">Current offer</div>
        <div class="bai-prval" id="bai-price">—</div>
        <div class="bai-prlabel" id="bai-floor">—</div>
      </div>
      <div class="bai-msgs" id="bai-msgs"></div>
      <div class="bai-qr" id="bai-qr">
        <button class="bai-qrbtn" onclick="baiSendQuick('bahut mehnga hai')">bahut mehnga hai</button>
        <button class="bai-qrbtn" onclick="baiSendQuick('quality kaisi?')">quality kaisi?</button>
        <button class="bai-qrbtn" onclick="baiSendQuick('aur discount?')">aur discount?</button>
        <button class="bai-qrbtn" onclick="baiSendQuick('le leta hoon!')">le leta hoon!</button>
      </div>
      <div class="bai-inputrow">
        <input class="bai-input" id="bai-input" placeholder="Type your message..." onkeydown="if(event.key==='Enter')baiSend()">
        <button class="bai-send" onclick="baiSend()">➤</button>
      </div>
    </div>
    <div class="bai-footer">Powered by <strong style="color:#8B4513">BargainAI</strong> — India's AI dukandaar</div>
  `;
  document.body.appendChild(widget);

  // Load products
  fetch('{products_url}')
    .then(r => r.json())
    .then(data => {{
      const panel = document.getElementById('bai-products');
      if(!data.products || data.products.length === 0){{
        panel.innerHTML = '<div style="text-align:center;padding:2rem;color:#999">No products found</div>';
        return;
      }}
      panel.innerHTML = '';
      data.products.forEach(p => {{
        const row = document.createElement('div');
        row.className = 'bai-prow';
        row.innerHTML = `
          <div class="bai-pemoji">${{p.emoji}}</div>
          <div style="flex:1">
            <div class="bai-pname">${{p.name}}</div>
            <div class="bai-pprice">Rs.${{p.price}}</div>
          </div>
          <button class="bai-bargainbtn" onclick="baiBargain('${{p.name}}','${{p.emoji}}',${{p.price}},${{p.floor_price}},'${{p.description}}')">Bargain!</button>
        `;
        panel.appendChild(row);
      }});
    }})
    .catch(() => {{
      document.getElementById('bai-products').innerHTML = '<div style="text-align:center;padding:2rem;color:#999">Could not load products</div>';
    }});

  function toggleWidget(){{
    isOpen = !isOpen;
    if(isOpen) widget.classList.add('bai-open');
    else widget.classList.remove('bai-open');
  }}

  window.baiSwitchTab = function(tab){{
    document.getElementById('bai-tab-p').classList.toggle('bai-active', tab==='products');
    document.getElementById('bai-tab-c').classList.toggle('bai-active', tab==='chat');
    document.getElementById('bai-products').style.display = tab==='products'?'flex':'none';
    document.getElementById('bai-chat').style.display = tab==='chat'?'flex':'none';
  }};

  window.baiBargain = function(name, emoji, price, floor, desc){{
    currentProduct = {{name, emoji, price, desc}};
    currentOffer = Math.round(price * 0.94);
    floorPrice = floor;
    chatHistory = [];
    document.getElementById('bai-price').textContent = 'Rs.' + currentOffer;
    document.getElementById('bai-floor').textContent = 'Floor Rs.' + floor;
    document.getElementById('bai-msgs').innerHTML = '';
    if(!isOpen) toggleWidget();
    baiSwitchTab('chat');

    setTimeout(() => {{
      baiAddBot(`Waah! ${{name}} — ekdum sahi choice! Aapke liye special price Rs.${{currentOffer}} kar diya hai 😊`);
    }}, 400);
  }};

  window.baiSendQuick = function(text){{
    document.getElementById('bai-input').value = text;
    baiSend();
  }};

  window.baiSend = async function(){{
    if(isTyping) return;
    const input = document.getElementById('bai-input');
    const text = input.value.trim();
    if(!text) return;
    input.value = '';
    baiAddUser(text);
    chatHistory.push({{role:'user', content:text}});
    baiShowTyping();

    try {{
      const response = await fetch('{bargain_url}', {{
        method: 'POST',
        headers: {{'Content-Type': 'application/json'}},
        body: JSON.stringify({{
          shop: SHOP,
          product_name: currentProduct.name,
          product_desc: currentProduct.desc,
          current_offer: currentOffer,
          floor_price: floorPrice,
          mrp: currentProduct.price,
          message: text,
          history: chatHistory.slice(-6),
          language: 'hinglish',
          gender: 'Unknown'
        }})
      }});
      const data = await response.json();
      baiRemoveTyping();
      baiAddBot(data.reply);
      chatHistory.push({{role:'assistant', content:data.reply}});
      if(data.new_offer && data.new_offer < currentOffer){{
        currentOffer = data.new_offer;
        document.getElementById('bai-price').textContent = 'Rs.' + currentOffer;
      }}
    }} catch(e) {{
      baiRemoveTyping();
      baiAddBot('Arre thoda technical issue hua — ek second mein try karo! 😊');
    }}
  }};

  function baiAddBot(text){{
    const div = document.createElement('div');
    div.className = 'bai-msg bai-bot';
    div.textContent = text;
    document.getElementById('bai-msgs').appendChild(div);
    baiScroll();
  }}

  function baiAddUser(text){{
    const div = document.createElement('div');
    div.className = 'bai-msg bai-user';
    div.textContent = text;
    document.getElementById('bai-msgs').appendChild(div);
    baiScroll();
  }}

  function baiShowTyping(){{
    isTyping = true;
    const div = document.createElement('div');
    div.className = 'bai-typing';
    div.id = 'bai-typing';
    div.innerHTML = '<span></span><span></span><span></span>';
    document.getElementById('bai-msgs').appendChild(div);
    baiScroll();
  }}

  function baiRemoveTyping(){{
    isTyping = false;
    const t = document.getElementById('bai-typing');
    if(t) t.remove();
  }}

  function baiScroll(){{
    const c = document.getElementById('bai-msgs');
    c.scrollTop = c.scrollHeight;
  }}
}})();
"""
    return HTMLResponse(content=js_code, media_type="application/javascript")


if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)
