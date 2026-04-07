from __future__ import annotations

import ast
import io
import json
import mimetypes
import os
import uuid
from collections.abc import Callable
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from typing import Any, Literal

import matplotlib
import numpy as np
import pandas as pd
from langchain_core.tools import StructuredTool
from pydantic import BaseModel, Field
from sklearn.cluster import KMeans
from sklearn.preprocessing import StandardScaler

from app.utils.files import ensure_directory, resolve_workspace_path

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402


def _load_tabular_data(path: Path) -> pd.DataFrame:
    suffix = path.suffix.lower()
    if suffix == ".csv":
        return pd.read_csv(path)
    if suffix in {".xlsx", ".xls"}:
        return pd.read_excel(path)
    if suffix == ".json":
        return pd.read_json(path)
    raise ValueError(f"Unsupported tabular file type: {path.suffix}")


def _write_tabular_data(df: pd.DataFrame, path: Path) -> None:
    suffix = path.suffix.lower()
    if suffix == ".csv":
        df.to_csv(path, index=False)
        return
    if suffix in {".xlsx", ".xls"}:
        df.to_excel(path, index=False)
        return
    if suffix == ".json":
        df.to_json(path, orient="records", indent=2)
        return
    raise ValueError(f"Unsupported output file type: {path.suffix}")


def _to_jsonable(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, (np.integer, np.floating)):
        return value.item()
    if isinstance(value, (int, float)):
        return None if pd.isna(value) else value
    if isinstance(value, (str, bool)):
        return value
    if isinstance(value, (pd.Timestamp, pd.Timedelta)):
        return str(value)
    if isinstance(value, np.ndarray):
        return [_to_jsonable(item) for item in value.tolist()]
    try:
        if pd.isna(value):
            return None
    except (TypeError, ValueError):
        pass
    return value


def _frame_preview(df: pd.DataFrame, rows: int = 5) -> list[dict[str, Any]]:
    preview_df = df.head(rows).replace({np.nan: None})
    records: list[dict[str, Any]] = []
    for record in preview_df.to_dict(orient="records"):
        records.append({key: _to_jsonable(value) for key, value in record.items()})
    return records


def _relative_output_path(root_dir: Path, output_path: Path) -> str:
    root_resolved = root_dir.resolve()
    output_resolved = output_path.resolve()
    try:
        return str(output_resolved.relative_to(root_resolved))
    except ValueError:
        return str(output_resolved)


class DatasetValidateInput(BaseModel):
    input_file_path: str = Field(..., description="Input Excel, CSV, or JSON path.")
    required_columns: list[str] = Field(..., description="Required dataset columns.")


class DatasetPreviewInput(BaseModel):
    input_file_path: str = Field(..., description="Input Excel, CSV, or JSON path.")
    n_rows: int = Field(5, ge=1, le=100, description="Rows to preview.")


class DatasetProfileInput(BaseModel):
    input_file_path: str = Field(..., description="Input Excel, CSV, or JSON path.")
    top_k_categories: int = Field(5, ge=1, le=10, description="Top values to show for categorical columns.")


class CleanDatasetInput(BaseModel):
    input_file_path: str = Field(..., description="Input Excel, CSV, or JSON path.")
    output_file_path: str = Field(..., description="Output path for the cleaned dataset.")
    numeric_columns: list[str] = Field(default_factory=list, description="Numeric columns to coerce and fill.")
    categorical_columns: list[str] = Field(default_factory=list, description="Categorical columns to fill.")
    drop_duplicates: bool = Field(True, description="Remove duplicate rows.")
    drop_empty_rows: bool = Field(True, description="Remove rows that are completely empty.")
    strip_whitespace: bool = Field(True, description="Trim whitespace on string columns.")
    fill_numeric_strategy: Literal["none", "median", "mean", "zero"] = Field(
        "median",
        description="How to fill missing numeric values.",
    )
    fill_categorical_value: str | None = Field(
        "Unknown",
        description="Fill value for missing categorical values. Use null to skip categorical filling.",
    )


