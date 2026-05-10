from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.middleware.cors import CORSMiddleware
import requests
import re
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
APP_URL = os.getenv("APP_URL", "https://bargainai-shopify.onrender.com")
SECRET_KEY = os.getenv("SECRET_KEY", "bargainai_secret_2026")

TOKENS_FILE = "store_tokens.json"


def load_tokens():
    try:
        with open(TOKENS_FILE, "r") as f:
            return json.load(f)
    except:
        return {}


def save_tokens(tokens):
    try:
        with open(TOKENS_FILE, "w") as f:
            json.dump(tokens, f)
    except Exception as e:
        print(f"Error saving tokens: {e}")


store_tokens = load_tokens()
claude_client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)


@app.get("/health")
def health():
    return {"status": "BargainAI Shopify App running!", "stores": list(store_tokens.keys())}


@app.get("/")
async def install(request: Request):
    shop = request.query_params.get("shop")

    if not shop:
        return HTMLResponse("""
        <html>
        <head><style>
        body{font-family:sans-serif;background:#f5f0eb;display:flex;align-items:center;justify-content:center;height:100vh;margin:0}
        .card{background:#fff;border-radius:16px;padding:3rem;text-align:center;box-shadow:0 4px 20px rgba(0,0,0,0.1);max-width:400px}
        h1{color:#8B4513;font-size:2rem;margin-bottom:0.5rem}
        </style></head>
        <body>
        <div class="card">
            <h1>🏪 BargainAI</h1>
            <p style="color:#666">India's first AI dukandaar for Shopify stores</p>
            <p style="font-size:13px;color:#999;margin-top:0.5rem">Install from the Shopify App Store</p>
        </div>
        </body></html>
        """)

    print(f"Install request: {shop}")
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


@app.get("/auth/callback")
async def auth_callback(request: Request):
    shop = request.query_params.get("shop")
    code = request.query_params.get("code")

    if not shop or not code:
        raise HTTPException(status_code=400, detail="Missing shop or code")

    print(f"Auth callback: {shop}")
    response = requests.post(
        f"https://{shop}/admin/oauth/access_token",
        json={
            "client_id": SHOPIFY_CLIENT_ID,
            "client_secret": SHOPIFY_CLIENT_SECRET,
            "code": code
        }
    )

    if response.status_code != 200:
        print(f"Token error: {response.text}")
        raise HTTPException(
            status_code=400, detail="Failed to get access token")

    access_token = response.json().get("access_token")
    store_tokens[shop] = access_token
    save_tokens(store_tokens)
    print(f"Installed: {shop}")

    return RedirectResponse(f"{APP_URL}/installed?shop={shop}")


@app.get("/installed")
async def installed(request: Request):
    shop = request.query_params.get("shop", "your-store.myshopify.com")
    return HTMLResponse(f"""
    <html>
    <head><style>
    body{{font-family:sans-serif;background:#f5f0eb;display:flex;align-items:center;justify-content:center;min-height:100vh;margin:0;padding:1rem}}
    .card{{background:#fff;border-radius:16px;padding:2.5rem;text-align:center;box-shadow:0 4px 20px rgba(0,0,0,0.1);max-width:520px;width:100%}}
    h1{{color:#8B4513;margin-bottom:0.5rem;font-size:1.8rem}}
    .code{{background:#1a1a2e;color:#f5c842;padding:1rem;border-radius:8px;font-family:monospace;font-size:11px;text-align:left;margin:1rem 0;word-break:break-all;line-height:1.6}}
    .step{{background:#fdf0e0;border-radius:8px;padding:0.7rem 1rem;margin:0.4rem 0;font-size:13px;color:#8B4513;text-align:left}}
    .btn{{background:#8B4513;color:#fff;padding:10px 24px;border-radius:8px;text-decoration:none;display:inline-block;margin-top:1rem;font-size:14px}}
    </style></head>
    <body>
    <div class="card">
        <h1>🏪 BargainAI Installed!</h1>
        <p style="color:#666;margin-bottom:1rem">Store: <strong>{shop}</strong></p>
        <p style="color:#666;font-size:14px">Add this one line to your Shopify theme:</p>
        <div class="code">&lt;script src="{APP_URL}/widget.js?shop={shop}"&gt;&lt;/script&gt;</div>
        <div class="step">1. Shopify Admin → Online Store → Themes → Edit Code</div>
        <div class="step">2. Open layout/theme.liquid</div>
        <div class="step">3. Paste the script above before &lt;/body&gt;</div>
        <div class="step">4. Save — widget appears on your store!</div>
        <a href="https://{shop}/admin" class="btn">Go to Shopify Admin →</a>
    </div>
    </body></html>
    """)


