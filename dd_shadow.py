#!/usr/bin/env python3
"""
DD-Shadow : prototype v0.2
Crée et compare des copies fantômes descriptives de runs (sans jugement, sans correction).

Sorties:
- Un "shadow" immuable par snapshot (copie brute + copie canonique + profil descriptif + manifest)
- Un diff JSON descriptif entre deux shadows (apparitions, disparitions, modifications)
"""

from __future__ import annotations

import argparse
import csv
import datetime as _dt
import hashlib
import json
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

import pandas as pd


TOOL_NAME = "dd_shadow"
TOOL_VERSION = "0.2"


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def utc_now_iso() -> str:
    return _dt.datetime.utcnow().replace(microsecond=0).isoformat() + "Z"


def ensure_dir(p: Path) -> None:
    p.mkdir(parents=True, exist_ok=True)


def write_json(path: Path, obj: Any) -> None:
    # JSON stable pour audit (tri des clés, indentation fixe)
    data = json.dumps(obj, ensure_ascii=False, indent=2, sort_keys=True).encode("utf-8")
    path.write_bytes(data)


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def is_numeric_dtype(dtype: Any) -> bool:
    return pd.api.types.is_numeric_dtype(dtype)


def is_datetime_dtype(dtype: Any) -> bool:
    return pd.api.types.is_datetime64_any_dtype(dtype)


def is_bool_dtype(dtype: Any) -> bool:
    return pd.api.types.is_bool_dtype(dtype)


def column_profile(s: pd.Series) -> Dict[str, Any]:
    # Profil strictement descriptif, pas d'inférence.
    prof: Dict[str, Any] = {
        "dtype": str(s.dtype),
        "rows": int(s.shape[0]),
        "non_null": int(s.notna().sum()),
        "null": int(s.isna().sum()),
    }

    # nunique peut être coûteux, mais utile en v0.2.
    # On limite l'empreinte pour les colonnes très longues.
    try:
        prof["distinct"] = int(s.nunique(dropna=True))
    except Exception:
        prof["distinct"] = None

    if is_numeric_dtype(s.dtype):
        # describe() renvoie aussi count/min/max/mean/std/quantiles
        desc = s.astype("float64", errors="ignore").describe(percentiles=[0.25, 0.5, 0.75])
        # Certaines colonnes numériques peuvent être entièrement NA.
        def _safe_get(k: str):
            v = desc.get(k, None)
            try:
                if pd.isna(v):
                    return None
            except Exception:
                pass
            return None if v is None else float(v)

        prof.update({
            "min": _safe_get("min"),
            "q25": _safe_get("25%"),
            "median": _safe_get("50%"),
            "q75": _safe_get("75%"),
            "max": _safe_get("max"),
            "mean": _safe_get("mean"),
            "std": _safe_get("std"),
        })
    elif is_datetime_dtype(s.dtype):
        # pour datetime, on reste descriptif
        try:
            prof["min"] = None if s.dropna().empty else str(s.dropna().min())
            prof["max"] = None if s.dropna().empty else str(s.dropna().max())
        except Exception:
            prof["min"] = None
            prof["max"] = None
    elif is_bool_dtype(s.dtype):
        try:
            prof["true"] = int((s == True).sum())  # noqa: E712
            prof["false"] = int((s == False).sum())  # noqa: E712
        except Exception:
            prof["true"] = None
            prof["false"] = None
    else:
        # texte / catégorie : top-3 valeurs (descriptif), limité
        try:
            vc = s.astype("string").value_counts(dropna=True).head(3)
            prof["top_values"] = [{"value": str(k), "count": int(v)} for k, v in vc.items()]
        except Exception:
            prof["top_values"] = None

    return prof


def canonical_csv_bytes(df: pd.DataFrame) -> bytes:
    # Canonicalisation légère: format float stable, séparateur ',', \n, pas d'index.
    # Objectif: hash sémantique plus robuste que le hash brut du fichier source.
    text = df.to_csv(
        index=False,
        lineterminator="\n",
        quoting=csv.QUOTE_MINIMAL,
        float_format="%.17g",
    )
    return text.encode("utf-8")


