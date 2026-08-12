"""Generate a schema-compatible stand-in for the Olist dataset.

Purpose is CI and first-run smoke tests: the real dataset needs Kaggle
credentials, but every downstream layer (dbt models, tests, RFM, Prophet,
sentiment) must still be runnable on a clean checkout. The generator reproduces
the properties the pipeline actually depends on — a 25-month order history with
growth and weekly seasonality, a small repeat-purchase population, delivery
delays correlated with lower review scores, and Portuguese review text.

It is NOT a substitute for the real data in the write-up. Numbers reported in
the README come from the Kaggle dataset.
"""

from __future__ import annotations

import argparse
import logging
import sys
from datetime import datetime, timedelta
from pathlib import Path

import numpy as np
import pandas as pd

from ingestion import provenance
from ingestion.config import get_settings

log = logging.getLogger(__name__)

HISTORY_START = datetime(2016, 9, 4)
HISTORY_END = datetime(2018, 10, 17)

# Share of orders that are a repeat purchase by an existing customer. Matches
# the source, where ~96.1k unique customers placed ~99.4k orders.
REPEAT_ORDER_RATE = 0.032

# (state, latitude, longitude, share of customers) - shares approximate Olist.
STATES: tuple[tuple[str, float, float, float], ...] = (
    ("SP", -23.55, -46.63, 0.420), ("RJ", -22.91, -43.17, 0.129),
    ("MG", -19.92, -43.94, 0.117), ("RS", -30.03, -51.23, 0.055),
    ("PR", -25.43, -49.27, 0.050), ("SC", -27.59, -48.55, 0.036),
    ("BA", -12.97, -38.50, 0.034), ("DF", -15.78, -47.93, 0.021),
    ("ES", -20.32, -40.34, 0.020), ("GO", -16.68, -49.25, 0.020),
    ("PE", -8.05, -34.88, 0.016), ("CE", -3.73, -38.53, 0.013),
    ("PA", -1.46, -48.50, 0.010), ("MT", -15.60, -56.10, 0.009),
    ("MA", -2.53, -44.30, 0.007), ("MS", -20.44, -54.65, 0.007),
    ("PB", -7.12, -34.86, 0.005), ("PI", -5.09, -42.80, 0.005),
    ("RN", -5.79, -35.21, 0.005), ("AL", -9.65, -35.71, 0.004),
    ("SE", -10.91, -37.07, 0.003), ("TO", -10.18, -48.33, 0.003),
    ("RO", -8.76, -63.90, 0.0025), ("AM", -3.12, -60.02, 0.0015),
    ("AC", -9.97, -67.81, 0.0008), ("AP", 0.03, -51.07, 0.0007),
    ("RR", 2.82, -60.67, 0.0005),
)

CITY_BY_STATE = {
    "SP": "sao paulo", "RJ": "rio de janeiro", "MG": "belo horizonte",
    "RS": "porto alegre", "PR": "curitiba", "SC": "florianopolis",
    "BA": "salvador", "DF": "brasilia", "ES": "vitoria", "GO": "goiania",
    "PE": "recife", "CE": "fortaleza", "PA": "belem", "MT": "cuiaba",
    "MA": "sao luis", "MS": "campo grande", "PB": "joao pessoa",
    "PI": "teresina", "RN": "natal", "AL": "maceio", "SE": "aracaju",
    "TO": "palmas", "RO": "porto velho", "AM": "manaus", "AC": "rio branco",
    "AP": "macapa", "RR": "boa vista",
}

