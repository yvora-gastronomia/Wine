import hashlib
import io
import re
import unicodedata
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from urllib.parse import parse_qs, urlencode, urlparse

import pandas as pd
import requests
import streamlit as st

APP_TITLE = "YVORA Wine Pairing"

BRAND_BG = "#EFE7DD"
BRAND_BLUE = "#0E2A47"
BRAND_MUTED = "#6B7785"
BRAND_CARD = "#F5EFE7"
BRAND_WARN = "#F3D6CF"
BRAND_SOFT = "#F8F4EE"
BRAND_WHITE = "#FFFFFF"
BRAND_GOLD = "#C6A96A"

BASE_DIR = Path(__file__).resolve().parent
POSSIBLE_LOGOS = [
    BASE_DIR / "yvora_logo.png",
    BASE_DIR / "assets" / "yvora_logo.png",
]


def _find_logo_path() -> Path:
    for p in POSSIBLE_LOGOS:
        try:
            if p.exists():
                return p
        except Exception:
            continue
    return POSSIBLE_LOGOS[0]


LOGO_LOCAL_PATH = _find_logo_path()


def _get_secret(key: str, default: str = "") -> str:
    try:
        return st.secrets.get(key, default)
    except Exception:
        return default


def norm_text(x) -> str:
    try:
        if pd.isna(x):
            return ""
    except Exception:
        pass
    s = str(x)
    s = s.replace("—", "-").replace("–", "-").replace("•", "-")
    s = unicodedata.normalize("NFC", s)
    return s.strip()


def clean_display_text(s: str) -> str:
    s = norm_text(s)
    if not s:
        return ""
    s = s.replace("_", " ")
    return re.sub(r"\s+", " ", s).strip()


def to_int(x, default: int = 0) -> int:
    s = norm_text(x)
    if s == "":
        return default
    try:
        return int(float(s.replace(",", ".")))
    except Exception:
        return default


def to_float(x) -> Optional[float]:
    s = norm_text(x).replace("R$", "").replace(".", "").replace(",", ".").strip()
    if s == "":
        return None
    try:
        return float(s)
    except Exception:
        return None


def safe_numeric_series(series: pd.Series) -> pd.Series:
    return pd.to_numeric(
        series.astype(str).str.replace(",", ".", regex=False).str.extract(r"(-?\d+(?:\.\d+)?)", expand=False),
        errors="coerce",
    )


def sheet_hash(df: pd.DataFrame) -> str:
    payload = df.fillna("").astype(str).to_csv(index=False)
    return hashlib.md5(payload.encode("utf-8")).hexdigest()[:10]