def build_table_profile(df: pd.DataFrame) -> Dict[str, Any]:
    dtypes = {c: str(df[c].dtype) for c in df.columns}
    cols = list(df.columns)
    prof = {
        "shape": [int(df.shape[0]), int(df.shape[1])],
        "columns": cols,
        "dtypes": dtypes,
        "column_profiles": {c: column_profile(df[c]) for c in cols},
    }
    return prof


def resolve_shadow_ref(p: Path) -> Tuple[Path, Dict[str, Any]]:
    """
    Accepte:
    - un dossier de shadow contenant manifest.json
    - un manifest.json
    """
    p = p.resolve()
    if p.is_dir():
        manifest = p / "manifest.json"
        if not manifest.exists():
            raise FileNotFoundError(f"manifest.json introuvable dans {p}")
        return p, read_json(manifest)
    if p.is_file() and p.name == "manifest.json":
        return p.parent, read_json(p)
    raise ValueError(f"Référence shadow invalide: {p}")


def diff_profiles(prev: Dict[str, Any], curr: Dict[str, Any]) -> Dict[str, Any]:
    p_prof = prev["table_profile"]
    c_prof = curr["table_profile"]

    p_cols = p_prof["columns"]
    c_cols = c_prof["columns"]
    p_set = set(p_cols)
    c_set = set(c_cols)

    added_cols = [c for c in c_cols if c not in p_set]
    removed_cols = [c for c in p_cols if c not in c_set]

    # Changements de dtypes
    common_cols = [c for c in c_cols if c in p_set]
    dtype_changes = {}
    for col in common_cols:
        p_dt = p_prof["dtypes"].get(col)
        c_dt = c_prof["dtypes"].get(col)
        if p_dt != c_dt:
            dtype_changes[col] = {"before": p_dt, "after": c_dt}

    # Changements de profil de colonnes
    col_changes: Dict[str, Any] = {}
    for col in common_cols:
        p_cp = p_prof["column_profiles"].get(col, {})
        c_cp = c_prof["column_profiles"].get(col, {})
        if p_cp != c_cp:
            # Deltas numériques si présents
            deltas = {}
            for k in ("mean", "std", "min", "max", "non_null", "null", "distinct"):
                if k in p_cp and k in c_cp and p_cp[k] is not None and c_cp[k] is not None:
                    try:
                        deltas[k + "_delta"] = c_cp[k] - p_cp[k]
                    except Exception:
                        pass
            col_changes[col] = {"before": p_cp, "after": c_cp, "deltas": deltas}

    return {
        "shape_change": {"before": p_prof["shape"], "after": c_prof["shape"]},
        "row_count_delta": int(c_prof["shape"][0]) - int(p_prof["shape"][0]),
        "added_columns": added_cols,
        "removed_columns": removed_cols,
        "dtype_changes": dtype_changes,
        "column_changes": col_changes,
        "hashes": {
            "raw_before": prev["raw_sha256"],
            "raw_after": curr["raw_sha256"],
            "canonical_before": prev["canonical_sha256"],
            "canonical_after": curr["canonical_sha256"],
            "profile_before": prev["profile_sha256"],
            "profile_after": curr["profile_sha256"],
        },
    }


