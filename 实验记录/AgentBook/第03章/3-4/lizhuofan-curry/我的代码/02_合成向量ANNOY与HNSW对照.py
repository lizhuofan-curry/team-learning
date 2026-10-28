"""固定合成向量的精确/ANNOY/HNSW对照；不加载模型，不联网。"""

import argparse
import ast
from datetime import datetime, timezone
import hashlib
import importlib.metadata
import importlib.util
import json
from pathlib import Path
import platform
import sys
import time
from typing import List

import numpy as np


ROOT = Path(__file__).resolve().parents[1]
UPSTREAM = ROOT / "官方资料/upstream"
MANIFEST = ROOT / "官方资料/manifest.json"
COMMIT = "dbc046eb896ac4e39aa19c7774c8bf49583b89a6"
PACKAGES = {"annoy": "1.17.3", "hnswlib": "0.8.0", "colorlog": "6.8.0"}
PROTOCOL = {"base_count": 3000, "query_count": 100, "dimension": 128, "seed": 42,
            "top_k": 10, "dtype": "float32", "annoy_trees": 10,
            "hnsw_M": 16, "hnsw_ef_construction": 100, "hnsw_ef_search": [20, 200],
            "hnsw_threads": 1, "annoy_build_threads": "upstream default (-1)",
            "index_random_seeds": "library defaults, not overridden",
            "timing": "one sequential pass, per-query wall time including official Python wrapper",
            "exact_timing": "per-query normalized dot product and full argsort via official dense_rank"}


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def dump(path, value):
    path = Path(path)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n",
                         encoding="utf-8")
    temporary.replace(path)


def verify_sources():
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    if manifest["commit"] != COMMIT:
        raise ValueError("官方提交发生变化")
    for item in manifest["files"]:
        source = (UPSTREAM / item["path"]).resolve()
        if not source.is_relative_to(UPSTREAM.resolve()) or sha(source) != item["sha256"]:
            raise ValueError(f"官方文件校验失败：{item['path']}")
    return manifest


def dependencies():
    versions, problems = {}, []
    for name, expected in PACKAGES.items():
        try:
            versions[name] = importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError:
            versions[name] = None
        if versions[name] != expected:
            problems.append(f"{name}：需要{expected}，当前{versions[name] or '未安装'}")
    return versions, problems


def load_official():
    directory = UPSTREAM / "chapter3/dense-embedding"
    source = directory / "cli.py"
    nodes = [node for node in ast.parse(source.read_text(encoding="utf-8")).body
             if isinstance(node, ast.FunctionDef) and node.name == "dense_rank"]
    if len(nodes) != 1:
        raise ValueError("官方dense_rank定义异常")
    namespace = {"np": np, "List": List}
    exec(compile(ast.fix_missing_locations(ast.Module(body=nodes, type_ignores=[])), str(source), "exec"), namespace)

    # 官方indexing以通用名logger导入；仅在加载期间绑定，随后恢复原模块。
    old_logger = sys.modules.get("logger")
    try:
        spec = importlib.util.spec_from_file_location("logger", directory / "logger.py")
        logger = importlib.util.module_from_spec(spec)
        sys.modules["logger"] = logger
        spec.loader.exec_module(logger)
        spec = importlib.util.spec_from_file_location("chapter3_pinned_indexes", directory / "indexing.py")
        indexes = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(indexes)
    finally:
        if old_logger is None:
            sys.modules.pop("logger", None)
        else:
            sys.modules["logger"] = old_logger
    return namespace["dense_rank"], indexes


def make_vectors(protocol):
    rng = np.random.default_rng(protocol["seed"])
    base = rng.standard_normal((protocol["base_count"], protocol["dimension"])).astype("float32")
    queries = rng.standard_normal((protocol["query_count"], protocol["dimension"])).astype("float32")
    for matrix in (base, queries):
        matrix /= np.linalg.norm(matrix, axis=1, keepdims=True)
        if not np.isfinite(matrix).all() or not np.allclose(np.linalg.norm(matrix, axis=1), 1, atol=2e-6):
            raise ValueError("归一化失败")
    return base, queries


def recall(ids, truth, k):
    if len(ids) != k or len(set(ids)) != k or len(truth) != k or len(set(truth)) != k:
        raise ValueError("检索结果数量不足或存在重复ID")
    return len(set(ids) & set(truth)) / k


def timed_queries(search, queries, truths, k):
    rows = []
    for i, query in enumerate(queries):
        start = time.perf_counter()
        ids, distances = search(query, k)
        elapsed = (time.perf_counter() - start) * 1000
        if any(not value.startswith("v") for value in ids) or not np.isfinite(distances).all():
            raise ValueError("检索返回无效ID或距离")
        rows.append({"query": i, "ids": ids, "distances": list(map(float, distances)),
                     "recall_at_k": recall(ids, truths[i], k), "query_ms": elapsed})
    times = [row["query_ms"] for row in rows]
    return {"recall_at_k": float(np.mean([row["recall_at_k"] for row in rows])),
            "mean_query_ms": float(np.mean(times)), "p95_query_ms": float(np.percentile(times, 95)),
            "queries": rows}