class CompareDatasetsInput(BaseModel):
    baseline_file_path: str = Field(..., description="Reference dataset path.")
    candidate_file_path: str = Field(..., description="Candidate dataset path to compare against the baseline.")
    key_columns: list[str] = Field(
        default_factory=list,
        description="Optional key columns used to measure row overlap between both datasets.",
    )


class SegmentDatasetInput(BaseModel):
    input_file_path: str = Field(..., description="Input Excel, CSV, or JSON path.")
    output_file_path: str = Field(..., description="Output path for the segmented dataset.")
    feature_columns: list[str] = Field(..., min_length=1, description="Numeric feature columns used for clustering.")
    n_clusters: int = Field(3, ge=2, le=10, description="Number of KMeans clusters to create.")
    cluster_label_column: str = Field("cluster_label", description="Name of the output cluster label column.")
    scale_features: bool = Field(True, description="Standardize features before clustering.")
    random_state: int = Field(42, description="Random seed used by KMeans.")


class ReportExportInput(BaseModel):
    output_file_path: str = Field(..., description="Output report path. Use .md for markdown or .json for JSON.")
    report_title: str = Field(..., min_length=3, description="Human-readable report title.")
    executive_summary: str = Field(..., min_length=10, description="Executive summary of the analysis.")
    key_findings: list[str] = Field(..., min_length=1, description="Ordered list of the most important findings.")
    recommended_actions: list[str] = Field(
        default_factory=list,
        description="Optional follow-up actions or recommendations.",
    )
    supporting_metrics: dict[str, Any] = Field(
        default_factory=dict,
        description="Optional metrics that should appear in the report.",
    )
    source_file_paths: list[str] = Field(
        default_factory=list,
        description="Relevant workspace files referenced by the report.",
    )
    report_format: Literal["markdown", "json"] = Field(
        "markdown",
        description="Output format for the exported report.",
    )


class PlotInput(BaseModel):
    code: str = Field(..., description="Python code to generate a plot.")


class SendFilesToUserInput(BaseModel):
    filename: str = Field(
        ...,
        description="File path relative to the workspace (e.g. 'generated_plots/plot_abc.png' or 'analysis/report.md').",
    )


class DatasetPreviewTool:
    def __init__(self, root_dir: Path):
        self.root_dir = root_dir

    def preview_dataset(self, input_file_path: str, n_rows: int = 5) -> dict[str, Any]:
        try:
            file_path = resolve_workspace_path(self.root_dir, input_file_path, must_exist=True)
            df = _load_tabular_data(file_path)
            return {
                "status": "success",
                "rows": int(df.shape[0]),
                "columns": list(df.columns),
                "dtypes": {col: str(dtype) for col, dtype in df.dtypes.items()},
                "preview": _frame_preview(df, rows=n_rows),
            }
        except Exception as exc:
            return {"status": "error", "error": str(exc)}

    def get_tool(self) -> StructuredTool:
        return StructuredTool.from_function(
            func=self.preview_dataset,
            name="preview_dataset",
            description="Preview dataset columns, dtypes, and head rows.",
            args_schema=DatasetPreviewInput,
        )


class DatasetValidateTool:
    def __init__(self, root_dir: Path):
        self.root_dir = root_dir

    def validate_dataset(self, input_file_path: str, required_columns: list[str]) -> dict[str, Any]:
        try:
            file_path = resolve_workspace_path(self.root_dir, input_file_path, must_exist=True)
            df = _load_tabular_data(file_path)
            available_columns = list(df.columns)
            missing = [col for col in required_columns if col not in df.columns]
            return {
                "status": "success",
                "valid": len(missing) == 0,
                "missing_columns": missing,
                "available_columns": available_columns,
                "dtypes": {col: str(dtype) for col, dtype in df.dtypes.items()},
            }
        except Exception as exc:
            return {"status": "error", "error": str(exc)}

    def get_tool(self) -> StructuredTool:
        return StructuredTool.from_function(
            func=self.validate_dataset,
            name="validate_dataset",
            description="Validate that a dataset contains the required columns.",
            args_schema=DatasetValidateInput,
        )