def snapshot(
    csv_path: Path,
    output_dir: Path,
    previous_shadow: Optional[Path] = None,
    numeric_only: bool = False,
    encoding: str = "utf-8",
) -> Dict[str, Any]:
    ensure_dir(output_dir)
    shadows_dir = output_dir / "shadows"
    ensure_dir(shadows_dir)

    raw_bytes = csv_path.read_bytes()
    raw_sha = sha256_bytes(raw_bytes)

    shadow_id = f"{utc_now_iso().replace(':', '').replace('-', '')}_{raw_sha[:12]}"
    shadow_dir = shadows_dir / shadow_id
    ensure_dir(shadow_dir)

    raw_copy_path = shadow_dir / "shadow_raw.csv"
    raw_copy_path.write_bytes(raw_bytes)

    # Lecture pandas pour profil et hash canonique
    # Note: dtype inféré par pandas, on enregistre la version et les paramètres.
    df = pd.read_csv(csv_path, encoding=encoding, low_memory=False)
    if numeric_only:
        df = df.select_dtypes(include=["number"])

    canonical_path = shadow_dir / "shadow_canonical.csv"
    canon_bytes = canonical_csv_bytes(df)
    canonical_path.write_bytes(canon_bytes)
    canonical_sha = sha256_bytes(canon_bytes)

    table_profile = build_table_profile(df)
    profile_path = shadow_dir / "shadow_profile.json"
    write_json(profile_path, table_profile)
    profile_sha = sha256_file(profile_path)

    manifest = {
        "tool": {"name": TOOL_NAME, "version": TOOL_VERSION},
        "created_at": utc_now_iso(),
        "source": {"path": str(csv_path.resolve()), "size_bytes": int(len(raw_bytes))},
        "pandas": {"version": getattr(pd, "__version__", None)},
        "options": {"numeric_only": bool(numeric_only), "encoding": encoding},
        "shadow_id": shadow_id,
        "raw_sha256": raw_sha,
        "canonical_sha256": canonical_sha,
        "profile_sha256": profile_sha,
        "files": [
            {
                "path": "shadow_raw.csv",
                "sha256": sha256_file(raw_copy_path),
                "size_bytes": raw_copy_path.stat().st_size,
            },
            {
                "path": "shadow_canonical.csv",
                "sha256": sha256_file(canonical_path),
                "size_bytes": canonical_path.stat().st_size,
            },
            {
                "path": "shadow_profile.json",
                "sha256": profile_sha,
                "size_bytes": profile_path.stat().st_size,
            },
        ],
    }

    # Diff optionnel
    diff_obj = None
    if previous_shadow is not None:
        prev_dir, prev_manifest = resolve_shadow_ref(previous_shadow)
        prev_profile_path = prev_dir / "shadow_profile.json"
        prev_raw = prev_manifest.get("raw_sha256")
        prev_canon = prev_manifest.get("canonical_sha256")
        prev_prof_sha = prev_manifest.get("profile_sha256")

        # Si les champs manquent (ancien format), on tente de recalculer descriptivement
        if not prev_profile_path.exists():
            raise FileNotFoundError(f"shadow_profile.json introuvable dans {prev_dir}")
        prev_table_profile = read_json(prev_profile_path)

        prev_obj = {
            "raw_sha256": prev_raw or sha256_file(prev_dir / "shadow_raw.csv"),
            "canonical_sha256": prev_canon or sha256_file(prev_dir / "shadow_canonical.csv"),
            "profile_sha256": prev_prof_sha or sha256_file(prev_profile_path),
            "table_profile": prev_table_profile,
        }
        curr_obj = {
            "raw_sha256": raw_sha,
            "canonical_sha256": canonical_sha,
            "profile_sha256": profile_sha,
            "table_profile": table_profile,
        }

        diff_obj = {
            "tool": {"name": TOOL_NAME, "version": TOOL_VERSION},
            "created_at": utc_now_iso(),
            "before": {"shadow_id": prev_manifest.get("shadow_id"), "path": str(prev_dir)},
            "after": {"shadow_id": shadow_id, "path": str(shadow_dir)},
            "diff": diff_profiles(prev_obj, curr_obj),
        }

        diff_path = shadow_dir / "shadow_diff.json"
        write_json(diff_path, diff_obj)
        manifest["files"].append(
            {
                "path": "shadow_diff.json",
                "sha256": sha256_file(diff_path),
                "size_bytes": diff_path.stat().st_size,
            }
        )

    manifest_path = shadow_dir / "manifest.json"
    write_json(manifest_path, manifest)

    result = {
        "shadow_dir": str(shadow_dir),
        "manifest": manifest,
    }
    if diff_obj is not None:
        result["diff"] = diff_obj

    return result


