"""
数据处理工具模块 —— Demo 4 演示用大文件

本文件是一个 200+ 行的 Python 模块，用于课程 Demo 4（ACI 信息粒度控制）的演示。
Demo 4 的目的是对比两种读取策略：
- 策略一：Bash("cat large_module.py") 一次性读入全文（上下文爆炸）
- 策略二：Read(file, offset=X, limit=Y) 按需精读（保护 token 预算）

通过这个对比，观众能直观感受到：
- 大文件一次性塞入上下文后，模型的推理质量会显著下降
- ACI 的「粗粒度定位 → 细粒度精读」漏斗策略是必要的工程选择

本模块模拟了一个真实的数据处理场景，包含：
- 数据类定义（DataRecord, DataSet）
- 数据验证器（DataValidator）
- 数据转换器（DataTransformer）
- 统计分析器（StatisticsCalculator）
- 故意留下的 bug（第 ~180 行附近的边界条件错误）
"""

import math
import statistics
from dataclasses import dataclass, field
from typing import List, Optional, Dict, Any, Tuple
from datetime import datetime


# ===========================================================================
# 数据模型
# ===========================================================================

@dataclass
class DataRecord:
    """
    单条数据记录。

    每条记录包含一个数值和一个时间戳，
    以及一个可选的标签用于分组。
    """
    value: float
    timestamp: datetime
    label: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)

    def is_valid(self) -> bool:
        """检查记录是否合法（值不是 NaN 或 Inf）"""
        return math.isfinite(self.value)

    def __repr__(self) -> str:
        label_str = f", label='{self.label}'" if self.label else ""
        return f"DataRecord(value={self.value}{label_str})"


@dataclass
class DataSet:
    """
    数据集：一组 DataRecord 的容器。

    提供基本的增删查改和迭代功能。
    """
    name: str
    records: List[DataRecord] = field(default_factory=list)

    def add(self, record: DataRecord) -> None:
        """添加一条记录"""
        self.records.append(record)

    def add_many(self, records: List[DataRecord]) -> None:
        """批量添加记录"""
        self.records.extend(records)

    def filter_by_label(self, label: str) -> List[DataRecord]:
        """按标签过滤记录"""
        return [r for r in self.records if r.label == label]

    def filter_by_range(self, min_val: float, max_val: float) -> List[DataRecord]:
        """按值范围过滤记录"""
        return [r for r in self.records if min_val <= r.value <= max_val]

    def get_valid_records(self) -> List[DataRecord]:
        """获取所有合法记录（排除 NaN/Inf）"""
        return [r for r in self.records if r.is_valid()]

    def size(self) -> int:
        """返回记录数量"""
        return len(self.records)

    def is_empty(self) -> bool:
        """检查数据集是否为空"""
        return len(self.records) == 0

    def __repr__(self) -> str:
        return f"DataSet(name='{self.name}', size={self.size()})"


# ===========================================================================
# 数据验证
# ===========================================================================

class DataValidator:
    """
    数据验证器：检查数据质量。

    验证规则：
    1. 值范围检查（是否在合理区间内）
    2. 空值检查（是否有 NaN/Inf）
    3. 时间戳单调性检查（是否按时间顺序排列）
    4. 重复值检查
    """

    def __init__(self, min_value: float = -1e6, max_value: float = 1e6):
        self.min_value = min_value
        self.max_value = max_value
        self.errors: List[str] = []

    def validate(self, dataset: DataSet) -> Tuple[bool, List[str]]:
        """
        对数据集执行全部验证。

        Returns:
            (是否通过, 错误列表)
        """
        self.errors = []

        self._check_empty(dataset)
        self._check_values(dataset)
        self._check_timestamps(dataset)
        self._check_duplicates(dataset)

        return len(self.errors) == 0, self.errors

    def _check_empty(self, dataset: DataSet) -> None:
        """检查空数据集"""
        if dataset.is_empty():
            self.errors.append(f"Dataset '{dataset.name}' is empty")

    def _check_values(self, dataset: DataSet) -> None:
        """检查值范围和合法性"""
        for i, record in enumerate(dataset.records):
            if not record.is_valid():
                self.errors.append(
                    f"Record {i}: invalid value {record.value} (NaN or Inf)"
                )
            elif record.value < self.min_value or record.value > self.max_value:
                self.errors.append(
                    f"Record {i}: value {record.value} out of range "
                    f"[{self.min_value}, {self.max_value}]"
                )

    def _check_timestamps(self, dataset: DataSet) -> None:
        """检查时间戳是否单调递增"""
        for i in range(1, len(dataset.records)):
            prev = dataset.records[i - 1].timestamp
            curr = dataset.records[i].timestamp
            if curr < prev:
                self.errors.append(
                    f"Record {i}: timestamp {curr} is before previous {prev}"
                )

    def _check_duplicates(self, dataset: DataSet) -> None:
        """检查完全重复的记录"""
        seen = set()
        for i, record in enumerate(dataset.records):
            key = (record.value, record.timestamp, record.label)
            if key in seen:
                self.errors.append(f"Record {i}: duplicate of a previous record")
            seen.add(key)


