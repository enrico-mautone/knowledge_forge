#!/usr/bin/env python3
import argparse
import json
import os
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple

import networkx as nx
from tqdm import tqdm
from tree_sitter import Node, Parser
from tree_sitter_language_pack import get_language

EXCLUDED_DIRS = {"venv", ".git", "__pycache__", "node_modules"}
PY_EXTENSIONS = {".py"}
ENTITY_HINTS = {"user", "order", "payment", "invoice", "customer", "product", "cart", "account"}


@dataclass
class FunctionInfo:
    name: str
    qualified_name: str
    module: str
    params: List[Dict[str, Optional[str]]] = field(default_factory=list)
    return_type: Optional[str] = None
    docstring: str = ""
    calls: List[str] = field(default_factory=list)
    complexity: int = 1
    nesting: int = 0


@dataclass
class ClassInfo:
    name: str
    module: str
    methods: List[FunctionInfo] = field(default_factory=list)


@dataclass
class ModuleInfo:
    name: str
    path: str
    imports: List[Dict[str, str]] = field(default_factory=list)
    functions: List[FunctionInfo] = field(default_factory=list)
    classes: List[ClassInfo] = field(default_factory=list)
    globals: List[str] = field(default_factory=list)
    comments: List[str] = field(default_factory=list)
    entrypoint: bool = False


