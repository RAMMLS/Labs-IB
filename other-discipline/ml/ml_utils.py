"""Общие функции экспериментов; сами учебные алгоритмы находятся в блокнотах."""
from pathlib import Path
import json
import platform
from importlib.metadata import version

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from sklearn.metrics import accuracy_score, f1_score
from sklearn.model_selection import RepeatedStratifiedKFold, train_test_split

RESULTS = Path("results")
FIGURES = RESULTS / "figures"
FIGURES.mkdir(parents=True, exist_ok=True)
plt.rcParams.update({"figure.figsize": (9, 4.5), "figure.dpi": 110,
                     "savefig.dpi": 160, "axes.grid": True,
                     "grid.alpha": 0.2, "font.size": 10})


def savefig(name):
    plt.tight_layout()
    plt.savefig(FIGURES / f"{name}.png", bbox_inches="tight")
    plt.show()
    plt.close()


def scores(y, pred):
    """Accuracy и F1 положительного класса 1 для бинарной задачи."""
    tp = np.sum((y == 1) & (pred == 1))
    fp = np.sum((y == 0) & (pred == 1))
    fn = np.sum((y == 1) & (pred == 0))
    denominator = 2 * tp + fp + fn
    return {"accuracy": float(np.mean(y == pred)),
            "f1": float(2 * tp / denominator) if denominator else 0.0}


# Независимая проверка оптимизированного вычисления метрик.
for y_check, p_check in [(np.array([0, 1, 1, 0]), np.array([0, 0, 1, 1])),
                         (np.zeros(3), np.zeros(3))]:
    assert scores(y_check, p_check)["accuracy"] == accuracy_score(y_check, p_check)
    assert scores(y_check, p_check)["f1"] == f1_score(y_check, p_check, zero_division=0)


def cv_splits(X, y):
    return list(RepeatedStratifiedKFold(n_splits=5, n_repeats=3,
                                     random_state=2026).split(X, y))


def evaluate_cv(factory, X, y, splits):
    rows = []
    for train, valid in splits:
        model = factory(X[train])
        model.fit(X[train], y[train])
        row = {f"train_{k}": v for k, v in scores(y[train], model.predict(X[train])).items()}
        row.update({f"cv_{k}": v for k, v in scores(y[valid], model.predict(X[valid])).items()})
        rows.append(row)
    frame = pd.DataFrame(rows)
    result = {f"{c}_mean": float(frame[c].mean()) for c in frame}
    result.update({f"{c}_std": float(frame[c].std(ddof=1)) for c in frame})
    return result


def table(frame, name):
    frame.to_csv(RESULTS / f"{name}.csv", index=False)
    return frame


def save_json(data, name):
    (RESULTS / f"{name}.json").write_text(
        json.dumps(data, ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8")


def environment():
    return {"python": platform.python_version(), **{p: version(p) for p in
            ["numpy", "pandas", "scipy", "scikit-learn", "matplotlib", "statsmodels",
             "nbformat", "nbclient", "ipykernel"]}}


def boundaries(models, X, y, name):
    """Границы решений и ошибки на отложенной выборке."""
    xx, yy = np.meshgrid(np.linspace(-1.7, 2.7, 220), np.linspace(-1.2, 1.7, 170))
    mesh = np.column_stack([xx.ravel(), yy.ravel()])
    fig, axes = plt.subplots(1, len(models), figsize=(5 * len(models), 4), squeeze=False)
    for ax, (title, model) in zip(axes.flat, models.items()):
        ax.contourf(xx, yy, model.predict(mesh).reshape(xx.shape),
                    levels=[-0.5, 0.5, 1.5], colors=["#d9e8ff", "#ffe1d4"], alpha=0.9)
        ax.scatter(*X[y == 0].T, c="#2166ac", s=20, label="Класс 0")
        ax.scatter(*X[y == 1].T, c="#d6604d", s=20, marker="^", label="Класс 1")
        wrong = model.predict(X) != y
        ax.scatter(*X[wrong].T, facecolors="none", edgecolors="black", s=85, label="Ошибка")
        ax.set(title=title, xlabel="Признак x₁", ylabel="Признак x₂")
        ax.legend(fontsize=8, loc="upper right")
    savefig(name)


def noise_experiment(factories, X, y, name):
    """20 парных разбиений только train; шум меток в обучающей части."""
    rows = []
    for seed in range(20):
        Xt, Xv, yt, yv = train_test_split(X, y, test_size=0.25,
                                        stratify=y, random_state=1000 + seed)
        order = np.random.default_rng(2000 + seed).permutation(len(yt))
        for label, factory in factories.items():
            clean = factory(Xt, seed).fit(Xt, yt).predict(Xv)
            for fraction in [0.0, 0.05, 0.1, 0.2]:
                noisy = yt.copy()
                selected = order[:round(fraction * len(yt))]
                noisy[selected] = 1 - noisy[selected]
                pred = factory(Xt, seed).fit(Xt, noisy).predict(Xv)
                rows.append({"model": label, "noise": fraction, "seed": seed,
                             **scores(yv, pred), "disagreement": float(np.mean(pred != clean))})
    raw = table(pd.DataFrame(rows), f"{name}_raw")
    summary = raw.groupby(["model", "noise"], sort=False).agg(
        accuracy_mean=("accuracy", "mean"), accuracy_std=("accuracy", "std"),
        f1_mean=("f1", "mean"), f1_std=("f1", "std"),
        disagreement_mean=("disagreement", "mean")).reset_index()
    table(summary, name)
    for label, group in summary.groupby("model", sort=False):
        plt.errorbar(group.noise * 100, group.accuracy_mean,
                     yerr=group.accuracy_std, marker="o", capsize=3, label=label)
    plt.xlabel("Доля изменённых меток в обучении, %")
    plt.ylabel("Accuracy на чистой валидации")
    plt.legend(fontsize=8)
    savefig(name)
    return summary
