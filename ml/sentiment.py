"""Review sentiment classification.

The obvious move here is an off-the-shelf lexicon like VADER. That would be
wrong: Olist's review comments are in Portuguese, and VADER's lexicon is
English, so it would score most of this corpus as neutral and the result would
look plausible while being meaningless.

Instead this trains a supervised classifier on the corpus itself, using the star
rating as a weak label (1-2 stars negative, 4-5 positive, 3 dropped as
ambiguous). TF-IDF over word and character n-grams handles Portuguese
morphology without needing a language-specific tokenizer, and logistic
regression keeps the model inspectable - the learned coefficients give the
actual driver terms, which is the part a business stakeholder cares about.

Reported metrics come from a stratified holdout, never from the training split.
"""

from __future__ import annotations

import argparse
import logging
import re
import sys
import unicodedata

import numpy as np
import pandas as pd
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import (
    accuracy_score,
    classification_report,
    f1_score,
    precision_score,
    recall_score,
    roc_auc_score,
)
from sklearn.model_selection import train_test_split
from sklearn.pipeline import FeatureUnion, Pipeline

from ml.common import configure_logging, read_sql, write_table

log = logging.getLogger(__name__)

MIN_TRAINING_ROWS = 500
SUSPICIOUS_AUC = 0.995

REVIEWS_QUERY = """
    select
        r.order_id,
        r.review_score,
        r.review_comment_message,
        r.review_creation_date,
        o.customer_state,
        o.is_late_delivery,
        o.delivery_days,
        o.order_total
    from staging.stg_order_reviews r
    inner join marts.fact_orders o on r.order_id = o.order_id
    where r.review_comment_message is not null
"""


