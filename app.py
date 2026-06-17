import io
import os
import re
from pathlib import Path
from typing import Optional, List, Tuple

import pandas as pd
import requests
import streamlit as st
from PIL import Image, ImageDraw, ImageFont


st.set_page_config(
    page_title="초등 장보기 미션 앱",
    page_icon="🛒",
    layout="wide",
)

MISSIONS = {
    "카레 만들기": {
        "emoji": "🍛",
        "budget": 18000,
        "description": "가족과 함께 먹을 카레를 만들 재료를 골라 보세요.",
    },
    "여름캠핑 준비하기": {
        "emoji": "🏕️",
        "budget": 45000,
        "description": "더운 여름 캠핑에 필요한 물건을 예산 안에서 준비해 보세요.",
    },
    "친구 생일파티 준비하기": {
        "emoji": "🎂",
        "budget": 35000,
        "description": "친구의 생일파티를 즐겁게 만들 물건을 골라 보세요.",
    },
}

CSV_PATH = "products.csv"
FONT_URL = "https://raw.githubusercontent.com/googlefonts/noto-cjk/main/Sans/OTF/Korean/NotoSansCJKkr-Regular.otf"


st.markdown(
    """
    <style>
    .main-title {
        font-size: 2.4rem;
        font-weight: 800;
        margin-bottom: 0.2rem;
    }
    .mission-card {
        padding: 1.1rem;
        border: 1px solid #e6e6e6;
        border-radius: 18px;
        background: #fffdf7;
        min-height: 180px;
        box-shadow: 0 2px 8px rgba(0,0,0,0.04);
    }
    .mission-emoji {
        font-size: 2.2rem;
        line-height: 1;
    }
    .product-card {
        padding: 0.8rem;
        border: 1px solid #ececec;
        border-radius: 16px;
        background: white;
        min-height: 430px;
        box-shadow: 0 2px 8px rgba(0,0,0,0.035);
    }
    .cart-box {
        padding: 1rem;
        border-radius: 16px;
        border: 2px dashed #d8d8d8;
        background: #fbfbff;
    }
    .small-note {
        color: #666;
        font-size: 0.9rem;
    }
    </style>
    """,
    unsafe_allow_html=True,
)


def normalize_col_name(name: str) -> str:
    return re.sub(r"\s+", "", str(name).strip().lower())


@st.cache_data(show_spinner=False)
def load_products(path: str) -> pd.DataFrame:
    df = pd.read_csv(path)
    normalized = {normalize_col_name(col): col for col in df.columns}
    rename_map = {}

    aliases = {
        "미션": ["미션", "mission"],
        "품명": ["품명", "상품명", "product", "name"],
        "가격": ["가격", "price"],
        "이미지url": ["이미지url", "이미지주소", "imageurl", "image", "url"],
    }
    for target, candidates in aliases.items():
        for candidate in candidates:
            key = normalize_col_name(candidate)
            if key in normalized:
                rename_map[normalized[key]] = target
                break

    df = df.rename(columns=rename_map)
    required = ["미션", "품명", "가격", "이미지url"]
    missing = [col for col in required if col not in df.columns]
    if missing:
        st.error(f"products.csv에 필요한 열이 없습니다: {', '.join(missing)}")
        st.stop()

    df = df[required].copy()
    df["가격"] = pd.to_numeric(df["가격"], errors="coerce").fillna(0).astype(int)
    df["품명"] = df["품명"].astype(str)
    df["미션"] = df["미션"].astype(str)
    df["이미지url"] = df["이미지url"].astype(str)
    return df


def money(value: int) -> str:
    return f"{int(value):,}원"


def safe_key(text: str) -> str:
    return re.sub(r"[^0-9A-Za-z가-힣_]+", "_", text)


def init_state() -> None:
    defaults = {
        "page": "start",
        "mission": None,
        "cart": {},
        "quantities": {},
        "reason": "",
    }
    for key, value in defaults.items():
        if key not in st.session_state:
            st.session_state[key] = value


def reset_for_mission(mission: str) -> None:
    st.session_state.page = "shopping"
    st.session_state.mission = mission
    st.session_state.cart = {}
    st.session_state.quantities = {}
    st.session_state.reason = ""


def go_start() -> None:
    st.session_state.page = "start"
    st.session_state.mission = None
    st.session_state.cart = {}
    st.session_state.quantities = {}
    st.session_state.reason = ""


def go_shopping() -> None:
    st.session_state.page = "shopping"