# ===========================================================================
# 数据转换
# ===========================================================================

class DataTransformer:
    """
    数据转换器：对数据集进行变换操作。

    支持的变换：
    - normalize: 归一化到 [0, 1] 范围
    - standardize: 标准化（z-score）
    - clip: 裁剪到指定范围
    """

    @staticmethod
    def normalize(dataset: DataSet) -> DataSet:
        """
        归一化：将值缩放到 [0, 1] 范围。

        公式：normalized = (value - min) / (max - min)
        """
        valid = dataset.get_valid_records()
        if not valid:
            return dataset

        values = [r.value for r in valid]
        min_val = min(values)
        max_val = max(values)

        # BUG: 当所有值相同时，max_val == min_val，除以零！
        # 这是故意留下的 bug，用于 Demo 3 的 bug 修复演示
        range_val = max_val - min_val

        new_records = []
        for record in dataset.records:
            if record.is_valid():
                normalized = (record.value - min_val) / range_val
                new_records.append(DataRecord(
                    value=normalized,
                    timestamp=record.timestamp,
                    label=record.label,
                    metadata={**record.metadata, "transform": "normalize"}
                ))
            else:
                new_records.append(record)

        result = DataSet(name=f"{dataset.name}_normalized")
        result.add_many(new_records)
        return result

    @staticmethod
    def standardize(dataset: DataSet) -> DataSet:
        """
        标准化：转为 z-score（均值 0，标准差 1）。

        公式：z = (value - mean) / std
        """
        valid = dataset.get_valid_records()
        if len(valid) < 2:
            return dataset

        values = [r.value for r in valid]
        mean = statistics.mean(values)
        std = statistics.stdev(values)

        if std == 0:
            return dataset

        new_records = []
        for record in dataset.records:
            if record.is_valid():
                z_score = (record.value - mean) / std
                new_records.append(DataRecord(
                    value=z_score,
                    timestamp=record.timestamp,
                    label=record.label,
                    metadata={**record.metadata, "transform": "standardize"}
                ))
            else:
                new_records.append(record)

        result = DataSet(name=f"{dataset.name}_standardized")
        result.add_many(new_records)
        return result

    @staticmethod
    def clip(dataset: DataSet, lower: float, upper: float) -> DataSet:
        """裁剪值到 [lower, upper] 范围"""
        new_records = []
        for record in dataset.records:
            clipped_value = max(lower, min(upper, record.value))
            new_records.append(DataRecord(
                value=clipped_value,
                timestamp=record.timestamp,
                label=record.label,
                metadata={**record.metadata, "transform": "clip"}
            ))
        result = DataSet(name=f"{dataset.name}_clipped")
        result.add_many(new_records)
        return result


# ===========================================================================
# 统计分析
# ===========================================================================

