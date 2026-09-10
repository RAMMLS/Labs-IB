"""Собрать Markdown-отчёт из фактических результатов выполненных блокнотов."""
from pathlib import Path
import json
import pandas as pd

ROOT = Path(__file__).resolve().parent
RESULTS = ROOT / 'results'

def read(name):
    return pd.read_csv(RESULTS / f'{name}.csv', keep_default_na=False)

def summary(name):
    return json.loads((RESULTS / f'{name}_summary.json').read_text())

def fmt(value):
    return f'{value:.4f}'

def pct(value):
    return f'{100 * value:.2f}%'

LABELS = {
    'model': 'Модель', 'method': 'Метод', 'variant': 'Вариант', 'degree': 'Степень',
    'k': 'k', 'weights': 'Веса', 'metric': 'Метрика', 'max_depth': 'Глубина',
    'criterion': 'Критерий', 'splitter': 'Splitter', 'max_features': 'max_features',
    'train_accuracy_mean': 'Train accuracy', 'cv_accuracy_mean': 'CV accuracy',
    'cv_accuracy_std': 'Std accuracy', 'cv_f1_mean': 'CV F1', 'cv_f1_std': 'Std F1',
    'accuracy': 'Test accuracy', 'f1': 'Test F1', 'accuracy_mean': 'Средняя accuracy',
    'accuracy_std_between_seeds': 'Std между seed', 'f1_mean': 'Средняя F1',
    'train_mse': 'Train MSE', 'cv_mse_mean': 'CV MSE', 'cv_mse_std': 'Std MSE',
    'test_mse': 'Test MSE', 'test_r2': 'Test R²', 'mse_train': 'Train MSE',
    'r2_train': 'Train R²', 'theta': 'Коэффициенты', 'condition_number': 'cond(X)',
    'intercept': 'Свободный член', 'slope': 'Наклон', 'p_slope': 'p-value наклона',
}

def tab(frame, cols=None):
    frame = frame.copy() if cols is None else frame[cols].copy()
    alignment = ['right' if pd.api.types.is_numeric_dtype(frame[c]) else 'left' for c in frame]
    for column in frame:
        if column == 'theta':
            frame[column] = frame[column].map(lambda value: '[' + ', '.join(f'{x:.6f}' for x in json.loads(value)) + ']')
        elif pd.api.types.is_float_dtype(frame[column]):
            frame[column] = frame[column].map(lambda value: f'{value:.4f}')
        else:
            frame[column] = frame[column].astype(str)
    return frame.rename(columns=LABELS).to_markdown(index=False, disable_numparse=True, colalign=alignment)

def noise_table(name):
    frame = read(name)
    frame = frame[frame.noise.isin([0.0, 0.1, 0.2])]
    pivot = frame.pivot(index='model', columns='noise', values='accuracy_mean')
    pivot = pivot.reindex(frame.model.drop_duplicates())
    pivot.columns = ['Без смены меток', '10% смены меток', '20% смены меток']
    return tab(pivot.reset_index())