class DatasetProfileTool:
    def __init__(self, root_dir: Path):
        self.root_dir = root_dir

    def profile_dataset(self, input_file_path: str, top_k_categories: int = 5) -> dict[str, Any]:
        try:
            file_path = resolve_workspace_path(self.root_dir, input_file_path, must_exist=True)
            df = _load_tabular_data(file_path)

            numeric_columns = list(df.select_dtypes(include=["number"]).columns)
            categorical_columns = list(df.select_dtypes(exclude=["number"]).columns)
            missing_counts = df.isna().sum().sort_values(ascending=False)
            missing_ratio = ((missing_counts / max(len(df), 1)) * 100).round(2)
            duplicate_rows = int(df.duplicated().sum())

            numeric_summary: dict[str, Any] = {}
            if numeric_columns:
                describe_df = df[numeric_columns].describe().transpose().round(4).replace({np.nan: None})
                numeric_summary = {
                    column: {metric: _to_jsonable(value) for metric, value in metrics.items()}
                    for column, metrics in describe_df.to_dict(orient="index").items()
                }

            categorical_summary: dict[str, Any] = {}
            for column in categorical_columns[: min(len(categorical_columns), 8)]:
                top_values = (
                    df[column]
                    .astype("string")
                    .fillna("<MISSING>")
                    .value_counts(dropna=False)
                    .head(top_k_categories)
                )
                categorical_summary[column] = {str(key): int(value) for key, value in top_values.items()}

            warnings: list[str] = []
            high_missing = [col for col, pct in missing_ratio.items() if pct >= 30]
            if high_missing:
                warnings.append(f"Columns with >=30% missing values: {', '.join(high_missing[:8])}.")
            if duplicate_rows:
                warnings.append(f"Dataset contains {duplicate_rows} duplicate rows.")
            constant_columns = [col for col in df.columns if df[col].nunique(dropna=False) <= 1]
            if constant_columns:
                warnings.append(f"Constant or near-empty columns detected: {', '.join(constant_columns[:8])}.")

            return {
                "status": "success",
                "shape": {"rows": int(df.shape[0]), "columns": int(df.shape[1])},
                "column_types": {
                    "numeric": numeric_columns,
                    "categorical": categorical_columns,
                },
                "missing_by_column": {
                    column: {
                        "missing_rows": int(missing_counts[column]),
                        "missing_pct": _to_jsonable(missing_ratio[column]),
                    }
                    for column in missing_counts.index[: min(len(missing_counts), 20)]
                    if int(missing_counts[column]) > 0
                },
                "duplicate_rows": duplicate_rows,
                "numeric_summary": numeric_summary,
                "categorical_summary": categorical_summary,
                "warnings": warnings,
            }
        except Exception as exc:
            return {"status": "error", "error": str(exc)}

    def get_tool(self) -> StructuredTool:
        return StructuredTool.from_function(
            func=self.profile_dataset,
            name="profile_dataset",
            description="Profile a tabular dataset and return quality warnings, missingness, and summary stats.",
            args_schema=DatasetProfileInput,
        )


