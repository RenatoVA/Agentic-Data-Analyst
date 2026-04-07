from __future__ import annotations

import ast
import io
import mimetypes
import os
import uuid
from collections.abc import Callable
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from typing import Any
import numpy as np
import matplotlib
import pandas as pd
from langchain_core.tools import StructuredTool
from pydantic import BaseModel, Field
from sklearn.neighbors import KDTree

from app.utils.files import ensure_directory, resolve_workspace_path

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402



class NearestNeighborInput(BaseModel):
    origin_file_path: str = Field(
        ...,
        description="Path to the origin CSV/Excel file (relative to ROOT_DIR). Contains the source points with attributes to transfer (e.g., drillhole assays, block model grades).",
    )
    destination_file_path: str = Field(
        ...,
        description="Path to the destination CSV/Excel file (relative to ROOT_DIR). Contains the target points that will receive attributes from their nearest origin neighbor.",
    )
    output_file_path: str = Field(
        ...,
        description="Output CSV path (relative to ROOT_DIR) where the destination data with assigned attributes and distances will be saved.",
    )
    radius: float = Field(
        ...,
        description="Maximum search radius for nearest neighbor assignment. Only origin points within this distance will be matched. Units must match the coordinate system (e.g., meters).",
    )
    col_x: str = Field(
        default="X",
        description="Name of the X coordinate column in both origin and destination files. Case-insensitive.",
    )
    col_y: str = Field(
        default="Y",
        description="Name of the Y coordinate column in both origin and destination files. Case-insensitive.",
    )
    col_z: str = Field(
        default="Z",
        description="Name of the Z coordinate column in both origin and destination files. Case-insensitive.",
    )


class CompositingInput(BaseModel):
    input_file_path: str = Field(..., description="Input Excel/CSV path relative to ROOT_DIR.")
    output_file_path: str = Field(..., description="Output CSV path relative to ROOT_DIR.")
    col_bhid: str = Field(..., description="Drillhole ID column.")
    col_from: str = Field(..., description="From depth column.")
    col_to: str = Field(..., description="To depth column.")
    col_grade: str = Field(..., description="Grade column.")
    col_lithology: str | None = Field(None, description="Lithology column.")
    cutoff_grade: float = Field(..., description="Minimum cutoff grade.")
    waste_cutoff: float = Field(..., description="Maximum waste grade.")
    max_waste_length: float = Field(..., description="Maximum contiguous waste length.")
    priority_ranges: list[list[float]] = Field(..., description="Grade priority ranges.")
    exclude_lithology: str | None = Field(None, description="Lithology code to exclude from surface.")


class PlotInput(BaseModel):
    code: str = Field(..., description="Python code to generate a plot.")


class DatasetValidateInput(BaseModel):
    input_file_path: str = Field(..., description="Input Excel/CSV path.")
    required_columns: list[str] = Field(..., description="Required dataset columns.")


class DatasetPreviewInput(BaseModel):
    input_file_path: str = Field(..., description="Input Excel/CSV path.")
    n_rows: int = Field(5, ge=1, le=100, description="Rows to preview.")

class SendFilesToUserInput(BaseModel):
    filename: str = Field(
        ...,
        description="File path relative to the workspace (e.g. 'generated_plots/plot_abc.png' or 'compositos.csv').",
    )