def _decode_csv_bytes(raw: bytes) -> str:
    for enc in ("utf-8-sig", "utf-8"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            pass
    return raw.decode("cp1252", errors="replace")


def _extract_sheet_id_and_gid(url: str) -> Tuple[str, str]:
    u = norm_text(url).replace("\n", "").replace(" ", "")
    if not u:
        return "", "0"

    parsed = urlparse(u)
    qs = parse_qs(parsed.query)
    gid = (qs.get("gid", ["0"]) or ["0"])[0] or "0"

    m = re.search(r"/spreadsheets/d/([a-zA-Z0-9-_]+)", u)
    if m:
        return m.group(1), gid

    return "", gid


def _to_gsheet_csv_export_url(url: str) -> str:
    u = norm_text(url).replace("\n", "").strip()
    if not u:
        return ""

    if "googleusercontent.com" in u:
        return u.replace(" ", "")

    if "docs.google.com/spreadsheets" in u and "export" in u and "format=csv" in u:
        return u

    if "docs.google.com/spreadsheets" in u:
        sheet_id, gid = _extract_sheet_id_and_gid(u)
        if sheet_id:
            return f"https://docs.google.com/spreadsheets/d/{sheet_id}/export?" + urlencode(
                {"format": "csv", "gid": gid or "0"}
            )

    return u


@st.cache_data(ttl=3600, show_spinner=False)
def get_asset_bytes(local_path: Path, fallback_url: str = "") -> Optional[bytes]:
    try:
        if local_path.exists():
            return local_path.read_bytes()
    except Exception:
        pass

    fb = norm_text(fallback_url)
    if fb:
        try:
            r = requests.get(fb, timeout=30)
            r.raise_for_status()
            return r.content
        except Exception:
            return None
    return None


def render_logo(width: Optional[int] = None, use_container_width: bool = False):
    logo_url = _get_secret("LOGO_URL", "")
    b = get_asset_bytes(LOGO_LOCAL_PATH, logo_url)
    if b:
        st.image(b, width=width, use_container_width=use_container_width)
    else:
        st.caption("Logo não encontrada. Inclua em assets/ ou configure LOGO_URL em secrets.")


def sidebar_brand():
    with st.sidebar:
        render_logo(use_container_width=True)
        st.caption("YVORA | Meat & Cheese Lab")


@st.cache_data(ttl=45)
def load_csv_from_url(url: str) -> pd.DataFrame:
    export_url = _to_gsheet_csv_export_url(url)
    if not export_url:
        raise ValueError("URL vazia.")

    try:
        r = requests.get(export_url, timeout=30)
        r.raise_for_status()
    except requests.HTTPError as e:
        raise ValueError(
            "Falha ao baixar CSV do Google Sheets.\n\n"
            "Verifique:\n"
            "1) A planilha está compartilhada como 'Anyone with the link can view'.\n"
            "2) O link aponta para a aba correta (gid correto).\n"
            "3) Use o link normal do Sheets (edit#gid=...) que o app converte automaticamente.\n\n"
            f"Detalhe técnico: {e}"
        )

    csv_text = _decode_csv_bytes(r.content)
    return pd.read_csv(io.StringIO(csv_text), dtype=str, keep_default_na=False)


def normalize_cols(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    df.columns = [str(c).strip().lower() for c in df.columns]
    for c in df.columns:
        df[c] = df[c].apply(norm_text)
    return df


def make_key_for_pratos(prato_ids: List[str]) -> str:
    return "|".join(sorted([norm_text(x) for x in prato_ids if norm_text(x)]))


def is_wine_available_now(w: Dict) -> bool:
    return to_int(w.get("ativo", w.get("active", 0)), 0) == 1 and to_int(w.get("estoque", 0), 0) > 0


def set_page_style():
    st.set_page_config(
        page_title=APP_TITLE,
        page_icon="🍷",
        layout="wide",
        initial_sidebar_state="expanded",
    )

    css = f"""
    <style>
    .stApp {{
        background:
            radial-gradient(circle at top right, rgba(198,169,106,0.12), transparent 22%),
            linear-gradient(180deg, {BRAND_BG} 0%, #FBF8F3 100%);
    }}

    [data-testid="stSidebar"] {{
        background: linear-gradient(180deg, rgba(14,42,71,0.98) 0%, rgba(14,42,71,0.94) 100%);
        border-right: 1px solid rgba(255,255,255,0.08);
    }}

    [data-testid="stSidebar"] * {{
        color: {BRAND_WHITE};
    }}

    .block-container {{
        padding-top: 1.2rem;
        padding-bottom: 2rem;
    }}

    h1, h2, h3, h4 {{
        color: {BRAND_BLUE};
        letter-spacing: -0.02em;
    }}

    .yvora-shell {{
        max-width: 1240px;
        margin: 0 auto;
    }}

    .yvora-hero {{
        background: linear-gradient(135deg, rgba(255,255,255,0.95) 0%, rgba(245,239,231,0.95) 100%);
        border: 1px solid rgba(14,42,71,0.08);
        box-shadow: 0 14px 36px rgba(14,42,71,0.08);
        border-radius: 26px;
        padding: 22px;
        margin-bottom: 18px;
    }}

    .yvora-title {{
        color: {BRAND_BLUE};
        font-size: 2.15rem;
        font-weight: 800;
        margin: 0;
        letter-spacing: -0.03em;
    }}

    .yvora-subtitle {{
        color: {BRAND_MUTED};
        font-size: 1rem;
        line-height: 1.45rem;
        margin-top: 8px;
        max-width: 700px;
    }}

    .yvora-card {{
        background: linear-gradient(180deg, {BRAND_CARD} 0%, {BRAND_SOFT} 100%);
        border-radius: 22px;
        padding: 18px 18px 14px 18px;
        border: 1px solid rgba(14,42,71,0.08);
        margin-bottom: 18px;
        box-shadow: 0 10px 28px rgba(14,42,71,0.05);
    }}

    .yvora-card-title {{
        font-size: 1.28rem;
        font-weight: 800;
        color: {BRAND_BLUE};
        margin-bottom: 4px;
    }}

    .yvora-card-sub, .yvora-mini, .yvora-muted {{
        color: {BRAND_MUTED};
    }}

    .yvora-card-sub {{
        font-size: 0.93rem;
        margin-bottom: 10px;
    }}

    .yvora-section-head {{
        color: {BRAND_BLUE};
        font-size: 1.02rem;
        font-weight: 800;
        margin: 6px 0 8px 0;
    }}

    .yvora-warn {{
        background: {BRAND_WARN};
        border-radius: 14px;
        padding: 14px 16px;
        border: 1px solid rgba(14,42,71,0.08);
        color: {BRAND_BLUE};
    }}

    .yvora-chip {{
        display: inline-flex;
        align-items: center;
        gap: 6px;
        padding: 6px 11px;
        border-radius: 999px;
        border: 1px solid rgba(14,42,71,0.12);
        color: {BRAND_BLUE};
        font-size: 0.82rem;
        font-weight: 600;
        margin-right: 7px;
        margin-top: 6px;
        background: rgba(255,255,255,0.8);
        white-space: nowrap;
    }}

    .yvora-quote {{
        background: rgba(255,255,255,0.86);
        border: 1px solid rgba(14,42,71,0.08);
        border-radius: 16px;
        padding: 14px 15px;
        margin: 14px 0 12px 0;
        color: {BRAND_BLUE};
        font-weight: 700;
        font-size: 1rem;
        line-height: 1.45rem;
    }}

    .yvora-context {{
        background: rgba(255,255,255,0.78);
        border: 1px solid rgba(14,42,71,0.08);
        border-radius: 18px;
        padding: 15px;
        margin: 12px 0;
        color: {BRAND_BLUE};
        font-size: 0.95rem;
        line-height: 1.5rem;
    }}

    .yvora-signal-box {{
        background: rgba(255,255,255,0.78);
        border: 1px solid rgba(14,42,71,0.08);
        border-radius: 16px;
        padding: 12px;
        min-height: 72px;
        height: 100%;
    }}

    .yvora-signal-label {{
        color: {BRAND_MUTED};
        font-size: 0.76rem;
        font-weight: 700;
        text-transform: uppercase;
        letter-spacing: 0.04em;
        margin-bottom: 4px;
    }}

    .yvora-signal-value {{
        color: {BRAND_BLUE};
        font-size: 1.1rem;
        font-weight: 800;
        line-height: 1.2rem;
    }}

    .yvora-signal-sub {{
        color: {BRAND_MUTED};
        font-size: 0.82rem;
        margin-top: 4px;
        line-height: 1.1rem;
    }}

    .yvora-meters {{
        display: grid;
        grid-template-columns: repeat(3, minmax(0, 1fr));
        gap: 10px 12px;
        margin-top: 12px;
    }}

    .yvora-meter {{
        background: rgba(255,255,255,0.78);
        border: 1px solid rgba(14,42,71,0.08);
        border-radius: 16px;
        padding: 10px 11px;
    }}

    .yvora-meter-top {{
        display: flex;
        justify-content: space-between;
        align-items: center;
        gap: 10px;
        font-size: 0.87rem;
        color: {BRAND_BLUE};
        margin-bottom: 7px;
        font-weight: 700;
    }}

    .yvora-bar {{
        width: 100%;
        height: 9px;
        border-radius: 99px;
        background: rgba(14,42,71,0.10);
        overflow: hidden;
    }}

    .yvora-bar-fill {{
        height: 9px;
        border-radius: 99px;
        background: linear-gradient(90deg, {BRAND_GOLD} 0%, rgba(14,42,71,0.85) 100%);
        width: 0%;
    }}

    .yvora-summary {{
        display: grid;
        grid-template-columns: 1fr;
        gap: 10px;
        margin-top: 12px;
    }}

    .yvora-line {{
        display: flex;
        gap: 10px;
        align-items: flex-start;
        background: rgba(255,255,255,0.8);
        border: 1px solid rgba(14,42,71,0.08);
        padding: 12px 13px;
        border-radius: 16px;
        color: {BRAND_BLUE};
        font-size: 0.95rem;
        line-height: 1.38rem;
    }}

    .yvora-line span {{
        white-space: normal;
        word-break: normal;
        overflow-wrap: break-word;
    }}

    .stMultiSelect label {{
        color: {BRAND_BLUE};
        font-weight: 700;
    }}

    [data-testid="stExpander"] {{
        border: 1px solid rgba(14,42,71,0.08);
        border-radius: 16px;
        background: rgba(255,255,255,0.72);
    }}

    @media (max-width: 980px) {{
        .yvora-meters {{
            grid-template-columns: 1fr;
        }}
    }}
    </style>
    """
    st.markdown(css, unsafe_allow_html=True)


def _signal_box(label: str, value: str, sub: str):
    st.markdown(
        f"""
        <div class="yvora-signal-box">
          <div class="yvora-signal-label">{label}</div>
          <div class="yvora-signal-value">{value}</div>
          <div class="yvora-signal-sub">{sub}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def score_to_stars(score_raw: str) -> int:
    score = to_int(score_raw, 0)
    if score >= 90:
        return 5
    if score >= 80:
        return 4
    if score >= 70:
        return 3
    if score >= 60:
        return 2
    return 1


def render_star_string(n: int) -> str:
    n = max(1, min(5, n))
    return "★" * n + "☆" * (5 - n)


def render_signal_grid(row: Dict, option_label: str):
    stars_n = score_to_stars(row.get("score_harmonizacao", ""))
    stars = render_star_string(stars_n)
    strategy = clean_display_text(row.get("estrategia_harmonizacao", ""))
    role = clean_display_text(row.get("papel_do_vinho", ""))

    c1, c2 = st.columns(2)
    with c1:
        _signal_box(f"✨ {option_label}", stars, "Score Match")
    with c2:
        _signal_box("Estratégia", strategy or "Não informada", "Como o vinho entra")

    c3, _ = st.columns([1, 1])
    with c3:
        _signal_box("Papel do vinho", role or "Não informado", "O que ele faz")


def summarize_single_title(title: str) -> str:
    t = clean_display_text(title)
    tl = t.lower()

    mapping = [
        ("steak tartare com fonduta quattro formaggi", "steak tartare"),
        ("tartare de atum com burrata, parmesão e pistache tostado", "tartare de atum"),
        ("tartare de atum fresco com chèvre cremoso e azeite cítrico", "tartare de atum"),
        ("croquetta de parma", "croquetta de parma"),
        ("parma italiano com creme de gorgonzola dolce", "parma"),
        ("roast beef rosado com creme aerado de gorgonzola", "roast beef"),
        ("espetinho de cupim de longa cocção com tortillas e provolone defumado", "cupim"),
        ("nuvem da fazenda atalaia em crosta com filé mignon", "nuvem atalaia com filé mignon"),
        ("tutano assado com tartare de filé mignon e gruyère ralado", "tutano com tartare"),
        ("carpaccio bovino", "carpaccio bovino"),
    ]

    for k, v in mapping:
        if k in tl:
            return v

    return t


def summarize_combo_title(title: str) -> str:
    t = clean_display_text(title)

    if "|" in t:
        parts = [clean_display_text(x) for x in t.split("|") if clean_display_text(x)]
        if len(parts) == 2:
            return f"{summarize_single_title(parts[0])} + {summarize_single_title(parts[1])}"

    if " + " in t:
        parts = [clean_display_text(x) for x in t.split(" + ") if clean_display_text(x)]
        if len(parts) == 2:
            return f"{summarize_single_title(parts[0])} + {summarize_single_title(parts[1])}"

    return summarize_single_title(t)


def is_combo_context(title: str) -> bool:
    t = clean_display_text(title)
    return "|" in t or " + " in t.lower()


def ensure_connected_summary(row: Dict, dish_title: str) -> str:
    frase = clean_display_text(row.get("frase_mesa", ""))
    nome_vinho = clean_display_text(row.get("nome_vinho", ""))
    prato = summarize_combo_title(dish_title)
    combo = clean_display_text(row.get("por_que_combo", ""))

    if frase and nome_vinho.lower() in frase.lower() and prato.lower() in frase.lower():
        return frase

    combo_sentence = combo.split(". ")[0].strip() if combo else ""
    if combo_sentence and nome_vinho and prato:
        text = combo_sentence
        if nome_vinho.lower() not in text.lower():
            text = f"{nome_vinho} acompanha {prato} porque {text[:1].lower() + text[1:] if len(text) > 1 else text.lower()}"
        elif prato.lower() not in text.lower():
            text = f"{text} em {prato}"
        return text.rstrip(".") + "."

    if nome_vinho and prato:
        if is_combo_context(dish_title):
            return f"{nome_vinho} acompanha {prato} porque foi escolhido para sustentar os dois elementos principais da combinação com leitura clara no paladar."
        return f"{nome_vinho} acompanha {prato} porque entrega estrutura e leitura clara no paladar."

    return frase or combo or "-"


def build_summary_lines(row: Dict, title: str) -> Tuple[str, str, str]:
    combo_label = summarize_combo_title(title)

    pc = clean_display_text(row.get("por_que_carne", ""))
    pq = clean_display_text(row.get("por_que_queijo", ""))
    combo = clean_display_text(row.get("por_que_combo", ""))

    if not pc:
        if is_combo_context(title):
            pc = f"No conjunto {combo_label}, o vinho sustenta a proteína principal sem perder presença."
        else:
            pc = "O vinho foi escolhido para acompanhar a proteína sem perder presença no prato."

    if not pq:
        if is_combo_context(title):
            pq = f"Na combinação {combo_label}, o vinho foi pensado para lidar com sal, gordura e textura dos queijos envolvidos."
        else:
            pq = "O vinho foi pensado para lidar com sal, gordura e textura do queijo."

    if not combo:
        if is_combo_context(title):
            combo = f"O vinho foi escolhido para organizar {combo_label} no paladar com leitura clara e sem conflito."
        else:
            combo = "A leitura final busca clareza no paladar e uma decisão fácil para o cliente."

    return pc, pq, combo


def build_reason_text(row: Dict, title: str) -> str:
    nome_vinho = clean_display_text(row.get("nome_vinho", ""))
    prato = summarize_combo_title(title)
    score_reason = clean_display_text(row.get("motivo_score", ""))
    role = clean_display_text(row.get("papel_do_vinho", ""))
    strategy = clean_display_text(row.get("estrategia_harmonizacao", ""))

    if score_reason and nome_vinho and prato:
        base = score_reason.rstrip(".")
        if nome_vinho.lower() not in base.lower():
            return f"{nome_vinho} foi recomendado para {prato} porque {base[:1].lower() + base[1:] if len(base) > 1 else base.lower()}."
        if prato.lower() not in base.lower():
            return f"{base} em {prato}."
        return base + "."

    parts = []
    if role:
        parts.append(role)
    if strategy:
        parts.append(strategy)

    if nome_vinho and prato and parts:
        return f"{nome_vinho} foi recomendado para {prato} por {', '.join(parts)}."
    if nome_vinho and prato:
        return f"{nome_vinho} foi recomendado para {prato} por leitura sensorial do prato e do vinho."
    return ""


def _parse_profile_line(text: str) -> Dict[str, str]:
    t = norm_text(text).lower()
    out: Dict[str, str] = {}

    def num(label: str):
        m = re.search(rf"{label}\s*[:=\-]?\s*(\d)\s*/\s*5", t)
        return int(m.group(1)) if m else None

    ac = num("acidez")
    co = num("corpo")
    ta = num("tanino")

    if ac is not None:
        out["acidez"] = str(max(0, min(5, ac)))
    if co is not None:
        out["corpo"] = str(max(0, min(5, co)))
    if ta is not None:
        out["tanino"] = str(max(0, min(5, ta)))

    m = re.search(r"final\s*[:=\-]?\s*(curto|medio|médio|longo)", t)
    if m:
        out["final"] = m.group(1).replace("medio", "médio")

    m = re.search(r"(aromas?|perfil\s+arom[aá]tico)\s*[:=\-]\s*([^|\n]{3,90})", norm_text(text), flags=re.IGNORECASE)
    if m:
        out["aromas"] = clean_display_text(m.group(2))
    return out


def _pct_from_5(n: int) -> int:
    return int((max(0, min(5, n)) / 5) * 100)


def render_visual_profile(row: Dict):
    prof = _parse_profile_line(row.get("a_melhor_para", ""))
    if not prof:
        return

    st.markdown("<div class='yvora-meters'>", unsafe_allow_html=True)

    def meter(title: str, value_0_5: Optional[int]):
        if value_0_5 is None:
            return
        pct = _pct_from_5(value_0_5)
        st.markdown(
            f"""
            <div class="yvora-meter">
              <div class="yvora-meter-top"><span>{title}</span><span>{value_0_5}/5</span></div>
              <div class="yvora-bar"><div class="yvora-bar-fill" style="width:{pct}%"></div></div>
            </div>
            """,
            unsafe_allow_html=True,
        )

    ac = int(prof.get("acidez")) if prof.get("acidez") else None
    co = int(prof.get("corpo")) if prof.get("corpo") else None
    ta = int(prof.get("tanino")) if prof.get("tanino") else None

    meter("Acidez", ac)
    meter("Corpo", co)
    meter("Tanino", ta)

    st.markdown("</div>", unsafe_allow_html=True)

    fi = prof.get("final", "")
    ar = prof.get("aromas", "")
    bits = []
    if fi:
        bits.append(f"Final: {fi}")
    if ar:
        bits.append(f"Aromas: {ar}")
    if bits:
        st.markdown(f"<div class='yvora-mini'>{'  |  '.join(bits)}</div>", unsafe_allow_html=True)


def render_icon_row(row: Dict, wine_type: str):
    chips = []
    for icon, key in [("🏷️", "rotulo_valor"), ("🍇", "perfil_vinho"), ("✨", "estrategia_harmonizacao")]:
        value = clean_display_text(row.get(key, ""))
        if value:
            chips.append(f"<span class='yvora-chip'>{icon} {value}</span>")

    if wine_type:
        chips.append(f"<span class='yvora-chip'>🍷 {wine_type}</span>")

    if chips:
        st.markdown("".join(chips), unsafe_allow_html=True)


def standardize_menu(menu_df: pd.DataFrame) -> pd.DataFrame:
    df = menu_df.copy()

    def pick(opts: List[str]) -> str:
        for c in opts:
            if c in df.columns:
                return c
        return ""

    c_id = pick(["id_prato", "id", "prato_id"])
    c_nome = pick(["nome_prato", "prato", "nome", "title"])
    c_desc = pick(["descricao_prato", "descricao", "descrição", "desc"])
    c_ativo = pick(["ativo", "active", "status"])

    if "id" in df.columns and not c_id:
        c_id = "id"
    if "prato" in df.columns and not c_nome:
        c_nome = "prato"
    if "nome" in df.columns and not c_nome:
        c_nome = "nome"
    if "descrição" in df.columns and not c_desc:
        c_desc = "descrição"
    if "descricao" in df.columns and not c_desc:
        c_desc = "descricao"

    out = pd.DataFrame()
    out["id_prato"] = df[c_id] if c_id else ""
    out["nome_prato"] = df[c_nome] if c_nome else ""
    out["descricao_prato"] = df[c_desc] if c_desc else ""
    out["ativo"] = df[c_ativo] if c_ativo else "1"

    out["id_prato"] = out["id_prato"].apply(norm_text)
    out["nome_prato"] = out["nome_prato"].apply(clean_display_text)
    out["descricao_prato"] = out["descricao_prato"].apply(clean_display_text)
    out["ativo"] = out["ativo"].apply(lambda x: 1 if norm_text(x).lower() in ["1", "1.0", "true", "sim"] else 0)

    m = out["id_prato"].eq("")
    out.loc[m, "id_prato"] = out.loc[m, "nome_prato"]
    out = out[(out["nome_prato"] != "") & (out["ativo"] == 1)].copy()
    return out.drop_duplicates(subset=["id_prato", "nome_prato"])


def _normalize_wine_type(raw: str) -> str:
    t = norm_text(raw).lower()
    if not t:
        return ""
    if "espum" in t or "spark" in t or "champ" in t:
        return "Espumante"
    if "rose" in t or "rosé" in t:
        return "Rosé"
    if "branco" in t or "white" in t:
        return "Branco"
    if "tinto" in t or "red" in t:
        return "Tinto"
    return clean_display_text(raw.title())


def standardize_wines(wines_df: pd.DataFrame) -> pd.DataFrame:
    df = wines_df.copy()

    def pick(opts: List[str]) -> str:
        for c in opts:
            if c in df.columns:
                return c
        return ""

    c_id = pick(["wine_id", "id_vinho", "id", "vinho_id"])
    c_nome = pick(["wine_name", "nome_vinho", "vinho", "nome"])
    c_price = pick(["price", "preco", "preço", "valor"])
    c_stock = pick(["estoque", "stock", "qtd", "quantidade"])
    c_active = pick(["active", "ativo", "status"])
    c_type = pick(["tipo", "cor", "estilo", "wine_type", "type", "categoria", "tipo_vinho_padrao"])
    c_profile = pick(["perfil_vinho", "style", "perfil"])
    c_country = pick(["country", "pais"])
    c_region = pick(["region", "regiao"])

    out = pd.DataFrame()
    out["id_vinho"] = df[c_id] if c_id else ""
    out["nome_vinho"] = df[c_nome] if c_nome else ""
    out["preco_num"] = df[c_price].apply(to_float) if c_price else None
    out["estoque"] = df[c_stock].apply(lambda x: to_int(x, 0)) if c_stock else 0
    out["ativo"] = df[c_active].apply(lambda x: 1 if norm_text(x).lower() in ["1", "1.0", "true", "sim"] else 0) if c_active else 0
    out["tipo_vinho"] = df[c_type] if c_type else ""
    out["perfil_vinho"] = df[c_profile] if c_profile else ""
    out["region"] = df[c_region] if c_region else ""
    out["country"] = df[c_country] if c_country else ""

    out["id_vinho"] = out["id_vinho"].apply(norm_text)
    out["nome_vinho"] = out["nome_vinho"].apply(clean_display_text)
    out["tipo_vinho"] = out["tipo_vinho"].apply(_normalize_wine_type)
    out["perfil_vinho"] = out["perfil_vinho"].apply(clean_display_text)
    out["region"] = out["region"].apply(clean_display_text)
    out["country"] = out["country"].apply(clean_display_text)

    m = out["id_vinho"].eq("")
    out.loc[m, "id_vinho"] = out.loc[m, "nome_vinho"]
    return out[out["nome_vinho"] != ""].drop_duplicates(subset=["id_vinho", "nome_vinho"])


def standardize_pairings(pair_df: pd.DataFrame) -> pd.DataFrame:
    p = pair_df.copy()
    defaults = {
        "chave_pratos": "",
        "id_vinho": "",
        "nome_vinho": "",
        "rotulo_valor": "",
        "tipo_vinho": "",
        "perfil_vinho": "",
        "score_harmonizacao": "",
        "estrategia_harmonizacao": "",
        "papel_do_vinho": "",
        "nivel_confianca": "",
        "estrutura_match": "",
        "acidez_match": "",
        "tanino_match": "",
        "ponte_aromatica": "",
        "risco_sensorial": "",
        "diversidade_penalidade": "",
        "contador_uso_vinho": "",
        "motivo_score": "",
        "perfil_custo_beneficio": "",
        "selo_harmonizacao": "",
        "a_melhor_para": "",
        "frase_mesa": "",
        "por_que_carne": "",
        "por_que_queijo": "",
        "por_que_combo": "",
        "por_que_vale": "",
        "ordem_recomendacao": "",
    }
    for c, default in defaults.items():
        if c not in p.columns:
            p[c] = default

    if "ativo" in p.columns:
        p["ativo"] = p["ativo"].apply(lambda x: 1 if norm_text(x).lower() in ["1", "1.0", "true", "sim"] else 0)
    else:
        p["ativo"] = 1

    for c in p.columns:
        if p[c].dtype == object:
            p[c] = p[c].apply(clean_display_text)

    p["score_ord"] = safe_numeric_series(p["score_harmonizacao"]).fillna(0)
    p["ordem_ord"] = safe_numeric_series(p["ordem_recomendacao"]).fillna(999)

    return p[p["ativo"] == 1].copy()


def load_all_data() -> Tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    menu_url = _get_secret("MENU_SHEET_URL", "")
    wines_url = _get_secret("WINES_SHEET_URL", "")
    pairings_url = _get_secret("PAIRINGS_SHEET_URL", "")

    if not menu_url:
        raise ValueError("MENU_SHEET_URL não configurado.")
    if not wines_url:
        raise ValueError("WINES_SHEET_URL não configurado.")
    if not pairings_url:
        raise ValueError("PAIRINGS_SHEET_URL não configurado.")

    menu_df = normalize_cols(load_csv_from_url(menu_url))
    wines_df = normalize_cols(load_csv_from_url(wines_url))
    pair_df = normalize_cols(load_csv_from_url(pairings_url))
    return menu_df, wines_df, pair_df


def header_area():
    col1, col2 = st.columns([1, 4], vertical_alignment="center")
    with col1:
        render_logo(width=130)
    with col2:
        st.markdown(
            """
            <div class="yvora-hero">
              <div class="yvora-title">Wine Pairing</div>
              <div class="yvora-subtitle">Escolha até 2 pratos para ver a recomendação de vinho.</div>
            </div>
            """,
            unsafe_allow_html=True,
        )


def sort_pairings_subset(p_subset: pd.DataFrame) -> pd.DataFrame:
    p_subset = p_subset.copy()

    if "ordem_ord" not in p_subset.columns:
        p_subset["ordem_ord"] = safe_numeric_series(p_subset.get("ordem_recomendacao", pd.Series([], dtype=str))).fillna(999)
    if "score_ord" not in p_subset.columns:
        p_subset["score_ord"] = safe_numeric_series(p_subset.get("score_harmonizacao", pd.Series([], dtype=str))).fillna(0)

    has_explicit_order = (p_subset["ordem_ord"] < 999).any()

    if has_explicit_order:
        p_subset = p_subset.sort_values(
            ["ordem_ord", "score_ord", "nome_vinho"],
            ascending=[True, False, True],
            kind="mergesort",
        )
    else:
        p_subset = p_subset.sort_values(
            ["score_ord", "nome_vinho"],
            ascending=[False, True],
            kind="mergesort",
        )

    return p_subset.head(2)


def render_recos_block(
    title: str,
    p_subset: pd.DataFrame,
    wines_type_map: Dict[str, str],
    wines_meta_map: Dict[str, Dict[str, str]],
):
    st.markdown("<div class='yvora-card'>", unsafe_allow_html=True)
    st.markdown(f"<div class='yvora-card-title'>{title}</div>", unsafe_allow_html=True)

    if is_combo_context(title):
        combo_short = summarize_combo_title(title)
        sub = f"Sugestões para a combinação {combo_short}, com leitura dos dois elementos principais."
    else:
        sub = "Sugestões organizadas para decisão rápida, com estratégia e leitura sensorial do prato."
    st.markdown(f"<div class='yvora-card-sub'>{sub}</div>", unsafe_allow_html=True)

    p_subset = sort_pairings_subset(p_subset)

    for idx, (_, row) in enumerate(p_subset.iterrows()):
        nome_vinho = clean_display_text(row.get("nome_vinho", ""))
        id_vinho = clean_display_text(row.get("id_vinho", ""))
        wine_type = clean_display_text(row.get("tipo_vinho", "")) or clean_display_text(wines_type_map.get(id_vinho, ""))
        option_label = "1ª opção" if idx == 0 else "2ª opção"
        meta = wines_meta_map.get(id_vinho, {})
        origem_wine = " • ".join(
            [x for x in [clean_display_text(meta.get("country", "")), clean_display_text(meta.get("region", ""))] if x]
        )

        st.markdown(f"### {nome_vinho}")
        if origem_wine:
            st.markdown(f"<div class='yvora-mini'>{origem_wine}</div>", unsafe_allow_html=True)

        render_signal_grid(row, option_label)
        render_icon_row(row, wine_type)

        resumo = ensure_connected_summary(row, title)
        st.markdown(f"<div class='yvora-quote'>💬 {resumo}</div>", unsafe_allow_html=True)

        render_visual_profile(row)

        role = clean_display_text(row.get("papel_do_vinho", ""))
        score_reason = build_reason_text(row, title)

        context_parts = []
        if role:
            context_parts.append(f"<b>Papel do vinho:</b> {role}")
        if score_reason:
            context_parts.append(f"<b>Leitura técnica:</b> {score_reason}")

        if context_parts:
            st.markdown(f"<div class='yvora-context'>{'<br>'.join(context_parts)}</div>", unsafe_allow_html=True)

        l1, l2, l3 = build_summary_lines(row, title)
        st.markdown(
            f"""
            <div class="yvora-summary">
              <div class="yvora-line">🥩 <span>{l1}</span></div>
              <div class="yvora-line">🧀 <span>{l2}</span></div>
              <div class="yvora-line">🧠 <span>{l3}</span></div>
            </div>
            """,
            unsafe_allow_html=True,
        )

        with st.expander("Ver leitura completa"):
            colA, colB = st.columns(2)
            with colA:
                st.markdown("**Carne**")
                st.write(clean_display_text(row.get("por_que_carne", "")) or "-")
                st.markdown("**Queijo**")
                st.write(clean_display_text(row.get("por_que_queijo", "")) or "-")
            with colB:
                st.markdown("**Conjunto**")
                st.write(clean_display_text(row.get("por_que_combo", "")) or "-")
                st.markdown("**Valor da escolha**")
                st.write(clean_display_text(row.get("por_que_vale", "")) or "-")

        st.divider()

    st.markdown("</div>", unsafe_allow_html=True)


def render_client(menu: pd.DataFrame, wines: pd.DataFrame, pairings: pd.DataFrame):
    st.markdown("<div class='yvora-section-head'>Escolha seus pratos</div>", unsafe_allow_html=True)
    st.markdown(
        "<div class='yvora-muted'>Selecione 1 ou 2 pratos. O app mostra apenas vinhos com estoque disponível.</div>",
        unsafe_allow_html=True,
    )

    selected_names = st.multiselect(
        "Selecione 1 ou 2 pratos",
        options=menu["nome_prato"].tolist(),
        max_selections=2,
        placeholder="Digite para buscar no menu",
    )

    if not selected_names:
        st.info("Selecione ao menos 1 prato para ver as sugestões.")
        return

    selected = menu[menu["nome_prato"].isin(selected_names)].copy()
    selected_ids = selected["id_prato"].tolist()
    selected_titles = selected["nome_prato"].tolist()

    wines_dict = wines.to_dict(orient="records")
    available_ids = {w["id_vinho"] for w in wines_dict if is_wine_available_now(w)}
    wines_type_map = {norm_text(w["id_vinho"]): norm_text(w.get("tipo_vinho", "")) for w in wines_dict}
    wines_meta_map = {
        norm_text(w["id_vinho"]): {
            "perfil_vinho": norm_text(w.get("perfil_vinho", "")),
            "region": norm_text(w.get("region", "")),
            "country": norm_text(w.get("country", "")),
        }
        for w in wines_dict
    }

    if len(selected_ids) == 2:
        key_pair = make_key_for_pratos(selected_ids)
        p_pair = pairings[pairings["chave_pratos"].astype(str).str.strip() == key_pair].copy()
        p_pair = p_pair[p_pair["id_vinho"].isin(available_ids)].copy()

        combo_title = " | ".join(selected_titles)

        if p_pair.empty:
            st.markdown(
                "<div class='yvora-warn'><b>Sem recomendação para a combinação agora.</b><br>Esta combinação ainda não foi gerada ou os vinhos sugeridos estão sem estoque.</div>",
                unsafe_allow_html=True,
            )
        else:
            render_recos_block(combo_title, p_pair, wines_type_map, wines_meta_map)

        st.write("")

    st.markdown("<div class='yvora-section-head'>Melhor por prato</div>", unsafe_allow_html=True)
    for pid in selected_ids:
        key_single = make_key_for_pratos([pid])
        p_one = pairings[pairings["chave_pratos"].astype(str).str.strip() == key_single].copy()
        p_one = p_one[p_one["id_vinho"].isin(available_ids)].copy()

        prato_nome = menu[menu["id_prato"] == pid]["nome_prato"].iloc[0]

        if p_one.empty:
            st.markdown(
                f"<div class='yvora-warn'><b>{prato_nome}:</b> sem sugestão disponível agora.</div>",
                unsafe_allow_html=True,
            )
            continue

        render_recos_block(prato_nome, p_one, wines_type_map, wines_meta_map)


def render_dm(menu: pd.DataFrame, wines: pd.DataFrame, pairings: pd.DataFrame):
    st.markdown("<div class='yvora-section-head'>Diagnóstico DM</div>", unsafe_allow_html=True)
    st.markdown(
        "<div class='yvora-muted'>Leitura rápida da base carregada e dos campos técnicos disponíveis.</div>",
        unsafe_allow_html=True,
    )

    st.write(f"Menu hash: `{sheet_hash(menu)}`")
    st.write(f"Vinhos hash: `{sheet_hash(wines)}`")
    st.write(f"Pairings hash: `{sheet_hash(pairings)}`")

    wines_dict = wines.to_dict(orient="records")
    available_ids = {w["id_vinho"] for w in wines_dict if is_wine_available_now(w)}
    st.write(f"Vinhos disponíveis agora: **{len(available_ids)}**")
    st.write(f"Linhas de pairings ativas: **{len(pairings)}**")

    st.markdown("### Verificação de ordenação")
    debug_cols = [
        "chave_pratos",
        "id_vinho",
        "nome_vinho",
        "ordem_recomendacao",
        "score_harmonizacao",
        "score_ord",
        "ativo",
    ]
    for c in debug_cols:
        if c not in pairings.columns:
            pairings[c] = ""

    st.dataframe(pairings[debug_cols].sort_values(["chave_pratos", "score_ord"], ascending=[True, False]), use_container_width=True)


def dm_login_block() -> bool:
    admin_password = _get_secret("ADMIN_PASSWORD", "")
    if "dm" not in st.session_state:
        st.session_state.dm = False

    with st.sidebar:
        st.markdown("### Acesso DM")
        if st.session_state.dm:
            st.success("Modo DM ativo")
            if st.button("Sair do DM", use_container_width=True):
                st.session_state.dm = False
                st.rerun()
        else:
            pwd = st.text_input("Senha", type="password", placeholder="Digite a senha do DM")
            if st.button("Entrar", use_container_width=True):
                if pwd and admin_password and pwd == admin_password:
                    st.session_state.dm = True
                    st.rerun()
                else:
                    st.error("Senha inválida.")
    return bool(st.session_state.dm)


def main():
    set_page_style()
    sidebar_brand()
    dm = dm_login_block()
    st.markdown("<div class='yvora-shell'>", unsafe_allow_html=True)
    header_area()

    try:
        menu_df, wines_df, pair_df = load_all_data()
        menu = standardize_menu(menu_df)
        wines = standardize_wines(wines_df)
        pairings = standardize_pairings(pair_df)
    except Exception as e:
        st.markdown(
            f"<div class='yvora-warn'><b>Erro ao carregar dados:</b><br>{e}</div>",
            unsafe_allow_html=True,
        )
        st.markdown("</div>", unsafe_allow_html=True)
        st.stop()

    if dm:
        render_dm(menu, wines, pairings)
    else:
        render_client(menu, wines, pairings)

    st.markdown("</div>", unsafe_allow_html=True)


if __name__ == "__main__":
    main()