class CleanDatasetTool:
    def __init__(self, root_dir: Path):
        self.root_dir = root_dir

    def clean_dataset(
        self,
        input_file_path: str,
        output_file_path: str,
        numeric_columns: list[str] | None = None,
        categorical_columns: list[str] | None = None,
        drop_duplicates: bool = True,
        drop_empty_rows: bool = True,
        strip_whitespace: bool = True,
        fill_numeric_strategy: Literal["none", "median", "mean", "zero"] = "median",
        fill_categorical_value: str | None = "Unknown",
    ) -> dict[str, Any]:
        try:
            input_path = resolve_workspace_path(self.root_dir, input_file_path, must_exist=True)
            output_path = resolve_workspace_path(self.root_dir, output_file_path, must_exist=False)
            ensure_directory(output_path.parent)

            df = _load_tabular_data(input_path).copy()
            rows_before = int(len(df))
            nulls_before = int(df.isna().sum().sum())

            if strip_whitespace:
                string_columns = list(df.select_dtypes(include=["object", "string"]).columns)
                for column in string_columns:
                    df[column] = df[column].map(lambda value: value.strip() if isinstance(value, str) else value)

            if drop_empty_rows:
                df = df.dropna(how="all")

            duplicates_removed = 0
            if drop_duplicates:
                duplicates_removed = int(df.duplicated().sum())
                df = df.drop_duplicates()

            numeric_targets = list(numeric_columns or df.select_dtypes(include=["number"]).columns)
            for column in numeric_targets:
                if column not in df.columns:
                    return {"status": "error", "error": f"Numeric column '{column}' not found in dataset."}
                df[column] = pd.to_numeric(df[column], errors="coerce")

            if fill_numeric_strategy != "none":
                for column in numeric_targets:
                    if fill_numeric_strategy == "median":
                        fill_value = df[column].median()
                    elif fill_numeric_strategy == "mean":
                        fill_value = df[column].mean()
                    else:
                        fill_value = 0

                    if pd.isna(fill_value):
                        fill_value = 0
                    df[column] = df[column].fillna(fill_value)

            categorical_targets = list(
                categorical_columns
                or df.select_dtypes(include=["object", "string", "category"]).columns
            )
            if fill_categorical_value is not None:
                for column in categorical_targets:
                    if column not in df.columns:
                        return {"status": "error", "error": f"Categorical column '{column}' not found in dataset."}
                    df[column] = df[column].fillna(fill_categorical_value)

            _write_tabular_data(df, output_path)

            return {
                "status": "success",
                "message": "Dataset cleaned successfully.",
                "input_rows": rows_before,
                "output_rows": int(len(df)),
                "rows_removed": rows_before - int(len(df)),
                "duplicates_removed": duplicates_removed,
                "null_values_before": nulls_before,
                "null_values_after": int(df.isna().sum().sum()),
                "output_file": _relative_output_path(self.root_dir, output_path),
                "preview": _frame_preview(df),
            }
        except Exception as exc:
            return {"status": "error", "error": str(exc)}

    def get_tool(self) -> StructuredTool:
        return StructuredTool.from_function(
            func=self.clean_dataset,
            name="clean_dataset",
            description="Clean a dataset by trimming strings, removing duplicates, and filling missing values.",
            args_schema=CleanDatasetInput,
        )


