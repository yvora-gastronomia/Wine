import hashlib
import io
import re
from pathlib import Path
import unicodedata
from typing import Dict, List, Optional, Tuple
from urllib.parse import urlparse, parse_qs, urlencode

import pandas as pd
import requests
import streamlit as st

APP_TITLE = "YVORA Wine Pairing"
BRAND_BG = "#EFE7DD"
BRAND_BLUE = "#0E2A47"
BRAND_MUTED = "#6B7785"
BRAND_CARD = "#F5EFE7"
BRAND_WARN = "#F3D6CF"

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
    if pd.isna(x):
        return ""
    s = str(x)
    s = s.replace("—", "-").replace("–", "-").replace("•", "-")
    s = unicodedata.normalize("NFC", s)
    return s.strip()


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


def normalize_cols(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    df.columns = [str(c).strip().lower() for c in df.columns]
    for c in df.columns:
        df[c] = df[c].apply(norm_text)
    return df


def to_int(x, default: int = 0) -> int:
    s = norm_text(x)
    if s == "":
        return default
    try:
        return int(float(s))
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
            base = f"https://docs.google.com/spreadsheets/d/{sheet_id}/export"
            params = {"format": "csv", "gid": gid or "0"}
            return base + "?" + urlencode(params)

    return u


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


def make_key_for_pratos(prato_ids: List[str]) -> str:
    ids_sorted = sorted([norm_text(x) for x in prato_ids if norm_text(x)])
    return "|".join(ids_sorted)


def is_wine_available_now(w: Dict) -> bool:
    ativo = to_int(w.get("ativo", w.get("active", 0)), 0)
    est = to_int(w.get("estoque", 0), 0)
    return ativo == 1 and est > 0


def set_page_style():
    st.set_page_config(
        page_title=APP_TITLE,
        page_icon="🍷",
        layout="wide",
        initial_sidebar_state="expanded",
    )
    st.markdown(
        f"""
        <style>
        .stApp {{
            background: {BRAND_BG};
        }}
        h1, h2, h3, h4 {{
            color: {BRAND_BLUE};
        }}
        .yvora-subtitle {{
            color: {BRAND_MUTED};
            font-size: 1.05rem;
            margin-top: -8px;
        }}
        .yvora-card {{
            background: {BRAND_CARD};
            border-radius: 16px;
            padding: 16px 16px;
            border: 1px solid rgba(14,42,71,0.10);
            margin-bottom: 14px;
        }}
        .yvora-warn {{
            background: {BRAND_WARN};
            border-radius: 12px;
            padding: 14px 16px;
            border: 1px solid rgba(14,42,71,0.08);
        }}
        .yvora-chip {{
            display: inline-flex;
            align-items: center;
            gap: 6px;
            padding: 4px 10px;
            border-radius: 999px;
            border: 1px solid rgba(14,42,71,0.16);
            color: {BRAND_BLUE};
            font-size: 0.82rem;
            margin-right: 6px;
            margin-top: 6px;
            background: rgba(255,255,255,0.55);
            white-space: nowrap;
        }}
        .yvora-quote {{
            background: rgba(255,255,255,0.65);
            border: 1px solid rgba(14,42,71,0.12);
            border-radius: 12px;
            padding: 10px 12px;
            margin: 10px 0 8px 0;
            color: {BRAND_BLUE};
            font-weight: 650;
        }}
        .yvora-mini {{
            color: {BRAND_MUTED};
            font-size: 0.92rem;
            margin-top: 2px;
        }}
        .yvora-context {{
            background: rgba(255,255,255,0.55);
            border: 1px solid rgba(14,42,71,0.10);
            border-radius: 14px;
            padding: 12px 12px;
            margin: 10px 0 10px 0;
            color: {BRAND_BLUE};
            font-size: 0.94rem;
            line-height: 1.35rem;
        }}
        .yvora-meters {{
            display: grid;
            grid-template-columns: 1fr 1fr 1fr;
            gap: 8px 12px;
            margin-top: 10px;
        }}
        .yvora-meter {{
            background: rgba(255,255,255,0.55);
            border: 1px solid rgba(14,42,71,0.10);
            border-radius: 12px;
            padding: 8px 10px;
        }}
        .yvora-meter-top {{
            display: flex;
            justify-content: space-between;
            align-items: center;
            gap: 10px;
            font-size: 0.88rem;
            color: {BRAND_BLUE};
            margin-bottom: 6px;
        }}
        .yvora-bar {{
            width: 100%;
            height: 8px;
            border-radius: 99px;
            background: rgba(14,42,71,0.12);
            overflow: hidden;
        }}
        .yvora-bar-fill {{
            height: 8px;
            border-radius: 99px;
            background: rgba(14,42,71,0.55);
            width: 0%;
        }}

        /* RESUMO VISUAL */
        .yvora-summary {{
            display: grid;
            grid-template-columns: 1fr;
            gap: 8px;
            margin-top: 10px;
        }}
        .yvora-line {{
            display: flex;
            gap: 10px;
            align-items: flex-start;
            background: rgba(255,255,255,0.55);
            border: 1px solid rgba(14,42,71,0.10);
            padding: 9px 10px;
            border-radius: 12px;
            color: {BRAND_BLUE};
            font-size: 0.92rem;
            line-height: 1.25rem;
        }}
        .yvora-line span {{
            white-space: normal;
            word-break: normal;
            overflow-wrap: break-word;
        }}
        .yvora-clamp1 {{
            display: -webkit-box;
            -webkit-line-clamp: 1;
            -webkit-box-orient: vertical;
            overflow: hidden;
        }}
        </style>
        """,
        unsafe_allow_html=True,
    )


def sidebar_brand():
    with st.sidebar:
        render_logo(use_container_width=True)
        st.caption("YVORA - Meat & Cheese Lab")


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


def header_area():
    col1, col2 = st.columns([1, 3], vertical_alignment="center")
    with col1:
        render_logo(width=120)
    with col2:
        st.markdown("# Wine Pairing")
        st.markdown(
            "<div class='yvora-subtitle'>Harmonização de vinhos com carnes e queijos, no padrão YVORA.</div>",
            unsafe_allow_html=True,
        )


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
    if "descrição" in df.columns and not c_desc:
        c_desc = "descrição"

    out = pd.DataFrame()
    out["id_prato"] = df[c_id] if c_id else ""
    out["nome_prato"] = df[c_nome] if c_nome else ""
    out["descricao_prato"] = df[c_desc] if c_desc else ""
    out["ativo"] = df[c_ativo] if c_ativo else "1"

    out["id_prato"] = out["id_prato"].apply(norm_text)
    out["nome_prato"] = out["nome_prato"].apply(norm_text)
    out["descricao_prato"] = out["descricao_prato"].apply(norm_text)
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
    if "laranja" in t or "orange" in t:
        return "Laranja"
    if "sobremesa" in t or "doce" in t or "dessert" in t or "porto" in t or "sherry" in t:
        return "Sobremesa"
    return raw.strip().title()


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
    c_type = pick(["tipo", "cor", "estilo", "wine_type", "type", "categoria"])

    out = pd.DataFrame()
    out["id_vinho"] = df[c_id] if c_id else ""
    out["nome_vinho"] = df[c_nome] if c_nome else ""
    out["preco_num"] = df[c_price].apply(to_float) if c_price else None
    out["estoque"] = df[c_stock].apply(lambda x: to_int(x, 0)) if c_stock else 0
    out["ativo"] = df[c_active].apply(lambda x: 1 if norm_text(x).lower() in ["1", "1.0", "true", "sim"] else 0) if c_active else 0
    out["tipo_vinho"] = df[c_type] if c_type else ""

    out["id_vinho"] = out["id_vinho"].apply(norm_text)
    out["nome_vinho"] = out["nome_vinho"].apply(norm_text)
    out["tipo_vinho"] = out["tipo_vinho"].apply(_normalize_wine_type)

    m = out["id_vinho"].eq("")
    out.loc[m, "id_vinho"] = out.loc[m, "nome_vinho"]

    return out[out["nome_vinho"] != ""].drop_duplicates(subset=["id_vinho", "nome_vinho"])


def standardize_pairings(pair_df: pd.DataFrame) -> pd.DataFrame:
    p = pair_df.copy()
    for c in ["chave_pratos", "id_vinho", "nome_vinho", "rotulo_valor"]:
        if c not in p.columns:
            p[c] = ""
    if "ativo" in p.columns:
        p["ativo"] = p["ativo"].apply(lambda x: 1 if norm_text(x).lower() in ["1", "1.0", "true", "sim"] else 0)
    else:
        p["ativo"] = 1
    return p[p["ativo"] == 1].copy()


def _clamp_0_5(x: int) -> int:
    try:
        v = int(x)
    except Exception:
        return 0
    return max(0, min(5, v))


def _pct_from_5(n: int) -> int:
    n = _clamp_0_5(n)
    return int((n / 5) * 100)


def _parse_profile_line(text: str) -> Dict[str, str]:
    t = norm_text(text).lower()
    out: Dict[str, str] = {}

    def num(label: str) -> Optional[int]:
        m = re.search(rf"{label}\s*[:=\-]?\s*(\d)\s*/\s*5", t)
        if m:
            return int(m.group(1))
        return None

    ac = num("acidez")
    co = num("corpo")
    ta = num("tanino")

    if ac is not None:
        out["acidez"] = str(_clamp_0_5(ac))
    if co is not None:
        out["corpo"] = str(_clamp_0_5(co))
    if ta is not None:
        out["tanino"] = str(_clamp_0_5(ta))

    m = re.search(r"final\s*[:=\-]?\s*(curto|medio|médio|longo)", t)
    if m:
        out["final"] = m.group(1).replace("medio", "médio")

    m = re.search(r"(aromas?|perfil\s+arom[aá]tico)\s*[:=\-]\s*([^|\n]{3,90})", norm_text(text), flags=re.IGNORECASE)
    if m:
        out["aromas"] = norm_text(m.group(2))

    return out


def _guess_strategy(text: str) -> str:
    t = norm_text(text).lower()
    if "limpeza" in t:
        return "Limpeza"
    if "ponte arom" in t or "ponte" in t:
        return "Ponte aromática"
    if "contraste" in t or "contraponto" in t:
        return "Contraste"
    if "amplifica" in t or "realça" in t:
        return "Amplificação"
    if "equilíb" in t or "equilibr" in t:
        return "Equilíbrio"
    return "Estratégia"


def _strategy_explain(strategy: str) -> str:
    s = norm_text(strategy)
    mapping = {
        "Limpeza": "Ideia da harmonização: o vinho limpa gordura e sal com a acidez, deixando a próxima mordida mais leve.",
        "Ponte aromática": "Ideia da harmonização: aromas do vinho repetem aromas do prato, dando sensação de encaixe.",
        "Contraste": "Ideia da harmonização: o vinho cria contraste controlado (ex.: acidez vs gordura) sem conflito.",
        "Amplificação": "Ideia da harmonização: o vinho realça o sabor dominante e prolonga o final do prato.",
        "Equilíbrio": "Ideia da harmonização: o vinho acompanha a intensidade e mantém o conjunto harmônico.",
    }
    return mapping.get(s, "Ideia da harmonização: o vinho foi escolhido para reduzir risco sensorial e destacar o prato.")


def first_sentence(text: str) -> str:
    s = norm_text(text)
    if not s:
        return ""
    m = re.split(r"(?<=[.!?])\s+", s)
    if m and m[0]:
        return m[0]
    return s


def _compact_one_line(text: str, hard_max: int = 150) -> str:
    s = norm_text(text)
    if not s:
        return ""
    s = re.sub(r"\s+", " ", s).strip()
    if len(s) <= hard_max:
        return s
    cut = s.rfind(" ", 0, hard_max)
    if cut <= 0:
        return s[:hard_max].rstrip()
    return s[:cut].rstrip()


def _remove_scale_mentions(text: str) -> str:
    s = norm_text(text)
    if not s:
        return ""
    s = re.sub(r"\b(acidez|corpo|tanino)\s*\d\s*/\s*5\b", "", s, flags=re.IGNORECASE)
    s = re.sub(r"\s{2,}", " ", s).strip()
    return s


def _extract_food_name_in_parentheses(text: str) -> str:
    s = norm_text(text)
    m = re.search(r"\(([^)]{2,60})\)", s)
    if m:
        return norm_text(m.group(1))
    return ""


def _prefix_wine(nome_vinho: str, wine_type: str) -> str:
    n = norm_text(nome_vinho)
    t = norm_text(wine_type)
    if t:
        return f"O vinho {n} ({t})"
    return f"O vinho {n}"


def _ensure_sentence(s: str) -> str:
    s = norm_text(s)
    if not s:
        return ""
    if s[-1] not in ".!?":
        s += "."
    return s


def make_context_sentence(nome_vinho: str, wine_type: str, sensacao: str) -> str:
    pre = _prefix_wine(nome_vinho, wine_type)
    s = _remove_scale_mentions(sensacao)
    s = _compact_one_line(s, 130)
    if not s:
        return ""
    s = s[0].lower() + s[1:] if len(s) > 1 else s.lower()
    return _ensure_sentence(f"{pre} {s}")


def make_summary_carne(nome_vinho: str, wine_type: str, text: str) -> str:
    pre = _prefix_wine(nome_vinho, wine_type)
    dish = _extract_food_name_in_parentheses(text)
    base = _remove_scale_mentions(first_sentence(text))
    base = re.sub(r"^a\s+carne\s*\([^)]+\)\s*", "", base, flags=re.IGNORECASE).strip()
    if dish:
        core = f"na carne ({dish}), {base}"
    else:
        core = f"na carne, {base}"
    core = core.replace("vem ", "").replace("traz ", "").strip()
    return _compact_one_line(_ensure_sentence(f"{pre} {core}"), 150)


def make_summary_queijo(nome_vinho: str, wine_type: str, text: str) -> str:
    pre = _prefix_wine(nome_vinho, wine_type)
    dish = _extract_food_name_in_parentheses(text)
    base = _remove_scale_mentions(first_sentence(text))
    base = re.sub(r"^o\s+queijo\s*\([^)]+\)\s*", "", base, flags=re.IGNORECASE).strip()
    if dish:
        core = f"no queijo ({dish}), {base}"
    else:
        core = f"no queijo, {base}"
    core = core.replace("traz ", "").strip()
    return _compact_one_line(_ensure_sentence(f"{pre} {core}"), 150)


def make_summary_combo(nome_vinho: str, wine_type: str, strategy: str, full_combo_text: str) -> str:
    pre = _prefix_wine(nome_vinho, wine_type)
    expl = _strategy_explain(strategy)
    t = norm_text(full_combo_text).lower()

    risk = ""
    if "não amarga" in t or "amargar" in t:
        risk = "Risco baixo: tanino não amarga com sal e tostado."
    elif "não apaga" in t or "não some" in t:
        risk = "Risco baixo: não apaga o prato."
    else:
        risk = "Risco baixo: não conflita com queijo e carne."

    return _compact_one_line(_ensure_sentence(f"{pre}. {expl} {risk}"), 185)


def render_visual_profile(row: Dict):
    prof = _parse_profile_line(row.get("a_melhor_para", ""))
    if not prof:
        return

    ac = int(prof.get("acidez", "0")) if prof.get("acidez") else None
    co = int(prof.get("corpo", "0")) if prof.get("corpo") else None
    ta = int(prof.get("tanino", "0")) if prof.get("tanino") else None

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

    meter("Acidez", ac)
    meter("Corpo", co)
    meter("Tanino", ta)

    st.markdown("</div>", unsafe_allow_html=True)

    fi = prof.get("final", "")
    ar = prof.get("aromas", "")
    if fi or ar:
        line = []
        if fi:
            line.append(f"Final: {fi}")
        if ar:
            line.append(f"Aromas: {ar}")
        st.markdown(f"<div class='yvora-mini'>{'  |  '.join(line)}</div>", unsafe_allow_html=True)


def render_icon_row(row: Dict, wine_type: str):
    strategy = _guess_strategy(row.get("por_que_combo", ""))
    rot = norm_text(row.get("rotulo_valor", "$")) or "$"

    chips = []
    chips.append(f"<span class='yvora-chip'>🏷️ {rot}</span>")

    if wine_type:
        chips.append(f"<span class='yvora-chip'>🍷 {wine_type}</span>")

    if strategy and strategy != "Estratégia":
        icon = "🧭"
        if strategy == "Limpeza":
            icon = "💧"
        elif strategy == "Ponte aromática":
            icon = "🌿"
        elif strategy == "Contraste":
            icon = "⚡"
        elif strategy == "Amplificação":
            icon = "🔥"
        elif strategy == "Equilíbrio":
            icon = "⚖️"
        chips.append(f"<span class='yvora-chip'>{icon} {strategy}</span>")

    st.markdown("".join(chips), unsafe_allow_html=True)


def _context_box(nome_vinho: str, wine_type: str, strategy: str, sensacao: str) -> str:
    pre = _prefix_wine(nome_vinho, wine_type)
    expl = _strategy_explain(strategy)
    ss = make_context_sentence(nome_vinho, wine_type, sensacao)
    if not ss:
        ss = _ensure_sentence(f"{pre} foi selecionado para encaixar com a intensidade do prato e do queijo")
    return f"""
    <div class="yvora-context">
      <b>Como ler esta sugestão</b><br>
      1) Você está avaliando <b>{pre}</b> com estes pratos.<br>
      2) <b>Ideia da harmonização:</b> {expl}<br>
      3) <b>O que você sente:</b> {ss}
    </div>
    """


def render_recos_block(title: str, p_subset: pd.DataFrame, wines_type_map: Dict[str, str]):
    st.markdown("<div class='yvora-card'>", unsafe_allow_html=True)
    st.markdown(f"#### {title}")

    order = {"$$$": 0, "$$": 1, "$": 2}
    p_subset = p_subset.copy()
    p_subset["ord"] = p_subset["rotulo_valor"].apply(lambda x: order.get(norm_text(x), 9))
    p_subset = p_subset.sort_values(["ord", "nome_vinho"], ascending=True).head(3)

    for _, row in p_subset.iterrows():
        nome_vinho = norm_text(row.get("nome_vinho", ""))
        id_vinho = norm_text(row.get("id_vinho", ""))
        wine_type = wines_type_map.get(id_vinho, "")

        st.markdown(f"### {nome_vinho}")
        render_icon_row(row, wine_type)

        frase = norm_text(row.get("frase_mesa", ""))
        if frase:
            # Frase de mesa: agora auto-explicativa e contextualizada com o vinho
            pre = _prefix_wine(nome_vinho, wine_type)
            mesa = _compact_one_line(frase, 130)
            if mesa:
                st.markdown(
                    f"<div class='yvora-quote'>💬 {pre}: <span class='yvora-clamp1'>{mesa}</span></div>",
                    unsafe_allow_html=True,
                )

        render_visual_profile(row)

        por_vale = norm_text(row.get("por_que_vale", ""))
        sensacao_raw = first_sentence(por_vale) if por_vale else first_sentence(row.get("por_que_combo", ""))
        sensacao_raw = _remove_scale_mentions(sensacao_raw)
        if sensacao_raw:
            st.markdown(f"<div class='yvora-mini yvora-clamp1'>✨ {make_context_sentence(nome_vinho, wine_type, sensacao_raw)}</div>", unsafe_allow_html=True)

        full_pc = norm_text(row.get("por_que_carne", ""))
        full_pq = norm_text(row.get("por_que_queijo", ""))
        full_combo = norm_text(row.get("por_que_combo", ""))

        strategy = _guess_strategy(full_combo)

        # Caixa de contexto para quem abriu o app e precisa entender tudo sem conhecer termos
        st.markdown(_context_box(nome_vinho, wine_type, strategy, sensacao_raw), unsafe_allow_html=True)

        # Resumo de decisão: 3 linhas curtas, sempre mencionando o vinho e o efeito
        pc_short = make_summary_carne(nome_vinho, wine_type, full_pc)
        pq_short = make_summary_queijo(nome_vinho, wine_type, full_pq)
        combo_short = make_summary_combo(nome_vinho, wine_type, strategy, full_combo)

        st.markdown(
            f"""
            <div class="yvora-summary">
              <div class="yvora-line">🥩 <span class="yvora-clamp1">{pc_short}</span></div>
              <div class="yvora-line">🧀 <span class="yvora-clamp1">{pq_short}</span></div>
              <div class="yvora-line">🧠 <span class="yvora-clamp1">{combo_short}</span></div>
            </div>
            """,
            unsafe_allow_html=True,
        )

        with st.expander("Detalhes completos"):
            best = norm_text(row.get("a_melhor_para", ""))

            colA, colB = st.columns(2)
            with colA:
                if full_pc:
                    st.markdown("**🥩 O que o vinho faz com a carne**")
                    st.write(_ensure_sentence(f"{_prefix_wine(nome_vinho, wine_type)} com a carne: {full_pc}"))
                if full_pq:
                    st.markdown("**🧀 O que o vinho faz com o queijo**")
                    st.write(_ensure_sentence(f"{_prefix_wine(nome_vinho, wine_type)} com o queijo: {full_pq}"))
            with colB:
                if full_combo:
                    st.markdown("**⚖️ Por que funciona no conjunto**")
                    st.write(_ensure_sentence(f"Nesta combinação, {_prefix_wine(nome_vinho, wine_type)} funciona assim: {full_combo}"))
                if best:
                    st.markdown("**⭐ Perfil do vinho (o que esperar na taça)**")
                    st.write(_ensure_sentence(f"Na taça, {_prefix_wine(nome_vinho, wine_type)} é descrito assim: {best}"))

        st.divider()

    st.markdown("</div>", unsafe_allow_html=True)


def render_client(menu: pd.DataFrame, wines: pd.DataFrame, pairings: pd.DataFrame):
    st.markdown("## Escolha seus pratos")
    st.markdown(
        "<div class='yvora-subtitle'>Selecione 1 ou 2 pratos. As sugestões são filtradas pelo estoque atualizado no momento da consulta.</div>",
        unsafe_allow_html=True,
    )
    st.write("")

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

    wines_dict = wines.to_dict(orient="records")
    available_ids = {w["id_vinho"] for w in wines_dict if is_wine_available_now(w)}
    wines_type_map = {norm_text(w["id_vinho"]): norm_text(w.get("tipo_vinho", "")) for w in wines_dict}

    if len(selected_ids) == 2:
        key_pair = make_key_for_pratos(selected_ids)
        p_pair = pairings[pairings["chave_pratos"].astype(str).str.strip() == key_pair].copy()
        p_pair = p_pair[p_pair["id_vinho"].isin(available_ids)].copy()

        if p_pair.empty:
            st.markdown(
                "<div class='yvora-warn'><b>Sem recomendação para o conjunto agora.</b><br>Esta combinação ainda não foi gerada ou os vinhos sugeridos estão sem estoque.</div>",
                unsafe_allow_html=True,
            )
        else:
            render_recos_block("Para os 2 pratos (equilíbrio do conjunto)", p_pair, wines_type_map)

        st.write("")

    st.markdown("### Melhor por prato")
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

        render_recos_block(prato_nome, p_one, wines_type_map)


def render_dm(menu: pd.DataFrame, wines: pd.DataFrame, pairings: pd.DataFrame):
    st.markdown("## DM")
    st.markdown(
        "<div class='yvora-subtitle'>Diagnóstico rápido de dados e cobertura de recomendações.</div>",
        unsafe_allow_html=True,
    )

    st.write(f"Menu hash: `{sheet_hash(menu)}`")
    st.write(f"Vinhos hash: `{sheet_hash(wines)}`")
    st.write(f"Pairings hash: `{sheet_hash(pairings)}`")

    wines_dict = wines.to_dict(orient="records")
    available_ids = {w["id_vinho"] for w in wines_dict if is_wine_available_now(w)}
    st.write(f"Vinhos disponíveis agora: **{len(available_ids)}**")
    st.write(f"Linhas de pairings ativas: **{len(pairings)}**")

    st.markdown("### Padrão necessário para as escalas")
    st.caption("Em a_melhor_para: acidez: X/5 | corpo: X/5 | tanino: X/5 | final: curto/médio/longo | aromas: ...")


def main():
    set_page_style()
    sidebar_brand()
    dm = dm_login_block()
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
        st.stop()

    if dm:
        render_dm(menu, wines, pairings)
    else:
        render_client(menu, wines, pairings)


if __name__ == "__main__":
    main()