class StatisticsCalculator:
    """
    统计分析器：计算数据集的各种统计指标。
    """

    @staticmethod
    def summary(dataset: DataSet) -> Dict[str, Any]:
        """
        计算数据集的汇总统计。

        返回：count, mean, std, min, max, median, q25, q75
        """
        valid = dataset.get_valid_records()
        if not valid:
            return {"count": 0, "error": "No valid records"}

        values = sorted([r.value for r in valid])
        n = len(values)

        result = {
            "count": n,
            "mean": statistics.mean(values),
            "min": values[0],
            "max": values[-1],
            "median": statistics.median(values),
        }

        if n >= 2:
            result["std"] = statistics.stdev(values)
            # 四分位数
            result["q25"] = values[n // 4]
            result["q75"] = values[3 * n // 4]
        else:
            result["std"] = 0.0
            result["q25"] = values[0]
            result["q75"] = values[0]

        return result

    @staticmethod
    def group_summary(dataset: DataSet) -> Dict[str, Dict[str, Any]]:
        """按标签分组计算统计指标"""
        labels = set(r.label for r in dataset.records if r.label)
        result = {}
        for label in sorted(labels):
            subset = DataSet(name=label)
            subset.add_many(dataset.filter_by_label(label))
            result[label] = StatisticsCalculator.summary(subset)
        return result

    @staticmethod
    def detect_outliers(dataset: DataSet, threshold: float = 2.0) -> List[int]:
        """
        基于 z-score 的异常值检测。

        异常值定义：|z-score| > threshold 的数据点。
        默认阈值为 2.0（约 95% 置信区间外的数据点）。
        """
        valid = dataset.get_valid_records()
        if len(valid) < 2:
            return []

        values = [r.value for r in valid]
        mean = statistics.mean(values)
        std = statistics.stdev(values)

        if std == 0:
            return []

        outlier_indices = []
        for i, record in enumerate(dataset.records):
            if record.is_valid():
                z = abs(record.value - mean) / std
                if z > threshold:
                    outlier_indices.append(i)

        return outlier_indices


# ===========================================================================
# 便捷函数
# ===========================================================================

def create_sample_dataset(n: int = 100, seed: int = 42) -> DataSet:
    """
    创建一个示例数据集用于测试。

    使用简单的线性公式加噪声生成数据，不依赖 numpy/random。
    使用确定性的伪随机序列保证可复现性。
    """
    dataset = DataSet(name="sample")
    labels = ["A", "B", "C"]

    # 简单的线性同余伪随机数生成器
    # LCG 参数来自 Numerical Recipes
    state = seed
    for i in range(n):
        state = (state * 1664525 + 1013904223) & 0xFFFFFFFF
        noise = (state / 0xFFFFFFFF - 0.5) * 10  # [-5, 5] 范围的噪声
        value = i * 0.5 + noise
        timestamp = datetime(2024, 1, 1 + i % 28, i % 24, i % 60)
        label = labels[i % len(labels)]
        dataset.add(DataRecord(
            value=value,
            timestamp=timestamp,
            label=label,
            metadata={"index": i}
        ))

    return dataset


def run_pipeline(dataset: DataSet) -> Dict[str, Any]:
    """
    运行完整的数据处理流水线：
    验证 → 标准化 → 异常值检测 → 统计汇总

    Returns:
        包含验证结果、异常值和统计信息的字典
    """
    # Step 1: 验证
    validator = DataValidator(min_value=-100, max_value=200)
    is_valid, errors = validator.validate(dataset)

    # Step 2: 标准化
    transformed = DataTransformer.standardize(dataset)

    # Step 3: 异常值检测
    outliers = StatisticsCalculator.detect_outliers(dataset)

    # Step 4: 统计汇总
    stats = StatisticsCalculator.summary(dataset)
    group_stats = StatisticsCalculator.group_summary(dataset)

    return {
        "validation": {"passed": is_valid, "errors": errors},
        "outliers": outliers,
        "statistics": stats,
        "group_statistics": group_stats,
    }


# ===========================================================================
# 入口：自检
# ===========================================================================

if __name__ == "__main__":
    # 创建示例数据集并运行流水线
    ds = create_sample_dataset(100)
    print(f"Created: {ds}")
    print(f"Sample records: {ds.records[:3]}")

    results = run_pipeline(ds)
    print(f"\nValidation passed: {results['validation']['passed']}")
    print(f"Outliers at indices: {results['outliers']}")
    print(f"Statistics: {results['statistics']}")

    # 测试 normalize 的 bug（当所有值相同时）
    uniform_ds = DataSet(name="uniform")
    ts = datetime(2024, 1, 1)
    uniform_ds.add_many([DataRecord(value=5.0, timestamp=ts) for _ in range(10)])
    print(f"\nTesting normalize on uniform data...")
    try:
        result = DataTransformer.normalize(uniform_ds)
        print(f"  Result: {[r.value for r in result.records[:3]]}")
    except ZeroDivisionError:
        print("  BUG: ZeroDivisionError when all values are the same!")