class CompareDatasetsTool:
    def __init__(self, root_dir: Path):
        self.root_dir = root_dir

    def compare_datasets(
        self,
        baseline_file_path: str,
        candidate_file_path: str,
        key_columns: list[str] | None = None,
    ) -> dict[str, Any]:
        try:
            baseline_path = resolve_workspace_path(self.root_dir, baseline_file_path, must_exist=True)
            candidate_path = resolve_workspace_path(self.root_dir, candidate_file_path, must_exist=True)
            baseline_df = _load_tabular_data(baseline_path)
            candidate_df = _load_tabular_data(candidate_path)

            baseline_columns = set(baseline_df.columns)
            candidate_columns = set(candidate_df.columns)
            common_columns = sorted(baseline_columns & candidate_columns)

            dtype_changes = {
                column: {
                    "baseline": str(baseline_df[column].dtype),
                    "candidate": str(candidate_df[column].dtype),
                }
                for column in common_columns
                if str(baseline_df[column].dtype) != str(candidate_df[column].dtype)
            }

            numeric_drift: dict[str, Any] = {}
            for column in common_columns:
                if pd.api.types.is_numeric_dtype(baseline_df[column]) and pd.api.types.is_numeric_dtype(candidate_df[column]):
                    base_mean = pd.to_numeric(baseline_df[column], errors="coerce").mean()
                    cand_mean = pd.to_numeric(candidate_df[column], errors="coerce").mean()
                    numeric_drift[column] = {
                        "baseline_mean": _to_jsonable(round(base_mean, 4)) if pd.notna(base_mean) else None,
                        "candidate_mean": _to_jsonable(round(cand_mean, 4)) if pd.notna(cand_mean) else None,
                        "delta": _to_jsonable(round(cand_mean - base_mean, 4))
                        if pd.notna(base_mean) and pd.notna(cand_mean)
                        else None,
                    }
            numeric_drift = dict(list(numeric_drift.items())[:10])

            key_overlap: dict[str, Any] | None = None
            key_columns = key_columns or []
            if key_columns:
                missing_key_columns = [column for column in key_columns if column not in common_columns]
                if missing_key_columns:
                    return {
                        "status": "error",
                        "error": f"Key columns missing in one or both datasets: {', '.join(missing_key_columns)}",
                    }

                baseline_keys = baseline_df[key_columns].astype("string").fillna("<MISSING>").agg("||".join, axis=1)
                candidate_keys = candidate_df[key_columns].astype("string").fillna("<MISSING>").agg("||".join, axis=1)
                baseline_key_set = set(baseline_keys.tolist())
                candidate_key_set = set(candidate_keys.tolist())
                overlap = baseline_key_set & candidate_key_set
                key_overlap = {
                    "baseline_unique_keys": len(baseline_key_set),
                    "candidate_unique_keys": len(candidate_key_set),
                    "shared_unique_keys": len(overlap),
                    "baseline_duplicate_keys": int(baseline_keys.duplicated().sum()),
                    "candidate_duplicate_keys": int(candidate_keys.duplicated().sum()),
                }

            return {
                "status": "success",
                "shape": {
                    "baseline_rows": int(len(baseline_df)),
                    "candidate_rows": int(len(candidate_df)),
                    "baseline_columns": int(len(baseline_df.columns)),
                    "candidate_columns": int(len(candidate_df.columns)),
                },
                "columns_only_in_baseline": sorted(baseline_columns - candidate_columns),
                "columns_only_in_candidate": sorted(candidate_columns - baseline_columns),
                "dtype_changes": dtype_changes,
                "numeric_drift": numeric_drift,
                "key_overlap": key_overlap,
            }
        except Exception as exc:
            return {"status": "error", "error": str(exc)}

    def get_tool(self) -> StructuredTool:
        return StructuredTool.from_function(
            func=self.compare_datasets,
            name="compare_datasets",
            description="Compare two tabular datasets for schema differences, row overlap, and numeric drift.",
            args_schema=CompareDatasetsInput,
        )