def normalise(text: str) -> str:
    """Lowercase, strip accents and collapse noise.

    Accent stripping matters here: Portuguese reviewers write both "nao" and
    "não", and without folding they become two unrelated features.
    """
    text = unicodedata.normalize("NFKD", str(text))
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    text = text.lower()
    text = re.sub(r"http\S+|www\.\S+", " ", text)
    text = re.sub(r"\d+", " ", text)
    text = re.sub(r"[^a-z\s]", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def build_pipeline(seed: int) -> Pipeline:
    return Pipeline([
        ("features", FeatureUnion([
            ("word", TfidfVectorizer(
                analyzer="word", ngram_range=(1, 2), min_df=3,
                max_features=40_000, sublinear_tf=True)),
            # Character n-grams recover inflected forms ("demorou"/"demorado")
            # that word n-grams treat as unrelated.
            ("char", TfidfVectorizer(
                analyzer="char_wb", ngram_range=(3, 5), min_df=3,
                max_features=40_000, sublinear_tf=True)),
        ])),
        ("classifier", LogisticRegression(
            max_iter=2_000, C=4.0, class_weight="balanced",
            solver="liblinear", random_state=seed)),
    ])


def _top_terms(pipeline: Pipeline, n: int = 25) -> pd.DataFrame:
    vectoriser = pipeline.named_steps["features"].transformer_list[0][1]
    coefficients = pipeline.named_steps["classifier"].coef_[0]
    names = np.asarray(vectoriser.get_feature_names_out())
    word_coefficients = coefficients[: len(names)]

    order = np.argsort(word_coefficients)
    rows = [
        {"term": names[i], "coefficient": round(float(word_coefficients[i]), 4),
         "direction": "negative"}
        for i in order[:n]
    ] + [
        {"term": names[i], "coefficient": round(float(word_coefficients[i]), 4),
         "direction": "positive"}
        for i in order[-n:][::-1]
    ]
    return pd.DataFrame(rows)


def run(seed: int = 42, test_size: float = 0.2,
        run_id: str | None = None) -> dict[str, object]:
    frame = read_sql(REVIEWS_QUERY)
    if frame.empty:
        raise RuntimeError("No review comments found - run dbt build first.")

    frame["clean_text"] = frame["review_comment_message"].map(normalise)
    frame = frame[frame["clean_text"].str.len() >= 3].reset_index(drop=True)
    log.info("%d reviews with usable comment text.", len(frame))

    # 3-star reviews are genuinely ambiguous; training on them teaches the model
    # to hedge and blurs the decision boundary.
    labelled = frame[frame["review_score"] != 3].copy()
    labelled["label"] = (labelled["review_score"] >= 4).astype(int)

    if len(labelled) < MIN_TRAINING_ROWS:
        raise RuntimeError(
            f"Only {len(labelled)} labelled reviews; need at least "
            f"{MIN_TRAINING_ROWS} to train a meaningful classifier."
        )

    positive_rate = labelled["label"].mean()
    log.info("Training on %d reviews (%.1f%% positive).", len(labelled), positive_rate * 100)

    x_train, x_test, y_train, y_test = train_test_split(
        labelled["clean_text"], labelled["label"],
        test_size=test_size, random_state=seed, stratify=labelled["label"],
    )

    pipeline = build_pipeline(seed)
    pipeline.fit(x_train, y_train)

    predictions = pipeline.predict(x_test)
    probabilities = pipeline.predict_proba(x_test)[:, 1]

    metrics = {
        "accuracy": accuracy_score(y_test, predictions),
        "precision": precision_score(y_test, predictions),
        "recall": recall_score(y_test, predictions),
        "f1": f1_score(y_test, predictions),
        "roc_auc": roc_auc_score(y_test, probabilities),
    }
    log.info("Holdout: accuracy=%.3f  f1=%.3f  roc_auc=%.3f",
             metrics["accuracy"], metrics["f1"], metrics["roc_auc"])
    if metrics["roc_auc"] >= SUSPICIOUS_AUC:
        # Real free-text sentiment tops out around 0.90-0.95 AUC. Anything
        # higher almost always means leakage or templated text, not a good
        # model - worth flagging loudly rather than reporting as a win.
        log.warning(
            "ROC-AUC of %.4f is implausibly high for free-text sentiment. Check "
            "for leakage, or confirm the corpus is real data rather than "
            "generated text (see ingestion/synthetic.py).", metrics["roc_auc"],
        )
    log.info("\n%s", classification_report(y_test, predictions,
                                           target_names=["negative", "positive"]))

    # Score the whole corpus, including the 3-star reviews held out of training.
    frame["sentiment_probability"] = pipeline.predict_proba(frame["clean_text"])[:, 1].round(4)
    frame["predicted_sentiment"] = np.where(
        frame["sentiment_probability"] >= 0.6, "positive",
        np.where(frame["sentiment_probability"] <= 0.4, "negative", "neutral"),
    )
    frame["rating_sentiment"] = np.where(
        frame["review_score"] >= 4, "positive",
        np.where(frame["review_score"] <= 2, "negative", "neutral"),
    )
    frame["agrees_with_rating"] = frame["predicted_sentiment"] == frame["rating_sentiment"]

    output = frame[[
        "order_id", "review_score", "review_creation_date", "customer_state",
        "is_late_delivery", "delivery_days", "order_total",
        "sentiment_probability", "predicted_sentiment", "rating_sentiment",
        "agrees_with_rating",
    ]]

    metrics_frame = pd.DataFrame([{
        "model": "tfidf_logreg",
        "training_rows": int(len(x_train)),
        "holdout_rows": int(len(x_test)),
        "positive_rate": round(float(positive_rate), 4),
        **{k: round(float(v), 4) for k, v in metrics.items()},
    }])

    write_table(output, "review_sentiment", run_id=run_id)
    write_table(metrics_frame, "sentiment_model_metrics", run_id=run_id)
    write_table(_top_terms(pipeline), "sentiment_top_terms", run_id=run_id)

    return {"reviews_scored": int(len(frame)), **{k: round(float(v), 4)
                                                  for k, v in metrics.items()}}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--test-size", type=float, default=0.2)
    parser.add_argument("--run-id", default=None)
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args(argv)

    configure_logging(args.verbose)
    summary = run(seed=args.seed, test_size=args.test_size, run_id=args.run_id)
    log.info("Sentiment complete: %s", summary)
    return 0


if __name__ == "__main__":
    sys.exit(main())