class PythonAnalyzer:
    def __init__(self, repo_path: Path):
        self.repo_path = repo_path
        self.parser = Parser(get_language("python"))
        self.modules: Dict[str, ModuleInfo] = {}
        self.symbol_functions: Dict[str, str] = {}
        self.symbol_classes: Dict[str, str] = {}

    def scan_files(self) -> List[Path]:
        files: List[Path] = []
        for root, dirs, filenames in os.walk(self.repo_path):
            dirs[:] = [d for d in dirs if d not in EXCLUDED_DIRS and not d.startswith(".")]
            for fname in filenames:
                path = Path(root) / fname
                if path.suffix in PY_EXTENSIONS:
                    files.append(path)
        return sorted(files)

    def module_name_from_path(self, path: Path) -> str:
        rel = path.relative_to(self.repo_path)
        parts = list(rel.parts)
        parts[-1] = parts[-1].replace(".py", "")
        if parts[-1] == "__init__":
            parts = parts[:-1]
        return ".".join([p for p in parts if p]) or path.stem

    def _text(self, src: bytes, node: Node) -> str:
        return src[node.start_byte:node.end_byte].decode("utf-8", errors="ignore")

    def parse_repo(self) -> None:
        for file_path in tqdm(self.scan_files(), desc="Parsing files"):
            src = file_path.read_bytes()
            tree = self.parser.parse(src)
            mod = self.module_name_from_path(file_path)
            mod_info = ModuleInfo(name=mod, path=str(file_path.relative_to(self.repo_path)))
            self._walk_module(tree.root_node, src, mod_info)
            self.modules[mod] = mod_info

        for module, info in self.modules.items():
            for f in info.functions:
                self.symbol_functions[f.qualified_name] = module
                self.symbol_functions[f.name] = module
            for c in info.classes:
                q = f"{module}.{c.name}"
                self.symbol_classes[q] = module
                self.symbol_classes[c.name] = module

    def _walk_module(self, root: Node, src: bytes, mod_info: ModuleInfo) -> None:
        for child in root.children:
            if child.type == "function_definition":
                mod_info.functions.append(self._parse_function(child, src, mod_info.name))
            elif child.type == "class_definition":
                mod_info.classes.append(self._parse_class(child, src, mod_info.name))
            elif child.type in {"import_statement", "import_from_statement"}:
                mod_info.imports.extend(self._parse_import(child, src))
            elif child.type == "expression_statement" and self._is_main_guard(child, src):
                mod_info.entrypoint = True
            elif child.type == "assignment":
                left = child.child_by_field_name("left")
                if left is not None and left.type == "identifier":
                    mod_info.globals.append(self._text(src, left))
            elif child.type == "comment":
                mod_info.comments.append(self._text(src, child))

        if "argparse" in {imp.get("module", "") for imp in mod_info.imports}:
            mod_info.entrypoint = True

    def _parse_import(self, node: Node, src: bytes) -> List[Dict[str, str]]:
        text = self._text(src, node).strip()
        out: List[Dict[str, str]] = []
        if text.startswith("import "):
            for item in text.replace("import ", "", 1).split(","):
                item = item.strip()
                if " as " in item:
                    mod, alias = [x.strip() for x in item.split(" as ", 1)]
                else:
                    mod, alias = item, ""
                out.append({"type": "import", "module": mod, "name": mod.split(".")[-1], "alias": alias})
        elif text.startswith("from "):
            left, right = text.split(" import ", 1)
            base = left.replace("from ", "", 1).strip()
            for item in right.split(","):
                item = item.strip()
                if " as " in item:
                    name, alias = [x.strip() for x in item.split(" as ", 1)]
                else:
                    name, alias = item, ""
                out.append({"type": "from", "module": base, "name": name, "alias": alias})
        return out

    def _parse_class(self, node: Node, src: bytes, module: str) -> ClassInfo:
        name = self._text(src, node.child_by_field_name("name"))
        methods: List[FunctionInfo] = []
        body = node.child_by_field_name("body")
        if body:
            for n in body.children:
                if n.type == "function_definition":
                    method_info = self._parse_function(n, src, module, class_name=name)
                    methods.append(method_info)
        return ClassInfo(name=name, module=module, methods=methods)

    def _parse_function(self, node: Node, src: bytes, module: str, class_name: Optional[str] = None) -> FunctionInfo:
        name = self._text(src, node.child_by_field_name("name"))
        params_node = node.child_by_field_name("parameters")
        params: List[Dict[str, Optional[str]]] = []
        if params_node:
            for ch in params_node.children:
                if ch.type == "identifier":
                    params.append({"name": self._text(src, ch), "type": None})
                elif ch.type == "typed_parameter":
                    p_name = self._text(src, ch.child_by_field_name("name"))
                    p_type = ch.child_by_field_name("type")
                    type_str = self._text(src, p_type) if p_type else None
                    params.append({"name": p_name, "type": type_str})
                elif ch.type == "default_parameter":
                    p_name = self._text(src, ch.child_by_field_name("name"))
                    params.append({"name": p_name, "type": None})
                elif ch.type == "typed_default_parameter":
                    p_name = self._text(src, ch.child_by_field_name("name"))
                    p_type = ch.child_by_field_name("type")
                    type_str = self._text(src, p_type) if p_type else None
                    params.append({"name": p_name, "type": type_str})
                elif ch.type == "list_splat_pattern":
                    params.append({"name": self._text(src, ch), "type": None})
                elif ch.type == "dictionary_splat_pattern":
                    params.append({"name": self._text(src, ch), "type": None})
        return_type_node = node.child_by_field_name("return_type")
        return_type = self._text(src, return_type_node) if return_type_node else None

        body = node.child_by_field_name("body")
        calls: List[str] = []
        docstring = ""
        complexity, nesting = self._complexity(body)
        if body:
            for n in self._iter_nodes(body):
                if n.type == "call":
                    fn = n.child_by_field_name("function")
                    if fn is not None:
                        calls.append(self._text(src, fn))
            if body.child_count > 0 and body.children[0].type == "expression_statement":
                txt = self._text(src, body.children[0])
                if txt.startswith(('"""', "''")):
                    docstring = txt.strip('"\'')
        qualified_name = f"{module}.{class_name}.{name}" if class_name else f"{module}.{name}"
        return FunctionInfo(name=name, qualified_name=qualified_name, module=module, params=params, return_type=return_type, docstring=docstring, calls=calls, complexity=complexity, nesting=nesting)

    def _iter_nodes(self, node: Optional[Node]):
        if node is None:
            return
        stack = [node]
        while stack:
            cur = stack.pop()
            yield cur
            stack.extend(reversed(cur.children))

    def _complexity(self, node: Optional[Node]) -> Tuple[int, int]:
        if node is None:
            return 1, 0
        decision_nodes = {"if_statement", "for_statement", "while_statement", "try_statement", "except_clause", "match_statement"}
        cpx = 1
        max_depth = 0

        def walk(n: Node, depth: int) -> None:
            nonlocal cpx, max_depth
            if n.type in decision_nodes:
                cpx += 1
                depth += 1
            max_depth = max(max_depth, depth)
            for ch in n.children:
                walk(ch, depth)

        walk(node, 0)
        return cpx, max_depth

    def _is_main_guard(self, node: Node, src: bytes) -> bool:
        txt = self._text(src, node)
        return "__name__" in txt and "__main__" in txt


def build_structure_tree(repo_path: Path) -> Dict:
    tree: Dict = {}
    for root, dirs, files in os.walk(repo_path):
        dirs[:] = [d for d in dirs if d not in EXCLUDED_DIRS and not d.startswith(".")]
        rel = Path(root).relative_to(repo_path)
        cur = tree
        for part in rel.parts:
            cur = cur.setdefault(part, {})
        for f in files:
            if Path(f).suffix in PY_EXTENSIONS:
                cur.setdefault(f, {})
    return tree


def classify_module(module: str) -> str:
    low = module.lower()
    if any(k in low for k in ["utils", "helper", "common"]):
        return "utility"
    if any(k in low for k in ["model", "entity", "domain", "order", "payment", "user"]):
        return "business"
    return "core"