def cart_total() -> int:
    return sum(item["가격"] * item["수량"] for item in st.session_state.cart.values())


def change_quantity(product_key: str, delta: int) -> None:
    current = st.session_state.quantities.get(product_key, 0)
    st.session_state.quantities[product_key] = max(0, current + delta)


def add_to_cart(product_key: str, name: str, price: int, image_url: str) -> None:
    qty = st.session_state.quantities.get(product_key, 0)
    if qty <= 0:
        return
    cart = st.session_state.cart
    if name not in cart:
        cart[name] = {"품명": name, "가격": int(price), "이미지url": image_url, "수량": 0}
    cart[name]["수량"] += int(qty)
    st.session_state.cart = cart
    st.session_state.quantities[product_key] = 0


def change_cart_quantity(name: str, delta: int) -> None:
    cart = st.session_state.cart
    if name not in cart:
        return
    cart[name]["수량"] += delta
    if cart[name]["수량"] <= 0:
        del cart[name]
    st.session_state.cart = cart


def remove_from_cart(name: str) -> None:
    cart = st.session_state.cart
    if name in cart:
        del cart[name]
    st.session_state.cart = cart


def get_font_path() -> Optional[str]:
    direct_candidates = [
        "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
        "/usr/share/fonts/opentype/noto/NotoSansCJKkr-Regular.otf",
        "/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc",
        "/usr/share/fonts/truetype/noto/NotoSansKR-Regular.ttf",
        "/usr/share/fonts/truetype/nanum/NanumGothic.ttf",
        "/usr/share/fonts/truetype/nanum/NanumBarunGothic.ttf",
        "/System/Library/Fonts/AppleSDGothicNeo.ttc",
        "/Library/Fonts/AppleGothic.ttf",
        "C:/Windows/Fonts/malgun.ttf",
    ]
    for candidate in direct_candidates:
        if os.path.exists(candidate):
            return candidate

    search_dirs = [
        "/usr/share/fonts",
        "/usr/local/share/fonts",
        "/System/Library/Fonts",
        "/Library/Fonts",
        "C:/Windows/Fonts",
    ]
    keywords = [
        "notosanscjk",
        "notosanskr",
        "nanumgothic",
        "nanumbarun",
        "applesdgothic",
        "malgun",
        "unbatang",
        "undotum",
    ]
    for search_dir in search_dirs:
        if not os.path.isdir(search_dir):
            continue
        for root, _dirs, files in os.walk(search_dir):
            for file in files:
                lower = file.lower()
                if lower.endswith((".ttf", ".otf", ".ttc")) and any(k in lower for k in keywords):
                    return os.path.join(root, file)

    cache_dir = Path.home() / ".cache" / "shopping_mission_app"
    cache_dir.mkdir(parents=True, exist_ok=True)
    downloaded_font = cache_dir / "NotoSansCJKkr-Regular.otf"
    if downloaded_font.exists() and downloaded_font.stat().st_size > 100_000:
        return str(downloaded_font)

    try:
        response = requests.get(FONT_URL, timeout=15)
        response.raise_for_status()
        downloaded_font.write_bytes(response.content)
        if downloaded_font.stat().st_size > 100_000:
            return str(downloaded_font)
    except Exception:
        return None
    return None


@st.cache_resource(show_spinner=False)
def load_fonts() -> dict:
    font_path = get_font_path()
    sizes = {"title": 42, "subtitle": 28, "body": 24, "small": 20, "tiny": 18}
    fonts = {}
    for key, size in sizes.items():
        try:
            fonts[key] = ImageFont.truetype(font_path, size) if font_path else ImageFont.load_default()
        except Exception:
            fonts[key] = ImageFont.load_default()
    return fonts


@st.cache_data(show_spinner=False)
def fetch_image_bytes(url: str) -> Optional[bytes]:
    try:
        response = requests.get(url, timeout=8, headers={"User-Agent": "Mozilla/5.0"})
        response.raise_for_status()
        return response.content
    except Exception:
        return None


def fit_image_to_box(image: Image.Image, size: Tuple[int, int]) -> Image.Image:
    box_w, box_h = size
    image = image.convert("RGB")
    image.thumbnail((box_w, box_h))
    background = Image.new("RGB", (box_w, box_h), "#F4F4F4")
    x = (box_w - image.width) // 2
    y = (box_h - image.height) // 2
    background.paste(image, (x, y))
    return background