class SegmentDatasetTool:
    def __init__(self, root_dir: Path):
        self.root_dir = root_dir

    def segment_dataset(
        self,
        input_file_path: str,
        output_file_path: str,
        feature_columns: list[str],
        n_clusters: int = 3,
        cluster_label_column: str = "cluster_label",
        scale_features: bool = True,
        random_state: int = 42,
    ) -> dict[str, Any]:
        try:
            input_path = resolve_workspace_path(self.root_dir, input_file_path, must_exist=True)
            output_path = resolve_workspace_path(self.root_dir, output_file_path, must_exist=False)
            ensure_directory(output_path.parent)

            df = _load_tabular_data(input_path).copy()
            missing_columns = [column for column in feature_columns if column not in df.columns]
            if missing_columns:
                return {"status": "error", "error": f"Feature columns not found: {', '.join(missing_columns)}"}

            feature_frame = df[feature_columns].apply(pd.to_numeric, errors="coerce")
            if feature_frame.dropna(how="all").empty:
                return {"status": "error", "error": "Selected feature columns do not contain usable numeric data."}

            fill_values = feature_frame.median(numeric_only=True).fillna(0)
            feature_frame = feature_frame.fillna(fill_values)
            model_input = feature_frame.to_numpy()

            if scale_features:
                scaler = StandardScaler()
                model_input = scaler.fit_transform(model_input)
            else:
                scaler = None

            model = KMeans(n_clusters=n_clusters, random_state=random_state, n_init=10)
            labels = model.fit_predict(model_input)

            output_df = df.copy()
            output_df[cluster_label_column] = labels
            _write_tabular_data(output_df, output_path)

            summary_path = output_path.with_name(f"{output_path.stem}_cluster_summary.csv")
            summary_df = (
                output_df.groupby(cluster_label_column)[feature_columns]
                .agg(["count", "mean", "median"])
                .round(4)
            )
            summary_df.to_csv(summary_path)

            cluster_counts = pd.Series(labels).value_counts().sort_index()
            warnings: list[str] = []
            if not cluster_counts.empty and cluster_counts.min() <= max(2, int(0.05 * len(output_df))):
                warnings.append("At least one cluster is very small; consider reducing the number of clusters.")

            centroids = model.cluster_centers_
            if scaler is not None:
                centroids = scaler.inverse_transform(centroids)

            return {
                "status": "success",
                "message": "Dataset segmented successfully.",
                "output_file": _relative_output_path(self.root_dir, output_path),
                "summary_file": _relative_output_path(self.root_dir, summary_path),
                "feature_columns": feature_columns,
                "n_clusters": n_clusters,
                "cluster_counts": {str(index): int(value) for index, value in cluster_counts.items()},
                "centroids": [
                    {
                        "cluster": int(cluster_id),
                        **{
                            column: _to_jsonable(round(value, 4))
                            for column, value in zip(feature_columns, centroid)
                        },
                    }
                    for cluster_id, centroid in enumerate(centroids)
                ],
                "warnings": warnings,
                "preview": _frame_preview(output_df),
            }
        except Exception as exc:
            return {"status": "error", "error": str(exc)}

    def get_tool(self) -> StructuredTool:
        return StructuredTool.from_function(
            func=self.segment_dataset,
            name="segment_dataset",
            description="Cluster a dataset into segments using KMeans and export labeled output files.",
            args_schema=SegmentDatasetInput,
        )


class ReportExportTool:
    def __init__(self, root_dir: Path):
        self.root_dir = root_dir

    def export_report(
        self,
        output_file_path: str,
        report_title: str,
        executive_summary: str,
        key_findings: list[str],
        recommended_actions: list[str] | None = None,
        supporting_metrics: dict[str, Any] | None = None,
        source_file_paths: list[str] | None = None,
        report_format: Literal["markdown", "json"] = "markdown",
    ) -> dict[str, Any]:
        try:
            output_path = resolve_workspace_path(self.root_dir, output_file_path, must_exist=False)
            ensure_directory(output_path.parent)

            recommended_actions = recommended_actions or []
            supporting_metrics = supporting_metrics or {}
            source_file_paths = source_file_paths or []

            if report_format == "json":
                payload = {
                    "title": report_title,
                    "executive_summary": executive_summary,
                    "key_findings": key_findings,
                    "recommended_actions": recommended_actions,
                    "supporting_metrics": supporting_metrics,
                    "source_files": source_file_paths,
                }
                output_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
            else:
                lines = [f"# {report_title}", "", "## Executive Summary", executive_summary, "", "## Key Findings"]
                lines.extend(f"- {item}" for item in key_findings)

                if recommended_actions:
                    lines.extend(["", "## Recommended Actions"])
                    lines.extend(f"- {item}" for item in recommended_actions)

                if supporting_metrics:
                    lines.extend(["", "## Supporting Metrics", "| Metric | Value |", "| --- | --- |"])
                    for metric, value in supporting_metrics.items():
                        lines.append(f"| {metric} | {_to_jsonable(value)} |")

                if source_file_paths:
                    lines.extend(["", "## Source Files"])
                    lines.extend(f"- {path}" for path in source_file_paths)

                output_path.write_text("\n".join(lines).strip() + "\n", encoding="utf-8")

            return {
                "status": "success",
                "message": "Report exported successfully.",
                "output_file": _relative_output_path(self.root_dir, output_path),
                "report_format": report_format,
            }
        except Exception as exc:
            return {"status": "error", "error": str(exc)}

    def get_tool(self) -> StructuredTool:
        return StructuredTool.from_function(
            func=self.export_report,
            name="export_report",
            description="Export a decision-ready markdown or JSON report to the workspace.",
            args_schema=ReportExportInput,
        )