def _module_root(module_name: str) -> str:
    return module_name.split(".")[0]


def main() -> None:
    ap = argparse.ArgumentParser(description="Static code intelligence engine (no LLM)")
    ap.add_argument("repo_path")
    ap.add_argument("output_path", nargs="?")
    args = ap.parse_args()

    repo_path = Path(args.repo_path).resolve()
    output_dir = Path(args.output_path) if args.output_path else Path(f"output_{repo_path.name}")
    output_dir.mkdir(parents=True, exist_ok=True)

    analyzer = PythonAnalyzer(repo_path)
    analyzer.parse_repo()

    dep_graph = nx.DiGraph()
    call_graph = nx.DiGraph()
    module_graph = nx.Graph()
    internal_modules = set(analyzer.modules.keys())

    all_functions: List[FunctionInfo] = []
    all_classes: List[ClassInfo] = []
    globals_out: List[Dict[str, str]] = []

    for module, m in analyzer.modules.items():
        dep_graph.add_node(module)
        module_graph.add_node(module)
        all_functions.extend(m.functions)
        all_classes.extend(m.classes)
        globals_out.extend({"module": module, "name": g} for g in m.globals)
        for imp in m.imports:
            # Keep module-level dependency graph focused on internal repository modules.
            # This prevents explosive graph growth from stdlib/3rd-party imports.
            raw_target = imp["module"]
            target = raw_target
            if target not in internal_modules:
                candidate = target.split(".")[0]
                if candidate in internal_modules:
                    target = candidate
            if target in internal_modules:
                dep_graph.add_edge(module, target)
                module_graph.add_edge(module, target)

    for fn in all_functions:
        call_graph.add_node(fn.qualified_name)

    for fn in all_functions:
        caller = fn.qualified_name
        mod_import_alias = {i["alias"] or i["name"]: i["module"] for i in analyzer.modules[fn.module].imports}
        for raw_call in fn.calls:
            base = raw_call.split("(")[0].strip()
            callee = None
            if base in mod_import_alias:
                callee = mod_import_alias[base]
            elif f"{fn.module}.{base}" in analyzer.symbol_functions:
                callee = f"{fn.module}.{base}"
            elif base in analyzer.symbol_functions:
                callee = f"{analyzer.symbol_functions[base]}.{base.split('.')[-1]}"
            else:
                parts = base.split(".")
                if len(parts) >= 2:
                    lhs = parts[0]
                    rhs = parts[-1]
                    if lhs in mod_import_alias:
                        callee = f"{mod_import_alias[lhs]}.{rhs}"
            if callee:
                # Keep the call graph constrained to application source modules only.
                callee_module = ".".join(callee.split(".")[:-1]) if "." in callee else callee
                if callee_module not in internal_modules and _module_root(callee_module) not in internal_modules:
                    continue
                call_graph.add_edge(caller, callee)

    dead_code = [n for n in call_graph.nodes if call_graph.in_degree(n) == 0]
    orphan_modules = [n for n in dep_graph.nodes if dep_graph.in_degree(n) == 0 and dep_graph.out_degree(n) == 0]

    fan = [{"function": n, "fan_in": int(call_graph.in_degree(n)), "fan_out": int(call_graph.out_degree(n))} for n in call_graph.nodes]
    coupling = [{"module": n, "incoming": int(dep_graph.in_degree(n)), "outgoing": int(dep_graph.out_degree(n)), "coupling_score": int(dep_graph.in_degree(n) + dep_graph.out_degree(n))} for n in dep_graph.nodes]

    clusters = [{"cluster_id": i + 1, "modules": sorted(list(comp))} for i, comp in enumerate(nx.connected_components(module_graph))]

    entrypoints = []
    for mod, m in analyzer.modules.items():
        impmods = {i["module"].lower() for i in m.imports}
        if m.entrypoint or any(x in impmods for x in ["argparse", "click", "fastapi", "flask"]):
            entrypoints.append(mod)

    api_surface = []
    for fn in all_functions:
        if not fn.name.startswith("_"):
            api_surface.append(fn.qualified_name)

    complexity_list = [{"function": f.qualified_name, "complexity": f.complexity, "nesting": f.nesting} for f in all_functions]
    fan_map = {x["function"]: x for x in fan}
    hotspots = [f.qualified_name for f in all_functions if f.complexity >= 8 and fan_map[f.qualified_name]["fan_in"] >= 2]

    business_entities = sorted({c.name for c in all_classes if any(h in c.name.lower() for h in ENTITY_HINTS)} | {g["name"] for g in globals_out if any(h in g["name"].lower() for h in ENTITY_HINTS)})

    module_types = [{"module": m, "type": classify_module(m)} for m in analyzer.modules]
    business_logic = [f.qualified_name for f in all_functions if classify_module(f.module) != "utility" and fan_map[f.qualified_name]["fan_out"] >= 2 and any(e.lower() in " ".join(f.calls).lower() for e in business_entities)]

    uml = {
        "classes": [{"name": c.name, "module": c.module, "methods": [{"name": m.name, "params": m.params, "return_type": m.return_type} for m in c.methods]} for c in all_classes],
        "relations": [{"from": u, "to": v, "type": "module_dep"} for u, v in dep_graph.edges],
    }

    circular_dependencies = [cycle for cycle in nx.simple_cycles(dep_graph)]
    high_fanout_modules = [n for n in dep_graph.nodes if dep_graph.out_degree(n) >= 8]

    reachable: Set[str] = set()
    for ep in entrypoints:
        for fn in [f for f in all_functions if f.module == ep]:
            reachable.update(nx.descendants(call_graph, fn.qualified_name))
            reachable.add(fn.qualified_name)
    coverage = len(reachable) / len(all_functions) if all_functions else 0.0

    deg = nx.degree_centrality(module_graph) if module_graph.nodes else {}
    if module_graph.nodes:
        node_count = module_graph.number_of_nodes()
        # Exact betweenness is O(V*E) and becomes very slow on large graphs.
        # Use approximation with sampling when the graph is large.
        if node_count > 300:
            k = min(100, node_count)
            btw = nx.betweenness_centrality(module_graph, k=k, seed=42)
        else:
            btw = nx.betweenness_centrality(module_graph)
    else:
        btw = {}
    centrality = [{"module": m, "score": round((deg.get(m, 0.0) + btw.get(m, 0.0)) / 2, 4)} for m in module_graph.nodes]

    refactoring = []
    for f in all_functions:
        if f.complexity >= 10:
            refactoring.append({"type": "split_function", "target": f.qualified_name})
    for c in coupling:
        if c["coupling_score"] >= 10:
            refactoring.append({"type": "decouple_module", "target": c["module"]})
    for d in dead_code:
        refactoring.append({"type": "remove_dead_code", "target": d})

    def _filter_internal_imports(imports: List[Dict[str, str]]) -> List[Dict[str, str]]:
        return [imp for imp in imports if imp["module"].split(".")[0] in internal_modules]

    def _filter_internal_calls(calls: List[str], mod_imports: List[Dict[str, str]]) -> List[str]:
        mod_import_alias = {i["alias"] or i["name"]: i["module"] for i in mod_imports}
        internal_calls = []
        for call in calls:
            base = call.split("(")[0].strip().split(".")[0]
            if base in mod_import_alias:
                if mod_import_alias[base].split(".")[0] in internal_modules:
                    internal_calls.append(call)
            elif call.split(".")[0] in internal_modules or call in analyzer.symbol_functions:
                internal_calls.append(call)
        return internal_calls

    output = {
        "project": {
            "name": repo_path.name,
            "path": str(repo_path),
            "structure": build_structure_tree(repo_path),
        },
        "modules": [{"name": m.name, "path": m.path, "imports": _filter_internal_imports(m.imports), "comments": m.comments} for m in analyzer.modules.values()],
        "symbols": {
            "functions": [{**f.__dict__, "calls": _filter_internal_calls(f.calls, analyzer.modules[f.module].imports)} for f in all_functions],
            "classes": [{"name": c.name, "module": c.module, "methods": [m.__dict__ for m in c.methods]} for c in all_classes],
            "globals": globals_out,
        },
        "business_entities": business_entities,
        "graphs": {
            "call_graph": [[u, v] for u, v in call_graph.edges],
            "dependency_graph": [[u, v] for u, v in dep_graph.edges],
            "module_graph": [[u, v] for u, v in module_graph.edges],
        },
        "analysis": {
            "dead_code": dead_code,
            "orphan_modules": orphan_modules,
            "fan_in_out": fan,
            "coupling": coupling,
            "circular_dependencies": circular_dependencies,
            "hotspots": hotspots,
            "centrality": centrality,
            "coverage_estimate": [{"coverage": round(coverage, 4)}],
        },
        "architecture": {
            "clusters": clusters,
            "module_types": module_types,
            "layers": [],
        },
        "api_surface": api_surface,
        "entrypoints": entrypoints,
        "uml": uml,
        "refactoring_suggestions": refactoring,
    }

    timestamp = time.strftime("%Y%m%d_%H%M%S")
    out_file = output_dir / f"{repo_path.name}_{timestamp}.json"
    out_file.write_text(json.dumps(output, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"Written: {out_file}")


if __name__ == "__main__":
    main()
