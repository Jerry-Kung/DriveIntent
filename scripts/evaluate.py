"""对照人工标注计算评论筛选指标。

用法: python scripts/evaluate.py data/annotation_filled.csv
标注文件即 make_annotation_template.py 的输出，"人工_"列由业务方填写；
未填写的行自动跳过。
"""
import csv
import sys


def _acc(pairs: list[tuple[int, int]]) -> float:
    if not pairs:
        return 0.0
    return sum(1 for a, b in pairs if a == b) / len(pairs)


def main(path: str) -> None:
    meaningful, purchase, marketing, strength_pairs = [], [], [], []
    with open(path, encoding="utf-8-sig") as f:
        for row in csv.DictReader(f):
            if row["人工_有意义(1/0)"].strip() == "":
                continue
            meaningful.append((int(row["模型_有意义"]),
                               int(row["人工_有意义(1/0)"])))
            purchase.append((int(row["模型_购车相关"]),
                             int(row["人工_购车相关(1/0)"])))
            marketing.append((int(row["模型_疑似营销"]),
                              int(row["人工_疑似营销(1/0)"])))
            strength_pairs.append(
                (row["模型_意向强度"],
                 row["人工_意向强度(none/low/medium/high)"].strip()))

    n = len(meaningful)
    print(f"已标注样本数: {n}")
    if n == 0:
        return
    print(f"有意义判断准确率:   {_acc(meaningful):.2%}")
    print(f"购车相关判断准确率: {_acc(purchase):.2%}")
    print(f"疑似营销判断准确率: {_acc(marketing):.2%}")
    print(f"意向强度一致率:     {_acc(strength_pairs):.2%}")
    high_pairs = [(a, b) for a, b in strength_pairs if a == "high"]
    if high_pairs:
        hit = sum(1 for a, b in high_pairs if b == "high")
        print(f"模型高意向精确率:   {hit / len(high_pairs):.2%} "
              f"({hit}/{len(high_pairs)})")


if __name__ == "__main__":
    main(sys.argv[1])