@app.get("/products/{shop_domain:path}")
async def get_products(shop_domain: str):
    token = store_tokens.get(shop_domain)
    if not token:
        return {"products": [], "error": "Store not authenticated"}

    response = requests.get(
        f"https://{shop_domain}/admin/api/2024-04/products.json?limit=20",
        headers={"X-Shopify-Access-Token": token}
    )

    if response.status_code != 200:
        return {"products": [], "error": "Failed to fetch products"}

    products = response.json().get("products", [])
    formatted = []
    for p in products:
        variant = p["variants"][0] if p.get("variants") else {}
        price = float(variant.get("price", 0))
        desc = p.get("body_html", "")
        desc = re.sub('<[^<]+?>', '', desc)[:150]
        formatted.append({
            "id": str(p["id"]),
            "name": p["title"],
            "description": desc,
            "price": price,
            "floor_price": round(price * 0.85),
            "emoji": "🛍"
        })

    return {"products": formatted}


@app.post("/bargain")
async def bargain(request: Request):
    body = await request.json()

    product_name = body.get("product_name", "Product")
    product_desc = body.get("product_desc", "")
    current_offer = body.get("current_offer", 0)
    floor_price = body.get("floor_price", 0)
    mrp = body.get("mrp", 0)
    customer_message = body.get("message", "")
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
Description: {product_desc[:150] if product_desc else 'Premium quality product'}
MRP: Rs.{mrp}
Current offer: Rs.{current_offer}
Floor price: Rs.{floor_price} — kabhi is se neeche mat jao
Customer address: {address}

Rules:
- Natural Hinglish mein baat karo
- Warm, friendly, thoda playful — real dukandaar jaisa
- Price drop karo Rs.10-25 lekin floor se neeche nahi
- New price clearly batao Rs.XXX format mein
- 2-3 sentences max
- 1-2 emojis only
- Customer ko special feel karao"""
    else:
        system_prompt = f"""You are a warm friendly Indian shopkeeper selling {product_name} online.

Product: {product_name}
Description: {product_desc[:150] if product_desc else 'Premium quality product'}
MRP: Rs.{mrp}
Current offer: Rs.{current_offer}
Floor price: Rs.{floor_price} — never go below this

Rules:
- Natural conversational English
- Warm, friendly, slightly playful
- Drop Rs.10-25 but never below floor
- Mention new price Rs.XXX format clearly
- 2-3 sentences max
- 1-2 emojis"""

    messages = history[-6:] + [{"role": "user", "content": customer_message}]

    try:
        response = claude_client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=150,
            system=system_prompt,
            messages=messages
        )
        reply = response.content[0].text.strip()
        price_match = re.search(r'Rs\.(\d+)', reply)
        new_offer = current_offer
        if price_match:
            extracted = int(price_match.group(1))
            if floor_price <= extracted < current_offer:
                new_offer = extracted
        return {"reply": reply, "new_offer": new_offer, "offer_dropped": new_offer < current_offer}
    except Exception as e:
        print(f"Claude error: {e}")
        fallback = f"Arre thoda technical issue hua! Rs.{current_offer} wala offer abhi bhi valid hai 😊" if language == "hinglish" else f"Small issue! Your offer of Rs.{current_offer} is still valid 😊"
        return {"reply": fallback, "new_offer": current_offer, "offer_dropped": False}


@app.get("/widget.js")
async def widget_js(request: Request):
    shop = request.query_params.get("shop", "")
    products_url = f"{APP_URL}/products/{shop}"
    bargain_url = f"{APP_URL}/bargain"

    js_code = f"""