class CodePreprocessor:
    TARGET_FUNCTIONS = {
        "read_csv",
        "read_excel",
        "read_json",
    }

    def __init__(self, root_dir_var: str = "ROOT_DIR"):
        self.root_dir_var = root_dir_var

    def preprocess(self, code: str) -> str:
        try:
            tree = ast.parse(code)
            transformer = PathInjectorTransformer(self.root_dir_var, self.TARGET_FUNCTIONS)
            new_tree = transformer.visit(tree)
            return ast.unparse(new_tree)
        except SyntaxError:
            return code


_FILE_TYPE_MAP: dict[str, str] = {
    ".png": "image",
    ".jpg": "image",
    ".jpeg": "image",
    ".gif": "image",
    ".svg": "image",
    ".bmp": "image",
    ".webp": "image",
    ".csv": "data",
    ".xlsx": "data",
    ".xls": "data",
    ".json": "data",
    ".pdf": "document",
    ".docx": "document",
    ".pptx": "document",
    ".txt": "document",
    ".md": "document",
}


def _classify_file(filename: str) -> tuple[str, str]:
    ext = Path(filename).suffix.lower()
    file_type = _FILE_TYPE_MAP.get(ext, "document")
    mime_type = mimetypes.guess_type(filename)[0] or "application/octet-stream"
    return file_type, mime_type


class SendFilesToUserTool:
    def __init__(
        self,
        root_dir: Path,
        user_id: str | None = None,
        url_signer: Callable[[str], str] | None = None,
    ):
        self.root_dir = root_dir
        self.user_id = user_id
        self.url_signer = url_signer

    def send_files_to_user(self, filename: str) -> tuple[dict[str, Any], dict[str, Any] | None]:
        try:
            resolved = resolve_workspace_path(self.root_dir, filename, must_exist=True)
        except FileNotFoundError:
            return {"status": "error", "message": f"File '{filename}' not found in workspace."}, None
        except ValueError as exc:
            return {"status": "error", "message": str(exc)}, None

        file_type, mime_type = _classify_file(resolved.name)

        if self.url_signer and self.user_id:
            relative_path = _relative_output_path(self.root_dir, resolved)
            secure_url = self.url_signer(relative_path)
        else:
            secure_url = f"/files/unknown/{filename}"

        content_for_llm = {
            "status": "success",
            "message": f"File '{resolved.name}' sent to user successfully.",
        }
        artifact_for_frontend = {
            "filename": resolved.name,
            "url": secure_url,
            "type": file_type,
            "mime_type": mime_type,
        }
        return content_for_llm, artifact_for_frontend

    def get_tool(self) -> StructuredTool:
        return StructuredTool.from_function(
            func=self.send_files_to_user,
            name="send_files_to_user",
            description=(
                "Send a file from the workspace to the user. "
                "Provide the filename relative to the workspace directory. "
                "Use this for plots, reports, cleaned datasets, or comparison outputs."
            ),
            args_schema=SendFilesToUserInput,
            response_format="content_and_artifact",
        )


class PathInjectorTransformer(ast.NodeTransformer):
    def __init__(self, root_var: str, target_funcs: set[str]):
        self.root_var = root_var
        self.target_funcs = target_funcs

    def visit_Call(self, node: ast.Call) -> ast.Call:
        if isinstance(node.func, ast.Attribute):
            func_name = node.func.attr
            if func_name in self.target_funcs and node.args:
                first_arg = node.args[0]
                if isinstance(first_arg, ast.Constant) and isinstance(first_arg.value, str):
                    path = first_arg.value
                    if self._is_relative_path(path):
                        node.args[0] = ast.BinOp(
                            left=ast.Name(id=self.root_var, ctx=ast.Load()),
                            op=ast.Add(),
                            right=ast.Constant(value=path),
                        )
        return node

    def _is_relative_path(self, path: str) -> bool:
        if path.startswith(self.root_var):
            return False
        if path.startswith("/") or path.startswith("\\"):
            return False
        if len(path) > 1 and path[1] == ":":
            return False
        return True