def main():
    knn, tree, reg = summary('knn'), summary('tree'), summary('regression')
    kp, tp = knn['best_params'], tree['best_params']
    k_curve, depth = read('knn_k'), read('tree_depth')
    metric = read('knn_metrics')
    chosen_metric = metric.sort_values(['cv_accuracy_mean','cv_f1_mean','cv_accuracy_std'],
                                     ascending=[False,False,True], kind='stable').iloc[0]
    poly = read('regression_polynomial')
    poly_winner = poly.sort_values(['cv_mse_mean','degree']).iloc[0]
    all_reg = read('regression_all_variants')
    env = knn['environment']
    assert len(read('knn_grid')) == 390
    assert len(read('tree_grid')) == 2520
    assert len(all_reg) == 9
    text = f'''# Отчёт по практической работе 1

**Тема:** исследование k ближайших соседей, дерева решений и методов регрессии.  
**Дата выполнения:** 10 сентября 2026 года.

## 1 Цель и состав работы

Выполнены оба задания из [Задание_1.docx](Задание_1.docx): подобраны и сопоставлены параметры k-NN и дерева решений, построены графики качества и границ классов, исследована устойчивость к шуму. Дополнительно заполнены задания в третьем блокноте по регрессии, включая матричное решение, полином третьей степени, функции потерь, регуляризацию и градиентный спуск.

Лучший k-NN в проверенной сетке получил **{pct(knn['test']['accuracy'])} accuracy** на 300 тестовых объектах. Лучшее дерево при фиксированном random_state=42 получило **{pct(tree['test']['accuracy'])} accuracy** на 120 объектах. Это результаты разных исходных наборов, поэтому напрямую ранжировать два алгоритма по этим числам нельзя.

| Требование | Где выполнено |
|---|---|
| Выбор k, графики accuracy/F1 | Раздел 3.2; k_neighbor_classification.ipynb |
| Uniform/distance и устойчивость | Раздел 3.3; опыт с шумом меток |
| Сравнение расстояний | Раздел 3.4; 15 спецификаций и объяснение исключений |
| Выбор глубины дерева | Раздел 4.2; decision_tree.ipynb |
| Gini/entropy/log_loss и best/random | Раздел 4.3; сравнение при одинаковой глубине и по 20 seed |
| Leaf/split/max_features и обобщение | Разделы 4.4–4.5; полный перебор и опыт с шумом |
| Таблицы, графики, изображения визуализаций | Встроены ниже; оригиналы PNG в results/figures |
| Доработка регрессии | Раздел 5; regression_task_1.ipynb |

## 2 Данные и методика экспериментов

| Задача | Данные | Обучение | Отложенный тест |
|---|---|---:|---:|
| k-NN | make_moons, 1000 точек, noise=0.2, random_state=42 | 700 | 300 |
| Дерево | make_moons, 400 точек, noise=0.2, random_state=42 | 280 | 120 |
| Регрессия | Три исходных варианта трафика по 100 точек | 50 на вариант | 50 на вариант |

Генерация данных и разбиение классификационных заготовок сохранены: test_size=0.3, random_state=42, без добавления stratify к исходному train/test. Для регрессии сохранены test_size=0.5 и random_state=19. В train/test k-NN классы распределены как 344/356 и 156/144; у дерева — 140/140 и 60/60.

Параметры классификации подбирались **только внутри train**: 5 стратифицированных фолдов, 3 повтора, random_state=2026, всего 15 оценок каждой настройки. Все конфигурации используют одинаковые разбиения. Основной критерий — средняя CV accuracy; при равенстве — большая F1, затем меньший разброс accuracy. При полной ничьей остаётся первый вариант сетки. В регрессии используется 5-fold CV внутри train и минимальная средняя MSE; при равенстве выбирается меньшая степень.

Accuracy — доля правильных ответов; ошибка классификации равна 1−accuracy. F1=2TP/(2TP+FP+FN) рассчитана для положительного класса 1. Обе метрики качества нужно максимизировать. В таблицах приведены доли, не проценты; std — выборочное стандартное отклонение. Фолды повторной CV зависимы, поэтому std нельзя считать доверительным интервалом, а малые различия — доказательством превосходства.

Для проверки шума проведены 20 парных разбиений **только train** (25% на чистую валидацию). В обучающей части случайно менялись метки 0%, 5%, 10% и 20% объектов. Seeds разбиений 1000–1019, перестановок для повреждения меток 2000–2019; модели сравниваются на одинаково повреждённых данных. Тестовая выборка в эти опыты не входит, выбор победителя по ним не меняется.

## 3 Задание 1 Метод k ближайших соседей

### 3.1 Реализация алгоритма

В ручной функции `k_neibours` вычисляются расстояния до всех обучающих объектов, выбираются k ближайших и суммируются голоса по классам. Добавлены произвольное число признаков и меток классов, четыре семейства расстояний и обе схемы весов. При нулевых расстояниях в режиме distance голосуют только совпавшие объекты; при равенстве голосов выбирается меньшая метка класса. Обработаны недопустимые k и размеры входа.

Предсказания ручного алгоритма и sklearn **совпали на 72 сочетаниях** k, weights и metric. Дополнительно проверены совпавшие точки, ничья, третий признак и недопустимые k. Ручной базовый k=5 получил {pct(read('knn_test').iloc[0].accuracy)} accuracy на test.

### 3.2 Как влияет число соседей

Для чистого сравнения меняется только k, остальные параметры — uniform и euclidean.

{tab(k_curve, ['k','train_accuracy_mean','cv_accuracy_mean','cv_accuracy_std','cv_f1_mean'])}

![Качество k-NN в зависимости от числа соседей](results/figures/knn_k.png)

При k=1 обучающая accuracy равна 1, но CV accuracy составляет {fmt(k_curve.loc[k_curve.k==1,'cv_accuracy_mean'].iloc[0])}: ближайшая шумная точка сильно влияет на ответ. При k=3–15 качество растёт; в этом срезе k=15 даёт {fmt(k_curve.loc[k_curve.k==15,'cv_accuracy_mean'].iloc[0])}. Значения 7–51 дают близкие результаты. При k=201 и 501 качество падает до {fmt(k_curve.loc[k_curve.k==201,'cv_accuracy_mean'].iloc[0])} и {fmt(k_curve.loc[k_curve.k==501,'cv_accuracy_mean'].iloc[0])}: модель чрезмерно сглаживает границу и смешивает два полумесяца. Это недообучение при слишком большом k.

### 3.3 Сравнение весов и устойчивость

В таблице зафиксирована euclidean; каждую пару uniform/distance нужно сравнивать при одинаковом k.

{tab(read('knn_weights'), ['k','weights','cv_accuracy_mean','cv_accuracy_std','cv_f1_mean'])}

Uniform даёт каждому соседу одинаковый голос, distance — вес, обратный расстоянию. Определения соответствуют [KNeighborsClassifier](https://scikit-learn.org/stable/modules/generated/sklearn.neighbors.KNeighborsClassifier.html). На исходных данных преимущество distance не универсально: при k=5 оно хуже, при k=15 средняя accuracy совпадает. Train accuracy=1 у distance объясняется нулевым расстоянием объекта до самого себя и не доказывает обобщающую способность.

Средняя accuracy при изменении обучающих меток:

{noise_table('knn_noise')}

![Устойчивость k-NN к шуму меток](results/figures/knn_noise.png)

**Ответ об устойчивости:** при одинаковом k=15 и euclidean устойчивее uniform. При 20% изменённых меток оно сохраняет accuracy 0.9566 против 0.9357 у distance; усреднение уменьшает влияние отдельного неверно размеченного близкого соседа. Выбранная по CV конфигурация с k=51 сохраняет 0.9600: устойчивость определяется сочетанием k, весов и метрики, а не только weights.

### 3.4 Сравнение расстояний

Здесь зафиксированы k=15 и uniform. Дисперсии для seuclidean и обратная ковариационная матрица для Mahalanobis рассчитываются отдельно по обучающей части каждого CV-фолда. Валидационные и тестовые данные не используются для этих оценок.

{tab(metric, ['metric','cv_accuracy_mean','cv_accuracy_std','cv_f1_mean'])}

![Сравнение расстояний k-NN](results/figures/knn_metrics.png)

Euclidean и Manhattan сохраняют геометрию полумесяцев и в данном срезе дают одинаковую accuracy 0.9695. По дополнительному критерию F1 первым идёт **{chosen_metric.metric}**. Minkowski(p=1) совпадает с Manhattan, Minkowski(p=2) — с Euclidean; sqeuclidean сохраняет порядок соседей при uniform, но меняет относительные веса при distance. Поэтому совпадения в таблице ожидаемы.

Cosine и correlation здесь существенно хуже: они отбрасывают информацию о расположении точек; в двух измерениях корреляционное расстояние особенно вырождено. Canberra и Bray–Curtis проверены как дополнительные меры различия, но Bray–Curtis на знаковых координатах нельзя трактовать как обычную геометрическую метрику. Формулы расстояний сверены с [SciPy cdist](https://docs.scipy.org/doc/scipy/reference/generated/scipy.spatial.distance.cdist.html).

Полный поиск включил 13 значений k × 2 варианта weights × 15 спецификаций расстояний = **390 конфигураций**, или 5850 обучений на CV. Лучшее сочетание — **k={kp['k']}, weights={kp['weights']}, metric={kp['metric_name']}**. Стандартизованное евклидово расстояние учитывает неодинаковый разброс двух координат. Его преимущество относится к совместному подбору параметров; при фиксированных k=15 и uniform лидируют другие строки.

**Почему не использованы остальные названия:** бинарные расстояния jaccard/dice/rogerstanimoto/russellrao/sokalmichener/sokalsneath/yule/kulsinski предназначены для бинарных признаков; Hamming/matching на непрерывных координатах почти всегда дают одинаковые расстояния. Haversine предназначена для географических координат, Jensen–Shannon — для распределений вероятностей. L1/cityblock и L2 являются псевдонимами; nan_euclidean без пропусков совпадает с euclidean. Precomputed означает готовую матрицу расстояний, callable — произвольную функцию. Эти варианты не образуют дополнительных содержательных сравнений на исходных данных.

### 3.5 Итог k-NN

{tab(read('knn_test'))}

Для выбранной конфигурации CV accuracy = **{fmt(knn['best_cv']['cv_accuracy_mean'])} ± {fmt(knn['best_cv']['cv_accuracy_std'])}**, CV F1 = **{fmt(knn['best_cv']['cv_f1_mean'])}**. На test: accuracy = **{fmt(knn['test']['accuracy'])}**, F1 = **{fmt(knn['test']['f1'])}**, ошибок **7 из 300**. Матрица ошибок: TN=153, FP=3, FN=4, TP=140.

![Скриншот итоговых метрик и визуализаций выполненного блокнота k-NN](results/figures/knn_notebook_screenshot.png)

На изображении слева видны локальные неровности k=1, в центре — выбранная конфигурация, справа — чрезмерное сглаживание k=501. Чёрными окружностями отмечены ошибки. Скриншот сделан с HTML-представления сохранённого вывода выполненной ячейки, включая таблицу и визуализацию.

## 4 Задание 2 Дерево решений

### 4.1 Реализация алгоритма

Ручное дерево строится рекурсивно. Для каждого признака проверяются пороги между соседними уникальными значениями; выбирается минимальная взвешенная нечистота дочерних узлов. Реализованы Gini, entropy/log_loss, max_depth, min_samples_leaf и min_samples_split. В лист записывается класс большинства. Повторное обучение очищает предыдущее дерево; пустые дочерние ветви не создаются. Допускается промежуточное разбиение с нулевым уменьшением нечистоты, что проверено на XOR.

Проверены постоянные признаки, чистый класс, несколько классов, повторное обучение и ограничения размера/глубины. Корневые пороги сопоставлены со sklearn для трёх критериев. Возможные равнозначные пороги sklearn разрешает с учётом random_state, поэтому полное совпадение произвольных деревьев не требуется. На исходной задаче ручное дерево и базовое sklearn получили одинаковые итоговые метрики.

### 4.2 Как влияет глубина

Фиксированы gini, best, min_samples_leaf=1, min_samples_split=2, max_features=None, random_state=42.

{tab(depth, ['max_depth','train_accuracy_mean','cv_accuracy_mean','cv_accuracy_std','cv_f1_mean'])}

![Качество дерева в зависимости от глубины](results/figures/tree_depth.png)

Глубина 1 даёт CV accuracy 0.7988: дерево слишком простое. При глубине 3 она растёт до 0.8893, при 5 — до 0.9417. С глубины 8 обучающая accuracy равна 1, а CV снижается до 0.9381. Дальнейшее увеличение ограничения ничего не меняет: дерево уже исчерпало полезные разбиения на обучении. Таким образом, для этого среза **max_depth=5** предпочтительнее глубокой неограниченной модели.

### 4.3 Критерии и стратегии разбиения

Сравнение при max_depth=5, leaf=1, split=2, max_features=None, random_state=42:

{tab(read('tree_criteria'), ['criterion','splitter','cv_accuracy_mean','cv_accuracy_std','cv_f1_mean'])}

При splitter=best критерии entropy и log_loss дают CV accuracy 0.9512 против 0.9417 у gini. Их совпадение объясняется тем, что оба используют информационный выигрыш Шеннона. При той же глубине random хуже best для всех трёх критериев. Определения критериев и параметров проверены по [DecisionTreeClassifier](https://scikit-learn.org/stable/modules/generated/sklearn.tree.DecisionTreeClassifier.html).

Для отдельной проверки случайности проведены 20 запусков каждого splitter с seeds 0–19 при глубине 5 и gini. В каждом запуске вычислена средняя по тем же 15 CV-фолдам, затем измерен разброс между seeds:

{tab(read('tree_seeds'))}

**Ответ об устойчивости:** при одинаковой глубине best здесь значительно стабильнее random. Std между seeds равно 0.00053 у best и 0.03396 у random. Фиксация random_state обеспечивает воспроизводимость конкретного дерева, но сама по себе не делает модель устойчивой к другой выборке или шуму.

### 4.4 Минимальные размеры узлов и число признаков

Для leaf/split использованы gini, best, глубина None, max_features=None.

{tab(read('tree_regularizers'), ['min_samples_leaf','min_samples_split','train_accuracy_mean','cv_accuracy_mean','cv_accuracy_std','cv_f1_mean'])}

![Влияние min_samples_leaf и min_samples_split](results/figures/tree_regularizers.png)

Небольшое увеличение min_samples_leaf до 3 улучшает CV accuracy с 0.9381 до 0.9417. Значение 10 снижает её до 0.9250 на исходных данных. Рост min_samples_split сам по себе не гарантирует улучшения: при leaf=1 значение split=10 уменьшает качество до 0.9345. Ограничения взаимодействуют: если leaf=5, разбиению всё равно нужны минимум 10 объектов, поэтому split=2, 5 и 10 здесь эквивалентны.

При сравнении max_features фиксированы depth=5, gini, best, leaf=1, split=2:

{tab(read('tree_features'), ['max_features','cv_accuracy_mean','cv_accuracy_std','cv_f1_mean'])}

**Лучший max_features в этом срезе — None.** У данных всего два признака; sqrt, log2, 0.25 и 0.5 задают один рассматриваемый признак на узел и здесь дают одинаковые результаты. Отбрасывание одного из двух полезных признаков уменьшает CV accuracy до 0.8952 и увеличивает разброс. Это не доказывает вред случайного выбора признаков для ансамблей или многомерных данных.

### 4.5 Обобщение и устойчивость к шуму

Средняя accuracy на чистой валидации при повреждении обучающих меток:

{noise_table('tree_noise')}

![Устойчивость дерева к шуму меток](results/figures/tree_noise.png)

При 20% изменённых меток дерево без ограничений падает до 0.7786; depth=3 сохраняет 0.8800, leaf=10 — 0.8771, depth=5 — 0.8664. Ограничение глубины и минимального размера листа мешает запоминать отдельные ошибочные метки. При отсутствии дополнительного шума depth=3 заметно недообучается (0.8900 против 0.9493 у дерева без ограничений). Поэтому **усиленная регуляризация оправданна при более шумных метках**, а не безусловно для любой задачи.

### 4.6 Итог дерева

Перебраны 7 глубин × 3 критерия × 2 splitter × 4 leaf × 3 split × 5 max_features = **2520 конфигураций**, или **37 800 обучений** на CV.

Максимум в этой сетке при random_state=42 получен с параметрами:

```python
{json.dumps(tp, ensure_ascii=False, indent=4).replace('null', 'None')}
```

CV accuracy = **{fmt(tree['best_cv']['cv_accuracy_mean'])} ± {fmt(tree['best_cv']['cv_accuracy_std'])}**, CV F1 = **{fmt(tree['best_cv']['cv_f1_mean'])}**. На test: accuracy = **{fmt(tree['test']['accuracy'])}**, F1 = **{fmt(tree['test']['f1'])}**, **4 ошибки из 120**. Фактическая глубина обученного дерева — {tree['depth']}, листьев — {tree['leaves']}.

{tab(read('tree_test'))}

![Скриншот итоговых метрик и визуализаций выполненного блокнота дерева](results/figures/tree_notebook_screenshot.png)

![Верхние четыре уровня выбранного дерева](results/figures/tree_structure.png)

Многоточие на схеме означает продолжение дерева ниже четвёртого отображённого уровня. Параметры, обучение и весь объект дерева воспроизводятся кодом блокнота.

**Максимум качества и устойчивость — разные выводы.** Победитель с random достиг лучшей CV accuracy при фиксированном seed, но в опыте с изменением меток и seeds не оказался самым устойчивым. Более простой вариант depth=5, entropy/log_loss, best, leaf=1, split=2, max_features=None даёт близкую CV accuracy 0.9512 (на 0.0024 меньше максимума); это разумный кандидат, если приоритет — простота. Для доказательства его устойчивости при повторных seeds нужен отдельный опыт именно с этим критерием. Превосходство победителя на 0.0024 не следует считать статистически доказанным.

## 5 Дополнительная часть Регрессия

### 5.1 Что заполнено и исправлено

В `regression_task_1.ipynb` сохранены без изменения все 300 исходных пар x/y. Устранена неявная подмена данных: три набора хранятся раздельно, `DATA_VARIANT=1` выбирает набор для пошагового примера. Для всех трёх вариантов отдельно выполнен подбор полиномов, Ridge и Lasso.

Заполнены матричные формулы степеней 1 и 2, написан полином степени 3, рассчитаны потери степеней 0–9, добавлены настоящая кроссвалидация и обучение с регуляризацией. Реализован градиентный спуск и сравнение с sklearn/statsmodels. Все промежуточные таблицы и графики сохранены в блокноте.

![Три исходных варианта регрессии](results/figures/regression_data.png)

### 5.2 Матричная форма и выбор степени

При X=[1,x,…,xᵈ] использована формула θ=(XᵀX)⁻¹Xᵀy. Все три решения проверены через `np.linalg.lstsq` с допуском 1e−7. Ниже результаты на всех 100 точках варианта 1; это обучающие оценки.

{tab(read('regression_matrix'), ['degree','theta','mse_train','r2_train','condition_number'])}

![Матричная регрессия степеней 1–3](results/figures/regression_matrix.png)

Для выбора сложности использована MSE=mean((y−ŷ)²), степени 0–9, пятичастная CV только на 50 обучающих объектах. Степень с минимальной CV MSE — **{int(poly_winner.degree)}**.

{tab(poly, ['degree','train_mse','cv_mse_mean','cv_mse_std','test_mse'])}

![Регрессионные зависимости разных степеней](results/figures/regression_degrees.png)

![Потери в зависимости от степени полинома](results/figures/regression_loss.png)

Test MSE для всех степеней показана как диагностика после фиксации выбора; степень по test не подбиралась. Рост степени уменьшает обучающую ошибку, но может ухудшать CV/test и обусловленность. Меньшая train MSE сама по себе не является основанием увеличивать степень.

### 5.3 Регуляризация

Сначала заполнены формулы исходной заготовки с L=1: Ridge objective = MSE/2 + L·Σθⱼ²/(2m), Lasso objective = MSE/2 + L·Σ|θⱼ|, без штрафа свободного члена. Эти значения на коэффициентах `np.polyfit` сохранены в `results/regression_penalties.csv` и являются диагностикой: добавление штрафа после OLS не изменяет модель.

Затем действительно обучены Ridge и Lasso с центрированием/масштабированием x до построения степеней и масштабированием полученных столбцов. Обе StandardScaler обучаются внутри каждого фолда; использованы степенями 1–9 и alpha ∈ {{0.01, 0.1, 1, 10, 100}}. Ridge минимизирует RSS+alpha·L2², Lasso — RSS/(2m)+alpha·L1, поэтому одинаковые числа alpha не означают одинаковую силу штрафа. Lasso решается методом LARS через [LassoLars](https://scikit-learn.org/stable/modules/generated/sklearn.linear_model.LassoLars.html); для каждого решения независимо проверены условия оптимальности KKT с допуском 1e−5. См. определения [Ridge](https://scikit-learn.org/stable/modules/generated/sklearn.linear_model.Ridge.html) и [Lasso](https://scikit-learn.org/stable/modules/generated/sklearn.linear_model.Lasso.html).

{tab(read('regression_regularization_test'), ['method','degree','alpha','cv_mse_mean','cv_mse_std','train_mse','test_mse','test_r2'])}

![OLS и действительно обученные Ridge и Lasso](results/figures/regression_regularized.png)

Регуляризация ограничивает коэффициенты, но не обязана улучшать результат каждого конкретного тестового разбиения. Сравнивать методы нужно по CV MSE и отложенным метрикам, а не по числам их разных штрафных функций.

### 5.4 Градиентный спуск и библиотечные решения

Реализованы J=||y−Xθ||²/(2m) и θ←θ+α·Xᵀ(y−Xθ)/m. Шаг α=0.01, число итераций — 1000. Признак x стандартизован для устойчивой сходимости, после чего коэффициенты возвращены в исходные единицы. Выполнены все итерации; на рисунке прямых показаны девять состояний для читаемости.

- Градиентный спуск: θ₀={reg['gradient_theta'][0]:.6f}, θ₁={reg['gradient_theta'][1]:.6f}.
- Матричное решение: θ₀={reg['exact_theta'][0]:.6f}, θ₁={reg['exact_theta'][1]:.6f}.
- Финальное J = {reg['gradient_final_loss']:.6f}; значения конечны и монотонно убывают.
- Коэффициенты градиентного спуска совпали с точным решением при относительном допуске 5e−5; sklearn и statsmodels проверены с абсолютным допуском 1e−10.

![Сходимость градиентного спуска](results/figures/regression_gradient_loss.png)

### 5.5 Интерпретация statsmodels

Для варианта 1 линейная модель на всех 100 точках имеет вид **ŷ={reg['exact_theta'][0]:.4f}+{reg['exact_theta'][1]:.4f}·x**. Наклон выражен в Мбит/с за час, свободный член — оценка трафика при x=0. R²={reg['ols']['r2']:.4f}, скорректированный R²={reg['ols']['adjusted_r2']:.4f}; линейная зависимость описывает часть разброса, но не всё.

F={reg['ols']['f_statistic']:.4f}, p(F)={reg['ols']['f_pvalue']:.3g}: при стандартных предпосылках OLS модель с наклоном отличается от модели с одной константой. Это не доказательство причинного влияния времени. AIC={reg['ols']['aic']:.2f}, BIC={reg['ols']['bic']:.2f} полезны для сравнения моделей на тех же наблюдениях.

В блокноте объяснены все поля summary: Dep. Variable, Model, R²/Adj. R², F/p(F), Log-Likelihood, AIC/BIC, coef, std err, t, p-value, доверительные интервалы, Omnibus, Durbin–Watson, Jarque–Bera, Skew, Kurtosis и Cond. No. Исправлено пояснение Kurtosis: это куртозис (норма 3), а не эксцесс (норма 0). Добавлены робастные ошибки HC3. Статистическая значимость коэффициента не заменяет оценку прогноза на test.

### 5.6 Итоги для всех трёх наборов

{tab(all_reg, ['variant','method','degree','alpha','cv_mse_mean','cv_mse_std','test_mse','test_r2'])}

Степень и alpha выбраны отдельно внутри каждой семьи по CV. Таблица не использовалась для повторного подбора по test. Для варианта 1 наименьшая CV MSE среди трёх выбранных моделей у **{all_reg[all_reg.variant==1].sort_values('cv_mse_mean').iloc[0]['method']}**; для варианта 2 — **{all_reg[all_reg.variant==2].sort_values('cv_mse_mean').iloc[0]['method']}**; для варианта 3 — **{all_reg[all_reg.variant==3].sort_values('cv_mse_mean').iloc[0]['method']}**.

При дальнейшем исследовании можно сравнивать сплайны, k-NN-регрессию, деревья, ансамбли и SVR. Текущий случайный train/test проверяет интерполяцию внутри диапазона 0–24 ч, а не прогноз будущего временного ряда.

## 6 Проверка и воспроизведение

Все три блокнота выполнены сверху вниз в отдельных чистых ядрах; сохранены номера выполнения, численные результаты, таблицы и графики. Старые outputs заменены результатами нового запуска. Ручные алгоритмы проверены на контрольных примерах, регрессионные решения — независимыми формулами и библиотеками. У Lasso предупреждение о несходимости считается ошибкой запуска; выполнено {reg['lasso_kkt_checks']} проверок KKT, максимальное нарушение условий оптимальности — {reg['lasso_kkt_max_violation']:.3g}.

Рабочая среда: Python {env['python']}, NumPy {env['numpy']}, pandas {env['pandas']}, SciPy {env['scipy']}, scikit-learn {env['scikit-learn']}, Matplotlib {env['matplotlib']}, statsmodels {env['statsmodels']}. Полный список версий закреплён в `requirements.txt`.

Повторный запуск из папки с блокнотами:

```bash
cd /Users/rammls/Projects/Labs-IB/other-discipline/ml
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python run_notebooks.py
.venv/bin/python build_report.py
.venv/bin/python validate_results.py
```

Для воспроизведения использован Python 3.12.14. Уже созданное `.venv` готово к работе: создание окружения и установку пакетов можно пропустить. Для одного блокнота передайте его имя, например `.venv/bin/python run_notebooks.py decision_tree.ipynb`. В Jupyter/VS Code нужно выбрать интерпретатор `.venv/bin/python` и выполнять из этой папки. `ml_utils.py` должен находиться рядом с блокнотами.

Полные данные экспериментов: [k-NN](results/knn_grid.csv), [дерево](results/tree_grid.csv), [регрессия по трём вариантам](results/regression_all_variants.csv). Папку `results/figures` нужно сохранять вместе с Markdown-отчётом, чтобы отображались изображения. Графики построены по фактическим расчётам. Два скриншота в разделах 3.5 и 4.6 сняты с HTML-представления сохранённых результатов блокнотов; соответствие их исходным outputs проверяется по SHA-256.

## 7 Общий вывод

Для исходных полумесяцев лучший найденный k-NN — **k={kp['k']}, {kp['weights']}, {kp['metric_name']}**, тестовая accuracy **{pct(knn['test']['accuracy'])}**. При фиксированном k=15 веса uniform устойчивее к ошибочным обучающим меткам. Euclidean/Manhattan подходят для геометрии данных; результат стандартизованного расстояния улучшился при совместном подборе k и weights.

Лучшее найденное дерево при seed=42 — **depth={tp['max_depth']}, {tp['criterion']}, {tp['splitter']}, leaf={tp['min_samples_leaf']}, split={tp['min_samples_split']}, max_features=None**, тестовая accuracy **{pct(tree['test']['accuracy'])}**. При глубине 5 splitter=best стабильнее random; при сильном шуме меток помогают меньшая глубина и более крупные листья. Максимум CV в конкретной сетке не равен универсально лучшей или самой устойчивой модели.

В регрессии заполнены все предусмотренные методы и подтверждено согласование независимых решений линейной задачи. Выбор сложности основан на CV, регуляризация действительно обучена, а все три исходных варианта рассчитаны отдельно.
'''
    output = ROOT / 'Отчёт_практическая_работа_1.md'
    output.write_text(text, encoding='utf-8')
    print(output)

if __name__ == '__main__':
    main()