def make_placeholder(size: Tuple[int, int], text: str = "이미지 없음") -> Image.Image:
    img = Image.new("RGB", size, "#F4F4F4")
    draw = ImageDraw.Draw(img)
    fonts = load_fonts()
    font = fonts["small"]
    bbox = draw.textbbox((0, 0), text, font=font)
    x = max(10, (size[0] - (bbox[2] - bbox[0])) // 2)
    y = max(10, (size[1] - (bbox[3] - bbox[1])) // 2)
    draw.text((x, y), text, fill="#777777", font=font)
    return img


def load_product_image(url: str, size: Tuple[int, int]) -> Image.Image:
    data = fetch_image_bytes(url)
    if not data:
        return make_placeholder(size)
    try:
        image = Image.open(io.BytesIO(data))
        return fit_image_to_box(image, size)
    except Exception:
        return make_placeholder(size)


def wrap_text_by_width(draw: ImageDraw.ImageDraw, text: str, font: ImageFont.ImageFont, max_width: int) -> List[str]:
    lines: List[str] = []
    for paragraph in str(text).splitlines() or [""]:
        current = ""
        for char in paragraph:
            candidate = current + char
            bbox = draw.textbbox((0, 0), candidate, font=font)
            if bbox[2] - bbox[0] <= max_width:
                current = candidate
            else:
                if current:
                    lines.append(current)
                current = char
        if current:
            lines.append(current)
        elif not paragraph:
            lines.append("")
    return lines


def draw_rounded_rect(draw: ImageDraw.ImageDraw, box: Tuple[int, int, int, int], radius: int, fill: str, outline: Optional[str] = None, width: int = 1) -> None:
    draw.rounded_rectangle(box, radius=radius, fill=fill, outline=outline, width=width)


def create_result_image(mission: str, budget: int, items: List[dict], reason: str) -> bytes:
    fonts = load_fonts()
    temp = Image.new("RGB", (1000, 1000), "white")
    temp_draw = ImageDraw.Draw(temp)
    reason_lines = wrap_text_by_width(temp_draw, reason, fonts["body"], 860)

    item_h = 116
    height = 250 + max(1, len(items)) * item_h + 210 + len(reason_lines) * 34
    width = 1000
    img = Image.new("RGB", (width, height), "#FFFDF7")
    draw = ImageDraw.Draw(img)

    margin = 48
    y = 38
    mission_info = MISSIONS.get(mission, {})
    emoji = mission_info.get("emoji", "🛒")
    title = f"{emoji} 장보기 미션 결과"
    draw.text((margin, y), title, fill="#222222", font=fonts["title"])
    y += 62
    draw.text((margin, y), f"미션: {mission}", fill="#333333", font=fonts["subtitle"])
    y += 45

    total = sum(item["가격"] * item["수량"] for item in items)
    remaining = budget - total
    summary = f"예산 {money(budget)}  |  사용한 금액 {money(total)}  |  남은 돈 {money(remaining)}"
    draw_rounded_rect(draw, (margin, y, width - margin, y + 56), 18, "#F2F6FF", "#D8E3FF", 2)
    draw.text((margin + 22, y + 14), summary, fill="#1F3B73", font=fonts["body"])
    y += 88

    draw.text((margin, y), "구매한 물건", fill="#222222", font=fonts["subtitle"])
    y += 48

    if not items:
        draw.text((margin, y), "구매한 물건이 없습니다.", fill="#555555", font=fonts["body"])
        y += item_h
    else:
        for item in items:
            draw_rounded_rect(draw, (margin, y, width - margin, y + 94), 16, "#FFFFFF", "#E3E3E3", 1)
            product_img = load_product_image(item["이미지url"], (82, 74))
            img.paste(product_img, (margin + 12, y + 10))

            name = item["품명"]
            qty = item["수량"]
            price = item["가격"]
            subtotal = price * qty
            draw.text((margin + 112, y + 15), name, fill="#222222", font=fonts["body"])
            draw.text((margin + 112, y + 52), f"수량 {qty}개 · 개당 {money(price)}", fill="#555555", font=fonts["small"])
            subtotal_text = money(subtotal)
            bbox = draw.textbbox((0, 0), subtotal_text, font=fonts["body"])
            draw.text((width - margin - (bbox[2] - bbox[0]) - 22, y + 31), subtotal_text, fill="#222222", font=fonts["body"])
            y += item_h

    y += 18
    draw.text((margin, y), "구매 이유", fill="#222222", font=fonts["subtitle"])
    y += 48
    reason_box_height = max(100, len(reason_lines) * 34 + 38)
    draw_rounded_rect(draw, (margin, y, width - margin, y + reason_box_height), 18, "#FFFFFF", "#E3E3E3", 1)
    text_y = y + 22
    for line in reason_lines:
        draw.text((margin + 24, text_y), line, fill="#333333", font=fonts["body"])
        text_y += 34

    buffer = io.BytesIO()
    img.save(buffer, format="PNG")
    return buffer.getvalue()


def render_start_page() -> None:
    st.markdown('<div class="main-title">🛒 초등 장보기 미션 앱</div>', unsafe_allow_html=True)
    st.write("미션을 고르고, 정해진 예산 안에서 필요한 물건을 골라 보세요.")
    st.divider()

    cols = st.columns(3)
    for col, (mission, info) in zip(cols, MISSIONS.items()):
        with col:
            st.markdown(
                f"""
                <div class="mission-card">
                    <div class="mission-emoji">{info['emoji']}</div>
                    <h3>{mission}</h3>
                    <p>{info['description']}</p>
                    <p><b>예산: {money(info['budget'])}</b></p>
                </div>
                """,
                unsafe_allow_html=True,
            )
            st.button(
                "이 미션 시작하기",
                key=f"start_{safe_key(mission)}",
                use_container_width=True,
                on_click=reset_for_mission,
                args=(mission,),
            )

    st.info("미션을 시작하면 장바구니가 비워지고 새로 쇼핑을 시작합니다.")


def render_product_card(row: pd.Series, idx: int) -> None:
    mission = st.session_state.mission
    product_key = safe_key(f"{mission}_{idx}_{row['품명']}")
    st.session_state.quantities.setdefault(product_key, 0)

    with st.container(border=True):
        st.image(row["이미지url"], use_container_width=True)
        st.subheader(row["품명"])
        st.write(f"**가격:** {money(row['가격'])}")

        minus_col, qty_col, plus_col = st.columns([1, 1.1, 1])
        with minus_col:
            st.button(
                "－",
                key=f"minus_{product_key}",
                use_container_width=True,
                on_click=change_quantity,
                args=(product_key, -1),
            )
        with qty_col:
            st.markdown(
                f"<p style='text-align:center; font-size:1.1rem; font-weight:700;'>{st.session_state.quantities[product_key]}개</p>",
                unsafe_allow_html=True,
            )
        with plus_col:
            st.button(
                "＋",
                key=f"plus_{product_key}",
                use_container_width=True,
                on_click=change_quantity,
                args=(product_key, 1),
            )

        st.button(
            "장바구니 담기",
            key=f"add_{product_key}",
            use_container_width=True,
            disabled=st.session_state.quantities[product_key] <= 0,
            on_click=add_to_cart,
            args=(product_key, row["품명"], int(row["가격"]), row["이미지url"]),
        )


def render_cart(budget: int) -> None:
    total = cart_total()
    remaining = budget - total
    st.divider()
    st.markdown("## 🧺 장바구니")

    metric_cols = st.columns(3)
    metric_cols[0].metric("예산", money(budget))
    metric_cols[1].metric("사용 예정 금액", money(total))
    metric_cols[2].metric("남은 돈", money(remaining))

    if budget > 0:
        progress_value = min(total / budget, 1.0)
        st.progress(progress_value)

    if not st.session_state.cart:
        st.info("아직 장바구니에 담은 물건이 없습니다. 상품 수량을 정한 뒤 '장바구니 담기'를 눌러 주세요.")
    else:
        for name, item in list(st.session_state.cart.items()):
            cols = st.columns([1, 3, 1.2, 1.2, 1.2, 1])
            with cols[0]:
                st.image(item["이미지url"], use_container_width=True)
            with cols[1]:
                st.write(f"**{item['품명']}**")
                st.caption(f"개당 {money(item['가격'])}")
            with cols[2]:
                st.write(f"수량 **{item['수량']}개**")
            with cols[3]:
                st.write(f"합계 **{money(item['가격'] * item['수량'])}**")
            with cols[4]:
                adj_cols = st.columns(2)
                adj_cols[0].button("－", key=f"cart_minus_{safe_key(name)}", on_click=change_cart_quantity, args=(name, -1))
                adj_cols[1].button("＋", key=f"cart_plus_{safe_key(name)}", on_click=change_cart_quantity, args=(name, 1))
            with cols[5]:
                st.button("삭제", key=f"remove_{safe_key(name)}", on_click=remove_from_cart, args=(name,))

    exceeded = total > budget
    empty = len(st.session_state.cart) == 0
    if exceeded:
        st.error(f"예산을 {money(total - budget)} 초과했습니다. 제출하려면 수량을 줄이거나 물건을 삭제해 주세요.")
    elif not empty:
        st.success("예산 안에 들어왔습니다. 제출할 준비가 되었어요!")

    submitted = st.button(
        "제출하기",
        type="primary",
        use_container_width=True,
        disabled=exceeded or empty,
    )
    if submitted:
        st.session_state.page = "result"
        st.rerun()


def render_shopping_page(products: pd.DataFrame) -> None:
    mission = st.session_state.mission
    if mission is None:
        st.session_state.page = "start"
        st.rerun()

    mission_info = MISSIONS[mission]
    budget = mission_info["budget"]

    top_cols = st.columns([4, 1])
    with top_cols[0]:
        st.markdown(f'<div class="main-title">{mission_info["emoji"]} {mission}</div>', unsafe_allow_html=True)
        st.write(mission_info["description"])
    with top_cols[1]:
        st.button("처음으로", use_container_width=True, on_click=go_start)

    st.info(f"이번 미션 예산은 **{money(budget)}**입니다. 필요한 물건을 골라 장바구니에 담아 보세요.")

    mission_products = products[products["미션"] == mission].reset_index(drop=True)
    if mission_products.empty:
        st.warning("선택한 미션의 상품이 없습니다. products.csv의 미션 이름을 확인해 주세요.")
        return

    st.markdown("## 🛍️ 상품 진열대")
    for start in range(0, len(mission_products), 4):
        cols = st.columns(4)
        for offset, col in enumerate(cols):
            index = start + offset
            if index >= len(mission_products):
                continue
            with col:
                render_product_card(mission_products.iloc[index], index)

    render_cart(budget)


def render_result_page() -> None:
    mission = st.session_state.mission
    if mission is None:
        st.session_state.page = "start"
        st.rerun()

    budget = MISSIONS[mission]["budget"]
    items = list(st.session_state.cart.values())
    total = cart_total()
    remaining = budget - total

    top_cols = st.columns([4, 1, 1])
    with top_cols[0]:
        st.markdown('<div class="main-title">✅ 장보기 결과</div>', unsafe_allow_html=True)
        st.write(f"**미션:** {mission}")
    with top_cols[1]:
        st.button("쇼핑화면", use_container_width=True, on_click=go_shopping)
    with top_cols[2]:
        st.button("처음으로", use_container_width=True, on_click=go_start)

    metric_cols = st.columns(3)
    metric_cols[0].metric("예산", money(budget))
    metric_cols[1].metric("사용한 금액", money(total))
    metric_cols[2].metric("남은 돈", money(remaining))

    st.markdown("## 🧾 구매한 물건 목록")
    if not items:
        st.info("구매한 물건이 없습니다.")
    for item in items:
        cols = st.columns([1, 3, 1.2, 1.2])
        with cols[0]:
            st.image(item["이미지url"], use_container_width=True)
        with cols[1]:
            st.write(f"### {item['품명']}")
            st.caption(f"개당 {money(item['가격'])}")
        with cols[2]:
            st.write(f"수량: **{item['수량']}개**")
        with cols[3]:
            st.write(f"합계: **{money(item['가격'] * item['수량'])}**")

    st.markdown("## ✏️ 구매 이유 쓰기")
    st.text_area(
        "왜 이 물건들을 골랐나요? 예산과 미션을 생각하며 적어 보세요.",
        key="reason",
        height=160,
        placeholder="예: 카레를 만들기 위해 꼭 필요한 감자와 당근을 샀고, 남은 돈으로 가족이 함께 마실 물도 골랐습니다.",
    )

    if st.session_state.reason.strip():
        image_bytes = create_result_image(mission, budget, items, st.session_state.reason.strip())
        safe_file_mission = safe_key(mission)
        st.download_button(
            "그림으로 저장",
            data=image_bytes,
            file_name=f"장보기_미션_결과_{safe_file_mission}.png",
            mime="image/png",
            type="primary",
            use_container_width=True,
            on_click="ignore",
        )
    else:
        st.info("구매 이유를 작성하면 '그림으로 저장' 버튼이 나타납니다.")


def main() -> None:
    init_state()
    products = load_products(CSV_PATH)

    if st.session_state.page == "start":
        render_start_page()
    elif st.session_state.page == "shopping":
        render_shopping_page(products)
    elif st.session_state.page == "result":
        render_result_page()
    else:
        st.session_state.page = "start"
        st.rerun()


if __name__ == "__main__":
    main()