# (portuguese name, english name, share of items, mean price BRL)
CATEGORIES: tuple[tuple[str, str, float, float], ...] = (
    ("cama_mesa_banho", "bed_bath_table", 0.098, 93.0),
    ("beleza_saude", "health_beauty", 0.089, 130.0),
    ("esporte_lazer", "sports_leisure", 0.078, 114.0),
    ("moveis_decoracao", "furniture_decor", 0.075, 87.0),
    ("informatica_acessorios", "computers_accessories", 0.070, 116.0),
    ("utilidades_domesticas", "housewares", 0.063, 90.0),
    ("relogios_presentes", "watches_gifts", 0.055, 201.0),
    ("telefonia", "telephony", 0.041, 71.0),
    ("ferramentas_jardim", "garden_tools", 0.038, 111.0),
    ("automotivo", "auto", 0.037, 140.0),
    ("brinquedos", "toys", 0.035, 118.0),
    ("cool_stuff", "cool_stuff", 0.033, 167.0),
    ("perfumaria", "perfumery", 0.030, 118.0),
    ("bebes", "baby", 0.028, 143.0),
    ("eletronicos", "electronics", 0.026, 58.0),
    ("papelaria", "stationery", 0.025, 89.0),
    ("fashion_bolsas_e_acessorios", "fashion_bags_accessories", 0.022, 105.0),
    ("pet_shop", "pet_shop", 0.020, 111.0),
    ("moveis_escritorio", "office_furniture", 0.019, 189.0),
    ("consoles_games", "consoles_games", 0.017, 130.0),
    ("construcao_ferramentas_construcao", "construction_tools_construction", 0.015, 152.0),
    ("livros_interesse_geral", "books_general_interest", 0.014, 66.0),
    ("malas_acessorios", "luggage_accessories", 0.013, 130.0),
    ("eletrodomesticos", "home_appliances", 0.012, 176.0),
    ("alimentos", "food", 0.011, 56.0),
)

PAYMENT_TYPES = ("credit_card", "boleto", "voucher", "debit_card")
PAYMENT_WEIGHTS = (0.738, 0.190, 0.055, 0.017)

ORDER_STATUSES = ("delivered", "shipped", "canceled", "unavailable", "invoiced", "processing")
STATUS_WEIGHTS = (0.970, 0.011, 0.006, 0.006, 0.004, 0.003)

POSITIVE_COMMENTS = (
    "Produto de otima qualidade, chegou antes do prazo. Recomendo!",
    "Entrega rapida e produto conforme o anunciado. Muito satisfeito.",
    "Excelente vendedor, embalagem caprichada e tudo certo.",
    "Amei o produto, superou minhas expectativas. Comprarei novamente.",
    "Chegou tudo perfeito e no prazo combinado. Nota dez.",
    "Muito bom, atendeu perfeitamente o que eu precisava.",
    "Produto original e bem embalado. Vendedor confiavel.",
    "Recebi antes da data prevista, produto impecavel.",
)
NEUTRAL_COMMENTS = (
    "Produto razoavel pelo preco, mas a entrega demorou um pouco.",
    "Chegou certo, porem a embalagem veio um pouco amassada.",
    "Atende ao proposto, nada excepcional.",
    "O produto e bom mas esperava um acabamento melhor.",
    "Entrega dentro do prazo, produto mediano.",
    "Serviu, mas o material poderia ser de melhor qualidade.",
)
NEGATIVE_COMMENTS = (
    "Produto nao chegou ate hoje, muito decepcionado com a loja.",
    "Veio errado e com defeito. Pessimo atendimento, quero meu dinheiro de volta.",
    "Entrega muito atrasada, nao recomendo este vendedor.",
    "Qualidade horrivel, nao corresponde ao anunciado. Nunca mais compro.",
    "Recebi apenas um item do pedido, e ninguem responde as mensagens.",
    "Pessima experiencia, produto quebrado e sem suporte nenhum.",
    "Demorou mais de um mes para chegar. Inaceitavel.",
)

REVIEW_TITLES = ("", "", "", "Recomendo", "Otimo", "Nao recomendo", "Produto bom", "Decepcionado")


def _hex_ids(rng: np.random.Generator, n: int) -> list[str]:
    """32-char hex ids matching the source's format, drawn 16 bytes at a time."""
    raw = rng.integers(0, 256, size=(n, 16), dtype=np.uint8)
    return [row.tobytes().hex() for row in raw]


COMMENT_POOLS = {
    5: POSITIVE_COMMENTS, 4: POSITIVE_COMMENTS, 3: NEUTRAL_COMMENTS,
    2: NEGATIVE_COMMENTS, 1: NEGATIVE_COMMENTS,
}
FILLERS = ("obrigado", "no geral", "enfim", "so isso", "vale a pena conferir",
           "chegou hoje", "recomendo pensar bem", "atendimento ok")