def measure(base, queries, ranker, indexes, protocol, checkpoint):
    k = protocol["top_k"]
    start = time.perf_counter()
    truths = [[f"v{int(i)}" for i in ranker(query, base)[0][:k]] for query in queries]
    truth_seconds = time.perf_counter() - start
    results = {}

    def exact_search(query, top_k):
        order, sims = ranker(query, base)
        chosen = order[:top_k]
        return [f"v{int(i)}" for i in chosen], [1 - float(sims[i]) for i in chosen]

    exact = timed_queries(exact_search, queries, truths, k)
    exact.update(build_seconds=0, distance_definition="1 - cosine", health=None)
    results["exact"] = exact
    checkpoint(truths, truth_seconds, results)

    def populate(index):
        for i, vector in enumerate(base):
            index.add_item(f"v{i}", vector)

    def health(index):
        checks = [f"v{i}" in index.search(base[i], k)[0] for i in range(min(5, len(base)))]
        return {"self_queries": len(checks), "all_found": all(checks), "checks": checks}

    start = time.perf_counter()
    annoy = indexes.AnnoyIndex(protocol["dimension"], n_trees=protocol["annoy_trees"], metric="angular")
    populate(annoy)
    annoy.rebuild_index()
    build_seconds = time.perf_counter() - start
    sanity = health(annoy)
    result = timed_queries(annoy.search, queries, truths, k)
    result.update(build_seconds=build_seconds, health=sanity, distance_definition="sqrt(2 - 2*cosine)",
                  search_k="library default: trees * top_k")
    results["annoy"] = result
    checkpoint(truths, truth_seconds, results)

    start = time.perf_counter()
    hnsw = indexes.HNSWIndex(protocol["dimension"], max_elements=len(base),
                             M=protocol["hnsw_M"], ef_construction=protocol["hnsw_ef_construction"],
                             ef_search=protocol["hnsw_ef_search"][0], space="cosine")
    hnsw.index.set_num_threads(protocol["hnsw_threads"])
    populate(hnsw)
    build_seconds = time.perf_counter() - start
    for ef in protocol["hnsw_ef_search"]:
        # 共享同一张图，仅扩大检索候选范围，不重建图或重抽数据。
        hnsw.ef_search = ef
        hnsw.index.set_ef(ef)
        sanity = health(hnsw)
        result = timed_queries(hnsw.search, queries, truths, k)
        result.update(build_seconds=build_seconds, build_shared=True, health=sanity,
                      ef_search=ef, distance_definition="1 - cosine")
        results[f"hnsw_ef{ef}"] = result
        checkpoint(truths, truth_seconds, results)
    return results


def main(argv=None):
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--preview", action="store_true", help="只核验源文件和依赖版本")
    parser.add_argument("--check-only", action="store_true", help="额外检查原生库导入，不开展评估")
    args = parser.parse_args(argv)
    verify_sources()
    versions, problems = dependencies()
    print("3-4合成向量：3000×128维底库、100次查询、Top-10、数据种子42。")
    print("对照：精确检索、ANNOY 10棵树、同一张HNSW图ef=20/200。")
    print("模型请求0，网络请求0；无模型下载、自动安装或自动重试。")
    if problems:
        print("DEPENDENCIES_NOT_READY：", "；".join(problems))
        print("先按本实验README安装chapter3-index依赖；不创建正式运行目录。")
        return 2
    if args.preview:
        print("ANN_PREVIEW_ONLY：材料与版本核验通过；未运行评估。")
        return 0
    ranker, indexes = load_official()
    if args.check_only:
        print("ANN_IMPORT_CHECK_ONLY：官方索引与原生库可导入；未运行评估。")
        return 0
    directory = ROOT / "运行结果" / ("synthetic_ann_" + datetime.now().strftime("%Y%m%d_%H%M%S_%f"))
    directory.mkdir(parents=True, exist_ok=False)
    record = {"stage": "chapter3_synthetic_ann", "status": "running",
              "created_at": datetime.now(timezone.utc).isoformat(), "upstream_commit": COMMIT,
              "manifest_sha256": sha(MANIFEST), "script_sha256": sha(__file__),
              "protocol": PROTOCOL, "packages": {**versions, "numpy": np.__version__},
              "platform": platform.platform(), "python": sys.version,
              "model_requests": 0, "network_requests": 0,
              "scope": "单次合成向量索引对照，不是文本语义评测或普遍速度排名"}
    dump(directory / "record.json", record)
    try:
        base, queries = make_vectors(PROTOCOL)
        record["arrays"] = {}
        for name, matrix in (("base", base), ("queries", queries)):
            path = directory / (name + ".npy")
            np.save(path, matrix, allow_pickle=False)
            record["arrays"][name] = {"file": path.name, "sha256": sha(path), "shape": list(matrix.shape)}

        def checkpoint(truths, seconds, results):
            record.update(exact_top_ids=truths, reference_seconds=seconds, results=results)
            dump(directory / "record.json", record)

        results = measure(base, queries, ranker, indexes, PROTOCOL, checkpoint)
        healthy = all(item["health"] is None or item["health"]["all_found"] for item in results.values())
        record["status"] = "synthetic_ann_saved" if healthy else "health_check_failed"
        dump(directory / "record.json", record)
        print("方法                 Recall@10    平均查询ms    建索引s")
        for name, item in results.items():
            print(f'{name:<20} {item["recall_at_k"]:>9.3%} {item["mean_query_ms"]:>12.4f} {item["build_seconds"]:>10.4f}')
        print("HNSW两行共用一次建图，建索引时间不累加。查询时间仅本次测量，线程配置有差别。")
        print("SYNTHETIC_ANN_SAVED" if healthy else "ANN_HEALTH_CHECK_FAILED")
        print("记录路径：", directory / "record.json")
        return 0 if healthy else 1
    except Exception as exc:
        record.update(status="incomplete", error={"type": type(exc).__name__, "message": str(exc)})
        dump(directory / "record.json", record)
        print("本次未完成：", record["error"])
        print("记录路径：", directory / "record.json")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