(function() {{
  const SHOP = '{shop}';
  const PRODUCTS_URL = '{products_url}';
  const BARGAIN_URL = '{bargain_url}';
  let currentOffer = 0;
  let floorPrice = 0;
  let currentProduct = {{}};
  let chatHistory = [];
  let isTyping = false;
  let isOpen = false;

  const style = document.createElement('style');
  style.textContent = `
    #bai-bubble{{position:fixed;bottom:24px;right:24px;width:60px;height:60px;border-radius:50%;background:linear-gradient(135deg,#8B4513,#D2691E);border:none;cursor:pointer;box-shadow:0 4px 20px rgba(139,69,19,0.4);font-size:26px;z-index:9999;animation:baiPulse 2.5s ease-in-out infinite;display:flex;align-items:center;justify-content:center}}
    @keyframes baiPulse{{0%,100%{{box-shadow:0 4px 20px rgba(139,69,19,0.4)}}50%{{box-shadow:0 6px 32px rgba(139,69,19,0.65)}}}}
    #bai-widget{{position:fixed;bottom:96px;right:24px;width:360px;height:560px;background:#fff;border-radius:20px;box-shadow:0 20px 60px rgba(0,0,0,0.2);display:none;flex-direction:column;overflow:hidden;z-index:9998;font-family:-apple-system,BlinkMacSystemFont,sans-serif}}
    #bai-widget.bai-open{{display:flex;animation:baiOpen 0.35s cubic-bezier(0.34,1.56,0.64,1) both}}
    @keyframes baiOpen{{from{{opacity:0;transform:scale(0.85) translateY(20px)}}to{{opacity:1;transform:scale(1) translateY(0)}}}}
    .bai-header{{background:linear-gradient(135deg,#8B4513,#D2691E);padding:14px 16px;display:flex;align-items:center;gap:10px;flex-shrink:0}}
    .bai-avatar{{width:40px;height:40px;border-radius:50%;background:rgba(255,255,255,0.2);display:flex;align-items:center;justify-content:center;font-size:20px;flex-shrink:0}}
    .bai-hinfo{{flex:1}}
    .bai-hname{{font-size:15px;font-weight:600;color:#fff}}
    .bai-hstatus{{font-size:10px;color:rgba(255,255,255,0.7)}}
    .bai-hclose{{background:rgba(255,255,255,0.15);border:none;color:#fff;width:28px;height:28px;border-radius:50%;cursor:pointer;font-size:14px;display:flex;align-items:center;justify-content:center;flex-shrink:0}}
    .bai-tabs{{display:flex;background:#fdf8f4;border-bottom:1px solid #f0ebe4;flex-shrink:0}}
    .bai-tab{{flex:1;padding:8px;font-size:11px;font-weight:500;color:#999;border:none;background:none;cursor:pointer;border-bottom:2px solid transparent}}
    .bai-tab.bai-active{{color:#8B4513;border-bottom-color:#D2691E}}
    .bai-products{{flex:1;overflow-y:auto;padding:10px;display:flex;flex-direction:column;gap:8px;background:#fdf8f4}}
    .bai-prow{{background:#fff;border-radius:12px;border:1px solid #f0ebe4;padding:10px;display:flex;gap:10px;align-items:center}}
    .bai-pemoji{{font-size:24px;width:40px;height:40px;background:#fdf0e0;border-radius:10px;display:flex;align-items:center;justify-content:center;flex-shrink:0}}
    .bai-pinfo{{flex:1;min-width:0}}
    .bai-pname{{font-size:13px;font-weight:500;color:#1a1a1a;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}}
    .bai-pprice{{font-size:14px;font-weight:600;color:#8B4513;margin-top:2px}}
    .bai-bargainbtn{{padding:5px 10px;border-radius:8px;background:linear-gradient(135deg,#8B4513,#D2691E);border:none;color:#fff;font-size:11px;font-weight:600;cursor:pointer;white-space:nowrap;flex-shrink:0}}
    .bai-pricebar{{background:linear-gradient(135deg,#8B4513,#D2691E);padding:6px 14px;display:flex;justify-content:space-between;align-items:center;flex-shrink:0}}
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
    .bai-qr{{padding:8px;display:flex;flex-wrap:wrap;gap:5px;background:#fff;border-top:1px solid #f0ebe4;flex-shrink:0}}
    .bai-qrbtn{{padding:5px 9px;border-radius:14px;border:1px solid #e8e0d8;background:#fff;font-size:11px;color:#8B4513;cursor:pointer;font-weight:500}}
    .bai-inputrow{{padding:8px 10px;background:#fff;border-top:1px solid #f0ebe4;display:flex;gap:8px;align-items:center;flex-shrink:0}}
    .bai-input{{flex:1;padding:8px 12px;border-radius:20px;border:1px solid #e8e0d8;font-size:12px;outline:none;font-family:inherit}}
    .bai-input:focus{{border-color:#D2691E}}
    .bai-send{{width:34px;height:34px;border-radius:50%;background:linear-gradient(135deg,#8B4513,#D2691E);border:none;cursor:pointer;color:#fff;font-size:16px;display:flex;align-items:center;justify-content:center;flex-shrink:0}}
    .bai-footer{{padding:5px;background:#fff;text-align:center;border-top:1px solid #f5f0eb;font-size:10px;color:#ccc;flex-shrink:0}}
  `;
  document.head.appendChild(style);

  const bubble = document.createElement('button');
  bubble.id = 'bai-bubble';
  bubble.innerHTML = '&#x1F3EA;';
  bubble.onclick = toggleWidget;
  document.body.appendChild(bubble);

  const widget = document.createElement('div');
  widget.id = 'bai-widget';
  widget.innerHTML = [
    '<div class="bai-header">',
    '<div class="bai-avatar">&#x1F3EA;</div>',
    '<div class="bai-hinfo">',
    '<div class="bai-hname">BargainAI Dukandaar</div>',
    '<div class="bai-hstatus">&#x25CF; Online</div>',
    '</div>',
    '<button class="bai-hclose" id="bai-close">&#x2715;</button>',
    '</div>',
    '<div class="bai-tabs">',
    '<button class="bai-tab bai-active" id="bai-tab-p">&#x1F6CD; Products</button>',
    '<button class="bai-tab" id="bai-tab-c">&#x1F4AC; Bargain</button>',
    '</div>',
    '<div id="bai-products" class="bai-products"><div style="text-align:center;padding:2rem;color:#999;font-size:13px">Loading products...</div></div>',
    '<div id="bai-chat" class="bai-chat" style="display:none">',
    '<div class="bai-pricebar"><div class="bai-prlabel">Current offer</div><div class="bai-prval" id="bai-price">-</div><div class="bai-prlabel" id="bai-floor">Floor -</div></div>',
    '<div class="bai-msgs" id="bai-msgs"></div>',
    '<div class="bai-qr">',
    '<button class="bai-qrbtn" id="bai-q1">bahut mehnga hai</button>',
    '<button class="bai-qrbtn" id="bai-q2">quality kaisi?</button>',
    '<button class="bai-qrbtn" id="bai-q3">aur discount?</button>',
    '<button class="bai-qrbtn" id="bai-q4">le leta hoon!</button>',
    '</div>',
    '<div class="bai-inputrow">',
    '<input class="bai-input" id="bai-input" placeholder="Type your message...">',
    '<button class="bai-send" id="bai-send">&#x27A4;</button>',
    '</div>',
    '</div>',
    '<div class="bai-footer">Powered by <strong style="color:#8B4513">BargainAI</strong></div>'
  ].join('');
  document.body.appendChild(widget);

  document.getElementById('bai-close').onclick = function() {{
    widget.classList.remove('bai-open');
    isOpen = false;
  }};
  document.getElementById('bai-tab-p').onclick = function() {{ baiTab('products'); }};
  document.getElementById('bai-tab-c').onclick = function() {{ baiTab('chat'); }};
  document.getElementById('bai-send').onclick = baiSend;
  document.getElementById('bai-input').onkeydown = function(e) {{ if(e.key === 'Enter') baiSend(); }};
  document.getElementById('bai-q1').onclick = function() {{ baiQuick('bahut mehnga hai'); }};
  document.getElementById('bai-q2').onclick = function() {{ baiQuick('quality kaisi?'); }};
  document.getElementById('bai-q3').onclick = function() {{ baiQuick('aur discount?'); }};
  document.getElementById('bai-q4').onclick = function() {{ baiQuick('le leta hoon!'); }};

  fetch(PRODUCTS_URL)
    .then(function(r) {{ return r.json(); }})
    .then(function(data) {{
      const panel = document.getElementById('bai-products');
      if (!data.products || data.products.length === 0) {{
        panel.innerHTML = '<div style="text-align:center;padding:2rem;color:#999;font-size:13px">No products found</div>';
        return;
      }}
      panel.innerHTML = '';
      data.products.forEach(function(p) {{
        const row = document.createElement('div');
        row.className = 'bai-prow';
        const nameEl = document.createElement('div');
        nameEl.className = 'bai-pemoji';
        nameEl.textContent = p.emoji || '🛍';
        const infoEl = document.createElement('div');
        infoEl.className = 'bai-pinfo';
        const nameDiv = document.createElement('div');
        nameDiv.className = 'bai-pname';
        nameDiv.textContent = p.name;
        const priceDiv = document.createElement('div');
        priceDiv.className = 'bai-pprice';
        priceDiv.textContent = 'Rs.' + p.price;
        infoEl.appendChild(nameDiv);
        infoEl.appendChild(priceDiv);
        const btn = document.createElement('button');
        btn.className = 'bai-bargainbtn';
        btn.textContent = 'Bargain!';
        btn.onclick = function() {{
          baiBargain(p.name, p.emoji || '🛍', p.price, p.floor_price, p.description || '');
        }};
        row.appendChild(nameEl);
        row.appendChild(infoEl);
        row.appendChild(btn);
        panel.appendChild(row);
      }});
    }})
    .catch(function() {{
      document.getElementById('bai-products').innerHTML = '<div style="text-align:center;padding:2rem;color:#999;font-size:13px">Could not load products</div>';
    }});

  function toggleWidget() {{
    isOpen = !isOpen;
    if (isOpen) widget.classList.add('bai-open');
    else widget.classList.remove('bai-open');
  }}

  function baiTab(tab) {{
    document.getElementById('bai-tab-p').classList.toggle('bai-active', tab === 'products');
    document.getElementById('bai-tab-c').classList.toggle('bai-active', tab === 'chat');
    document.getElementById('bai-products').style.display = tab === 'products' ? 'flex' : 'none';
    document.getElementById('bai-chat').style.display = tab === 'chat' ? 'flex' : 'none';
  }}

  function baiBargain(name, emoji, price, floor, desc) {{
    currentProduct = {{name: name, emoji: emoji, price: price, desc: desc}};
    currentOffer = Math.round(price * 0.94);
    floorPrice = floor;
    chatHistory = [];
    document.getElementById('bai-price').textContent = 'Rs.' + currentOffer;
    document.getElementById('bai-floor').textContent = 'Floor Rs.' + floor;
    document.getElementById('bai-msgs').innerHTML = '';
    if (!isOpen) toggleWidget();
    baiTab('chat');
    setTimeout(function() {{
      baiAddBot('Waah! ' + name + ' — ekdum sahi choice! Aapke liye special price Rs.' + currentOffer + ' kar diya hai 😊');
    }}, 400);
  }}

  function baiQuick(text) {{
    document.getElementById('bai-input').value = text;
    baiSend();
  }}

  async function baiSend() {{
    if (isTyping) return;
    const input = document.getElementById('bai-input');
    const text = input.value.trim();
    if (!text) return;
    input.value = '';
    baiAddUser(text);
    chatHistory.push({{role: 'user', content: text}});
    baiShowTyping();
    try {{
      const resp = await fetch(BARGAIN_URL, {{
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
      const data = await resp.json();
      baiRemoveTyping();
      baiAddBot(data.reply);
      chatHistory.push({{role: 'assistant', content: data.reply}});
      if (data.new_offer && data.new_offer < currentOffer) {{
        currentOffer = data.new_offer;
        document.getElementById('bai-price').textContent = 'Rs.' + currentOffer;
      }}
    }} catch(e) {{
      baiRemoveTyping();
      baiAddBot('Arre thoda technical issue hua — ek second mein try karo! 😊');
    }}
  }}

  function baiAddBot(text) {{
    const div = document.createElement('div');
    div.className = 'bai-msg bai-bot';
    div.textContent = text;
    document.getElementById('bai-msgs').appendChild(div);
    baiScroll();
  }}

  function baiAddUser(text) {{
    const div = document.createElement('div');
    div.className = 'bai-msg bai-user';
    div.textContent = text;
    document.getElementById('bai-msgs').appendChild(div);
    baiScroll();
  }}

  function baiShowTyping() {{
    isTyping = true;
    const div = document.createElement('div');
    div.className = 'bai-typing';
    div.id = 'bai-typing';
    div.innerHTML = '<span></span><span></span><span></span>';
    document.getElementById('bai-msgs').appendChild(div);
    baiScroll();
  }}

  function baiRemoveTyping() {{
    isTyping = false;
    const t = document.getElementById('bai-typing');
    if (t) t.remove();
  }}

  function baiScroll() {{
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
