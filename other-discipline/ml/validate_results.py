"""Проверить готовность блокнотов, метрик и Markdown-отчёта к передаче."""
from pathlib import Path
import ast
import hashlib
import json
import re
import subprocess

import nbformat
import numpy as np
import pandas as pd
from PIL import Image
from sklearn.datasets import make_moons
from sklearn.metrics import accuracy_score, f1_score, confusion_matrix
from sklearn.model_selection import train_test_split
from sklearn.neighbors import KNeighborsClassifier
from sklearn.tree import DecisionTreeClassifier

ROOT = Path(__file__).resolve().parent
RESULTS = ROOT / 'results'

def read(name):
    return pd.read_csv(RESULTS / f'{name}.csv', keep_default_na=False)

def main():
    checks = []
    notebook_counts = {}
    notebooks = {}
    for path in sorted(ROOT.glob('*.ipynb')):
        nb = nbformat.read(path, as_version=4)
        nbformat.validate(nb)
        cells = [c for c in nb.cells if c.cell_type == 'code']
        assert [c.execution_count for c in cells] == list(range(1, len(cells) + 1)), path.name
        for cell in cells:
            compile(cell.source, path.name, 'exec')
            assert not re.search('введите формулу|ваш код|рассчитайте функцию потерь', cell.source, re.I)
            assert not any(out.output_type == 'error' for out in cell.outputs)
            assert not any('ConvergenceWarning' in out.get('text', '') for out in cell.outputs)
        assert any('image/png' in out.get('data', {}) for c in cells for out in c.outputs)
        notebook_counts[path.name] = len(cells)
        notebooks[path.name] = nb
    assert len(notebooks) == 3
    checks.append('Все три блокнота выполнены последовательно, без ошибок и незаполненного кода')

    for name, expected, keys in [
        ('knn_grid', 390, ['k', 'weights', 'metric']),
        ('tree_grid', 2520, ['max_depth', 'criterion', 'splitter', 'min_samples_leaf', 'min_samples_split', 'max_features']),
    ]:
        frame = read(name)
        assert len(frame) == expected and not frame.duplicated(keys).any()
        assert np.isfinite(frame.select_dtypes('number')).all().all()
        for column in [c for c in frame if 'accuracy' in c or 'f1' in c]:
            assert frame[column].between(0, 1).all()
    kg, tg = read('knn_grid'), read('tree_grid')
    assert {1, 3, 5, 15}.issubset(set(kg.k)) and set(kg.weights) == {'uniform', 'distance'}
    assert {'3','5','8','12','20'}.issubset(set(tg.max_depth.astype(str)))
    assert set(tg.criterion) == {'gini','entropy','log_loss'}
    assert set(tg.splitter) == {'best','random'}
    assert set(tg.min_samples_leaf) == {1,3,5,10} and set(tg.min_samples_split) == {2,5,10}
    assert set(tg.max_features.astype(str)) == {'None','sqrt','log2','0.25','0.5'}
    checks.append('Сетки параметров полностью покрывают все значения из DOCX')

    for name, size in [('knn', 1000), ('tree', 400)]:
        summary = json.loads((RESULTS / f'{name}_summary.json').read_text())
        X, y = make_moons(n_samples=size, noise=.2, random_state=42)
        Xt, Xe, yt, ye = train_test_split(X, y, test_size=.3, random_state=42)
        if name == 'knn':
            p = summary['best_params']
            extras = {}
            metric = p['metric_name']
            if metric.startswith('minkowski_p'):
                extras['p'] = float(metric.split('_p')[1]); metric = 'minkowski'
            if metric == 'seuclidean':
                extras['metric_params'] = {'V': Xt.var(axis=0, ddof=1)}
            if metric == 'mahalanobis':
                extras['metric_params'] = {'VI': np.linalg.inv(np.cov(Xt.T))}
            fitted = KNeighborsClassifier(n_neighbors=p['k'], weights=p['weights'], metric=metric,
                                          algorithm='brute', **extras).fit(Xt, yt)
            chosen = kg.sort_values(['cv_accuracy_mean','cv_f1_mean','cv_accuracy_std'],
                                    ascending=[False,False,True], kind='stable').iloc[0]
            assert int(chosen.k) == p['k'] and chosen.weights == p['weights'] and chosen.metric == p['metric_name']
        else:
            p = summary['best_params']
            fitted = DecisionTreeClassifier(**p).fit(Xt, yt)
            chosen = tg.sort_values(['cv_accuracy_mean','cv_f1_mean','cv_accuracy_std'],
                                    ascending=[False,False,True], kind='stable').iloc[0]
            assert str(p['max_depth']) == str(chosen.max_depth)
            for key in ['criterion','splitter','min_samples_leaf','min_samples_split']:
                assert p[key] == chosen[key]
            assert str(p['max_features']) == str(chosen.max_features)
        predicted = fitted.predict(Xe)
        np.testing.assert_allclose(summary['test']['accuracy'], accuracy_score(ye, predicted), atol=1e-12)
        np.testing.assert_allclose(summary['test']['f1'], f1_score(ye, predicted), atol=1e-12)
        np.testing.assert_array_equal(summary['confusion'], confusion_matrix(ye, predicted))
        np.testing.assert_allclose(summary['best_cv']['cv_accuracy_mean'], chosen.cv_accuracy_mean, atol=1e-12)
    checks.append('Итоговые test accuracy, F1 и матрицы ошибок независимо воспроизведены')

    score_cols = ['train_accuracy_mean','train_f1_mean','cv_accuracy_mean','cv_f1_mean']
    for a, b in [('euclidean','minkowski_p2'),('manhattan','minkowski_p1')]:
        np.testing.assert_allclose(kg[kg.metric==a][score_cols], kg[kg.metric==b][score_cols], atol=1e-12)
    np.testing.assert_allclose(tg[tg.criterion=='entropy'][score_cols], tg[tg.criterion=='log_loss'][score_cols], atol=1e-12)
    checks.append('Подтверждены совпадения эквивалентных метрик и критериев')

    DATA = None
    for cell in notebooks['regression_task_1.ipynb'].cells:
        if cell.cell_type != 'code':
            continue
        for node in ast.parse(cell.source).body:
            if isinstance(node, ast.Assign) and isinstance(node.targets[0], ast.Name) and node.targets[0].id == 'DATA':
                DATA = ast.literal_eval(node.value)
    assert set(DATA) == {1,2,3} and all(len(v['x']) == len(v['y']) == 100 for v in DATA.values())
    # При наличии исходного Git-коммита дополнительно сверяем неизменность всех чисел.
    original = subprocess.run(['git','show','f9c8c7e:other-discipline/ml/regression_task_1.ipynb'],
                              cwd=ROOT, capture_output=True, text=True)
    if original.returncode == 0:
        old = json.loads(original.stdout)
        for variant, index in enumerate([3,7,9], 1):
            for node in ast.parse(''.join(old['cells'][index]['source'])).body:
                if isinstance(node, ast.Assign) and isinstance(node.targets[0], ast.Name) and node.targets[0].id in ['x','y']:
                    np.testing.assert_array_equal(DATA[variant][node.targets[0].id], ast.literal_eval(node.value))
        checks.append('Все 300 исходных пар регрессии точно совпадают с исходным коммитом')
    reg = json.loads((RESULTS / 'regression_summary.json').read_text())
    assert reg['lasso_kkt_checks'] == 679 and reg['lasso_kkt_max_violation'] < 1e-5
    losses = read('regression_gradient').loss.to_numpy()
    assert len(losses) == 1000 and np.isfinite(losses).all() and np.all(np.diff(losses) <= 1e-9)
    np.testing.assert_allclose(reg['gradient_theta'], reg['exact_theta'], rtol=5e-5, atol=1e-5)
    assert len(read('regression_all_variants')) == 9
    assert len(read('regression_all_regularization_grid')) == 270
    checks.append('Проверены все варианты регрессии, 1000 итераций градиентного спуска и 679 проверок оптимальности Lasso')

    screenshots = json.loads((RESULTS / 'screenshots.json').read_text())
    for name, expected in screenshots.items():
        cell = [c for c in notebooks[name].cells if c.cell_type == 'code'][-1]
        html = next(o.data['text/html'] for o in cell.outputs if 'text/html' in o.get('data', {}))
        png = next(o.data['image/png'] for o in cell.outputs if 'image/png' in o.get('data', {}))
        assert hashlib.sha256((html + png).encode()).hexdigest() == expected['output_sha256']
        assert (RESULTS / expected['screenshot']).exists()
    checks.append('Скриншоты соответствуют сохранённым outputs блокнотов по SHA-256')

    report_path = ROOT / 'Отчёт_практическая_работа_1.md'
    report = report_path.read_text()
    links = re.findall(r'\]\(([^)]+)\)', report)
    for link in links:
        if not link.startswith(('http://', 'https://', '#')):
            assert (ROOT / link).exists(), link
    pngs = sorted((RESULTS / 'figures').glob('*.png'))
    for path in pngs:
        with Image.open(path) as image:
            image.verify()
    assert len(pngs) >= 20
    checks.append('Изображения PNG читаются, все локальные ссылки отчёта существуют')
    files = [*ROOT.glob('*.ipynb'), *ROOT.glob('*.py'), ROOT/'Задание_1.docx',
             ROOT/'requirements.txt', report_path, *RESULTS.glob('*.csv'), *pngs]
    hashes = {str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(files)}
    (RESULTS / 'validation.json').write_text(json.dumps({
        'status':'passed', 'checks':checks, 'executed_code_cells':notebook_counts,
        'png_count':len(pngs), 'sha256':hashes}, ensure_ascii=False, indent=2))
    print('\n'.join(checks))
    print('PASS:', notebook_counts, 'PNG:', len(pngs))

if __name__ == '__main__':
    main()