class DatasetPreviewTool:
    def __init__(self, root_dir: Path):
        self.root_dir = root_dir

    @staticmethod
    def _load_data(path: Path) -> pd.DataFrame:
        if path.suffix.lower() == ".csv":
            return pd.read_csv(path)
        return pd.read_excel(path)

    def preview_dataset(self, input_file_path: str, n_rows: int = 5) -> dict[str, Any]:
        try:
            file_path = resolve_workspace_path(self.root_dir, input_file_path, must_exist=True)
            df = self._load_data(file_path)
            preview = df.head(n_rows).to_dict(orient="list")
            dtypes = {col: str(dtype) for col, dtype in df.dtypes.items()}
            return {
                "status": "success",
                "rows": int(df.shape[0]),
                "columns": list(df.columns),
                "dtypes": dtypes,
                "preview": preview,
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

    @staticmethod
    def _load_data(path: Path) -> pd.DataFrame:
        if path.suffix.lower() == ".csv":
            return pd.read_csv(path)
        return pd.read_excel(path)

    def validate_dataset(self, input_file_path: str, required_columns: list[str]) -> dict[str, Any]:
        try:
            file_path = resolve_workspace_path(self.root_dir, input_file_path, must_exist=True)
            df = self._load_data(file_path)
            missing = [col for col in required_columns if col not in df.columns]
            dtypes = {col: str(dtype) for col, dtype in df.dtypes.items()}
            return {
                "status": "success",
                "missing_columns": missing,
                "available_columns": list(df.columns),
                "dtypes": dtypes,
                "valid": len(missing) == 0,
            }
        except Exception as exc:
            return {"status": "error", "error": str(exc)}

    def get_tool(self) -> StructuredTool:
        return StructuredTool.from_function(
            func=self.validate_dataset,
            name="validate_dataset",
            description="Validate required columns in dataset.",
            args_schema=DatasetValidateInput,
        )

class CodePreprocessor:
    TARGET_FUNCTIONS = {
        "read_csv",
        "read_excel",
        "read_json",
        "read_parquet",
        "read_sql",
        "read_html",
        "read_xml",
        "read_feather",
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
    ".png": "image", ".jpg": "image", ".jpeg": "image", ".gif": "image",
    ".svg": "image", ".bmp": "image", ".webp": "image",
    ".csv": "data", ".xlsx": "data", ".xls": "data", ".json": "data",
    ".parquet": "data",
    ".pdf": "document", ".docx": "document", ".pptx": "document",
    ".txt": "document", ".md": "document",
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
            try:
                relative_path = str(resolved.relative_to(self.root_dir))
            except ValueError:
                relative_path = resolved.name
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
                "Use this for images, plots, CSV results, or any file the user needs."
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
                "image_path": str(image_path) if image_path else None,
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


class MiningCompositingTool:
    def __init__(self, root_dir: Path):
        self.root_dir = root_dir

    @staticmethod
    def _load_data(path: Path) -> pd.DataFrame:
        if path.suffix.lower() == ".csv":
            return pd.read_csv(path)
        return pd.read_excel(path)

    @staticmethod
    def _dentro_rango(val: float, rango: tuple[float, float]) -> bool:
        return rango[0] <= val < rango[1]

    def run_compositing(
        self,
        input_file_path: str,
        output_file_path: str,
        col_bhid: str,
        col_from: str,
        col_to: str,
        col_grade: str,
        cutoff_grade: float,
        waste_cutoff: float,
        max_waste_length: float,
        priority_ranges: list[list[float]],
        col_lithology: str | None = None,
        exclude_lithology: str | None = None,
    ) -> dict[str, Any]:
        try:
            input_path = resolve_workspace_path(self.root_dir, input_file_path, must_exist=True)
            output_path = resolve_workspace_path(self.root_dir, output_file_path, must_exist=False)
            ensure_directory(output_path.parent)

            df = self._load_data(input_path)

            internal_cols = {
                col_bhid: "BHID",
                col_from: "FROM",
                col_to: "TO",
                col_grade: "GRADE",
            }
            if col_lithology:
                internal_cols[col_lithology] = "LITO"

            for user_col in internal_cols.keys():
                if user_col not in df.columns:
                    return {"status": "error", "error": f"Column '{user_col}' not found in input."}

            work_df = df.rename(columns=internal_cols).copy()
            work_df["LENGTH"] = work_df["TO"] - work_df["FROM"]
            work_df["GRADE"] = pd.to_numeric(work_df["GRADE"], errors="coerce").fillna(0)

            ranges_tuples = [(r[0], r[1]) for r in priority_ranges]
            compositos_finales: list[dict[str, Any]] = []

            for sondaje_id, grupo in work_df.groupby("BHID"):
                grupo = grupo.sort_values("FROM").reset_index(drop=True)

                if col_lithology and exclude_lithology:
                    idx_excluded = grupo.index[grupo["LITO"].astype(str).str.strip() == exclude_lithology]
                    if len(idx_excluded) > 0:
                        grupo = grupo.loc[idx_excluded.max() + 1 :].reset_index(drop=True)

                if grupo.empty:
                    continue

                for i in range(len(grupo)):
                    fila = grupo.iloc[i]

                    if col_lithology and exclude_lithology:
                        if str(fila.get("LITO", "")).strip() == exclude_lithology:
                            continue

                    ley_actual = fila["GRADE"]
                    largo_actual = fila["LENGTH"]

                    if ley_actual < cutoff_grade:
                        continue

                    inicio = fila["FROM"]
                    fin = fila["TO"]
                    acumulado_metal = ley_actual * largo_actual
                    acumulado_largo = largo_actual

                    izq = i - 1
                    der = i + 1
                    puentes_temporales: list[tuple[float, float, float, float]] = []

                    while True:
                        candidatos: list[tuple[str, int, float, float, float, float]] = []

                        if izq >= 0:
                            f = grupo.iloc[izq]
                            valido = not (
                                col_lithology
                                and exclude_lithology
                                and str(f.get("LITO", "")).strip() == exclude_lithology
                            )
                            if valido:
                                candidatos.append(("izq", izq, f["GRADE"], f["LENGTH"], f["FROM"], f["TO"]))

                        if der < len(grupo):
                            f = grupo.iloc[der]
                            valido = not (
                                col_lithology
                                and exclude_lithology
                                and str(f.get("LITO", "")).strip() == exclude_lithology
                            )
                            if valido:
                                candidatos.append(("der", der, f["GRADE"], f["LENGTH"], f["FROM"], f["TO"]))

                        if not candidatos:
                            break

                        elegido: tuple[str, int, float, float, float, float] | None = None
                        for r in ranges_tuples:
                            filtrados = [c for c in candidatos if self._dentro_rango(c[2], r)]
                            if filtrados:
                                elegido = max(filtrados, key=lambda x: x[2])
                                break

                        if elegido is None:
                            break

                        lado, _, au_cand, largo_cand, desde_cand, hasta_cand = elegido

                        if au_cand < waste_cutoff:
                            puentes_temporales.append((au_cand * largo_cand, largo_cand, desde_cand, hasta_cand))
                            if sum(p[1] for p in puentes_temporales) > max_waste_length:
                                break
                        else:
                            metal_puente = sum(p[0] for p in puentes_temporales)
                            largo_puente = sum(p[1] for p in puentes_temporales)
                            nuevo_metal = acumulado_metal + metal_puente + (au_cand * largo_cand)
                            nuevo_largo = acumulado_largo + largo_puente + largo_cand
                            nueva_ley = nuevo_metal / nuevo_largo

                            if nueva_ley >= cutoff_grade:
                                acumulado_metal = nuevo_metal
                                acumulado_largo = nuevo_largo
                                min_start = min(inicio, desde_cand)
                                if puentes_temporales:
                                    min_start = min(min_start, min(p[2] for p in puentes_temporales))

                                max_end = max(fin, hasta_cand)
                                if puentes_temporales:
                                    max_end = max(max_end, max(p[3] for p in puentes_temporales))

                                inicio = min_start
                                fin = max_end
                                puentes_temporales = []
                            else:
                                break

                        if lado == "izq":
                            izq -= 1
                        else:
                            der += 1

                    compositos_finales.append(
                        {
                            "BHID": sondaje_id,
                            "FROM": inicio,
                            "TO": fin,
                            "LENGTH": acumulado_largo,
                            "GRADE": round(acumulado_metal / acumulado_largo, 4),
                        }
                    )

            if not compositos_finales:
                return {
                    "status": "warning",
                    "message": "No composites generated with current parameters.",
                    "output_file": None,
                }

            df_comp = pd.DataFrame(compositos_finales).sort_values(by=["BHID", "FROM"])
            resultados_limpios = []
            for _, corte in df_comp.iterrows():
                if not resultados_limpios:
                    resultados_limpios.append(corte)
                    continue
                ultimo = resultados_limpios[-1]

                if corte["BHID"] == ultimo["BHID"]:
                    if corte["FROM"] < ultimo["TO"]:
                        largo_corte = corte["TO"] - corte["FROM"]
                        largo_ultimo = ultimo["TO"] - ultimo["FROM"]
                        if largo_corte > largo_ultimo:
                            resultados_limpios[-1] = corte
                    else:
                        resultados_limpios.append(corte)
                else:
                    resultados_limpios.append(corte)

            df_final = pd.DataFrame(resultados_limpios).rename(
                columns={
                    "BHID": col_bhid,
                    "FROM": "COMP_FROM",
                    "TO": "COMP_TO",
                    "LENGTH": "COMP_LENGTH",
                    "GRADE": f"COMP_{col_grade}",
                }
            )

            df_final.to_csv(output_path, index=False)
            try:
                output_ref = str(output_path.relative_to(self.root_dir))
            except ValueError:
                output_ref = str(output_path)

            return {
                "status": "success",
                "message": f"Compositing completed. {len(df_final)} intervals generated.",
                "output_file": output_ref,
                "preview": df_final.head(5).to_dict(),
            }
        except Exception as exc:
            return {"status": "error", "error": str(exc)}

    def get_tool(self) -> StructuredTool:
        return StructuredTool.from_function(
            func=self.run_compositing,
            name="run_mining_compositing",
            description="Run mining compositing and output CSV path.",
            args_schema=CompositingInput,
        )
class NearestNeighborAssignmentTool:
    """Tool para asignar atributos del origen al destino usando KDTree (vecino más cercano)."""

    def __init__(self, root_dir: Path):
        self.root_dir = root_dir

    @staticmethod
    def _load_data(path: Path) -> pd.DataFrame:
        if path.suffix.lower() == ".csv":
            return pd.read_csv(path, encoding="utf-8")
        return pd.read_excel(path)

    def run_nearest_neighbor(
        self,
        origin_file_path: str,
        destination_file_path: str,
        output_file_path: str,
        radius: float,
        col_x: str = "X",
        col_y: str = "Y",
        col_z: str = "Z",
    ) -> dict[str, Any]:
        """
        Asigna atributos del archivo origen al archivo destino basándose en el
        vecino más cercano (KDTree) dentro de un radio especificado.

        Args:
            origin_file_path: Ruta al CSV/Excel de origen (puntos con atributos a transferir).
            destination_file_path: Ruta al CSV/Excel de destino (puntos que recibirán atributos).
            output_file_path: Ruta del CSV de salida con los atributos asignados.
            radius: Radio máximo de búsqueda para la asignación.
            col_x: Nombre de la columna X en ambos archivos.
            col_y: Nombre de la columna Y en ambos archivos.
            col_z: Nombre de la columna Z en ambos archivos.
        """
        try:
            origin_path = resolve_workspace_path(self.root_dir, origin_file_path, must_exist=True)
            dest_path = resolve_workspace_path(self.root_dir, destination_file_path, must_exist=True)
            output_path = resolve_workspace_path(self.root_dir, output_file_path, must_exist=False)
            ensure_directory(output_path.parent)

            # --- Carga y normalización ---
            df_origin = self._load_data(origin_path)
            df_origin.columns = [c.upper() for c in df_origin.columns]

            df_dest = self._load_data(dest_path)
            df_dest.columns = [c.upper() for c in df_dest.columns]

            coord_cols = [col_x.upper(), col_y.upper(), col_z.upper()]

            # --- Validación de columnas requeridas ---
            for col in coord_cols:
                if col not in df_origin.columns:
                    return {"status": "error", "error": f"Column '{col}' not found in origin file."}
                if col not in df_dest.columns:
                    return {"status": "error", "error": f"Column '{col}' not found in destination file."}

            # --- Forzar numérico y filtrar filas válidas ---
            for col in coord_cols:
                df_origin[col] = pd.to_numeric(df_origin[col], errors="coerce")
                df_dest[col] = pd.to_numeric(df_dest[col], errors="coerce")

            origin_valid_mask = df_origin[coord_cols].notna().all(axis=1)
            dest_valid_mask = df_dest[coord_cols].notna().all(axis=1)

            df_origin_valid = df_origin.loc[origin_valid_mask].reset_index(drop=True)
            df_dest_out = df_dest.copy()

            if len(df_origin_valid) == 0:
                df_dest_out.to_csv(output_path, index=False)
                return {
                    "status": "warning",
                    "message": "Origin file has no valid rows with numeric X, Y, Z. Output generated without assignments.",
                    "output_file": str(output_path.relative_to(self.root_dir)),
                }

            if int(dest_valid_mask.sum()) == 0:
                df_dest_out.to_csv(output_path, index=False)
                return {
                    "status": "warning",
                    "message": "Destination file has no valid rows with numeric X, Y, Z. Output generated without assignments.",
                    "output_file": str(output_path.relative_to(self.root_dir)),
                }

            # --- KDTree ---
            origin_coords = df_origin_valid[coord_cols].values
            dest_coords = df_dest_out.loc[dest_valid_mask, coord_cols].values
            tree = KDTree(origin_coords, leaf_size=2)

            # --- Preparar columnas de atributos a transferir ---
            attribute_cols = [c for c in df_origin_valid.columns if c not in coord_cols]

            col_mapping: list[tuple[str, str]] = []  # (origen_col, destino_col)
            for col in attribute_cols:
                col_out = col
                if col in df_dest_out.columns:
                    col_out = f"{col}_2"
                if pd.api.types.is_numeric_dtype(df_origin_valid[col]):
                    df_dest_out[col_out] = np.nan
                else:
                    df_dest_out[col_out] = pd.Series(dtype="object")
                col_mapping.append((col, col_out))

            df_dest_out["YP_DISTANCIA"] = np.nan

            # --- Consulta KDTree: vecino más cercano ---
            distances, indices = tree.query(dest_coords, k=1, return_distance=True)
            distances = distances.flatten()
            indices = indices.flatten()

            valid_dest_indices = df_dest_out.index[dest_valid_mask].to_numpy()

            match_count = 0
            for i, dest_idx in enumerate(valid_dest_indices):
                dist = distances[i]
                origin_idx = indices[i]

                if dist <= radius:
                    for col_o, col_d in col_mapping:
                        df_dest_out.loc[dest_idx, col_d] = df_origin_valid.loc[origin_idx, col_o]
                    df_dest_out.loc[dest_idx, "YP_DISTANCIA"] = dist
                    match_count += 1

            # --- Exportar ---
            df_dest_out.to_csv(output_path, index=False)

            try:
                output_ref = str(output_path.relative_to(self.root_dir))
            except ValueError:
                output_ref = str(output_path)

            total_dest_valid = int(dest_valid_mask.sum())
            unmatched = total_dest_valid - match_count

            return {
                "status": "success",
                "message": (
                    f"Nearest neighbor assignment completed. "
                    f"{match_count} matches found within radius {radius}. "
                    f"{unmatched} destination points had no neighbor within radius. "
                    f"{len(attribute_cols)} attribute(s) transferred from origin."
                ),
                "output_file": output_ref,
                "summary": {
                    "origin_valid_points": len(df_origin_valid),
                    "destination_valid_points": total_dest_valid,
                    "matches_within_radius": match_count,
                    "unmatched_points": unmatched,
                    "attributes_transferred": attribute_cols,
                    "radius": radius,
                },
                "preview": df_dest_out.head(5).to_dict(),
            }

        except Exception as exc:
            return {"status": "error", "error": str(exc)}

    def get_tool(self) -> StructuredTool:
        return StructuredTool.from_function(
            func=self.run_nearest_neighbor,
            name="run_nearest_neighbor_assignment",
            description=(
                "Assign attributes from an origin point dataset to the nearest neighbor "
                "in a destination dataset using a KDTree spatial search within a given radius. "
                "Requires origin CSV, destination CSV, output path, and search radius."
            ),
            args_schema=NearestNeighborInput,
        )

def build_tool_registry(
    root_dir: Path,
    *,
    user_id: str | None = None,
    url_signer: Callable[[str], str] | None = None,
) -> dict[str, Any]:
    preview_tool = DatasetPreviewTool(root_dir=root_dir).get_tool()
    validate_tool = DatasetValidateTool(root_dir=root_dir).get_tool()
    plotting_tool = PlottingTool(root_dir=root_dir).get_tool()
    compositing_tool = MiningCompositingTool(root_dir=root_dir).get_tool()
    send_files_tool = SendFilesToUserTool(
        root_dir=root_dir,
        user_id=user_id,
        url_signer=url_signer,
    ).get_tool()
    nearest_neighbor_tool = NearestNeighborAssignmentTool(root_dir=root_dir).get_tool()

    return {
        "preview_dataset": preview_tool,
        "validate_dataset": validate_tool,
        "generate_plot": plotting_tool,
        "run_mining_compositing": compositing_tool,
        "send_files_to_user": send_files_tool,
        "run_nearest_neighbor_assignment": nearest_neighbor_tool,
    }