class PlottingTool:
    def __init__(self, root_dir: Path):
        self.root_dir = root_dir
        self.output_dir = self.root_dir / "generated_plots"
        ensure_directory(self.output_dir)
        self.preprocessor = CodePreprocessor(root_dir_var="ROOT_DIR")

    def python_visual_tool(self, code: str) -> dict[str, Any]:
        safe_code = self.preprocessor.preprocess(code)
        stdout_buffer = io.StringIO()
        stderr_buffer = io.StringIO()
        image_path: Path | None = None

        try:
            exec_globals = {
                "pd": pd,
                "plt": plt,
                "np": np,
                "io": io,
                "ROOT_DIR": self._root_prefix(),
                "__builtins__": __builtins__,
            }

            with redirect_stdout(stdout_buffer), redirect_stderr(stderr_buffer):
                exec(safe_code, exec_globals)

            if plt.get_fignums():
                filename = f"plot_{uuid.uuid4().hex}.png"
                image_path = self.output_dir / filename
                plt.savefig(image_path, format="png", bbox_inches="tight", dpi=300)
                plt.close("all")

            stdout_content = stdout_buffer.getvalue()
            stderr_content = stderr_buffer.getvalue()
            summary = stdout_content or "Plot generated successfully."

            return {
                "status": "success",
                "summary": summary,
                "image_path": _relative_output_path(self.root_dir, image_path) if image_path else None,
                "error_output": stderr_content or None,
            }
        except Exception as exc:
            plt.close("all")
            stdout_content = stdout_buffer.getvalue()
            stderr_content = stderr_buffer.getvalue()
            return {
                "status": "error",
                "summary": stdout_content or "Error running plot code.",
                "error_output": f"{stderr_content}\nException: {exc}" if stderr_content else str(exc),
                "image_path": None,
            }

    def _root_prefix(self) -> str:
        root = str(self.root_dir)
        if root.endswith(("\\", "/")):
            return root
        return f"{root}{os.sep}"

    def get_tool(self) -> StructuredTool:
        return StructuredTool.from_function(
            func=self.python_visual_tool,
            name="generate_plot",
            description="Generate chart files from Python code using pandas and matplotlib.",
            args_schema=PlotInput,
        )


def build_tool_registry(
    root_dir: Path,
    *,
    user_id: str | None = None,
    url_signer: Callable[[str], str] | None = None,
) -> dict[str, Any]:
    preview_tool = DatasetPreviewTool(root_dir=root_dir).get_tool()
    validate_tool = DatasetValidateTool(root_dir=root_dir).get_tool()
    profile_tool = DatasetProfileTool(root_dir=root_dir).get_tool()
    clean_tool = CleanDatasetTool(root_dir=root_dir).get_tool()
    compare_tool = CompareDatasetsTool(root_dir=root_dir).get_tool()
    segment_tool = SegmentDatasetTool(root_dir=root_dir).get_tool()
    report_tool = ReportExportTool(root_dir=root_dir).get_tool()
    plotting_tool = PlottingTool(root_dir=root_dir).get_tool()
    send_files_tool = SendFilesToUserTool(
        root_dir=root_dir,
        user_id=user_id,
        url_signer=url_signer,
    ).get_tool()

    return {
        "preview_dataset": preview_tool,
        "validate_dataset": validate_tool,
        "profile_dataset": profile_tool,
        "clean_dataset": clean_tool,
        "compare_datasets": compare_tool,
        "segment_dataset": segment_tool,
        "export_report": report_tool,
        "generate_plot": plotting_tool,
        "send_files_to_user": send_files_tool,
    }