MISMATCH_RATE = 0.14


def _review_comment(rng: np.random.Generator, score: int) -> str:
    """Draw a comment for a star rating, with realistic label noise.

    Sampling verbatim from a score-keyed pool makes the sentiment task
    perfectly separable, which produces a meaningless 1.000 ROC-AUC. Real
    reviewers write text that sometimes contradicts their own star rating and
    never repeats word for word, so both effects are reproduced here: a share
    of comments are drawn from an adjacent sentiment pool, and every comment is
    perturbed by dropping words and appending filler.
    """
    pool = COMMENT_POOLS[score]
    if rng.random() < MISMATCH_RATE:
        if score == 3:
            pool = POSITIVE_COMMENTS if rng.random() < 0.5 else NEGATIVE_COMMENTS
        else:
            pool = NEUTRAL_COMMENTS

    words = str(rng.choice(pool)).split()
    keep = rng.random(len(words)) > 0.22
    if not keep.any():
        keep[rng.integers(0, len(words))] = True
    kept = [w for w, k in zip(words, keep, strict=False) if k]

    if rng.random() < 0.35:
        kept.append(str(rng.choice(FILLERS)))
    return " ".join(kept)


def _sample_states(rng: np.random.Generator, n: int) -> np.ndarray:
    codes = np.array([s[0] for s in STATES])
    weights = np.array([s[3] for s in STATES], dtype=float)
    return rng.choice(codes, size=n, p=weights / weights.sum())


def _zip_for_state(rng: np.random.Generator, states: np.ndarray) -> np.ndarray:
    # Brazilian CEP prefixes are geographically ordered; give each state its own
    # non-overlapping band so geo joins behave like the real thing.
    base = {code: 1000 + idx * 3000 for idx, (code, *_) in enumerate(STATES)}
    offsets = rng.integers(0, 2900, size=len(states))
    return np.array([f"{base[s] + int(o):05d}" for s, o in zip(states, offsets, strict=False)])


def _order_timestamps(rng: np.random.Generator, n_orders: int) -> np.ndarray:
    """Purchase timestamps with linear growth plus weekly seasonality."""
    total_days = (HISTORY_END - HISTORY_START).days
    days = np.arange(total_days)

    growth = np.linspace(0.25, 1.0, total_days) ** 1.4
    weekday = np.array([(HISTORY_START + timedelta(days=int(d))).weekday() for d in days])
    weekly = np.where(weekday >= 5, 0.62, 1.0)  # weekends are quiet
    weekly = weekly * np.where(weekday == 0, 1.22, 1.0)  # Monday spike

    month = np.array([(HISTORY_START + timedelta(days=int(d))).month for d in days])
    seasonal = np.where(month == 11, 1.55, 1.0) * np.where(month == 1, 0.88, 1.0)

    intensity = growth * weekly * seasonal
    probs = intensity / intensity.sum()

    chosen_days = rng.choice(days, size=n_orders, p=probs)
    seconds = rng.integers(0, 86_400, size=n_orders)
    start = np.datetime64(HISTORY_START)
    return start + chosen_days.astype("timedelta64[D]") + seconds.astype("timedelta64[s]")