def compare(shadow_a: Path, shadow_b: Path, output_path: Optional[Path] = None) -> Dict[str, Any]:
    a_dir, a_manifest = resolve_shadow_ref(shadow_a)
    b_dir, b_manifest = resolve_shadow_ref(shadow_b)

    a_profile = read_json(a_dir / "shadow_profile.json")
    b_profile = read_json(b_dir / "shadow_profile.json")

    a_obj = {
        "raw_sha256": a_manifest.get("raw_sha256") or sha256_file(a_dir / "shadow_raw.csv"),
        "canonical_sha256": (
            a_manifest.get("canonical_sha256")
            or sha256_file(a_dir / "shadow_canonical.csv")
        ),
        "profile_sha256": (
            a_manifest.get("profile_sha256")
            or sha256_file(a_dir / "shadow_profile.json")
        ),
        "table_profile": a_profile,
    }
    b_obj = {
        "raw_sha256": b_manifest.get("raw_sha256") or sha256_file(b_dir / "shadow_raw.csv"),
        "canonical_sha256": (
            b_manifest.get("canonical_sha256")
            or sha256_file(b_dir / "shadow_canonical.csv")
        ),
        "profile_sha256": (
            b_manifest.get("profile_sha256")
            or sha256_file(b_dir / "shadow_profile.json")
        ),
        "table_profile": b_profile,
    }

    diff_obj = {
        "tool": {"name": TOOL_NAME, "version": TOOL_VERSION},
        "created_at": utc_now_iso(),
        "before": {"shadow_id": a_manifest.get("shadow_id"), "path": str(a_dir)},
        "after": {"shadow_id": b_manifest.get("shadow_id"), "path": str(b_dir)},
        "diff": diff_profiles(a_obj, b_obj),
    }

    if output_path is not None:
        ensure_dir(output_path.parent)
        write_json(output_path, diff_obj)

    return diff_obj


def build_arg_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="DD-Shadow : double fantôme descriptif")
    sub = p.add_subparsers(dest="cmd")

    # snapshot
    ps = sub.add_parser("snapshot", help="Créer un shadow immuable à partir d'un CSV")
    ps.add_argument("csv_path", type=str, help="CSV à observer")
    ps.add_argument(
        "--previous-shadow",
        type=str,
        default=None,
        help="Dossier shadow ou manifest.json précédent (optionnel)",
    )
    ps.add_argument("--output-dir", type=str, default="dd_shadow_output", help="Dossier de sortie")
    ps.add_argument(
        "--numeric-only",
        action="store_true",
        help="Limiter le profil aux colonnes numériques",
    )
    ps.add_argument("--encoding", type=str, default="utf-8", help="Encodage du CSV")

    # compare
    pc = sub.add_parser("compare", help="Comparer deux shadows existants")
    pc.add_argument("shadow_a", type=str, help="Dossier shadow ou manifest.json A")
    pc.add_argument("shadow_b", type=str, help="Dossier shadow ou manifest.json B")
    pc.add_argument("--out", type=str, default=None, help="Chemin de sortie JSON (optionnel)")

    # compat: si l'utilisateur ne met pas de sous-commande, on traite comme snapshot
    p.add_argument("--csv-path", type=str, default=None, help=argparse.SUPPRESS)

    return p


def main() -> None:
    parser = build_arg_parser()
    args = parser.parse_args()

    if args.cmd is None:
        # Compat v0.1: python dd_shadow.py data.csv --previous_shadow ... --output_dir ...
        # On re-mappe vers snapshot
        # On suppose que le 1er argument était un CSV (argparse a déjà consommé).
        parser.print_help()
        raise SystemExit(2)

    if args.cmd == "snapshot":
        csv_path = Path(args.csv_path)
        prev = Path(args.previous_shadow) if args.previous_shadow else None
        out_dir = Path(args.output_dir)

        res = snapshot(
            csv_path=csv_path,
            output_dir=out_dir,
            previous_shadow=prev,
            numeric_only=bool(args.numeric_only),
            encoding=str(args.encoding),
        )
        # résumé minimal en stdout
        print(json.dumps({
            "shadow_dir": res["shadow_dir"],
            "shadow_id": res["manifest"]["shadow_id"],
            "raw_sha256": res["manifest"]["raw_sha256"],
            "canonical_sha256": res["manifest"]["canonical_sha256"],
            "profile_sha256": res["manifest"]["profile_sha256"],
            "has_diff": "diff" in res,
        }, indent=2, ensure_ascii=False))

    elif args.cmd == "compare":
        out = Path(args.out) if args.out else None
        diff_obj = compare(Path(args.shadow_a), Path(args.shadow_b), output_path=out)
        print(json.dumps(diff_obj, indent=2, ensure_ascii=False))

    else:
        raise SystemExit(f"Commande inconnue: {args.cmd}")


if __name__ == "__main__":
    main()