def generate(n_orders: int = 20_000, seed: int = 42) -> dict[str, pd.DataFrame]:
    rng = np.random.default_rng(seed)
    log.info("Generating synthetic Olist-shaped dataset: %d orders (seed=%d)", n_orders, seed)

    # ------------------------------------------------------------- people --
    # Olist's repeat rate is ~3%: almost every customer buys exactly once. That
    # is the single most important property to reproduce, because the cohort and
    # RFM analysis draws its main conclusion from it. Sampling customer ids
    # uniformly would produce ~38% repeats by the birthday problem alone, so the
    # repeat population is constructed explicitly instead.
    n_unique_customers = int(round(n_orders / (1 + REPEAT_ORDER_RATE)))
    unique_customer_ids = _hex_ids(rng, n_unique_customers)
    unique_states = _sample_states(rng, n_unique_customers)
    unique_zips = _zip_for_state(rng, unique_states)

    extra_orders = n_orders - n_unique_customers
    picks = np.concatenate([
        np.arange(n_unique_customers),                                  # one each
        rng.choice(n_unique_customers, size=extra_orders, replace=True),  # the repeats
    ])
    rng.shuffle(picks)

    # Each order gets its own customer_id row keyed to a customer_unique_id -
    # this quirk of the source is what makes repeat-purchase analysis non-trivial.
    customers = pd.DataFrame({
        "customer_id": _hex_ids(rng, n_orders),
        "customer_unique_id": [unique_customer_ids[i] for i in picks],
        "customer_zip_code_prefix": [unique_zips[i] for i in picks],
        "customer_state": [unique_states[i] for i in picks],
    })
    customers["customer_city"] = customers["customer_state"].map(CITY_BY_STATE)
    customers = customers[[
        "customer_id", "customer_unique_id", "customer_zip_code_prefix",
        "customer_city", "customer_state",
    ]]

    n_sellers = max(50, int(n_orders * 0.031))
    seller_states = _sample_states(rng, n_sellers)
    sellers = pd.DataFrame({
        "seller_id": _hex_ids(rng, n_sellers),
        "seller_zip_code_prefix": _zip_for_state(rng, seller_states),
        "seller_city": [CITY_BY_STATE[s] for s in seller_states],
        "seller_state": seller_states,
    })

    # ----------------------------------------------------------- products --
    n_products = max(200, int(n_orders * 0.33))
    cat_names = np.array([c[0] for c in CATEGORIES])
    cat_weights = np.array([c[2] for c in CATEGORIES], dtype=float)
    cat_weights = cat_weights / cat_weights.sum()
    product_categories = rng.choice(cat_names, size=n_products, p=cat_weights)

    products = pd.DataFrame({
        "product_id": _hex_ids(rng, n_products),
        "product_category_name": product_categories,
        "product_name_lenght": rng.integers(20, 70, size=n_products),
        "product_description_lenght": rng.integers(100, 3000, size=n_products),
        "product_photos_qty": rng.integers(1, 8, size=n_products),
        "product_weight_g": rng.integers(50, 30_000, size=n_products),
        "product_length_cm": rng.integers(7, 105, size=n_products),
        "product_height_cm": rng.integers(2, 105, size=n_products),
        "product_width_cm": rng.integers(6, 105, size=n_products),
    })
    # Mirror the ~1.9% of source products with a missing category.
    missing_cat = rng.random(n_products) < 0.019
    products.loc[missing_cat, "product_category_name"] = None
    products.loc[missing_cat, ["product_weight_g", "product_length_cm"]] = np.nan

    price_by_category = {c[0]: c[3] for c in CATEGORIES}
    product_price = np.array([
        max(3.0, rng.lognormal(np.log(price_by_category.get(c, 100.0)), 0.55))
        if c is not None else rng.lognormal(np.log(90.0), 0.55)
        for c in products["product_category_name"]
    ]).round(2)

    translation = pd.DataFrame(
        [(c[0], c[1]) for c in CATEGORIES],
        columns=["product_category_name", "product_category_name_english"],
    )

    # ------------------------------------------------------------- orders --
    order_ids = _hex_ids(rng, n_orders)
    purchase_ts = _order_timestamps(rng, n_orders)
    statuses = rng.choice(list(ORDER_STATUSES), size=n_orders, p=list(STATUS_WEIGHTS))

    approved = purchase_ts + (rng.exponential(6.0, n_orders) * 3600).astype("timedelta64[s]")
    carrier = approved + (rng.gamma(2.0, 1.1, n_orders) * 86_400).astype("timedelta64[s]")
    transit_days = rng.gamma(2.6, 3.1, n_orders) + 1.0
    delivered = carrier + (transit_days * 86_400).astype("timedelta64[s]")
    # Estimates are padded generously by the marketplace, which is why most
    # orders land early and lateness is the interesting signal.
    estimated = purchase_ts + (rng.normal(24.0, 5.0, n_orders).clip(6, 60) * 86_400
                               ).astype("timedelta64[s]")

    orders = pd.DataFrame({
        "order_id": order_ids,
        "customer_id": customers["customer_id"].to_numpy(),
        "order_status": statuses,
        "order_purchase_timestamp": purchase_ts,
        "order_approved_at": approved,
        "order_delivered_carrier_date": carrier,
        "order_delivered_customer_date": delivered,
        "order_estimated_delivery_date": estimated,
    })

    not_delivered = orders["order_status"] != "delivered"
    orders.loc[not_delivered, "order_delivered_customer_date"] = pd.NaT
    orders.loc[orders["order_status"].isin(["canceled", "unavailable"]),
               ["order_delivered_carrier_date", "order_approved_at"]] = pd.NaT
    # A small share of approvals genuinely never recorded, as in the source.
    orders.loc[rng.random(n_orders) < 0.0016, "order_approved_at"] = pd.NaT

    # -------------------------------------------------------- order items --
    items_per_order = rng.choice([1, 2, 3, 4, 5], size=n_orders,
                                 p=[0.885, 0.075, 0.025, 0.010, 0.005])
    item_rows = []
    product_idx_pool = np.arange(n_products)
    for pos, (oid, n_items) in enumerate(zip(order_ids, items_per_order, strict=False)):
        chosen = rng.choice(product_idx_pool, size=int(n_items), replace=True)
        ship_limit = purchase_ts[pos] + np.timedelta64(int(rng.integers(2, 9)), "D")
        for item_no, p_idx in enumerate(chosen, start=1):
            price = float(product_price[p_idx])
            freight = round(max(0.0, rng.normal(0.19 * price + 8.0, 4.0)), 2)
            item_rows.append((
                oid, item_no, products.at[p_idx, "product_id"],
                sellers.at[int(rng.integers(0, n_sellers)), "seller_id"],
                ship_limit, price, freight,
            ))
    order_items = pd.DataFrame(item_rows, columns=[
        "order_id", "order_item_id", "product_id", "seller_id",
        "shipping_limit_date", "price", "freight_value",
    ])

    # ----------------------------------------------------------- payments --
    order_totals = order_items.groupby("order_id", sort=False)[["price", "freight_value"]].sum()
    order_totals = order_totals.reindex(order_ids).fillna(0.0)
    totals = (order_totals["price"] + order_totals["freight_value"]).to_numpy()

    pay_types = rng.choice(list(PAYMENT_TYPES), size=n_orders, p=list(PAYMENT_WEIGHTS))
    installments = np.where(
        pay_types == "credit_card",
        rng.choice([1, 2, 3, 4, 5, 6, 8, 10, 12], size=n_orders,
                   p=[0.26, 0.13, 0.13, 0.09, 0.09, 0.09, 0.07, 0.08, 0.06]),
        1,
    )
    payments = pd.DataFrame({
        "order_id": order_ids,
        "payment_sequential": 1,
        "payment_type": pay_types,
        "payment_installments": installments,
        "payment_value": np.round(totals, 2),
    })
    # ~3% of orders are split across a second payment method (usually a voucher).
    split = rng.random(n_orders) < 0.03
    if split.any():
        split_rows = payments.loc[split].copy()
        voucher_part = np.round(split_rows["payment_value"] * 0.35, 2)
        payments.loc[split, "payment_value"] = np.round(
            payments.loc[split, "payment_value"] - voucher_part, 2)
        split_rows["payment_sequential"] = 2
        split_rows["payment_type"] = "voucher"
        split_rows["payment_installments"] = 1
        split_rows["payment_value"] = voucher_part
        payments = pd.concat([payments, split_rows], ignore_index=True)
    payments.loc[payments["payment_value"] <= 0, "payment_value"] = 0.01

    # ------------------------------------------------------------ reviews --
    delivered_mask = orders["order_delivered_customer_date"].notna()
    days_late = (
        (orders["order_delivered_customer_date"] - orders["order_estimated_delivery_date"])
        .dt.total_seconds() / 86_400
    )
    is_late = (days_late > 0).fillna(False)

    # Lateness is the dominant driver of a bad score - this is the correlation
    # the analytics layer is meant to surface.
    scores = np.where(
        is_late,
        rng.choice([1, 2, 3, 4, 5], size=n_orders, p=[0.44, 0.17, 0.16, 0.12, 0.11]),
        rng.choice([1, 2, 3, 4, 5], size=n_orders, p=[0.06, 0.03, 0.07, 0.20, 0.64]),
    )
    scores = np.where(orders["order_status"].isin(["canceled", "unavailable"]),
                      rng.choice([1, 2], size=n_orders, p=[0.8, 0.2]), scores)

    has_review = rng.random(n_orders) < 0.987
    review_creation = orders["order_delivered_customer_date"].where(
        delivered_mask, orders["order_purchase_timestamp"] + pd.Timedelta(days=25))
    review_creation = review_creation + pd.to_timedelta(rng.integers(0, 3, n_orders), unit="D")

    has_comment = rng.random(n_orders) < 0.41
    messages = [
        _review_comment(rng, int(score)) if wants_comment else None
        for score, wants_comment in zip(scores, has_comment, strict=False)
    ]
    titles = [rng.choice(REVIEW_TITLES) if c else None for c in has_comment]
    titles = [t if t else None for t in titles]

    reviews = pd.DataFrame({
        "review_id": _hex_ids(rng, n_orders),
        "order_id": order_ids,
        "review_score": scores,
        "review_comment_title": titles,
        "review_comment_message": messages,
        "review_creation_date": review_creation,
        "review_answer_timestamp": review_creation + pd.to_timedelta(
            rng.exponential(2.0, n_orders), unit="D"),
    })[has_review]

    # Reproduce the source's duplicated review_id defect so stg_order_reviews'
    # de-duplication logic is actually exercised by the tests.
    n_dupes = max(1, int(len(reviews) * 0.008))
    dupes = reviews.sample(n=n_dupes, random_state=seed).copy()
    dupes["review_score"] = dupes["review_score"].clip(upper=4)
    reviews = pd.concat([reviews, dupes], ignore_index=True)

    # -------------------------------------------------------- geolocation --
    geo_frames = []
    for state, lat, lng, share in STATES:
        n_points = max(40, int(share * n_orders * 1.2))
        state_zips = _zip_for_state(rng, np.array([state] * n_points))
        geo_frames.append(pd.DataFrame({
            "geolocation_zip_code_prefix": state_zips,
            "geolocation_lat": np.round(lat + rng.normal(0, 0.55, n_points), 6),
            "geolocation_lng": np.round(lng + rng.normal(0, 0.55, n_points), 6),
            "geolocation_city": CITY_BY_STATE[state],
            "geolocation_state": state,
        }))
    geolocation = pd.concat(geo_frames, ignore_index=True)

    return {
        "olist_customers_dataset.csv": customers,
        "olist_geolocation_dataset.csv": geolocation,
        "olist_order_items_dataset.csv": order_items,
        "olist_order_payments_dataset.csv": payments,
        "olist_order_reviews_dataset.csv": reviews,
        "olist_orders_dataset.csv": orders,
        "olist_products_dataset.csv": products,
        "olist_sellers_dataset.csv": sellers,
        "product_category_name_translation.csv": translation,
    }


def write_csvs(frames: dict[str, pd.DataFrame], destination: Path,
               seed: int | None = None) -> Path:
    destination.mkdir(parents=True, exist_ok=True)
    for filename, frame in frames.items():
        target = destination / filename
        frame.to_csv(target, index=False)
        log.info("Wrote %-45s %8d rows", filename, len(frame))

    provenance.write(
        destination,
        source="synthetic",
        dataset="generated by ingestion.synthetic",
        seed=seed,
        orders=int(len(frames["olist_orders_dataset.csv"])),
        history_start=HISTORY_START.date().isoformat(),
        history_end=HISTORY_END.date().isoformat(),
    )
    return destination


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--orders", type=int, default=20_000, help="Number of orders to generate.")
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--out", type=Path, default=None,
                        help="Output directory (default data/raw).")
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)-8s %(message)s")
    destination = args.out or get_settings().raw_dir
    write_csvs(generate(n_orders=args.orders, seed=args.seed), destination, seed=args.seed)
    return 0


if __name__ == "__main__":
    sys.exit(main())
